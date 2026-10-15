from pathlib import Path
import subprocess,shutil,json,os,socket,time

BASE=Path('/home/system/cpcloud-operations/shared-entry-20261015')
assert os.geteuid()==0

def run(*args,allowed=(0,),timeout=30):
    p=subprocess.run(args,text=True,capture_output=True,timeout=timeout)
    if p.returncode not in allowed:
        raise RuntimeError(Path(args[0]).name+' failed ('+str(p.returncode)+'): '+p.stderr[:800])
    return p.stdout

def create(path,text,mode=0o644):
    p=Path(path); assert not p.exists(),str(p)
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text); p.chmod(mode)

assert run('systemctl','is-active','cpcloud-shared-entry-rollback.timer').strip()=='active'
assert not (BASE/'switch-complete.json').exists()
shutil.copy2('/etc/cpcloud/backend.env',BASE/'backend.original.env')
(BASE/'backend.original.env').chmod(0o600)
run('systemctl','stop','cpcloud-entry-preview.service','cpcloud-ssh-preview.service')

create('/etc/ssh/sshd_config.d/90-cpcloud-shared-entry.conf',
       '# Approved CPCloud protocol proxy; external SSH endpoint stays unchanged.\n'
       'Port 2222\nListenAddress 127.0.0.1\n'
       '# Proxied clients share loopback; real source is logged by HAProxy.\n'
       'PerSourcePenaltyExemptList 127.0.0.1\n')
create('/etc/systemd/system/ssh.socket.d/zz-cpcloud-shared-entry.conf',
       '[Socket]\nListenStream=\nListenStream=127.0.0.1:2222\n')
create('/etc/systemd/system/haproxy.service.d/cpcloud-shared-entry.conf',
       '[Unit]\nAfter=ssh.service nginx.service\nWants=ssh.service nginx.service\n')
run('/usr/sbin/sshd','-t')
effective=run('/usr/sbin/sshd','-T').splitlines()
assert [x for x in effective if x.startswith('port ')]==['port 2222']
assert [x for x in effective if x.startswith('listenaddress ')]==['listenaddress 127.0.0.1:2222']
run('haproxy','-c','-f',str(BASE/'haproxy.production.cfg'))
shutil.copy2(BASE/'haproxy.production.cfg','/etc/haproxy/haproxy.cfg')
Path('/etc/haproxy/haproxy.cfg').chmod(0o644)
run('systemctl','daemon-reload')
run('systemctl','stop','ssh.service','ssh.socket')
run('systemctl','start','ssh.socket','ssh.service')
with socket.create_connection(('127.0.0.1',2222),timeout=5) as probe:
    assert probe.recv(128).startswith(b'SSH-')
run('systemctl','restart','haproxy')
run('systemctl','enable','ssh.service','ssh.socket','haproxy.service')

environment=Path('/etc/cpcloud/backend.env')
lines=environment.read_text().splitlines()
origin='http://10.72.63.42:64022'
for index,line in enumerate(lines):
    if line.startswith('CORS_ORIGINS='):
        values=line.partition('=')[2].split(',')
        if origin not in values: values.append(origin)
        lines[index]='CORS_ORIGINS='+','.join(values)
environment.write_text('\n'.join(lines)+'\n'); environment.chmod(0o600)
shutil.chown(environment,user='CPCloud',group='CPCloud')
run('systemctl','restart','computing-platform-backend')
(BASE/'switch-complete.json').write_text(json.dumps({'switched':True,'public_url':origin,'ssh_internal':'127.0.0.1:2222'}))
print('Shared entry switched; automatic rollback remains armed until independent verification.')
