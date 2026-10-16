import asyncio
from dataclasses import replace
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from kubernetes import client
from kubernetes.client.exceptions import ApiException
import pytest

from app.core.workspace import LEGACY_LAYOUT, SEPARATE_LAYOUT
from app.core.exceptions import ClusterOperationError
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.manifests import build_pod, SSH_START
from app.infrastructure.kubernetes.shell_runtime import SHELL_SETUP
from app.models import Allocation, AllocationOperation, AllocationStatus
from app.models.operation import OperationKind
from app.services.instance_service import InstanceService
from app.services.job_service import JobService
from app.services.k8s_service import K8sService
from app.services.scheduler_service import SchedulerService
from test_kubernetes_gateway import spec


def test_new_layout_has_private_system_workdir_and_mounted_personal_storage():
    pod = build_pod(replace(spec(), storage_layout=SEPARATE_LAYOUT, ssh_enabled=True))
    container = pod["spec"]["containers"][0]
    mounts = {item["mountPath"]: item for item in container["volumeMounts"]}
    assert "/workspace" not in mounts
    assert mounts["/data"]["subPath"] == "user_1"
    assert mounts["/run/platform-shell"]["name"] == "platform-shell"
    assert container["workingDir"] == "/workspace"
    assert "ForceCommand /run/platform-shell/ssh-session" in container["command"][2]
    assert "--ServerApp.root_dir=/" in container["args"]
    assert "--ServerApp.preferred_dir=/workspace" in container["args"]
    assert any(
        "shell_command" in value and "/bin/bash" in value and "-il" in value
        for value in container["args"]
    )
    assert (
        next(value for value in container["env"] if value["name"] == "SHELL")["value"]
        == "/bin/bash"
    )


def test_legacy_layout_keeps_existing_mount_and_command_for_recovery():
    workload = replace(spec(), ssh_enabled=True)
    container = build_pod(workload)["spec"]["containers"][0]
    assert container["volumeMounts"][0]["mountPath"] == "/workspace"
    assert container["command"] == [
        "/bin/bash",
        "-c",
        SSH_START,
        "platform-start",
        workload.jupyter_command,
    ]
    assert "--ServerApp.root_dir=/workspace" in container["args"]


@pytest.mark.parametrize("mutation", ["other-user", "persistent-workspace"])
def test_recovery_rejects_a_different_users_data_or_persistent_scratch(mutation):
    workload = replace(spec(), storage_layout=SEPARATE_LAYOUT)
    manifest = build_pod(workload)
    pod = client.ApiClient()._ApiClient__deserialize(manifest, "V1Pod")
    create = Mock(side_effect=ApiException(status=409))
    read = Mock(return_value=pod)
    gateway = KubernetesGateway(Mock(), Mock())
    assert gateway._ensure(create, read, manifest, workload, "pod") is pod
    if mutation == "other-user":
        pod.spec.containers[0].volume_mounts[0].sub_path = "user_2"
    else:
        pod.spec.containers[0].volume_mounts.append(
            client.V1VolumeMount(name="workspace", mount_path="/workspace", sub_path="user_1")
        )
    with pytest.raises(ClusterOperationError):
        gateway._ensure(create, read, manifest, workload, "pod")


def test_allocation_freezes_new_layout_and_old_records_keep_legacy(db, monkeypatch):
    monkeypatch.setattr(K8sService, "create_pod", AsyncMock(return_value={"status": "pending"}))
    asyncio.run(
        SchedulerService.create_allocation(db, user_id=1, pool_id=1, gpu_count=1, image_id=1)
    )
    allocation = db.query(Allocation).one()
    response = InstanceService.to_response(db, allocation)
    assert response.storage_layout == SEPARATE_LAYOUT and response.persistent_path == "/data"
    operation = allocation.operations[0]
    options = {
        key: value for key, value in operation.payload["options"].items() if key != "storage_layout"
    }
    operation.payload = {**operation.payload, "options": options}
    db.flush()
    response = InstanceService.to_response(db, allocation)
    assert response.storage_layout == LEGACY_LAYOUT and response.persistent_path == "/workspace"


@pytest.mark.parametrize("layout,root", [(LEGACY_LAYOUT, "/workspace"), (SEPARATE_LAYOUT, "/data")])
def test_job_launch_and_cancel_use_the_allocations_saved_layout(db, monkeypatch, layout, root):
    row = Allocation(
        request_id=uuid4().hex,
        user_id=1,
        node_id=1,
        requested_gpu_count=1,
        status=AllocationStatus.ACTIVE,
        container_id="owned-layout",
        pod_name="owned-layout",
    )
    db.add(row)
    db.flush()
    db.add(
        AllocationOperation(
            allocation_id=row.id,
            kind=OperationKind.CREATE,
            payload={"options": {"storage_layout": layout}},
        )
    )
    db.commit()
    job_id = uuid4().hex

    def execute(allocation, code):
        JobService.write(1, JobService.relative(job_id, "pid.json"), ' {"pid":123} ')
        return "started" if "Popen" in code else "cancelled"

    runner = Mock(side_effect=execute)
    monkeypatch.setattr(JobService, "execute", runner)
    body = SimpleNamespace(
        job_id=job_id, container_id=row.container_id, name="layout", command="python hello.py"
    )
    asyncio.run(JobService.submit(db, 1, body))
    asyncio.run(JobService.cancel(db, 1, job_id))
    assert all(root + "/.cloud-jobs/" in call.args[1] for call in runner.call_args_list)


def test_shell_setup_preserves_saved_work_and_profiles_and_uses_shared_bash(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".profile").write_text("# user profile\n")
    runtime = tmp_path / "runtime"
    work = tmp_path / "workspace"
    work.mkdir()
    (work / "from-saved-image.txt").write_text("keep")
    passwd = tmp_path / "passwd"
    passwd.write_text("root:x:0:0:root:/root:/bin/sh\nother:x:1:1:other:/tmp:/bin/sh\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JUPYTER_TOKEN", "not-for-shell-files")
    monkeypatch.setenv("NCCL_P2P_DISABLE", "1")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    source = (
        SHELL_SETUP.replace("/run/platform-shell", str(runtime))
        .replace("/workspace", str(work))
        .replace("/etc/passwd", str(passwd))
    )
    for _ in range(2):
        exec(source, {})
    assert (home / ".profile").read_text().startswith("# user profile")
    assert (home / ".profile").read_text().count("# BEGIN PLATFORM SHELL") == 1
    assert (work / "from-saved-image.txt").read_text() == "keep"
    assert "root:x:0:0:root:/root:/bin/bash" in passwd.read_text()
    assert "not-for-shell-files" not in (runtime / "environment.sh").read_text()
    assert (runtime / "ssh-session").stat().st_mode & 0o777 == 0o755
    result = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--rcfile",
            str(runtime / "bashrc"),
            "-ic",
            'printf "SHELL_CHECK=%s\\n" "$SHELL"; printf "NCCL_CHECK=%s\\n" "$NCCL_P2P_DISABLE"; printf "%s\\n" "$PWD"; alias ll',
        ],
        cwd=home,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "NCCL_P2P_DISABLE"},
    )
    assert result.returncode == 0
    assert "SHELL_CHECK=/bin/bash" in result.stdout
    assert "NCCL_CHECK=1" in result.stdout
    assert str(work) in result.stdout and "ls -alF" in result.stdout
