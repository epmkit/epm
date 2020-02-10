import os

from epm.util.files import mkdir, rmdir
from epm.test import TestCase, CONFIG
from unittest import skipIf

Config = CONFIG


@skipIf(not Config.with_vs2019, 'BuildVS2019: Visual Studio 2019 not installed')
class VS2019(TestCase):
    conan_server = True
    remotes = ['epm']

    def test_lib_vs2019(self):
        #self.assertTrue(False)
        return
        mkdir('lib1')
        os.chdir('lib1')
        from subprocess import run as call
        call('epm init lib', check=True)
        call('epm build --scheme vs2019')
