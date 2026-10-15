from pathlib import Path
import subprocess,shutil,json,os

BASE=Path('/home/system/cpcloud-operations/shared-entry-20261015')
STAGE=Path('/home/system/cpcloud-stage')
assert os.geteuid()==0
BASE.mkdir(mode=0o700)

def run(*args):
    p=subprocess.run(args,text=True,capture_output=True,timeout=30)
    if p.returncode: raise RuntimeError(Path(args[0]).name+' failed: '+p.stderr[:1000])
    return p.stdout

def create(path,content,mode=0o644):
    p=Path(path); assert not p.exists(),str(p)
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(content); p.chmod(mode)

state={}
for unit in ['ssh.service','ssh.socket','haproxy.service']:
    state[unit]={}
    for flag in ['is-enabled','is-active']:
        p=subprocess.run(['systemctl',flag,unit],text=True,capture_output=True)
        state[unit][flag]=p.stdout.strip()
(BASE/'original-unit-state.json').write_text(json.dumps(state,indent=2))
shutil.copy2('/etc/haproxy/haproxy.cfg',BASE/'haproxy.original.cfg')
shutil.copy2('/etc/ssh/sshd_config',BASE/'sshd.original.conf')
old=Path('/etc/haproxy/haproxy.cfg').read_text()
import re
assert not re.search(r'(?m)^\s*(frontend|backend|listen)\s',old),'Unexpected existing HAProxy deployment'
published=STAGE/'nginx-shared-entry.conf.example'
create('/etc/nginx/conf.d/cpcloud-published.conf',published.read_text())
run('nginx','-t'); run('systemctl','reload','nginx')

candidate=(STAGE/'haproxy-ssh-web.cfg.example').read_text().replace(
    '# DRAFT: requires explicit approval before installing HAProxy or changing SSH listeners.',
    '# Approved CPCloud shared SSH/HTTP entry.')
create(BASE/'haproxy.production.cfg',candidate,0o600)
preview=candidate.replace('    bind 0.0.0.0:22\n    bind [::]:22 v6only', '    bind 127.0.0.1:18081')
frontend=preview.split('frontend cpcloud_shared_entry\n',1)[1].split('\nbackend cpcloud_web',1)[0]
frontend=frontend.replace('bind 127.0.0.1:18081','bind 127.0.0.1:18082 accept-proxy')
preview+='\n# Private test listener for simulated source-address metadata; never published.\nfrontend cpcloud_source_preview\n'+frontend+'\n'
create(BASE/'haproxy.preview.cfg',preview,0o600)
run('haproxy','-c','-f',str(BASE/'haproxy.production.cfg'))
run('haproxy','-c','-f',str(BASE/'haproxy.preview.cfg'))

create('/etc/systemd/system/cpcloud-ssh-preview.service','''[Unit]
Description=CPCloud private SSH preview
After=ssh.service
[Service]
Type=simple
ExecStartPre=/usr/sbin/sshd -t
ExecStart=/usr/sbin/sshd -D -p 2222 -o ListenAddress=127.0.0.1 -o PidFile=/run/cpcloud-ssh-preview.pid -o PerSourcePenaltyExemptList=127.0.0.1
KillMode=process
Restart=on-failure
''')
create('/etc/systemd/system/cpcloud-entry-preview.service',f'''[Unit]
Description=CPCloud private protocol preview
After=cpcloud-ssh-preview.service nginx.service
[Service]
Type=simple
ExecStart=/usr/sbin/haproxy -W -db -f {BASE}/haproxy.preview.cfg
Restart=on-failure
''')
run('systemctl','daemon-reload')
run('systemctl','start','cpcloud-ssh-preview.service','cpcloud-entry-preview.service')
print('Prepared production configuration and private previews; original SSH still listens on TCP 22.')
