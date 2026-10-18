from dataclasses import replace
from datetime import datetime,timedelta
import json

from app.core.config import settings
from app.infrastructure.kubernetes.manifests import build_pod,WorkloadSpec
from app.models import Allocation, Notice, User
from app.services.operational_alert_service import OperationalAlertService
from app.services.maintenance_service import MaintenanceService


def spec():
    return WorkloadSpec(allocation_id=1,user_id=1,pod_name='pod-1',image='test',gpu_count=2,node_name='worker',
                        namespace='default',ingress_enabled=False,ingress_host='localhost',ingress_class='traefik',
                        use_tls=False,image_pull_policy='Never',jupyter_command='jupyter-lab',jupyter_token='test',workspace_claim='workspaces')


def test_scratch_budget_excludes_persistent_data_and_memory_shm():
    manifest=build_pod(replace(spec(),storage_layout='separate-v1',ssh_enabled=True,ephemeral_storage_gib=80))
    resources=manifest['spec']['containers'][0]['resources']
    assert resources['requests']['ephemeral-storage']==resources['limits']['ephemeral-storage']=='80Gi'
    for volume in manifest['spec']['volumes']:
        if 'persistentVolumeClaim' in volume:assert 'sizeLimit' not in volume
        elif volume.get('emptyDir',{}).get('medium')=='Memory':assert volume['emptyDir']['sizeLimit']=='1Gi'
        elif 'emptyDir' in volume:assert volume['emptyDir']['sizeLimit']=='256Mi'


def test_new_create_freezes_disk_budget_without_changing_legacy_operations(db,monkeypatch):
    from app.services.operation_service import OperationService
    from app.models import Node
    node=db.query(Node).first()
    monkeypatch.setattr(settings,'WORKLOAD_EPHEMERAL_GIB_PER_GPU',40)
    payload=OperationService.creation_payload(node,'localhost','jupyter-lab',gpu_count=2)
    monkeypatch.setattr(settings,'WORKLOAD_EPHEMERAL_GIB_PER_GPU',60)
    assert payload['options']['ephemeral_storage_gib']==80
    assert OperationService.creation_payload(node,'localhost','jupyter-lab')['options']['ephemeral_storage_gib'] is None
    assert 'ephemeral-storage' not in build_pod(spec())['spec']['containers'][0]['resources']['limits']


def test_operator_can_disable_backup_reminders_and_resolve_existing_notices(db,monkeypatch):
    db.get(User,2).role_id=1
    now=datetime.utcnow()
    db.add(Notice(user_id=2,dedup_key='ops:backup:unavailable:'+str(now.date()),title='备份状态需要处理',message='old',expires_at=now+timedelta(days=1)))
    db.commit()
    monkeypatch.setattr(settings,'BACKUP_ALERTS_ENABLED',False)
    def forbidden():raise AssertionError('Backup monitoring must not run after operator opt-out')
    monkeypatch.setattr(MaintenanceService,'status',forbidden)
    OperationalAlertService.refresh(db,now)
    assert db.query(Notice).filter(Notice.dedup_key.like('ops:backup:%'),Notice.expires_at>now).count()==0


def test_worker_progress_retains_last_completion_while_a_cycle_is_running(tmp_path,monkeypatch):
    from app.core.worker_heartbeat import record_worker_cycle
    path=tmp_path/'worker.json';monkeypatch.setattr(settings,'RECONCILIATION_HEARTBEAT_FILE',str(path))
    record_worker_cycle('ok',summary={'errors':0});completed=json.loads(path.read_text())['last_completed_at']
    record_worker_cycle('running');assert json.loads(path.read_text())['last_completed_at']==completed
    record_worker_cycle('error');assert json.loads(path.read_text())['state']=='error'


def test_failed_heartbeat_io_does_not_prevent_resource_processing(tmp_path,monkeypatch):
    from app.core.worker_heartbeat import record_worker_cycle
    monkeypatch.setattr(settings,'RECONCILIATION_HEARTBEAT_FILE',str(tmp_path/'missing'/'heartbeat.json'))
    record_worker_cycle('running')


def test_invalid_heartbeat_state_is_replaced_without_blocking_processing(tmp_path,monkeypatch):
    from app.core.worker_heartbeat import record_worker_cycle
    path=tmp_path/'heartbeat.json';path.write_text('[]')
    monkeypatch.setattr(settings,'RECONCILIATION_HEARTBEAT_FILE',str(path))
    record_worker_cycle('ok',summary={'errors':0})
    assert json.loads(path.read_text())['last_completed_at']


def test_retry_rejects_owned_pod_with_a_different_temporary_disk_limit():
    from unittest.mock import MagicMock
    import pytest
    from kubernetes.client import ApiClient
    from kubernetes.client.exceptions import ApiException
    from app.core.exceptions import ClusterOperationError
    from app.infrastructure.kubernetes.gateway import KubernetesGateway
    workload=replace(spec(),ephemeral_storage_gib=80)
    manifest=build_pod(workload)
    actual=ApiClient()._ApiClient__deserialize(manifest,'V1Pod')
    actual.spec.containers[0].resources.limits['ephemeral-storage']='40Gi'
    core=MagicMock();core.create_namespaced_pod.side_effect=ApiException(status=409)
    core.read_namespaced_pod.return_value=actual
    gateway=KubernetesGateway(core,MagicMock())
    with pytest.raises(ClusterOperationError,match='临时磁盘'):
        gateway._ensure(core.create_namespaced_pod,core.read_namespaced_pod,manifest,workload,'pod')
    core.delete_namespaced_pod.assert_not_called()
