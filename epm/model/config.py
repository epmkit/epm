import os
import yaml
from epm.util.files import save_yaml, load_yaml
from collections import namedtuple, OrderedDict
from epm.errors import EMetadataError
from conans.model.ref import ConanFileReference, get_reference_fields
from conans.client.tools import environment_append
import pathlib
import re
_P_PROJECT = r'(?P<project>\w[\w\-]+)/'
_P_TYPE = r'((?P<project>\w[\w\-]+)/)?(?P<type>(build|package))/'
_P_FOLDER = r'(?P<folder>bin)?'
_P_PROGRAM = r'/(?P<program>\w[\w\-]+)'
_SANDBOX_PATTERN = re.compile(_P_TYPE + _P_FOLDER + _P_PROGRAM + r'$')


class Config(object):

    def __init__(self, filename='~/.epm/config.yml'):
        self._data = {}
        self._filename = filename
        if os.path.exists(self._filename):
            self._data = load_yaml(self._filename)
        self._data = dict({'wenv': {},
                           'registry': {}
                           }, **self._data)

    @property
    def wenv(self):
        WEnv = namedtuple('WEnv', ['name', 'with_default_profiles', 'buildin_profiles'])

        value = self._data.get('wenv')

        if value is None or value.get('name') is None:
            return None
        with_default_profiles = value.get('with_default_profiles', False)
        buildin_profiles = value.get('buildin_profiles')
        return WEnv(value['name'], with_default_profiles, buildin_profiles)

    @property
    def environment(self):
        return self._data.get('environment', {})

    @property
    def remotes(self):
        Remote = namedtuple('Remote', ['name', 'url', 'username', 'password'])
        remotes = []
        for item in self._data.get('remotes', []):
            for name, r in item.items():
                url = r['url']
                username = r.get('username', None)
                password = r.get('password', None)
                remotes.append(Remote(name, url, username, password))
        return remotes

    @property
    def env_vars(self):
        '''
        '''
        env = {}
        for key, value in self.environment.items():
            val = os.environ.get(key)
            if val:
                env[key] = val
        return dict(self.environment, **env)

    def get(self, section, default=None):
        return self._data.get(section, default)


class MetaInformation(object):
    _data = None
    _text = None
    _filename = None
    _conanfile = None

    def __init__(self, filename):

        if isinstance(filename, dict):
            self._data = filename
            if '__file__' in self.data:
                self.filename = self._data['__file__']
        else:
            if not os.path.exists(filename):
                raise FileNotFoundError('epm package configure file %s not exits!' % filename)

            self._filename = os.path.abspath(filename)

            with open(filename) as f:
                self._data = yaml.safe_load(f)

        name = self._data['name']
        version = self._data['version']
        user = self._data.get('user', None)

    @property
    def name(self):
        return self._data['name']

    @property
    def version(self):
        return self._data['version']

    @property
    def user(self):
        return self._data.get('user', None)

    @property
    def data(self):
        return self._data

    @property
    def filename(self):
        return self._filename

    @property
    def text(self):
        if self._text is None:
            if self._filename:
                with open(self._filename) as f:
                    self._text = f.read()
        return self._text

    @staticmethod
    def condition_only(conditions, settings):

        for cond in conditions:
            for key, value in cond.items():
                if key == 'compiler':

                    if value != settings.get('compiler'):
                        return False
        return True

    def get_requirements(self, settings):
        from epm.tools.conan import get_channel
        dependencies = self.data.get('dependencies', [])

        deps = OrderedDict()
        for packages in dependencies:
            if isinstance(packages, str):
                name, version, user, channel, revision = get_reference_fields(packages)
                if user:
                    channel = channel or get_channel(user=user)
                deps[name] = ConanFileReference(name, version, user, channel, revision)

            elif isinstance(packages, dict):
                process = True
                if 'only' in packages and settings:
                    process = self.condition_only(packages['only'], settings)

                if process:
                    for name, option in packages.items():
                        version = option['version']
                        user = option.get('user', None)
                        channel = get_channel(user=user)
                        channel = option.get('channel', channel)
                        revision = option.get('revision', None)
                        deps[name] = ConanFileReference(name, version, user, channel, revision)
        return deps

    def get_scheme(self, scheme, settings):
        scheme = scheme or 'default'

        info = self.data.get('scheme', {}).get(scheme, None)

        if scheme != 'default' and info is None:
            raise EMetadataError('scheme <{}> not defined in metadata file'.format(scheme))

        import copy
        if info:
            info = copy.deepcopy(info)
        info = info or dict()

        options = dict()
        if 'options' in info:
            options = info['options']
            info.pop('options')
        requirements = self.get_requirements(settings)
        deps = dict()

        for name in requirements.keys():
            deps[name] = 'default'

        for name, value in info.items():

            if name in deps:
                deps[name] = self._get_package_scheme(value, settings)
        return options, deps

    def _get_package_scheme(self, item, settings):
        if isinstance(item, str):
            return item
        if not isinstance(item, list):
            raise EMetadataError('Invalid scheme assign', item)
        default = []
        for i in item:
            if isinstance(i, str):
                default.append(i)
                continue

            for name, conditions in i.items():
                if self.condition_only(conditions, settings):
                    return name
        assert len(default) == 1
        return default[0] if default else 'default'


    def get_options(self, scheme, settings, storage, api):
        package_options = dict()

        options, deps = self.get_scheme(scheme, settings)

        if not deps:
            return options, package_options

        refs = self.get_requirements(settings)
        conan = api.conan
        storage = storage or api.conan_storage_path
        for pkg, sch in deps.items():
            storage = storage or api.conan_storage_path
            with environment_append({'CONAN_STORAGE_PATH': storage}):
                conanfile = conan.inspect(str(refs[pkg]), ['options', 'default_options', 'settings', '_META_INFO'])

            metainfo = conanfile['_META_INFO']
            if metainfo is None:
                raise EMetadataError('scheme {0}:{1} invalid because {0} no metaifo file(package.yml)'.format(
                    pkg, sch))

            opt, pkg_opt = metainfo.get_options(sch, settings, storage, api)

            def _merge(base, new):
                for k, v in new.items():
                    if k in base and v != base[k]:
                        raise EMetadataError('package scheme conflict, {}: {} <-> {}'.format(k, v, base[k]))
                    base[k] = v

            def _check_consistency(name, opt):
                if name not in package_options:
                    return
            import pprint

            if opt:
                if pkg in package_options:
                    if package_options[pkg] != opt:
                        raise EMetadataError('different options in scheme {} {}'.format(
                            pprint.pformat(opt), pprint.pformat(package_options[pkg])))
                else:
                    package_options[pkg] = opt

            for key, value in pkg_opt.items():
                if key in package_options:
                    if package_options[key] == value:
                        continue
                    print("{} CONFLICT".format(key))
                    print(pprint.pformat(opt))
                    print(pprint.pformat(package_options[pkg]))
                    raise EMetadataError('different options in scheme {} {}'.format(
                        pprint.pformat(opt), pprint.pformat(package_options[pkg])))
                else:
                    package_options[key] = value

        return options, package_options

    def get_sandbox(self):
        Sandbox = namedtuple('Sandbox', 'content name directory type folder program param argv ports privileged')
        result = {}
        ports = []
        privileged = False
        for name, item in self.data.get('sandbox', {}).items():
            cmdstr = item
            if isinstance(item, dict):
                cmdstr = item['command']
                ports = item.get('ports', []) or []
                if isinstance(ports, int):
                    ports = [ports]
                privileged = item.get('privileged', False)

            parts = cmdstr.split(' ', 1)
            command = parts[0]
            command = pathlib.PurePath(command).as_posix()
            param = None if len(parts) < 2 else parts[1].strip()
            argv = param.split() if param else []
            m = _SANDBOX_PATTERN.match(command)
            if not m:
                raise Exception('sandbox {} invalid'.format(name))

            result[name] = Sandbox(item, name,
                                   m.group('project'), m.group('type'),
                                   m.group('folder'), m.group('program'),
                                   param, argv, ports, privileged)

        return result








