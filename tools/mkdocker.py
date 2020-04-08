#
#
#
# config file (YAML format)
# pip:
#   mirror: http://<hostname>:<port>/...
#   http_proxy: http://<hostname>:<port>
#
##########################################################
import os
import sys
import yaml
import jinja2
import argparse
from urllib.parse import urlparse

_DIR = os.path.join(os.path.dirname(__file__), '..')
_DIR = os.path.normpath(os.path.abspath(_DIR))

class Config(object):
    mirror = None
    http_proxy = None
    debug = False
    epm_source_dir = '.cache/epm'

    def __init__(self, filename=None, debug=False):
        if filename:
            with open(filename) as f:
                self._items = yaml.safe_load(f)
            self.mirror = self._items.get('pip', {}).get('mirror')
            self.http_proxy = self._items.get('pip', {}).get('proxy')
            self.archive_url = self._items.get('archive_url')
            self.conan_version = self._items.get('conan_version')
            sourced = self._items.get('epm_source_dir')
            if sourced:
                self.epm_source_dir = sourced
        self.debug = debug

    @property
    def trusted_host(self):
        if self.mirror:
            result = urlparse(self.mirror)
            if result.scheme == 'http':
                return result.hostname
        return None


class Dockerfile(object):

    def __init__(self, name, version, config=None):
        self._name = name
        self._dir = os.path.join(_DIR, 'tools', 'docker')
        self._version = version
        self._config = config or Config()

    def _render(self, **kwargs):
        if not os.path.exists(os.path.join(self._dir, self._name +'.j2')):
            raise Exception('Jinja2 template %s not exists' % self._name)

        loader = jinja2.FileSystemLoader(searchpath=self._dir)
        env = jinja2.Environment(loader=loader)
        template = env.get_template('%s.j2' % self._name)
        options = ''
        if self._config.mirror:
            options += ' -i %s' % self._config.mirror
            if self._config.trusted_host:
                options += ' --trusted-host %s' % self._config.trusted_host
            if self._config.http_proxy:
                options += ' --proxy %s' % self._config.http_proxy

        install_epm = 'sudo pip install %s %s %s' % (options,
                                                '-e' if self._config.debug else '',
                                                self._config.epm_source_dir)
        vars = dict({'name': self._name,
                     'version': self._version,
                     'debug': self._config.debug,
                     'options': options,
                     'epm_source_dir': self._config.epm_source_dir,
                     'install_epm': install_epm,
                     'archive_url': self._config.archive_url,
                     'conan_version': self._config.conan_version
                     },
                    **kwargs)

        return template.render(vars)

    def write(self, filename='Dockerfile'):
        content = self._render()
        with open(filename, 'w') as f:
            f.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('name', nargs=1, help="name of the docker image to build.")
    parser.add_argument('--version', help="specify version of the image to build instead read from epm module")
    parser.add_argument('-c', '--config', help="path of configure file.")
    parser.add_argument('-B', '--build', default=False, action="store_true", help="generate Dockerfile and build image.")
    parser.add_argument('--debug', default=False, action="store_true", help="generate a debug Dockerfile.")
    sys.path.insert(0, _DIR)
    import epm

    args = parser.parse_args()
    config = Config(args.config or None, args.debug)
    name = args.name[0]
    filename = 'Dockerfile-%s' % name
    version = args.version
    if not version:
        version = 'debug' if args.debug else epm.__version__
    docerfile = Dockerfile(name, version, config=config)
    docerfile.write(os.path.join(_DIR, filename))
    if args.build:
        import subprocess
        command = ['docker', 'build', '.', '-f', filename, '-t', 'epmkit/%s:%s' % (name, version)]
        subprocess.run(command, check=True, cwd=_DIR)


if __name__ == '__main__':
    print(os.path.abspath('.'))
    main()
