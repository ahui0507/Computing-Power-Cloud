"""GPU-only IOMMU maintenance. Default is a read-only plan; execution is gated."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--inventory',type=Path,required=True)
parser.add_argument('--indices',default='0,1')
parser.add_argument('--restore',action='store_true')
parser.add_argument('--execute',action='store_true')
parser.add_argument('--maintenance-proof',type=Path)
parser.add_argument('--record',type=Path)
args=parser.parse_args()
inventory=json.loads(args.inventory.read_text())['gpu_only_candidate']
selected={int(value) for value in args.indices.split(',')}
devices=[row for row in inventory if row['index'] in selected]
assert len(devices)==len(selected) and devices
all_gpu_addresses={row['pci'] for row in inventory}
def non_gpu_domains():
    result={}
    for path in Path('/sys/bus/pci/devices').iterdir():
        if path.name not in all_gpu_addresses and (path/'iommu_group/type').exists():
            result[path.name]=(path/'iommu_group/type').read_text().strip()
    return result
def validate(row):
    path=Path('/sys/bus/pci/devices')/row['pci']
    assert (path/'vendor').read_text().strip()=='0x10de'
    assert (path/'class').read_text().strip().startswith('0x03')
    assert sorted(item.name for item in (path/'iommu_group/devices').iterdir())==[row['pci']]
    assert (path/'iommu_group').resolve().name==row['group']
    return path
plan=[]
for row in devices:
    path=validate(row)
    plan.append({'pci':row['pci'],'group':row['group'],'current':(path/'iommu_group/type').read_text().strip(),'requested':row['current_domain'] if args.restore else 'identity'})
if not args.execute:
    print(json.dumps({'changes_applied':False,'plan':plan,'requires_maintenance_and_user_approval':True},indent=2))
    raise SystemExit(0)
assert args.record and args.maintenance_proof
proof=json.loads(args.maintenance_proof.read_text())
assert proof['gpu_identity_domain_approved'] is True
assert selected.issubset(set(proof.get('approved_gpu_indices',[6,7]))),'Selected GPUs exceed the approved maintenance scope'
assert proof['node_database_status']=='maintenance' and proof['kubernetes_unschedulable'] is True
assert proof['active_workloads']==0 and proof['gpu_plugin_stopped'] is True
age=datetime.now(timezone.utc).timestamp()-proof['created_at_utc_timestamp']
assert 0<=age<300,'Maintenance state must be rechecked immediately before execution'
device_files=[str(p) for p in Path('/dev').glob('nvidia*') if p.is_char_device()]
assert device_files,'NVIDIA device files missing'
clients=subprocess.run(['fuser',*device_files],capture_output=True,text=True,timeout=15)
assert clients.returncode==1,'GPU clients remain open; do not unbind devices'
before=non_gpu_domains()
unselected_before={row['pci']:(validate(row)/'iommu_group/type').read_text().strip() for row in inventory if row['index'] not in selected}
record={'started_at':datetime.now(timezone.utc).isoformat(),'requested':plan,'completed':[],'non_gpu_domains_before':before,'unselected_gpu_domains_before':unselected_before}
args.record.write_text(json.dumps(record,indent=2));args.record.chmod(0o600)
def switch(row,requested):
    path=validate(row)
    if (path/'iommu_group/type').read_text().strip()==requested:return
    driver=Path('/sys/bus/pci/drivers/nvidia')
    if (path/'driver').exists():
        assert (path/'driver').resolve()==driver
        (driver/'unbind').write_text(row['pci'])
    try:
        assert not (path/'driver').exists()
        (path/'iommu_group/type').write_text(requested)
        assert (path/'iommu_group/type').read_text().strip()==requested
    finally:
        if not (path/'driver').exists():(driver/'bind').write_text(row['pci'])
    assert (path/'driver').resolve()==driver
try:
    for row in devices:
        switch(row,row['current_domain'] if args.restore else 'identity')
        record['completed'].append(row['pci'])
        args.record.write_text(json.dumps(record,indent=2))
        print(json.dumps({'device_rebound':row['pci'],'domain':(validate(row)/'iommu_group/type').read_text().strip()}),flush=True)
    assert non_gpu_domains()==before,'A non-GPU domain changed unexpectedly'
    assert all((Path('/sys/bus/pci/devices')/pci/'iommu_group/type').read_text().strip()==value for pci,value in unselected_before.items()),'An unselected GPU domain changed unexpectedly'
    record['non_gpu_domains_unchanged']=True
    record['unselected_gpu_domains_unchanged']=True
    record['finished_at']=datetime.now(timezone.utc).isoformat()
    args.record.write_text(json.dumps(record,indent=2))
except BaseException:
    errors=[]
    for row in reversed(devices):
        try:switch(row,row['current_domain'])
        except Exception as error:errors.append({'pci':row['pci'],'error':str(error)})
    record['rollback_errors']=errors
    record['rolled_back']=not errors
    args.record.write_text(json.dumps(record,indent=2))
    raise
