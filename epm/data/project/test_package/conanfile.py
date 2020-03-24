#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os

from conans import ConanFile, CMake, tools
from epm.tool.conan import ConanMeta


class PackageInvokerMakefile(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "cmake"

    @property
    def target_reference(self):
        print(os.getcwd()， '**************')
        reference = os.environ.get('EPM_TARGET_PACKAGE_REFERENCE')
        if reference:
            return reference
        pkg_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
        filename = os.path.join(pkg_dir, 'package.yml')
        print(self)
        print(self.__file__)
        filename = 'package.yml'
        if os.path.exists(filename):
            meta = ConanMeta(filename)
            return meta.reference
        raise Exception('environment var EPM_TARGET_PACKAGE_REFERENCE not set.')

    def requirements(self):
        self.requires(self.target_reference)  # the lib to be linked in this program

        self.requires("gtest/1.8.1@epm/public")

    def build(self):
        cmake = CMake(self)
        cmake.definitions['WITH_GMOCK'] = self.options['gtest'].build_gmock
        cmake.definitions['WITH_MAIN'] = not self.options['gtest'].no_main
        cmake.configure()
        cmake.build()

    def package(self):
        cmake = CMake(self)
        cmake.configure()
        cmake.install()

    def test(self):
        if not tools.cross_building(self.settings):
            bin_path = os.path.join("bin", "{{ name }}_test")
            self.run(bin_path, run_environment=True)
