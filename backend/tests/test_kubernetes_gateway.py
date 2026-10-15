from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kubernetes.client.exceptions import ApiException

from app.core.exceptions import ClusterOperationError
from app.core.exceptions import ClusterUnavailableError
from app.infrastructure.kubernetes.manifests import build_auth_secret
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.manifests import WorkloadSpec, build_ingress, build_pod


def spec(host="platform.local"):
    return WorkloadSpec(
        allocation_id=1,
        user_id=1,
        pod_name="pod-1-test",
        image="test-jupyter:v1",
        gpu_count=2,
        node_name="worker-a",
        namespace="default",
        ingress_enabled=True,
        ingress_host=host,
        ingress_class="traefik",
        use_tls=False,
        image_pull_policy="Never",
        jupyter_command="jupyter-lab",
        jupyter_token="isolated-instance-token",
        workspace_claim="platform-workspaces",
    )


def test_gpu_workload_is_constrained_to_reserved_node():
    pod = build_pod(spec())
    assert pod["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "worker-a"}
    assert pod["spec"]["containers"][0]["resources"]["limits"]["nvidia.com/gpu"] == "2"


def test_ip_access_uses_hostless_ingress_rule():
    rule = build_ingress(spec("192.0.2.2"))["spec"]["rules"][0]
    assert "host" not in rule
    assert rule["http"]["paths"][0]["path"] == "/jupyter/1/"


@pytest.mark.parametrize("host", ["192.0.2.2:64022", "[2001:db8::2]:64022"])
def test_mapped_ip_port_uses_hostless_ingress_and_keeps_public_port(host):
    from app.services.access_service import AccessService

    workload = spec(host)
    assert "host" not in build_ingress(workload)["spec"]["rules"][0]
    assert AccessService.get_jupyter_url(None, 1, options={"ingress_host": host}) == (
        f"http://{host}/jupyter/1/"
    )


def test_mapped_dns_port_is_excluded_from_ingress_host_and_tls():
    from dataclasses import replace

    manifest = build_ingress(replace(spec("cloud.example.com:64022"), use_tls=True))
    assert manifest["spec"]["rules"][0]["host"] == "cloud.example.com"
    assert manifest["spec"]["tls"][0]["hosts"] == ["cloud.example.com"]


def test_bare_ipv6_jupyter_access_is_bracketed():
    from app.services.access_service import AccessService

    assert AccessService.get_jupyter_url(None, 1, options={"ingress_host": "2001:db8::2"}) == (
        "http://[2001:db8::2]/jupyter/1/"
    )


def test_running_pod_without_readiness_is_still_pending():
    core = MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        status=SimpleNamespace(
            phase="Running", conditions=[SimpleNamespace(type="Ready", status="False")]
        )
    )
    gateway = KubernetesGateway(core, MagicMock())
    assert gateway.status("pod-1-test") == "pending"


def test_ingress_creation_failure_is_left_for_durable_cleanup():
    core, network = MagicMock(), MagicMock()
    core.read_namespaced_persistent_volume_claim.return_value = SimpleNamespace(
        status=SimpleNamespace(phase="Bound"), spec=SimpleNamespace(access_modes=["ReadWriteMany"])
    )
    network.create_namespaced_ingress.side_effect = ApiException(status=500)
    core.read_namespaced_pod.side_effect = ApiException(status=404)
    with pytest.raises(ClusterOperationError) as caught:
        KubernetesGateway(core, network).create(spec())
    assert caught.value.cleanup_confirmed is False
    network.delete_namespaced_ingress.assert_not_called()
    core.delete_namespaced_service.assert_not_called()
    core.delete_namespaced_pod.assert_not_called()


def test_deletion_error_is_not_swallowed():
    core, network = MagicMock(), MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels={"allocation-id": "1", "user-id": "1"})
    )
    core.delete_namespaced_pod.side_effect = ApiException(status=403)
    with pytest.raises(ClusterOperationError):
        KubernetesGateway(core, network).delete("pod-1-test")


def test_deletion_waits_for_actual_pod_removal():
    core, network = MagicMock(), MagicMock()
    network.read_namespaced_ingress.side_effect = ApiException(status=404)
    core.read_namespaced_service.side_effect = ApiException(status=404)
    core.read_namespaced_secret.side_effect = ApiException(status=404)
    pod = SimpleNamespace(metadata=SimpleNamespace(labels={"allocation-id": "1"}))
    core.read_namespaced_pod.side_effect = [pod, pod, ApiException(status=404)]
    KubernetesGateway(core, network).delete("pod-1-test")
    assert core.read_namespaced_pod.call_count == 3


def test_retry_adopts_owned_resources_instead_of_creating_another_pod():
    import base64

    core, network = MagicMock(), MagicMock()
    labels = {"allocation-id": "1", "user-id": "1"}
    metadata = SimpleNamespace(labels=labels)
    workload = spec()
    core.read_namespaced_persistent_volume_claim.return_value = SimpleNamespace(
        status=SimpleNamespace(phase="Bound"), spec=SimpleNamespace(access_modes=["ReadWriteMany"])
    )
    secret = SimpleNamespace(
        metadata=metadata,
        data={"token": base64.b64encode(workload.jupyter_token.encode()).decode()},
    )
    pod = SimpleNamespace(
        metadata=metadata,
        spec=SimpleNamespace(
            volumes=[
                SimpleNamespace(
                    name="workspace",
                    persistent_volume_claim=SimpleNamespace(claim_name=workload.workspace_claim),
                )
            ],
            node_selector={"kubernetes.io/hostname": "worker-a"},
            containers=[
                SimpleNamespace(
                    image=workload.image,
                    resources=SimpleNamespace(limits={"nvidia.com/gpu": "2"}),
                    command=[workload.jupyter_command],
                    args=build_pod(workload)["spec"]["containers"][0]["args"],
                    env=[
                        SimpleNamespace(
                            name="JUPYTER_TOKEN",
                            value_from=SimpleNamespace(
                                secret_key_ref=SimpleNamespace(
                                    name=workload.auth_secret_name, key="token"
                                )
                            ),
                        )
                    ],
                    volume_mounts=[SimpleNamespace(mount_path="/workspace", sub_path="user_1")],
                )
            ],
        ),
        status=SimpleNamespace(phase="Pending", conditions=[], container_statuses=[]),
    )
    service = SimpleNamespace(metadata=metadata)
    ingress = SimpleNamespace(metadata=metadata)
    for create in (
        core.create_namespaced_secret,
        core.create_namespaced_pod,
        core.create_namespaced_service,
        network.create_namespaced_ingress,
    ):
        create.side_effect = ApiException(status=409)
    core.read_namespaced_secret.return_value = secret
    core.read_namespaced_pod.return_value = pod
    core.read_namespaced_service.return_value = service
    network.read_namespaced_ingress.return_value = ingress
    result = KubernetesGateway(core, network).create(workload)
    assert result["status"] == "pending"
    core.delete_namespaced_pod.assert_not_called()
    assert result["pod_name"] == workload.pod_name


def test_name_conflict_does_not_delete_existing_pod():
    core, network = MagicMock(), MagicMock()
    core.read_namespaced_persistent_volume_claim.return_value = SimpleNamespace(
        status=SimpleNamespace(phase="Bound"), spec=SimpleNamespace(access_modes=["ReadWriteMany"])
    )
    core.create_namespaced_pod.side_effect = ApiException(status=409)
    with pytest.raises(ClusterOperationError) as caught:
        KubernetesGateway(core, network).create(spec())
    assert caught.value.cleanup_confirmed is False
    core.delete_namespaced_pod.assert_not_called()


def test_owner_mismatch_does_not_delete_any_resources():
    core, network = MagicMock(), MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        metadata=SimpleNamespace(labels={"allocation-id": "1", "user-id": "2"})
    )
    with pytest.raises(ClusterOperationError):
        KubernetesGateway(core, network).delete("pod-1-test", user_id=1)
    core.delete_namespaced_pod.assert_not_called()
    core.delete_namespaced_service.assert_not_called()
    network.delete_namespaced_ingress.assert_not_called()


def test_workspace_and_authentication_are_bound_to_the_instance():
    workload = spec()
    pod = build_pod(workload)
    container = pod["spec"]["containers"][0]
    assert pod["spec"]["runtimeClassName"] == "nvidia"
    assert container["volumeMounts"][0]["subPath"] == "user_1"
    assert pod["spec"]["volumes"][0]["persistentVolumeClaim"]["claimName"] == "platform-workspaces"
    assert "--IdentityProvider.token=$(JUPYTER_TOKEN)" in container["args"]
    assert "--ServerApp.token=''" not in container["args"]
    assert "isolated-instance-token" not in str(container["args"])
    secret = build_auth_secret(workload)
    assert container["env"][0]["valueFrom"]["secretKeyRef"]["name"] == secret["metadata"]["name"]


def test_missing_shared_volume_fails_before_creating_resources():
    core = MagicMock()
    core.read_namespaced_persistent_volume_claim.side_effect = ApiException(status=404)
    with pytest.raises(ClusterUnavailableError):
        KubernetesGateway(core, MagicMock()).create(spec())
    core.create_namespaced_secret.assert_not_called()
    core.create_namespaced_pod.assert_not_called()


def test_crash_loop_is_reported_as_failure_with_runtime_metadata():
    from datetime import datetime, timezone

    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    core = MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        status=SimpleNamespace(
            phase="Running",
            conditions=[],
            container_statuses=[
                SimpleNamespace(
                    state=SimpleNamespace(
                        running=None,
                        terminated=None,
                        waiting=SimpleNamespace(reason="CrashLoopBackOff", message="exited"),
                    ),
                    last_state=SimpleNamespace(
                        running=None,
                        terminated=SimpleNamespace(
                            started_at=started,
                            finished_at=started,
                        ),
                    ),
                )
            ],
        )
    )
    state = KubernetesGateway(core, MagicMock()).status("pod-1-test")
    assert state == "failed"
    assert state.started_at == started.replace(tzinfo=None)
    assert "CrashLoopBackOff" in state.message


def test_standard_kubeconfig_environment_is_respected(monkeypatch):
    from app.core.config import settings
    from app.infrastructure.kubernetes import client as module

    monkeypatch.setattr(settings, "K8S_CONFIG_PATH", None)
    monkeypatch.setenv("KUBECONFIG", "test-kubeconfig.yaml")
    load = MagicMock()
    monkeypatch.setattr(module.config, "load_kube_config", load)
    core, _ = module.create_clients()
    try:
        assert load.call_args.kwargs["config_file"] == "test-kubeconfig.yaml"
    finally:
        core.api_client.close()


def test_admission_failure_without_containers_retains_reason_and_startup_evidence():
    core = MagicMock()
    core.read_namespaced_pod.return_value = SimpleNamespace(
        status=SimpleNamespace(
            phase="Failed",
            reason="UnexpectedAdmissionError",
            message="Allocate failed due to no healthy devices present",
            conditions=[],
            container_statuses=None,
        )
    )
    state = KubernetesGateway(core, MagicMock()).status("pod-1-test")
    assert state == "failed"
    assert state.admission_rejected
    assert state.started_at is None
    assert "no healthy devices" in state.message


@pytest.mark.parametrize("kind", ["service", "ingress"])
@pytest.mark.parametrize(
    "labels,target_matches,allowed",
    [
        ({"allocation-id": "1", "app": "pod-1-test"}, True, True),
        ({"app": "pod-1-test"}, True, True),
        ({"allocation-id": "2", "app": "pod-1-test"}, True, False),
        ({"allocation-id": "1", "user-id": "2"}, True, False),
        ({"allocation-id": "1", "app": "pod-1-test"}, False, False),
    ],
)
def test_legacy_resource_ownership_requires_matching_labels_and_target(
    kind, labels, target_matches, allowed
):
    resource = SimpleNamespace(metadata=SimpleNamespace(labels=labels))
    if kind == "service":
        resource.spec = SimpleNamespace(
            selector={"app": "pod-1-test" if target_matches else "another-pod"}
        )
    else:
        backend = SimpleNamespace(
            service=SimpleNamespace(name="svc-1" if target_matches else "another-service")
        )
        resource.spec = SimpleNamespace(
            rules=[SimpleNamespace(http=SimpleNamespace(paths=[SimpleNamespace(backend=backend)]))]
        )
    if allowed:
        KubernetesGateway._check_owner(resource, 1, 1, kind=kind, pod_name="pod-1-test")
    else:
        with pytest.raises(ClusterOperationError):
            KubernetesGateway._check_owner(resource, 1, 1, kind=kind, pod_name="pod-1-test")
