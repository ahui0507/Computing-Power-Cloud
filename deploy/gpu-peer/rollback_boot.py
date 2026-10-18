"""Remove only this deployment's files and restore its exact saved initramfs.

Run during fenced GPU maintenance with clients stopped, then restore runtime
GPU domains using the saved inventory and switch_gpu_domains.py --restore.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--record',type=Path,required=True)
args=parser.parse_args()
record=json.loads(args.record.read_text())
allowed={'/etc/initramfs-tools/scripts/init-top/00-cpcloud-gpu-domains',
         '/etc/initramfs-tools/hooks/cpcloud-gpu-domains','/usr/local/sbin/cpcloud-verify-gpu-domains',
         '/etc/systemd/system/cpcloud-gpu-domains.service','/etc/cpcloud/gpu-domains.json',
         '/etc/cpcloud/gpu-domains-early.conf','/etc/systemd/system/k3s-agent.service.d/gpu-domains.conf',
         '/etc/systemd/system/platform-worker-agent.service.d/gpu-domains.conf',
         '/etc/systemd/system/platform-monitor-agent.service.d/gpu-domains.conf'}
if not set(record['files']).issubset(allowed):raise RuntimeError('Unexpected rollback paths')
backup=Path(record['backup']);image=Path(record['initrd'])
if image!=Path('/boot')/('initrd.img-'+record['kernel']):raise RuntimeError('Unexpected boot image')
if hashlib.sha256(backup.read_bytes()).hexdigest()!=record['original_initrd_sha256']:
    raise RuntimeError('Backup checksum failed')
subprocess.run(['systemctl','disable','--now','cpcloud-gpu-domains'],check=True)
for name in record['files']:Path(name).unlink(missing_ok=True)
shutil.copy2(backup,image)
subprocess.run(['systemctl','daemon-reload'],check=True)
print(json.dumps({'original_initramfs_restored':True,'runtime_domains_still_require_fenced_restoration':True}))
