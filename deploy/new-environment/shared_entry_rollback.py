from pathlib import Path
import subprocess,shutil,json,os
BASE=Path('/home/system/cpcloud-operations/shared-entry-20261015')
assert os.geteuid()==0

def run(*args,timeout=30):
    result=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
    return {'command':args[0], 'status':result.returncode}

results=[]
results.append(run('systemctl','stop','haproxy.service','cpcloud-entry-preview.service','cpcloud-ssh-preview.service'))
results.append(run('systemctl','stop','ssh.service','ssh.socket'))
for name in ['/etc/ssh/sshd_config.d/90-cpcloud-shared-entry.conf',
             '/etc/systemd/system/ssh.socket.d/zz-cpcloud-shared-entry.conf',
             '/etc/systemd/system/haproxy.service.d/cpcloud-shared-entry.conf']:
    path=Path(name)
    if path.exists(): path.unlink()
shutil.copy2(BASE/'haproxy.original.cfg','/etc/haproxy/haproxy.cfg')
results.append(run('systemctl','daemon-reload'))
results.append(run('systemctl','start','ssh.socket','ssh.service'))
state=json.loads((BASE/'original-unit-state.json').read_text())
for unit,values in state.items():
    results.append(run('systemctl','enable' if values['is-enabled']=='enabled' else 'disable',unit))
if state['haproxy.service']['is-active']=='active':
    results.append(run('systemctl','start','haproxy.service'))
published=Path('/etc/nginx/conf.d/cpcloud-published.conf')
if published.exists(): published.unlink()
results.append(run('nginx','-t'))
results.append(run('systemctl','reload','nginx'))
if (BASE/'backend.original.env').exists():
    # Undo only this publishing origin; never restore obsolete passwords or signing keys.
    environment=Path('/etc/cpcloud/backend.env')
    lines=environment.read_text().splitlines()
    for index,line in enumerate(lines):
        if line.startswith('CORS_ORIGINS='):
            origins=[v for v in line.partition('=')[2].split(',') if v!='http://10.72.63.42:64022']
            lines[index]='CORS_ORIGINS='+','.join(origins)
    environment.write_text('\n'.join(lines)+'\n')
    shutil.chown(environment,user='CPCloud',group='CPCloud')
    environment.chmod(0o600)
    results.append(run('systemctl','restart','computing-platform-backend'))
(BASE/'rollback-result.json').write_text(json.dumps(results,indent=2))
print('Rollback executed: original SSH listener and platform configuration restored; inspect result statuses.')
