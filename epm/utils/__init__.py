import os
import sys
import uuid
import pathlib
import yaml
from collections import OrderedDict
from conans.client.conan_api import ConanAPIV1 as ConanAPI
from conans.tools import mkdir
from jinja2 import Environment, FileSystemLoader, BaseLoader
from epm import HOME_DIR, DATA_DIR
from epm.enums import Platform, Architecture
from epm.errors import EException
from jinja2 import Environment, FileSystemLoader


def windows_arch():
    """
    Detecting the 'native' architecture of Windows is not a trivial task. We
    cannot trust that the architecture that Python is built for is the 'native'
    one because you can run 32-bit apps on 64-bit Windows using WOW64 and
    people sometimes install 32-bit Python on 64-bit Windows.
    """
    # These env variables are always available. See:
    # https://msdn.microsoft.com/en-us/library/aa384274(VS.85).aspx
    # https://blogs.msdn.microsoft.com/david.wang/2006/03/27/howto-detect-process-bitness/
    arch = os.environ.get('PROCESSOR_ARCHITEW6432', '').lower()
    if not arch:
        # If this doesn't exist, something is messing with the environment
        try:
            arch = os.environ['PROCESSOR_ARCHITECTURE'].lower()
        except KeyError:
            raise EException('Unable to detect Windows architecture')
    return arch


def system_info():
    '''
    Get the sysem information.
    Return a tuple with the platform type, the architecture and the
    distribution
    '''
    # Get the platform info
    platform = os.environ.get('OS', '').lower()
    if not platform:
        platform = sys.platform
    if platform.startswith('win'):
        platform = Platform.WINDOWS
    elif platform.startswith('darwin'):
        platform = Platform.DARWIN
    elif platform.startswith('linux'):
        platform = Platform.LINUX
    else:
        raise EException("Platform %s not supported" % platform)

    # Get the architecture info
    if platform == Platform.WINDOWS:
        arch = windows_arch()
        if arch in ('x64', 'amd64'):
            arch = Architecture.X86_64
        elif arch == 'x86':
            arch = Architecture.X86
        else:
            raise EException(_("Windows arch %s is not supported") % arch)
    else:
        uname = os.uname()
        arch = uname[4]
        if arch == 'x86_64':
            arch = Architecture.X86_64
        elif arch.endswith('86'):
            arch = Architecture.X86
        elif arch.startswith('armv7'):
            arch = Architecture.ARMv7
        elif arch.startswith('arm'):
            arch = Architecture.ARM
        else:
            raise EException(_("Architecture %s not supported") % arch)

    return platform, arch


PLATFORM, ARCH = system_info()


def get_workbench_dir(name=None):
    workbench = os.path.join(HOME_DIR, '.workbench')
    if not name or name in ['default']:
        return HOME_DIR

    path = os.path.join(workbench, name)
    if os.path.isfile(path):
        with open(path) as f:
            path = f.read().strip()
            return path

    if os.path.isdir(path):
        return path

    return None





def conanfile_inspect(path, attributes=None):
    if not os.path.exists(path):
        return None
    attributes = attributes or ['generators', 'exports', 'settings', 'options', 'default_options',
                                '__meta_information__']
    conan = ConanAPI()
    return conan.inspect(path, attributes)



def abspath(path):
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    path = os.path.normpath(path)
    return path


def load_module(path, name=None):
    from importlib.util import spec_from_file_location, module_from_spec
    name = name or str(uuid.uuid1())
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Jinja2(object):
    Filters = {
        'basename': os.path.basename,
        'dirname': os.path.dirname,
        'abspath': abspath
    }

    def __init__(self, directory=None, context=None):
        self._dir = directory
        self._context = context or {}

    def _add_filters(self, env):
        for name, fn in self.Filters.items():
            env.filters[name] = fn
        return env

    def render(self, template, context={}, outfile=None, encoding='utf-8', trim_blocks=False):
        from epm.utils import abspath
        path = abspath(self._dir or '.')

        env = Environment(loader=FileSystemLoader(path))
        includes_loader = FileSystemLoader(path)
        includes_env = Environment(loader=includes_loader)

        env.trim_blocks = trim_blocks
        self._add_filters(env)
        T = env.get_template(template)
        T.environment = includes_env
        context = dict(self._context, **context)
        text = T.render(context)
        #if newline == '\n':
        #    text.replace("\r\n", "\n")
        if outfile:
            path = os.path.abspath(outfile)
            folder = os.path.dirname(path)
            if not os.path.exists(folder):
                os.makedirs(folder)
            with open(path, 'wb') as f:
                f.write(bytes(text, encoding=encoding))
        return text

    def parse(self, text, context={}):
        env = Environment(loader=BaseLoader())
        self._add_filters(env)
        T = env.from_string(text)
        context = dict(self._context, **context)
        return T.render(context)


class ObjectView(object):
    """Object view of a dict, updating the passed in dict when values are set
    or deleted. "ObjectView" the contents of a dict...: """

    def __init__(self, d):
        # since __setattr__ is overridden, self.__dict = d doesn't work
        object.__setattr__(self, '_ObjectView__dict', d)

    # Dictionary-like access / updates
    def __getitem__(self, name):
        if name not in self.__dict:
            return None
        value = self.__dict[name]
        if isinstance(value, dict):  # recursively view sub-dicts as objects
            value = ObjectView(value)
        elif isinstance(value, (list, tuple, set)):
            value = []
            for i in self.__dict[name]:
                if isinstance(i, dict):
                    value.append(ObjectView(i))
                else:
                    value.append(i)

        return value

    def __iter__(self):
        return iter(self._ObjectView__dict)

    def __setitem__(self, name, value):
        self.__dict[name] = value

    def __delitem__(self, name):
        del self.__dict[name]

    # Object-like access / updates
    def __getattr__(self, name):
        return self[name] if name in self else None

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        del self[name]

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.__dict)

    def __str__(self):
        return str(self.__dict)

    def __contains__(self, name):
        return name in self.__dict


def sequence_cast(value, sequence_type=list):
    sequence_types = (list, set, tuple)
    assert sequence_type in sequence_types
    if isinstance(value, sequence_type):
        return value
    if isinstance(value, sequence_types):
        return sequence_type(value)
    if sequence_type == list:
        return [value]
    elif sequence_type == set:
        return {value}
    elif sequence_type == tuple:
        return tuple([value])