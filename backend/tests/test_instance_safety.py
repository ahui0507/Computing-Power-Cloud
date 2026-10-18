from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient
from jose import jwt
import pytest

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.infrastructure.kubernetes import ephemeral_storage as disk
from app.main import app
from app.models import Allocation, AllocationStatus, GPU, Notice, User
from app.services.job_service import JobService
from app.services.k8s_service import K8sService
from app.services.release_inspection_service import ReleaseInspectionService as Inspection
from app.services.temporary_storage_monitor import refresh_temporary_storage


def pod(uid='owned', limit='40Gi'):
    return NS(metadata=NS(name='pod', uid=uid), spec=NS(node_name='worker',
        containers=[NS(resources=NS(limits={'ephemeral-storage':limit} if limit else {}))]))


def summary(used=35*1024**3, uid='owned', at=None):
    return {'pods':[{'podRef':dict(name='pod',namespace='tenant',uid=uid),
        'ephemeral-storage':{'usedBytes':used,'time':(at or datetime.now(timezone.utc)).isoformat()},
        'volume':[{'name':'persistent-data','usedBytes':999*1024**3}, {'name':'shm','usedBytes':1024**3}]}]}


@pytest.fixture
def core():
    disk._cache.clear()
    value=Mock();value.api_client.configuration.host='test-only'
    value.api_client.call_api.return_value=summary()
    return value


def test_disk_uses_kubelet_ephemeral_total_and_actual_limit_without_pvc_or_shm(core):
    result=disk.storage_from_pod(core,pod(),'tenant')
    assert result['state']=='live' and result['used_bytes']==35*1024**3
    assert result['limit_bytes']==40*1024**3 and result['remaining_bytes']==5*1024**3
    assert result['warning']=='warning' and result['used_percent']==87.5


@pytest.mark.parametrize('uid,namespace',[('different-pod','tenant'),('owned','other-tenant')])
def test_disk_sample_requires_namespace_name_and_exact_pod_uid(core,uid,namespace):
    core.api_client.call_api.return_value=summary(uid=uid)
    result=disk.storage_from_pod(core,pod(),namespace)
    assert result['state']=='missing' and result['used_bytes'] is None


@pytest.mark.parametrize('age',[-90,121])
def test_stale_or_future_sample_is_not_zero_or_recovery(core,age):
    core.api_client.call_api.return_value=summary(at=datetime.now(timezone.utc)-timedelta(seconds=age))
    result=disk.storage_from_pod(core,pod(),'tenant')
    assert result['state']=='stale' and result['used_bytes'] is None and result['warning']=='unknown'


@pytest.mark.parametrize('used,warning,remaining',[(0,'none',40),(36,'critical',4),(41,'critical',0)])
def test_zero_and_over_limit_are_real_measurements(core,used,warning,remaining):
    core.api_client.call_api.return_value=summary(used=used*1024**3)
    result=disk.storage_from_pod(core,pod(),'tenant')
    assert result['state']=='live' and result['used_bytes']==used*1024**3
    assert result['warning']==warning and result['remaining_bytes']==remaining*1024**3


def test_node_summary_is_cached_including_failures(core):
    core.api_client.call_api.side_effect=RuntimeError('node offline')
    for _ in range(8):assert disk.storage_from_pod(core,pod(),'tenant')['state']=='missing'
    assert core.api_client.call_api.call_count==1


def test_legacy_no_limit_reports_usage_without_inventing_remaining_space(core):
    result=disk.storage_from_pod(core,pod(limit=None),'tenant')
    assert result['used_bytes']==35*1024**3 and result['limit_bytes'] is None
    assert result['remaining_bytes'] is None and result['used_percent'] is None


def test_user_disk_reminders_deduplicate_escalate_and_keep_unknown_distinct(db,monkeypatch):
    now=datetime.utcnow()
    allocation=Allocation(request_id='storage-alert-test',user_id=1,container_id='owned-instance',requested_gpu_count=1,gpu_type_id=1,status=AllocationStatus.ACTIVE)
    db.add(allocation);db.commit()
    sample=dict(state='live',used_percent=85,warning='warning')
    monkeypatch.setattr('app.services.temporary_storage_monitor.pod_storage_usage',lambda *a:sample)
    refresh_temporary_storage(db,[allocation],now);refresh_temporary_storage(db,[allocation],now)
    assert db.query(Notice).count()==1 and db.query(Notice).one().user_id==1
    sample.update(used_percent=92,warning='critical');refresh_temporary_storage(db,[allocation],now)
    assert db.query(Notice).count()==2 and db.query(Notice).filter_by(severity='critical').count()==1
    sample.update(state='missing',warning='unknown');refresh_temporary_storage(db,[allocation],now)
    assert db.query(Notice).filter(Notice.expires_at>now).count()==2
    sample.update(state='live',warning='none');refresh_temporary_storage(db,[allocation],now)
    assert db.query(Notice).filter(Notice.expires_at>now).count()==0


@pytest.fixture
def runtime():
    return dict(pod_uid='owned-pod',processes_checked=True,notebooks_checked=True,tmux_checked=True,
        processes=[dict(pid=100,start_ticks=1000,name='python train.py',category='program',elapsed_seconds=90)],
        notebooks=[dict(id='kernel-1',name='train.ipynb',state='idle',connections=1)],tmux_sessions=[])


@pytest.fixture
def client(db,monkeypatch,runtime):
    monkeypatch.setattr(settings,'INSTANCE_SAFETY_ENABLED',True)
    monkeypatch.setattr(Inspection,'inspect_runtime',lambda allocation:deepcopy(runtime))
    monkeypatch.setattr(JobService,'list',lambda *a:[])
    monkeypatch.setattr(K8sService,'create_pod',AsyncMock(return_value={'status':'running'}))
    monkeypatch.setattr(K8sService,'get_pod_status',AsyncMock(return_value='running'))
    monkeypatch.setattr(K8sService,'delete_pod',AsyncMock())
    app.dependency_overrides[get_db]=lambda:db
    app.dependency_overrides[get_current_user]=lambda:db.get(User,1)
    with TestClient(app,raise_server_exceptions=False) as value:yield value
    app.dependency_overrides.clear()


def create(client,key='safety'):
    response=client.post('/resource/apply',json=dict(pool_id=1,gpu_count=1,image_id=1),headers={'Idempotency-Key':key})
    assert response.status_code==200,response.text
    return response.json()['data']['container_id']


def check(client,id):return client.get(f'/resource/{id}/release-check').json()['data']
def release(client,id,token=None,**extra):
    return client.post('/resource/release',json=dict(container_id=id,confirmation_token=token,**extra))


def test_manual_release_requires_current_confirmation_and_keeps_retries_idempotent(client,db):
    id=create(client);snapshot=check(client,id)
    assert snapshot['processes'][0]['name']=='python train.py' and snapshot['notebooks'][0]['name']=='train.ipynb'
    assert release(client,id).status_code==409
    assert db.query(Allocation).one().status==AllocationStatus.ACTIVE
    assert release(client,id,snapshot['confirmation_token']).status_code==200
    assert all(g.allocation_id is None for g in db.query(GPU))
    assert release(client,id,snapshot['confirmation_token']).status_code==200


@pytest.mark.parametrize('change',['new_process','pid_reused','new_kernel','kernel_busy','new_tmux'])
def test_changed_runtime_requires_review_before_any_gpu_is_released(client,db,runtime,change):
    id=create(client);token=check(client,id)['confirmation_token']
    if change=='new_process':runtime['processes'].append(dict(pid=200,start_ticks=2000,name='python new.py',category='program',elapsed_seconds=0))
    elif change=='pid_reused':runtime['processes'][0]['start_ticks']+=1
    elif change=='new_kernel':runtime['notebooks'].append(dict(id='kernel-2',name='new.ipynb',state='idle',connections=1))
    elif change=='kernel_busy':runtime['notebooks'][0]['state']='busy'
    else:runtime['tmux_sessions'].append(dict(name='training',windows=1,attached=0))
    assert release(client,id,token).status_code==409
    assert db.query(Allocation).one().status==AllocationStatus.ACTIVE
    assert db.query(GPU).filter(GPU.allocation_id.isnot(None)).count()==1


def test_elapsed_time_is_not_treated_as_new_activity(client,runtime):
    id=create(client);token=check(client,id)['confirmation_token'];runtime['processes'][0]['elapsed_seconds']+=60
    assert release(client,id,token).status_code==200


def test_confirmation_cannot_target_another_instance_or_user(client,db):
    first=create(client,'first');second=create(client,'second');token=check(client,first)['confirmation_token']
    assert release(client,second,token).status_code==409
    app.dependency_overrides[get_current_user]=lambda:db.get(User,2)
    assert client.get(f'/resource/{first}/release-check').status_code==404
    assert release(client,first,token).status_code==404


@pytest.mark.parametrize('expired,kind',[(True,'release-confirmation'),(False,'access')])
def test_expired_or_wrong_purpose_confirmation_is_rejected(client,expired,kind):
    id=create(client);claims=jwt.decode(check(client,id)['confirmation_token'],settings.SECRET_KEY,algorithms=[settings.ALGORITHM])
    claims['type']=kind
    if expired:claims['exp']=int(datetime.now(timezone.utc).timestamp())-1
    token=jwt.encode(claims,settings.SECRET_KEY,algorithm=settings.ALGORITHM)
    assert release(client,id,token).status_code==409


def test_partial_probe_needs_explicit_unknown_state_confirmation(client,runtime):
    runtime['notebooks_checked']=False
    id=create(client);snapshot=check(client,id)
    assert not snapshot['checks_complete']
    assert release(client,id,snapshot['confirmation_token']).status_code==409
    assert release(client,id,snapshot['confirmation_token'],confirm_unchecked=True).status_code==200


def test_probe_never_executes_in_a_pod_owned_by_someone_else(db,monkeypatch):
    monkeypatch.setattr(settings,'INSTANCE_SAFETY_ENABLED',True)
    core,network=Mock(),Mock()
    core.read_namespaced_pod.return_value=NS(metadata=NS(labels={'user-id':'2','allocation-id':'1'},uid='other'))
    monkeypatch.setattr('app.services.release_inspection_service.create_clients',lambda:(core,network))
    execute=Mock();monkeypatch.setattr('app.services.release_inspection_service.stream',execute)
    value=Inspection.inspect_runtime(NS(id=1,user_id=1,pod_name='same-name',operations=[]))
    assert not value['processes_checked'] and value['pod_uid'] is None
    execute.assert_not_called()


def test_probe_uses_isolated_python_bounded_stream_and_closes_channel(monkeypatch,runtime):
    monkeypatch.setattr(settings,'INSTANCE_SAFETY_ENABLED',True)
    core,network=Mock(),Mock()
    core.read_namespaced_pod.return_value=NS(metadata=NS(labels={'user-id':'1','allocation-id':'1'},uid='owned-pod'))
    monkeypatch.setattr('app.services.release_inspection_service.create_clients',lambda:(core,network))
    channel=Mock();channel.is_open.side_effect=[True,False];channel.returncode=0
    channel.read_stdout.return_value='INSTANCE_INSPECTION='+json.dumps(runtime);channel.read_stderr.return_value=''
    execute=Mock(return_value=channel);monkeypatch.setattr('app.services.release_inspection_service.stream',execute)
    result=Inspection.inspect_runtime(NS(id=1,user_id=1,pod_name='pod',operations=[]))
    assert result['processes_checked'] and result['pod_uid']=='owned-pod'
    assert execute.call_args.kwargs['command'][:3]==['python','-I','-c']
    assert execute.call_args.kwargs['_preload_content'] is False
    channel.close.assert_called_once();core.api_client.close.assert_called_once()


def test_process_inspector_finds_ssh_python_notebooks_and_redacts_arguments(tmp_path,monkeypatch):
    path=Path(__file__).resolve().parents[1]/'app/assets/inspect_processes.py'
    spec=importlib.util.spec_from_file_location('inspect_asset',path);asset=importlib.util.module_from_spec(spec);spec.loader.exec_module(asset)
    (tmp_path/'uptime').write_text('1000.0 0')
    def process(pid,comm,args):
        root=tmp_path/str(pid);root.mkdir();fields=['S','1']+['0']*17+['1000']+['0']*4
        (root/'stat').write_text(f'{pid} ({comm}) '+' '.join(fields))
        (root/'comm').write_text(comm);(root/'cmdline').write_bytes(b'\0'.join(s.encode() for s in args))
    process(1,'jupyter-lab',['python','/opt/conda/bin/jupyter-lab','--port=8888','--ServerApp.base_url=/jupyter/1/','--IdentityProvider.token=NEVER_LEAK'])
    process(10,'sshd',['/usr/sbin/sshd','-f','/run/platform-ssh/sshd_config'])
    process(100,'python',['python','/data/train.py','--secret=NEVER_LEAK'])
    process(101,'sshd',['sshd: root@pts/0'])
    process(102,'python',['python','-m','ipykernel_launcher','-f','/run/kernel-secret.json'])
    opener=Mock()
    def read(request,timeout):
        data=[{'kernel':{'id':'k'},'path':'folder/train.ipynb'}] if request.full_url.endswith('sessions') else [{'id':'k','execution_state':'busy','connections':1}]
        return io.BytesIO(json.dumps(data).encode())
    opener.open.side_effect=read;monkeypatch.setattr(asset,'build_opener',lambda *a:opener);monkeypatch.setattr(asset.shutil,'which',lambda x:None)
    result=asset.inspect(tmp_path)
    assert result['processes_checked'] and result['notebooks_checked']
    assert {p['pid'] for p in result['processes']}=={100,101,102}
    assert 'NEVER_LEAK' not in json.dumps(result) and 'kernel-secret' not in json.dumps(result)
    assert result['notebooks'][0]['name']=='train.ipynb' and result['notebooks'][0]['state']=='busy'
    (tmp_path/'103').mkdir();(tmp_path/'103/stat').write_text('invalid')
    assert not asset.inspect(tmp_path)['processes_checked']
