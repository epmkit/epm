import os
import sys
import pathlib
import subprocess
import paramiko

from conans.client.output import ConanOutput as Output
from epm.util import is_elf, system_info
PLATFORM, ARCH = system_info()

class SSH(object):

    def __init__(self, hostname, username, password, port=22, out=None):
        self._ssh = None
        self._out = out or Output(sys.stdout)

        self._hostname = hostname
        self._port = port or 22
        self._username = username
        self._password = password
        self.WD = '~'

        self.LD_LIBRARY_PATH = None

    def open(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=self._hostname, port=self._port, username=self._username, password=self._password)
        self._ssh = ssh

    def close(self):
        if self._ssh:
            self._ssh.close()

    def call(self, cmd, cwd=None, timeout=None, out=None, check=False):

        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        if cwd and not pathlib.PurePath(cwd).is_absolute():
            cwd = os.path.join(self.WD, cwd)
            cwd = pathlib.PurePath(cwd).as_posix()

        cwd = cwd or self.WD
        out = out or self._out
        script = ''
        if self.LD_LIBRARY_PATH:
            script += ' export LD_LIBRARY_PATH=%s:$LD_LIBRARY_PATH;' % self.LD_LIBRARY_PATH

        script += 'cd %s && %s' % (cwd, cmd)

        _, stdout, stderr = self._ssh.exec_command(script, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()

        def _(o):
            stream = o.read()
            return stream.decode('utf-8', errors='ignore') if stream else ''

        if stdout:
            out.write(_(stdout))
        if stderr:
            out.write(_(stderr))
        if check and exit_code:
            raise Exception('ssh cmd failed -> %s' % cmd)

        return exit_code

    def mount(self, path, directory, interface=None, username=None, password=None):
        if not pathlib.PurePath(directory).is_absolute():
            directory = os.path.join(self.WD, directory)

        path = pathlib.PurePath(path).as_posix()
        directory = pathlib.PurePath(directory).as_posix()

        try:
            self.call('[[ -d {0} ]] && umount {0}'.format(directory))
        except:
            pass

        formatter = 'mount -t nfs -o nolock {hostname}:{path} {directory}'

        if PLATFORM == 'Windows':
            path = path.replace(':', '')
            auth = ''
            if username:
                auth = '-o user=%s,pass=%s' % (username, password)
            formatter = 'mount -t cifs %s //{hostname}/{path} {directory}' % auth

        cmd = formatter.format(hostname=interface, path=path, directory=directory)
        self.call(cmd, check=True)
