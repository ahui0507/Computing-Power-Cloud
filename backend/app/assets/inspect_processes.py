"""Read-only inspection in the workload PID namespace. Never emit argv or environment."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.request import build_opener, ProxyHandler, Request


def text(value):
    return re.sub(r'[\x00-\x1f\x7f]', '', str(value))[:120]


def description(args, comm):
    if comm == 'sshd':
        return 'SSH 会话'
    if comm.startswith('tmux'):
        return 'tmux 会话'
    executable = Path(args[0]).name if args else comm
    if executable.startswith('python'):
        if '-m' in args:
            at = args.index('-m') + 1
            return text('python -m ' + args[at]) if at < len(args) else 'python'
        for arg in args[1:]:
            if arg == '-c':
                return 'python（内联程序）'
            if not arg.startswith('-'):
                return text('python ' + Path(arg).name)
    return text(executable)


def inspect(proc_root=Path('/proc')):
    started = time.monotonic()
    ticks = os.sysconf('SC_CLK_TCK')
    uptime = float((proc_root/'uptime').read_text().split()[0])
    processes, checked, base = [], True, None
    paths = sorted((p for p in proc_root.iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    if len(paths) > 4096:
        checked = False
    for path in paths[:4096]:
        if time.monotonic()-started > 3:
            checked = False
            break
        pid = int(path.name)
        if pid == os.getpid():
            continue
        try:
            stat = (path/'stat').read_text()
            fields = stat[stat.rfind(')')+2:].split()
            state, parent, birth = fields[0], int(fields[1]), int(fields[19])
            if state in ('Z', 'X'):
                continue
            with (path/'cmdline').open('rb') as handle:
                args = [a.decode(errors='replace') for a in handle.read(16384).split(b'\0') if a]
            comm = (path/'comm').read_text().strip()
        except FileNotFoundError:
            continue  # Normal exit during the sample.
        except (OSError, ValueError, IndexError):
            checked = False
            continue
        boot = any(Path(a).name in ('jupyter-lab', 'jupyter-notebook') for a in args[:2])
        boot = boot and '--port=8888' in args
        url = next((a.split('=', 1)[1] for a in args if a.startswith('--ServerApp.base_url=')), None)
        if boot and url:
            base = url
            continue
        # Only the platform SSH listener is infrastructure; logged-in SSH sessions remain visible.
        ssh_listener = ('/run/platform-ssh/sshd_config' in ' '.join(args)
                        and (('[listener]' in ' '.join(args)) or args[:3] == ['/usr/sbin/sshd', '-f', '/run/platform-ssh/sshd_config']))
        if ssh_listener or (pid == 1 and comm in ('tini', 'dumb-init')):
            continue
        name = description(args, comm)
        category = 'notebook' if any('ipykernel' in a for a in args[:5]) else \
                   'terminal' if comm in ('sshd', 'bash', 'sh', 'zsh', 'tmux: server', 'screen') or comm.startswith('tmux') else 'program'
        processes.append(dict(pid=pid, start_ticks=birth, name=name, category=category,
                              elapsed_seconds=max(0, int(uptime-birth/ticks))))
    sessions, kernels, notebooks_checked = [], [], False
    if base and base.startswith('/') and not base.startswith('//'):
        try:
            opener = build_opener(ProxyHandler({}))
            def get(resource):
                request = Request('http://127.0.0.1:8888'+base.rstrip('/')+'/api/'+resource,
                                  headers={'Authorization':'token '+os.environ.get('JUPYTER_TOKEN', '')})
                with opener.open(request, timeout=2) as response:
                    data = json.loads(response.read(1024*1024))
                if not isinstance(data, list) or len(data) > 200:
                    raise ValueError('Unexpected notebook data')
                return data
            sessions = get('sessions')
            names = {s.get('kernel', {}).get('id'): text(Path(s.get('path') or s.get('notebook', {}).get('path') or 'Notebook').name) for s in sessions}
            kernels = [dict(id=text(k['id']), name=names.get(k['id'], '未关联文件的内核'),
                            state=text(k.get('execution_state', 'unknown')),
                            connections=int(k.get('connections', 0))) for k in get('kernels')]
            notebooks_checked = True
        except Exception:
            pass
    tmux_sessions, tmux_checked = [], True
    if shutil.which('tmux'):
        try:
            result = subprocess.run(['tmux', 'list-sessions', '-F', '#{session_name}|#{session_windows}|#{session_attached}'],
                                    capture_output=True, text=True, timeout=1)
            if result.returncode == 0:
                for line in result.stdout.splitlines()[:200]:
                    name, windows, attached = line.rsplit('|', 2)
                    tmux_sessions.append(dict(name=text(name), windows=int(windows), attached=int(attached)))
            elif not any(s in result.stderr.lower() for s in ('no server running', 'no such file or directory')):
                tmux_checked = False
        except Exception:
            tmux_checked = False
    return dict(processes_checked=checked and len(processes) <= 200, processes=processes[:200],
                notebooks_checked=notebooks_checked, notebooks=kernels,
                tmux_checked=tmux_checked, tmux_sessions=tmux_sessions)


if __name__ == '__main__':
    print('INSTANCE_INSPECTION='+json.dumps(inspect(), ensure_ascii=False))
