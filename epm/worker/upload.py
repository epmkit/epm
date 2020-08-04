import os
from epm.worker import Worker
from conans.tools import environment_append
from epm.errors import EConanException


class Uploader(Worker):

    def __init__(self, api=None):
        super(Uploader, self).__init__(api)

    def exec(self, param):
        profile = param.get('PROFILE')
        scheme = param.get('SCHEME')
        storage = param.get('storage')
        storage = os.path.abspath(storage) if storage else self.api.conan_storage_path

        project = self.api.project(profile, scheme)
        package_id = project.record.get('package_id')
        reference = str(project.reference)

        remote = param.get('remote', None)

        from conans.client.cmd.uploader import UPLOAD_POLICY_FORCE

        with environment_append({'CONAN_STORAGE_PATH': storage}):
            info = self.conan.upload(pattern=reference, package=package_id,
                                     policy=UPLOAD_POLICY_FORCE,
                                     remote_name=remote, all_packages=False)
            if info['error']:
                raise EConanException('configure step failed on conan.install.', info)
