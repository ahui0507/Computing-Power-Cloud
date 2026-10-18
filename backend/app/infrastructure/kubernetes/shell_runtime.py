"""Shared interactive Bash profile installed into each fresh instance."""

SHELL_SETUP = r'''
import os,shlex
from pathlib import Path

runtime=Path('/run/platform-shell')
runtime.mkdir(parents=True,exist_ok=True)
Path('/workspace').mkdir(parents=True,exist_ok=True)
exports=''.join('export '+name+'='+shlex.quote(os.environ[name])+'\n'
    for name in ('PATH','LD_LIBRARY_PATH','CUDA_HOME','NVIDIA_VISIBLE_DEVICES','NVIDIA_DRIVER_CAPABILITIES','NCCL_P2P_DISABLE')
    if name in os.environ)
(runtime/'environment.sh').write_text(exports)
(runtime/'ssh-session').write_text(r"""#!/bin/bash
set -e
umask 0002
[ ! -r /run/platform-shell/environment.sh ] || . /run/platform-shell/environment.sh
cd /workspace
case "${SSH_ORIGINAL_COMMAND:-}" in
    internal-sftp*)
        for server in /usr/lib/openssh/sftp-server /usr/libexec/openssh/sftp-server; do
            if [ -x "$server" ]; then exec "$server" -u 0002; fi
        done
        exit 127
        ;;
    '') exec /bin/bash -il ;;
    *) exec /bin/bash -c "$SSH_ORIGINAL_COMMAND" ;;
esac
""")
(runtime/'ssh-session').chmod(0o755)
(runtime/'bashrc').write_text(r"""case "$-" in *i*) ;; *) return ;; esac
[ ! -r /run/platform-shell/environment.sh ] || . /run/platform-shell/environment.sh
export SHELL=/bin/bash
export USER="$(id -un)"
export LOGNAME="$USER"
umask 0002
PS1='\u@Ubuntu:\w\$ '
if [ -r /usr/share/bash-completion/bash_completion ] && [ -z "${BASH_COMPLETION_VERSINFO:-}" ]; then
    . /usr/share/bash-completion/bash_completion
fi
alias ll='ls -alF'
alias la='ls -A'
if [ "$PWD" = "$HOME" ] || [ "$PWD" = / ]; then cd /workspace; fi
""")
hook='\n# BEGIN PLATFORM SHELL\n[ ! -r /run/platform-shell/bashrc ] || . /run/platform-shell/bashrc\n# END PLATFORM SHELL\n'
home=Path.home()
home.mkdir(parents=True,exist_ok=True)
login=next((home/name for name in ('.bash_profile','.bash_login','.profile') if (home/name).is_file()),home/'.bash_profile')
for path in (home/'.bashrc',login):
    content=path.read_text() if path.is_file() else ''
    if '# BEGIN PLATFORM SHELL' not in content:
        path.write_text(content+hook)
if os.geteuid()==0:
    passwd=Path('/etc/passwd')
    rows=passwd.read_text().splitlines()
    rows=[':'.join(row.split(':')[:-1]+['/bin/bash']) if row.startswith('root:') else row for row in rows]
    passwd.write_text('\n'.join(rows)+'\n')
'''
