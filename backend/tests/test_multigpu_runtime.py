import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.infrastructure.kubernetes.manifests import build_pod
from app.services.k8s_service import K8sService
from app.services.operation_service import OperationService
from test_kubernetes_gateway import spec


@pytest.mark.parametrize("cards", [1, 2, 4])
@pytest.mark.parametrize("ssh_enabled", [False, True])
def test_gpu_instances_have_private_shared_memory_for_nccl_and_dataloaders(cards, ssh_enabled):
    pod = build_pod(replace(spec(), gpu_count=cards, ssh_enabled=ssh_enabled))
    volumes = {volume["name"]: volume for volume in pod["spec"]["volumes"]}
    mounts = {mount["mountPath"]: mount for mount in pod["spec"]["containers"][0]["volumeMounts"]}
    shared = volumes[mounts["/dev/shm"]["name"]]
    assert shared["emptyDir"] == {"medium": "Memory", "sizeLimit": "1Gi"}
    assert not pod["spec"].get("hostIPC"), "Different users must not share host IPC"
    assert mounts["/workspace"]["subPath"] == "user_1"
    assert volumes["workspace"]["persistentVolumeClaim"]["claimName"] == "platform-workspaces"


def test_retry_uses_shared_memory_limit_frozen_at_purchase(monkeypatch):
    from app.services import k8s_service
    monkeypatch.setattr(settings, "WORKLOAD_SHM_SIZE_LIMIT", "2Gi")
    payload = OperationService.creation_payload(SimpleNamespace(hostname="worker-a", ip="10.0.0.2"), "campus.example", "jupyter-lab")
    monkeypatch.setattr(settings, "WORKLOAD_SHM_SIZE_LIMIT", "4Gi")
    captured = []
    monkeypatch.setattr(k8s_service, "_execute", lambda operation, workload: captured.append(workload) or {})
    allocation = SimpleNamespace(id=1, user_id=1, pod_name="pod-test")
    asyncio.run(K8sService.create_pod(allocation, "workbench:test", 4, node_name="worker-a",
                                    host="campus.example", options=payload["options"]))
    assert captured[0].shared_memory_size == "2Gi"


@pytest.mark.parametrize("enabled", [False, True])
def test_nccl_compatibility_survives_configuration_changes_on_retry(monkeypatch, enabled):
    from app.services import k8s_service

    monkeypatch.setattr(settings, "WORKLOAD_NCCL_P2P_DISABLE", enabled)
    payload = OperationService.creation_payload(
        SimpleNamespace(hostname="worker-a", ip="10.0.0.2"), "campus.example", "jupyter-lab"
    )
    monkeypatch.setattr(settings, "WORKLOAD_NCCL_P2P_DISABLE", not enabled)
    captured = []
    monkeypatch.setattr(k8s_service, "_execute", lambda operation, workload: captured.append(build_pod(workload)) or {})
    asyncio.run(K8sService.create_pod(
        SimpleNamespace(id=1, user_id=1, pod_name="pod-test"), "workbench:test", 2,
        node_name="worker-a", host="campus.example", options=payload["options"],
    ))
    environment = {item["name"]: item.get("value") for item in captured[0]["spec"]["containers"][0]["env"]}
    assert environment.get("NCCL_P2P_DISABLE") == ("1" if enabled else None)


def test_old_creation_options_keep_the_original_nccl_behavior(monkeypatch):
    from app.services import k8s_service

    monkeypatch.setattr(settings, "WORKLOAD_NCCL_P2P_DISABLE", True)
    captured = []
    monkeypatch.setattr(k8s_service, "_execute", lambda operation, workload: captured.append(build_pod(workload)) or {})
    asyncio.run(K8sService.create_pod(
        SimpleNamespace(id=1, user_id=1, pod_name="pod-test"), "workbench:test", 2,
        node_name="worker-a", host="campus.example", options={"shared_memory_size": "1Gi"},
    ))
    environment = {item["name"] for item in captured[0]["spec"]["containers"][0]["env"]}
    assert "NCCL_P2P_DISABLE" not in environment
