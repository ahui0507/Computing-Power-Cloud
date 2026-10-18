"""Read-only startup gate: require the approved GPU domains and stable identity."""
import argparse
import json
from pathlib import Path
import subprocess


def verify(config, sysfs=Path('/sys/bus/pci/devices'), gpu_output=None):
    expected=config['gpus']
    approved={row['pci'] for row in expected}
    actual_gpu_addresses={path.name for path in sysfs.iterdir()
                          if (path/'vendor').read_text().strip()=='0x10de'
                          and (path/'class').read_text().strip().startswith('0x03')}
    if approved!=actual_gpu_addresses:
        raise RuntimeError('GPU PCI inventory changed; leave workloads stopped')
    for row in expected:
        path=sysfs/row['pci']
        for field,value in (('vendor','0x10de'),('device',row['device']),('class',row['class'])):
            if (path/field).read_text().strip()!=value:
                raise RuntimeError('GPU hardware identity changed: '+row['pci'])
        if sorted(p.name for p in (path/'iommu_group/devices').iterdir())!=[row['pci']]:
            raise RuntimeError('GPU IOMMU group is shared: '+row['pci'])
        if (path/'iommu_group/type').read_text().strip()!='identity':
            raise RuntimeError('GPU identity domain missing: '+row['pci'])
        if (path/'driver').resolve().name!='nvidia':
            raise RuntimeError('NVIDIA driver not bound: '+row['pci'])
    non_gpu={path.name:(path/'iommu_group/type').read_text().strip() for path in sysfs.iterdir()
             if path.name not in approved and (path/'iommu_group/type').exists()}
    if non_gpu!=config['non_gpu_domains']:
        raise RuntimeError('Non-GPU IOMMU domains changed; review before scheduling')
    if gpu_output is None:
        gpu_output=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,pci.bus_id',
                                           '--format=csv,noheader'],text=True,timeout=45)
    actual=[]
    for line in gpu_output.splitlines():
        index,uuid,bus=[item.strip() for item in line.split(',')]
        bus=bus.lower()
        if bus.startswith('00000000:'):bus='0000:'+bus.split(':',1)[1]
        actual.append((int(index),uuid,bus))
    if sorted(actual)!=sorted((row['index'],row['uuid'],row['pci']) for row in expected):
        raise RuntimeError('GPU indices/UUIDs changed; leave workloads stopped')
    return {'gpu_domains_verified':True,'gpu_count':len(expected),'domain':'identity',
            'non_gpu_domains_unchanged':True,'indices_and_uuids_verified':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('/etc/cpcloud/gpu-domains.json'))
    args=parser.parse_args()
    print(json.dumps(verify(json.loads(args.config.read_text()))),flush=True)
