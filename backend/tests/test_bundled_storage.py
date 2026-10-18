import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import settings
from app.core.exceptions import ResourceConflictError
from app.models import Allocation, GPU, GPUStatus, OwnerType, Quota, User
from app.services.k8s_service import K8sService
from app.services.scheduler_service import SchedulerService
from app.services.storage_quota_service import StorageQuotaService


@pytest.fixture
def storage_bundle(monkeypatch):
    monkeypatch.setattr(settings, 'STORAGE_QUOTA_MODE', 'fixed')
    monkeypatch.setattr(settings, 'STORAGE_QUOTA_ENABLED', True)
    monkeypatch.setattr(settings, 'DEFAULT_STORAGE_LIMIT_GIB', 300)
    helper=Mock(return_value={'enforcement':'filesystem','used_percent':0})
    monkeypatch.setattr(StorageQuotaService, 'helper', helper)
    monkeypatch.setattr(K8sService, 'create_pod', AsyncMock(return_value={'status':'pending'}))
    monkeypatch.setattr(K8sService, 'delete_pod', AsyncMock())
    monkeypatch.setattr(K8sService, 'get_pod_status', AsyncMock(return_value='not_found'))
    return helper


def apply(db, key):
    return asyncio.run(SchedulerService.create_allocation(db,user_id=1,pool_id=1,gpu_count=1,image_id=1,idempotency_key=key))


def test_gpu_application_includes_one_account_storage_quota_and_keeps_it_after_release(db, storage_bundle):
    first=apply(db,'first');second=apply(db,'second')
    assert first['personal_storage_limit_gib']==second['personal_storage_limit_gib']==300
    assert first['persistent_path']==second['persistent_path']=='/data'
    assert first['storage_scope']==second['storage_scope']=='user'
    assert db.get(User,1).storage_default_bytes==300*1024**3
    assert all(call.kwargs['limit_bytes']==300*1024**3 for call in storage_bundle.call_args_list)
    assert apply(db,'first')['container_id']==first['container_id']
    assert db.query(Allocation).count()==2
    for result in (first,second):
        asyncio.run(SchedulerService.release_allocation(db,1,result['container_id']))
    assert db.get(User,1).storage_default_bytes==300*1024**3


def test_application_uses_admin_storage_override_without_increasing_it(db,storage_bundle):
    db.add(Quota(owner_type=OwnerType.USER,owner_id=1,storage_limit_bytes=500*1024**3,max_gpus=2,max_instances=2))
    db.commit()
    assert apply(db,'custom')['personal_storage_limit_gib']==500
    assert storage_bundle.call_args.kwargs['limit_bytes']==500*1024**3


def test_storage_pool_full_rejects_before_reserving_gpu_or_creating_order(db,storage_bundle):
    storage_bundle.side_effect=ResourceConflictError('pool full')
    with pytest.raises(ResourceConflictError):apply(db,'pool-full')
    assert db.query(Allocation).count()==0
    assert all(gpu.status==GPUStatus.FREE and gpu.allocation_id is None for gpu in db.query(GPU))
    assert db.get(User,1).storage_default_bytes is None
