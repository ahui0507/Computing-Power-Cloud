from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kubernetes.client import ApiClient, V1NetworkPolicy, V1Pod
from kubernetes.client.exceptions import ApiException

from app.core.exceptions import ClusterOperationError, ClusterUnavailableError
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.isolation import (
    CAPABILITIES, POLICY_NAME, TENANT_LABEL, build_network_policy, policy_digest,
)
from app.infrastructure.kubernetes.manifests import build_pod
from test_kubernetes_gateway import spec


def deserialize(body, kind):
    with ApiClient() as serializer:
        return serializer._ApiClient__deserialize(body, kind)


def isolated_spec():
    policy = build_network_policy("platform-workloads", ["192.168.24.64/32"])
    return replace(spec(), namespace="platform-workloads", ssh_enabled=True,
                   isolation_enabled=True, isolation_policy_sha256=policy_digest(policy["spec"]))


def boundary_gateway():
    core, network = MagicMock(), MagicMock()
    core.read_namespace.return_value.metadata.labels = {
        "cpcloud.io/tenant-namespace": "true", "pod-security.kubernetes.io/enforce": "baseline",
    }
    core.read_namespaced_service_account.return_value.automount_service_account_token = False
    core.read_node.return_value.metadata.labels = {"cpcloud.io/tenant-isolation": "v1"}
    policy = deserialize(build_network_policy("platform-workloads", ["192.168.24.64/32"]), V1NetworkPolicy)
    network.list_namespaced_network_policy.return_value = SimpleNamespace(items=[policy])
    return KubernetesGateway(core, network)


def test_isolated_gpu_pod_has_no_cluster_credentials_or_host_privileges():
    pod = build_pod(isolated_spec())
    runtime = pod["spec"]
    assert runtime["automountServiceAccountToken"] is False
    assert runtime["enableServiceLinks"] is False
    assert runtime["serviceAccountName"] == "platform-workload"
    assert not any(runtime[key] for key in ("hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"))
    assert runtime["nodeSelector"]["cpcloud.io/tenant-isolation"] == "v1"
    security = runtime["containers"][0]["securityContext"]
    assert security["runAsUser"] == 0
    assert security["privileged"] is False and security["allowPrivilegeEscalation"] is False
    assert security["capabilities"]["drop"] == ["ALL"]
    assert not {"NET_RAW", "NET_ADMIN", "SYS_ADMIN", "SYS_PTRACE", "SYS_MODULE", "MKNOD"}.intersection(security["capabilities"]["add"])
    assert security["seccompProfile"] == {"type": "RuntimeDefault"}
    assert not any("hostPath" in volume or "projected" in volume for volume in runtime["volumes"])


def test_actual_sdk_policy_roundtrip_preserves_reviewed_digest():
    gateway = boundary_gateway()
    gateway._verify_isolation(isolated_spec())


@pytest.mark.parametrize("failure", ["namespace", "identity", "extra_policy", "policy_edited", "node"])
def test_missing_or_modified_boundary_prevents_any_workload_creation(failure):
    gateway = boundary_gateway()
    if failure == "namespace":
        gateway.core.read_namespace.return_value.metadata.labels = {}
    elif failure == "identity":
        gateway.core.read_namespaced_service_account.return_value.automount_service_account_token = True
    elif failure == "extra_policy":
        gateway.networking.list_namespaced_network_policy.return_value.items.append(MagicMock())
    elif failure == "policy_edited":
        gateway.networking.list_namespaced_network_policy.return_value.items[0].spec.egress = [{}]
    else:
        gateway.core.read_node.return_value.metadata.labels = {}
    with pytest.raises(ClusterUnavailableError):
        gateway.create(isolated_spec())
    gateway.core.create_namespaced_pod.assert_not_called()
    gateway.core.create_namespaced_secret.assert_not_called()


@pytest.mark.parametrize("change", ["privileged", "raw_network", "host_network", "credentials", "extra_volume", "entire_workspace_mount", "other_auth_secret"])
def test_retry_refuses_to_adopt_pods_with_weaker_isolation(change):
    workload = isolated_spec()
    expected = build_pod(workload)
    modified = deepcopy(expected)
    if change == "privileged":
        modified["spec"]["containers"][0]["securityContext"]["privileged"] = True
    elif change == "raw_network":
        modified["spec"]["containers"][0]["securityContext"]["capabilities"]["add"].append("NET_RAW")
    elif change == "host_network":
        modified["spec"]["hostNetwork"] = True
    elif change == "credentials":
        modified["spec"]["automountServiceAccountToken"] = True
    elif change == "extra_volume":
        modified["spec"]["volumes"].append({"name": "host", "hostPath": {"path": "/"}})
    elif change == "entire_workspace_mount":
        modified["spec"]["containers"][0]["volumeMounts"].append({"name": "workspace", "mountPath": "/mnt/all-users"})
    else:
        next(v for v in modified["spec"]["volumes"] if v["name"] == "platform-auth")["secret"]["secretName"] = "other-user-auth"
    gateway = boundary_gateway()
    create, read = MagicMock(side_effect=ApiException(status=409)), MagicMock(return_value=deserialize(modified, V1Pod))
    with pytest.raises(ClusterOperationError, match="租户隔离"):
        gateway._ensure(create, read, expected, workload, "pod")


def test_network_boundary_is_default_deny_with_scoped_dns_and_proxy_access():
    policy = build_network_policy("platform-workloads", ["192.168.24.64/32"])
    boundary = policy["spec"]
    assert boundary["podSelector"] == {}
    assert set(boundary["policyTypes"]) == {"Ingress", "Egress"}
    dns = boundary["egress"][0]
    assert dns["to"][0]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"] == "kube-system"
    assert dns["to"][0]["podSelector"]["matchLabels"]["k8s-app"] == "kube-dns"
    internet = boundary["egress"][1]
    assert {"10.0.0.0/8", "192.168.0.0/16", "169.254.0.0/16"}.issubset(internet["to"][0]["ipBlock"]["except"])
    assert {p["port"] for p in internet["ports"]} == {22, 80, 443, 9418}
    assert boundary["ingress"][0]["from"][0]["podSelector"]["matchLabels"]["app.kubernetes.io/name"] == "traefik"


def test_retry_accepts_an_identical_hardened_pod():
    workload = isolated_spec()
    expected = build_pod(workload)
    resource = deserialize(expected, V1Pod)
    gateway = boundary_gateway()
    create = MagicMock(side_effect=ApiException(status=409))
    assert gateway._ensure(create, MagicMock(return_value=resource), expected, workload, "pod") is resource


def test_creation_payload_freezes_the_reviewed_security_boundary(monkeypatch):
    from app.core.config import settings
    from app.services.operation_service import OperationService

    monkeypatch.setattr(settings, "WORKLOAD_ISOLATION_ENABLED", True)
    monkeypatch.setattr(settings, "WORKLOAD_NETWORK_POLICY_SHA256", "a" * 64)
    payload = OperationService.creation_payload(SimpleNamespace(hostname="worker"), "platform.local", "jupyter-lab")
    monkeypatch.setattr(settings, "WORKLOAD_ISOLATION_ENABLED", False)
    monkeypatch.setattr(settings, "WORKLOAD_NETWORK_POLICY_SHA256", "")
    assert payload["options"]["isolation_enabled"] is True
    assert payload["options"]["isolation_policy_sha256"] == "a" * 64
