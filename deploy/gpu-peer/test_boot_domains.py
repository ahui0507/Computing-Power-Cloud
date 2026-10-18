"""Exercise boot failure paths against synthetic PCI devices, without GPU writes."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('boot_guard',HERE/'verify_boot_domains.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


class BootDomainTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.sysfs=self.root/'pci';self.sysfs.mkdir()
        self.rows=[]
        for index,address in enumerate(('0000:3d:00.0','0000:3e:00.0')):
            self.device(address,'0x10de','0x20f1','0x030200')
            self.rows.append({'pci':address,'index':index,'uuid':f'GPU-test-{index}',
                              'device':'0x20f1','class':'0x030200'})
        self.device('0000:01:00.0','0x8086','0x1234','0x020000')
        self.config=self.root/'early.conf'
        self.config.write_text(''.join(f"{r['pci']} {r['device']} {r['class']}\n" for r in self.rows))
        self.state=self.root/'state'

    def device(self,address,vendor,device,pci_class):
        path=self.sysfs/address;path.mkdir()
        for name,value in (('vendor',vendor),('device',device),('class',pci_class)):
            (path/name).write_text(value)
        (path/'iommu_group/devices'/address).mkdir(parents=True)
        (path/'iommu_group/type').write_text('DMA-FQ')
        return path

    def apply(self):
        env=dict(os.environ,CPCLOUD_GPU_SYSFS=str(self.sysfs),CPCLOUD_GPU_CONFIG=str(self.config),CPCLOUD_GPU_STATE=str(self.state))
        subprocess.run(['sh',str(HERE/'initramfs-gpu-domains.sh')],env=env,check=True,timeout=10)
        return self.state.read_text().strip()

    def domains(self):
        return {p.name:(p/'iommu_group/type').read_text().strip() for p in self.sysfs.iterdir()}

    def test_only_approved_gpu_domains_change_and_apply_is_idempotent(self):
        self.assertEqual(self.apply(),'applied:identity:2')
        self.assertEqual(self.domains()['0000:01:00.0'],'DMA-FQ')
        self.assertEqual(self.apply(),'applied:identity:2')

    def test_bound_driver_prevents_all_changes(self):
        (self.sysfs/self.rows[1]['pci']/'driver').mkdir()
        self.assertEqual(self.apply(),'failed:driver-already-bound')
        self.assertEqual(set(self.domains().values()),{'DMA-FQ'})

    def test_shared_group_prevents_all_changes(self):
        (self.sysfs/self.rows[1]['pci']/'iommu_group/devices/0000:02:00.0').mkdir()
        self.assertEqual(self.apply(),'failed:shared-iommu-group')
        self.assertEqual(set(self.domains().values()),{'DMA-FQ'})

    def test_additional_gpu_requires_explicit_inventory_review(self):
        self.device('0000:40:00.0','0x10de','0x20f1','0x030200')
        self.assertEqual(self.apply(),'failed:unapproved-gpu')
        self.assertEqual(set(self.domains().values()),{'DMA-FQ'})

    def test_duplicate_manifest_cannot_hide_an_unapproved_gpu(self):
        self.config.write_text('0000:3d:00.0 0x20f1 0x030200\n'*2)
        self.assertEqual(self.apply(),'failed:duplicate-gpu')
        self.assertEqual(set(self.domains().values()),{'DMA-FQ'})

    def test_startup_guard_rejects_uuid_index_and_domain_drift(self):
        self.apply()
        driver=self.root/'nvidia';driver.mkdir()
        for row in self.rows:(self.sysfs/row['pci']/'driver').symlink_to(driver)
        config={'gpus':self.rows,'non_gpu_domains':{'0000:01:00.0':'DMA-FQ'}}
        output=''.join(f"{r['index']}, {r['uuid']}, {r['pci']}\n" for r in self.rows)
        self.assertTrue(guard.verify(config,self.sysfs,output)['gpu_domains_verified'])
        with self.assertRaises(RuntimeError):guard.verify(config,self.sysfs,output.replace('GPU-test-0','GPU-other'))
        (self.sysfs/self.rows[0]['pci']/'iommu_group/type').write_text('DMA-FQ')
        with self.assertRaises(RuntimeError):guard.verify(config,self.sysfs,output)

    def test_non_gpu_domain_drift_blocks_startup(self):
        self.apply()
        driver=self.root/'nvidia';driver.mkdir()
        for row in self.rows:(self.sysfs/row['pci']/'driver').symlink_to(driver)
        config={'gpus':self.rows,'non_gpu_domains':{'0000:01:00.0':'DMA-FQ'}}
        (self.sysfs/'0000:01:00.0/iommu_group/type').write_text('identity')
        with self.assertRaises(RuntimeError):guard.verify(config,self.sysfs,'')


if __name__=='__main__':unittest.main()
