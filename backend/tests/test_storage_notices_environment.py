import errno
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.exceptions import ResourceConflictError
from app.main import app
from app.models import Allocation, AllocationStatus, Notice, User
from app.routers.monitoring import QuotaInput
from app.services.job_service import JobService
from app.services.notice_service import NoticeService
from app.services.quota_service import QuotaService
from app.services.storage_quota_service import StorageQuotaService


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, 1)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def allocation(db, status=AllocationStatus.ACTIVE):
    row = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        requested_gpu_count=1,
        gpu_type_id=1,
        node_id=1,
        container_id="diagnostic-owned",
        pod_name="pod-owned",
        status=status,
    )
    db.add(row)
    db.commit()
    return row


def test_notices_deduplicate_and_do_not_cross_accounts(client, db):
    NoticeService.emit(db, 1, "own", "Own", "Owned notification")
    NoticeService.emit(db, 1, "own", "Duplicate", "Duplicate")
    NoticeService.emit(db, 2, "other", "Other", "Other notification")
    db.commit()
    result = client.get("/notices").json()["data"]
    assert result["unread_count"] == 1 and len(result["items"]) == 1
    other = db.query(Notice).filter_by(user_id=2).one()
    assert client.post(f"/notices/{other.id}/read").status_code == 404
    assert client.post("/notices/read-all").status_code == 200
    assert client.get("/notices").json()["data"]["unread_count"] == 0
    assert other.read_at is None


def test_expired_notices_do_not_count_as_unread(client, db):
    NoticeService.emit(
        db,
        1,
        "expired",
        "Ended",
        "Ended",
        expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db.commit()
    result = client.get("/notices").json()["data"]
    assert result["unread_count"] == 0 and result["items"][0]["expired"]


def test_package_and_debt_deadlines_emit_once_and_expire_on_release(db):
    row = allocation(db)
    now = datetime.utcnow()
    row.package_expires_at = now + timedelta(minutes=9)
    user = db.get(User, 1)
    user.balance = 0
    user.grace_expires_at = now + timedelta(minutes=9)
    db.commit()
    for _ in range(2):
        NoticeService.refresh(db, now=now, force=True)
    assert db.query(Notice).count() == 4  # Package, balance, initial debt, debt deadline.
    row.status = AllocationStatus.RELEASED
    db.commit()
    NoticeService.refresh(db, now=now, force=True)
    assert db.query(Notice).filter_by(allocation_id=row.id).one().expires_at == now


def test_storage_share_survives_older_admin_request_and_can_reset(db):
    QuotaService.set_limits(db, 1, QuotaInput(storage_share_percent=25))
    db.commit()
    assert QuotaService.set_limits(db, 1, QuotaInput(max_gpus=2))["storage_share_percent"] == 25
    assert QuotaService.set_limits(db, 1, QuotaInput(storage_share_percent=None))[
        "storage_inherited"
    ]
    assert (
        QuotaService.set_limits(db, 1, QuotaInput(inherited=True))["storage_share_percent"]
        == settings.DEFAULT_STORAGE_SHARE_PERCENT
    )


@pytest.mark.parametrize("number", [errno.EDQUOT, errno.ENOSPC])
def test_quota_write_errors_are_useful_conflicts(number):
    with pytest.raises(ResourceConflictError, match="原有文件继续保留"):
        with StorageQuotaService.write_guard():
            raise OSError(number, "full")


def test_examples_are_unique_and_preserve_existing_files(client, workspace):
    first = client.post("/storage/examples/training").json()["data"]
    second = client.post("/storage/examples/training").json()["data"]
    assert first["folder"] != second["folder"]
    assert first["framework"] == "pytorch"
    assert (workspace / "user_1" / first["folder"] / "train.py").is_file()
    assert "torchrun" in first["multi_command"] and "<申请的GPU数量>" in first["multi_command"]
    assert "torchrun" in first["multi_resume_command"] and "--resume" in first["multi_resume_command"]
    assert client.post("/storage/folder", json={"path": first["folder"]}).status_code == 409


def test_tensorflow_example_generates_its_own_script_and_recovery_commands(client, workspace):
    response = client.post("/storage/examples/training", json={"framework": "tensorflow"})
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["framework"] == "tensorflow"
    assert result["folder"].startswith("training-tensorflow-")
    source = (workspace / "user_1" / result["folder"] / "train.py").read_text(encoding="utf-8")
    assert "import tensorflow as tf" in source and "import torch" not in source
    compile(source, "generated_tensorflow_train.py", "exec")
    assert "--gpus 1" in result["single_command"]
    assert "--gpus <申请的GPU数量>" in result["multi_command"]
    assert "--resume --epochs 10" in result["resume_command"]
    assert "--gpus <申请的GPU数量>" in result["multi_resume_command"]
    for key in ("single_command", "multi_command", "resume_command", "multi_resume_command"):
        assert "/data/" + result["folder"] + "/train.py" in result[key]
        assert "checkpoint-tensorflow" in result[key]
        assert "torchrun" not in result[key]


@pytest.mark.parametrize("framework", ["../../secrets", "keras", 123, None])
def test_invalid_training_framework_does_not_create_files(client, workspace, framework):
    folder = workspace / "user_1"
    before = set(folder.iterdir()) if folder.exists() else set()
    response = client.post("/storage/examples/training", json={"framework": framework})
    assert response.status_code == 422
    assert (set(folder.iterdir()) if folder.exists() else set()) == before


def test_diagnostics_enforce_ownership_and_running_state(client, db, monkeypatch):
    execute = Mock(
        return_value="PLATFORM_CHECK_RESULT="
        + json.dumps({"checks": [{"name": "Python", "ok": True}]})
    )
    monkeypatch.setattr(JobService, "execute", execute)
    row = allocation(db)
    assert client.post("/resource/diagnostic-owned/diagnostics").json()["data"]["checks"][0]["ok"]
    row.user_id = 2
    db.commit()
    assert client.post("/resource/diagnostic-owned/diagnostics").status_code == 404
    row.user_id = 1
    row.status = AllocationStatus.RELEASED
    db.commit()
    assert client.post("/resource/diagnostic-owned/diagnostics").status_code == 409
    assert execute.call_count == 1


def test_pod_metrics_use_frozen_quota_and_capture_oom(monkeypatch):
    from app.infrastructure.kubernetes import runtime_metrics as metrics

    pod = SimpleNamespace(
        metadata=SimpleNamespace(labels={"user-id": "1", "allocation-id": "2"}),
        status=SimpleNamespace(
            container_statuses=[
                SimpleNamespace(
                    restart_count=1,
                    state=None,
                    last_state=SimpleNamespace(terminated=SimpleNamespace(reason="OOMKilled")),
                )
            ]
        ),
    )
    core = Mock()
    core.read_namespaced_pod.return_value = pod
    network = Mock()
    monkeypatch.setattr(metrics, "create_clients", lambda: (core, network))
    api = Mock()
    api.get_namespaced_custom_object.return_value = {
        "containers": [{"usage": {"cpu": "500m", "memory": "256Mi"}}]
    }
    monkeypatch.setattr(metrics.client, "CustomObjectsApi", lambda **kwargs: api)
    row = SimpleNamespace(pod_name="pod", id=2, user_id=1, cpu_quota_cores=2, ram_mb=1024)
    result = metrics.pod_usage(row, "default")
    assert result["cpu_percent"] == 25 and result["memory_percent"] == 25
    assert result["last_exit_reason"] == "OOMKilled" and result["restart_count"] == 1
    api.get_namespaced_custom_object.side_effect = metrics.client.exceptions.ApiException(
        status=404
    )
    result = metrics.pod_usage(row, "default")
    assert result["state"] == "missing" and result["cpu_percent"] is None
