import os
import yaml
import pprint
import copy
import glob
import shutil

import epm
from conans.client.profile_loader import read_profile
from conans.model.options import OptionsValues
from conans.tools import RunEnvironment
from epm.errors import EException
from epm.paths import DATA_DIR, get_epm_home_dir
from epm.util.files import load_yaml
from epm.util import split_plan_name

from collections import OrderedDict, namedtuple

from epm.util import is_elf, system_info
from epm.util.files import remove, rmdir, load_yaml
from epm.paths import get_epm_home_dir, HOME_EPM_DIR

from conans.client.tools import environment_append

PLATFORM, ARCH = system_info()


# if
class Profile(object):
    """ Specific profile

    """

    def __init__(self, name, epm_dir):
        self.name = name
        self._epm_dir = epm_dir or get_epm_home_dir()
        self._filename = os.path.join(self._epm_dir, 'profiles', name)
        manifest = os.path.join(os.path.dirname(self._filename), 'manifest.yml')
        if not os.path.exists(manifest):
            raise EException('No %s for %s, you need to install.' % (manifest, name))

        if not os.path.exists(self._filename):
            raise EException('No  %s profile, you need to install.' % name)

        with open(manifest) as f:
            self._manifest = yaml.safe_load(f)

        self._meta = None

        for family, value in self._manifest.items():
            for name, spec in value['profiles'].items():
                if name == os.path.basename(self.name):
                    self._meta = dict(value, **spec)
                    del self._meta['profiles']
                    break
        if self._meta is None:
            raise EException('No properties defined for profile %s' % self.name)

        name = os.path.basename(self.name)
        folder = os.path.dirname(self._filename)
        self._profile, _ = read_profile(name, folder, folder)

    @property
    def docker(self):
        Docker = namedtuple('Docker', ['builder', 'runner'])
        docker = self._meta.get('docker')
        runner = docker.get('runner') if docker else None
        builder = docker.get('builder') if docker else None

        return Docker(builder, runner)

    def save(self, filename):
        shutil.copyfile(self._filename, filename)

    @property
    def settings(self):
        return self._profile.settings

    @property
    def is_running_native(self):
        if PLATFORM != self.settings['os']:
            return False
        arch = self.settings['arch']
        assert(arch in ['x86', 'x86_64'])
        if ARCH == arch:
            return True

        if PLATFORM == 'Windows':
            return 'x86' == arch
        else:
            return False

    @property
    def builders(self):

        arch = self.settings['arch']
        platform = self.settings['os']

        if PLATFORM == 'Windows':
            if platform == 'Windows':
                return ['shell']
            elif platform == 'Linux':
                return ['docker']
        elif PLATFORM == 'Linux':
            if platform == 'Linux':
                return ['docker', 'shell']
        return None

    @property
    def is_cross_build(self):
        return PLATFORM != self.settings['os'] or ARCH != self.settings['arch']


def install_default_profiles(self):
    pd = os.path.join(HOME_EPM_DIR, 'profiles')
    if not os.path.exists(pd):
        os.makedirs(pd)

    manifest = os.path.join(pd, 'manifest.yml')
    if not os.path.exists(manifest):
        for i in ['manifest.yml', 'gcc5', 'gcc5.d', 'vs2019', 'vs2019d', 'vs2019MT', 'vs2019MT.d']:
            shutil.copy(os.path.join(DATA_DIR,'profiles', i), os.path.join(pd, i))

