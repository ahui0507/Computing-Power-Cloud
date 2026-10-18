"""Read-only plan for GPU-only IOMMU default-domain maintenance."""
import json
import os
from pathlib import Path
import stat
import subprocess

inventory = subprocess.check_output([
    'nvidia-smi', '--query-gpu=index,uuid,pci.bus_id,name,driver_version,memory.used,utilization.gpu',
    '--format=csv,noheader,nounits',
], text=True)
devices = []
for line in inventory.strip().splitlines():
    index, uuid, bus, name, driver, memory, utilization = [field.strip() for field in line.split(',')]
    bus = bus.lower()
    if bus.startswith('00000000:'):bus = '0000:' + bus.split(':', 1)[1]
    path = Path('/sys/bus/pci/devices') / bus
    assert (path/'vendor').read_text().strip() == '0x10de'
    assert (path/'class').read_text().strip().startswith('0x03')
    group = (path/'iommu_group').resolve()
    members = sorted(item.name for item in (group/'devices').iterdir())
    assert members == [bus], 'Refuse groups shared with other PCI devices'
    domain = (group/'type').read_text().strip()
    mode = (group/'type').stat().st_mode
    devices.append({'index':int(index),'uuid':uuid,'pci':bus,'name':name,'driver_version':driver,
                    'memory_used_mb':int(memory),'utilization_percent':int(utilization),
                    'group':group.name,'group_members':members,'current_domain':domain,
                    'type_owner_writable':bool(mode & stat.S_IWUSR),
                    'bound_driver':(path/'driver').resolve().name})
assert len(devices) == 8
assert all(row['current_domain'] == 'DMA-FQ' for row in devices)
report = {'read_only':True,'gpu_only_candidate':devices,'requires_driver_unbind':True,
          'proposed_domain':'identity','gpu_dma_remapping_would_be_disabled':True,
          'non_gpu_domains_would_remain_unchanged':True,'changes_applied':False}
print(json.dumps(report,indent=2))
