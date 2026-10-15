from base64 import b64decode
from dataclasses import replace
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from kubernetes import client
from kubernetes.client.exceptions import ApiException
import pytest
from passlib.hash import sha512_crypt

from app.core.instance_credentials import ssh_password, ssh_password_hash
from app.core.exceptions import ClusterOperationError, ResourceNotFoundError
from app.infrastructure.kubernetes.manifests import build_auth_secret, build_pod, LEGACY_SSH_START
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.ssh_runtime import SSH_PASSWORD_SETUP
from app.models import Allocation, AllocationStatus
from app.models.operation import AllocationOperation, OperationKind
from app.services.job_service import JobService
from app.services.ssh_service import SSHService
from test_kubernetes_gateway import spec


def test_password_is_stable_per_instance_and_secret_contains_only_hash():
    password = ssh_password(1, 1)
    assert password == ssh_password(1, 1)
    assert len({password, ssh_password(2, 1), ssh_password(1, 2)}) == 3
    hashed = ssh_password_hash(1, 1)
    assert sha512_crypt.verify(password, hashed)
    workload = replace(spec(), ssh_enabled=True, ssh_password_hash=hashed)
    secret = build_auth_secret(workload)
    assert b64decode(secret["data"]["password_hash"]).decode() == hashed
    assert password not in str(build_pod(workload)) and password not in str(secret)


def test_password_shadow_is_ephemeral_and_repeated_setup_is_safe(tmp_path):
    shadow = tmp_path / "etc/shadow"
    shadow.parent.mkdir()
    shadow.write_text("root:!:1:0:99999:7:::\nnobody:!:1:0:99999:7:::\n")
    runtime = tmp_path / "runtime"
    source = SSH_PASSWORD_SETUP.replace("/etc/shadow", str(shadow)).replace("/run/platform-ssh", str(runtime))
    for allocation_id in (1, 2):
        hashed = ssh_password_hash(allocation_id, 1)
        exec(source, {"PASSWORD_HASH": hashed})
        assert shadow.is_symlink() and os.readlink(shadow) == str(runtime / "shadow")
        assert hashed in shadow.read_text() and "nobody:" in shadow.read_text()
        assert ssh_password(allocation_id, 1) not in shadow.read_text()
        assert (runtime / "shadow").stat().st_mode & 0o777 == 0o600


def test_connection_without_public_keys_returns_password_after_runtime_sync(db, monkeypatch):
    from app.services import ssh_service
    row = Allocation(request_id="password-ssh", user_id=1, node_id=1, pool_id=1, image_id=1,
        requested_gpu_count=1, gpu_type_id=1, status=AllocationStatus.ACTIVE,
        container_id="ssh-owned", pod_name="pod-password", ssh_port=31022)
    db.add(row)
    db.flush()
    db.add(AllocationOperation(allocation_id=row.id, kind=OperationKind.CREATE,
        payload={"options": {"namespace": "default", "ssh_enabled": True}, "access_host": "campus.example.edu"}))
    db.commit()
    core, network = MagicMock(), MagicMock()
    owned = SimpleNamespace(metadata=SimpleNamespace(labels={"allocation-id": str(row.id), "user-id": "1"}))
    core.read_namespaced_pod.return_value = core.read_namespaced_secret.return_value = owned
    monkeypatch.setattr(ssh_service, "create_clients", lambda: (core, network))
    execute = MagicMock(return_value="SSH_PASSWORD_READY")
    monkeypatch.setattr(JobService, "execute", execute)
    response = SSHService.connection(db, 1, row.container_id)
    assert response["password"] == ssh_password(row.id, 1)
    assert response["key_count"] == 0 and response["auth_type"] == "password"
    assert response["command"] == "ssh -p 31022 root@campus.example.edu"
    assert response["password"] not in execute.call_args.args[1]
    with pytest.raises(ResourceNotFoundError):
        SSHService.connection(db, 2, row.container_id)


def test_recovery_accepts_exact_legacy_ssh_start_but_rejects_other_commands():
    workload = replace(spec(), ssh_enabled=True, ssh_password_hash=ssh_password_hash(1, 1))
    manifest = build_pod(workload)
    pod = client.ApiClient()._ApiClient__deserialize(manifest, "V1Pod")
    pod.spec.containers[0].command = ["/bin/bash", "-c", LEGACY_SSH_START, "platform-start", workload.jupyter_command]
    create = MagicMock(side_effect=ApiException(status=409))
    read = MagicMock(return_value=pod)
    gateway = KubernetesGateway(MagicMock(), MagicMock())
    assert gateway._ensure(create, read, manifest, workload, "pod") is pod
    pod.spec.containers[0].command = ["sh", "-c", "unrelated command"]
    with pytest.raises(ClusterOperationError):
        gateway._ensure(create, read, manifest, workload, "pod")
