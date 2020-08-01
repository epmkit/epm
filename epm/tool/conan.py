from epm.tools import conan as _conan
from epm.tools.conan import get_channel

Packager = _conan.Packager
TestPackager = _conan.TestPackager

import os
import re
from conans import ConanFile as _ConanFile
from epm.model.config import MetaInformation
from epm.util.mirror import Mirror, register_mirror


class MetaInfo(object):

    def __init__(self, metainfo, conanfile):
        self._metainfo = metainfo
        self._conanfile = conanfile

    @property
    def dependencies(self):
        return self._metainfo.get_requirements(self._conanfile.settings, self._conanfile.options)



class Helper(object):

    @property
    def metainfo(self):
        return MetaInfo(self._META_INFO, self)


def MetaClass(ConanFileClass=None, manifest=None, test_package=False):

    manifest = manifest or '../package.yml' if test_package else 'package.yml'
    try:
        metainfo = MetaInformation(manifest)
        print(metainfo)
    except BaseException as e:
        print('==============================================')
        print(e)
    name = metainfo.name
    version = metainfo.version
    user = metainfo.user
    exports = [manifest]
    ClassName = re.sub(r'\W', '_', os.path.basename(os.path.normpath(os.path.abspath(manifest))))
    ConanFileClass = ConanFileClass or _ConanFile

    mirror = Mirror.load()
    if mirror:

        mirror.register(name)
    from conans.client.generators import registered_generators
    registered_generators.add('pkg_config', PkgConfigGenerator, custom=True)
    print(registered_generators['pkg_config'],'<------------------------------------')


    member = dict(name=name, version=version, _META_INFO=metainfo)
    if test_package:
        folder = os.path.basename(os.path.abspath('.'))
        ClassName = '{}_TestPackage_{}'.format(re.sub(r'\W', '_', folder), ClassName)

        requires = ('%s/%s@%s/%s' % (name, version,
                                     user or '_',
                                     get_channel(user) or '_'))
        member['name'] += '-{}'.format(folder)
        member['requires'] = requires
    else:
        member['exports'] = exports

    return type(ClassName, (Helper, ConanFileClass), member)




######################### MESON HACK #################################
import os
import platform

from conans.client import tools
from conans.client.build import defs_to_string, join_arguments
from conans.client.build.autotools_environment import AutoToolsBuildEnvironment
from conans.client.build.cppstd_flags import cppstd_from_settings
from conans.client.tools.env import environment_append, _environment_add
from conans.client.tools.oss import args_to_string
from conans.errors import ConanException
from conans.model.build_info import DEFAULT_BIN, DEFAULT_INCLUDE, DEFAULT_LIB
from conans.model.version import Version
from conans.util.files import decode_text, get_abs_path, mkdir
from conans.util.runners import version_runner

from epm.enums import Platform
from epm.util import system_info
PLATFORM, ARCH = system_info()


class Meson(object):

    def __init__(self, conanfile, backend=None, build_type=None, append_vcvars=False):
        """
        :param conanfile: Conanfile instance (or settings for retro compatibility)
        :param backend: Generator name to use or none to autodetect.
               Possible values: ninja,vs,vs2010,vs2015,vs2017,xcode
        :param build_type: Overrides default build type comming from settings
        """
        self._conanfile = conanfile
        self._settings = conanfile.settings
        self._append_vcvars = append_vcvars

        self._os = self._ss("os")
        self._compiler = self._ss("compiler")
        self._compiler_version = self._ss("compiler.version")
        self._build_type = self._ss("build_type")

        self.backend = backend or "ninja"  # Other backends are poorly supported, not default other.

        self.options = dict()
        if self._conanfile.package_folder:
            self.options['prefix'] = self._conanfile.package_folder
        self.options['libdir'] = DEFAULT_LIB
        self.options['bindir'] = DEFAULT_BIN
        self.options['sbindir'] = DEFAULT_BIN
        self.options['libexecdir'] = DEFAULT_BIN
        self.options['includedir'] = DEFAULT_INCLUDE

        # C++ standard
        cppstd = cppstd_from_settings(self._conanfile.settings)
        cppstd_conan2meson = {
            '98': 'c++03', 'gnu98': 'gnu++03',
            '11': 'c++11', 'gnu11': 'gnu++11',
            '14': 'c++14', 'gnu14': 'gnu++14',
            '17': 'c++17', 'gnu17': 'gnu++17',
            '20': 'c++1z', 'gnu20': 'gnu++1z'
        }

        if cppstd:
            self.options['cpp_std'] = cppstd_conan2meson[cppstd]

        # shared
        shared = self._so("shared")
        self.options['default_library'] = "shared" if shared is None or shared else "static"

        # fpic
        if self._os and "Windows" not in self._os:
            fpic = self._so("fPIC")
            if fpic is not None:
                shared = self._so("shared")
                self.options['b_staticpic'] = "true" if (fpic or shared) else "false"

        self.build_dir = None
        if build_type and build_type != self._build_type:
            # Call the setter to warn and update the definitions if needed
            self.build_type = build_type

    def _ss(self, setname):
        """safe setting"""
        return self._conanfile.settings.get_safe(setname)

    def _so(self, setname):
        """safe option"""
        return self._conanfile.options.get_safe(setname)

    @property
    def build_type(self):
        return self._build_type

    @build_type.setter
    def build_type(self, build_type):
        settings_build_type = self._settings.get_safe("build_type")
        if build_type != settings_build_type:
            self._conanfile.output.warn(
                'Set build type "%s" is different than the settings build_type "%s"'
                % (build_type, settings_build_type))
        self._build_type = build_type

    @property
    def build_folder(self):
        return self.build_dir

    @build_folder.setter
    def build_folder(self, value):
        self.build_dir = value

    def _get_dirs(self, source_folder, build_folder, source_dir, build_dir, cache_build_folder):
        if (source_folder or build_folder) and (source_dir or build_dir):
            raise ConanException("Use 'build_folder'/'source_folder'")

        if source_dir or build_dir:  # OLD MODE
            build_ret = build_dir or self.build_dir or self._conanfile.build_folder
            source_ret = source_dir or self._conanfile.source_folder
        else:
            build_ret = get_abs_path(build_folder, self._conanfile.build_folder)
            source_ret = get_abs_path(source_folder, self._conanfile.source_folder)

        if self._conanfile.in_local_cache and cache_build_folder:
            build_ret = get_abs_path(cache_build_folder, self._conanfile.build_folder)

        return source_ret, build_ret

    @property
    def flags(self):
        return defs_to_string(self.options)

    def configure(self, args=None, defs=None, source_dir=None, build_dir=None,
                  pkg_config_paths=None, cache_build_folder=None,
                  build_folder=None, source_folder=None):
        if not self._conanfile.should_configure:
            return
        args = args or []
        defs = defs or {}

        # overwrite default values with user's inputs
        self.options.update(defs)

        source_dir, self.build_dir = self._get_dirs(source_folder, build_folder,
                                                    source_dir, build_dir,
                                                    cache_build_folder)

        if pkg_config_paths:
            pc_paths = os.pathsep.join(get_abs_path(f, self._conanfile.install_folder)
                                       for f in pkg_config_paths)
        else:
            pc_paths = self._conanfile.install_folder

        mkdir(self.build_dir)

        bt = {"RelWithDebInfo": "debugoptimized",
              "MinSizeRel": "release",
              "Debug": "debug",
              "Release": "release"}.get(str(self.build_type), "")

        build_type = "--buildtype=%s" % bt
        arg_list = join_arguments([
            "--backend=%s" % self.backend,
            self.flags,
            args_to_string(args),
            build_type
        ])
        command = 'meson "%s" "%s" %s' % (source_dir, self.build_dir, arg_list)
        pc_paths = pc_paths.replace('\\', '/')

        if PLATFORM == Platform.WINDOWS:
            from conans.client.tools.win import unix_path, MSYS2
            pc_paths = unix_path(pc_paths, MSYS2)

        with environment_append({"PKG_CONFIG_PATH": pc_paths}):
            self._run(command)

    @property
    def _vcvars_needed(self):
        return (self._compiler == "Visual Studio" and self.backend == "ninja" and
                platform.system() == "Windows")

    def _run(self, command):
        def _build():
            env_build = AutoToolsBuildEnvironment(self._conanfile)
            with environment_append(env_build.vars):
                self._conanfile.run(command)

        if self._vcvars_needed:
            vcvars_dict = tools.vcvars_dict(self._settings, output=self._conanfile.output)
            with _environment_add(vcvars_dict, post=self._append_vcvars):
                _build()
        else:
            _build()

    def _run_ninja_targets(self, args=None, build_dir=None, targets=None):
        if self.backend != "ninja":
            raise ConanException("Build only supported with 'ninja' backend")

        args = args or []
        build_dir = build_dir or self.build_dir or self._conanfile.build_folder

        arg_list = join_arguments([
            '-C "%s"' % build_dir,
            args_to_string(args),
            args_to_string(targets)
        ])
        self._run("ninja %s" % arg_list)

    def _run_meson_command(self, subcommand=None, args=None, build_dir=None):
        args = args or []
        build_dir = build_dir or self.build_dir or self._conanfile.build_folder

        arg_list = join_arguments([
            subcommand,
            '-C "%s"' % build_dir,
            args_to_string(args)
        ])
        self._run("meson %s" % arg_list)

    def build(self, args=None, build_dir=None, targets=None):
        if not self._conanfile.should_build:
            return
        self._run_ninja_targets(args=args, build_dir=build_dir, targets=targets)

    def install(self, args=None, build_dir=None):
        if not self._conanfile.should_install:
            return
        mkdir(self._conanfile.package_folder)
        if not self.options.get('prefix'):
            raise ConanException("'prefix' not defined for 'meson.install()'\n"
                                 "Make sure 'package_folder' is defined")
        self._run_ninja_targets(args=args, build_dir=build_dir, targets=["install"])

    def test(self, args=None, build_dir=None, targets=None):
        if not self._conanfile.should_test:
            return
        if not targets:
            targets = ["test"]
        self._run_ninja_targets(args=args, build_dir=build_dir, targets=targets)

    def meson_install(self, args=None, build_dir=None):
        if not self._conanfile.should_install:
            return
        self._run_meson_command(subcommand='install', args=args, build_dir=build_dir)

    def meson_test(self, args=None, build_dir=None):
        if not self._conanfile.should_test:
            return
        self._run_meson_command(subcommand='test', args=args, build_dir=build_dir)

    @staticmethod
    def get_version():
        try:
            out = version_runner(["meson", "--version"])
            version_line = decode_text(out).split('\n', 1)[0]
            version_str = version_line.rsplit(' ', 1)[-1]
            return Version(version_str)
        except Exception as e:
            raise ConanException("Error retrieving Meson version: '{}'".format(e))


############################ PKG-CONFIG ########################################
from conans.client.generators.pkg_config import PkgConfigGenerator as _PkgConfigGenerator

import pathlib


class PkgConfigGenerator(_PkgConfigGenerator):
    
    @property
    def content(self):
        ret = {}

        for depname, cpp_info in self.deps_build_info.dependencies:
            pc_files = []
            for i in cpp_info.libdirs:
                path = os.path.join(cpp_info.rootpath, i, 'pkgconfig')
                import glob
                pc_files += glob.glob('%s/*.pc' % path)

            if not pc_files:
                pc_files = glob.glob('%s/pkgocnfig/*.pc' % cpp_info.rootpath)

            if pc_files:

                for pc in pc_files:
                    name = os.path.basename(pc)
                    with open(pc) as f:
                        txt = f.read()
                    line = 'prefix=%s' % pathlib.PurePath(cpp_info.rootpath).as_posix()

                    ret[name] = re.sub(r'prefix=.+', line, txt, 1)
            else:
                name = cpp_info.get_name(PkgConfigGenerator.name)
                ret["%s.pc" % name] = self.single_pc_file_contents(name, cpp_info)

        return ret
