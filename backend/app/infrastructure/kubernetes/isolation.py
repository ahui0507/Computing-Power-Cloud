"""Tenant pod permissions and the reviewed namespace network boundary."""
import hashlib
import json

TENANT_LABEL = "cpcloud.io/tenant-workload"
SERVICE_ACCOUNT = "platform-workload"
POLICY_NAME = "cpcloud-tenant-boundary"
CAPABILITIES = [
    "CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID", "KILL", "SETGID", "SETUID",
    "SETPCAP", "NET_BIND_SERVICE", "SYS_CHROOT", "AUDIT_WRITE",
]
PRIVATE_NETWORKS = [
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16", "192.0.0.0/24",
    "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
    "224.0.0.0/4", "240.0.0.0/4",
]


def policy_digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_network_policy(namespace, control_cidrs):
    system = {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}}
    spec = {
        "podSelector": {},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [
            {"from": [{"namespaceSelector": system, "podSelector": {"matchLabels": {"app.kubernetes.io/name": "traefik"}}}], "ports": [{"protocol": "TCP", "port": 8888}]},
            {"from": [{"ipBlock": {"cidr": cidr}} for cidr in control_cidrs], "ports": [{"protocol": "TCP", "port": 22}]},
        ],
        "egress": [
            {"to": [{"namespaceSelector": system, "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}}}], "ports": [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]},
            {"to": [{"ipBlock": {"cidr": "0.0.0.0/0", "except": PRIVATE_NETWORKS}}], "ports": [{"protocol": "TCP", "port": port} for port in (80, 443, 22, 9418)]},
        ],
    }
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": POLICY_NAME, "namespace": namespace, "labels": {"app.kubernetes.io/managed-by": "cpcloud"}, "annotations": {"cpcloud.io/policy-sha256": policy_digest(spec)}}, "spec": spec}


def harden_pod(manifest, service_account=SERVICE_ACCOUNT):
    manifest["metadata"]["labels"][TENANT_LABEL] = "true"
    pod = manifest["spec"]
    pod.update(automountServiceAccountToken=False, serviceAccountName=service_account, enableServiceLinks=False, hostNetwork=False, hostPID=False, hostIPC=False, shareProcessNamespace=False)
    for container in pod["containers"]:
        security = container.setdefault("securityContext", {})
        security.update(privileged=False, allowPrivilegeEscalation=False, capabilities={"drop": ["ALL"], "add": CAPABILITIES.copy()}, seccompProfile={"type": "RuntimeDefault"})


def hardened_pod_matches(resource, expected):
    """Reject adoption of pods with additional host access or credentials."""
    pod = resource.spec
    if (resource.metadata.labels or {}).get(TENANT_LABEL) != "true":
        return False
    if pod.automount_service_account_token is not False or pod.service_account_name != expected["spec"]["serviceAccountName"]:
        return False
    if any(getattr(pod, field, False) for field in ("host_network", "host_pid", "host_ipc", "share_process_namespace")):
        return False
    if pod.enable_service_links is not False or len(pod.containers) != 1 or pod.init_containers or pod.ephemeral_containers:
        return False
    if (pod.node_selector or {}).get("cpcloud.io/tenant-isolation") != "v1":
        return False
    if {v.name for v in (pod.volumes or [])} != {v["name"] for v in expected["spec"]["volumes"]}:
        return False
    if any(v.host_path is not None or v.projected is not None for v in (pod.volumes or [])):
        return False
    expected_volumes = {item["name"]: item for item in expected["spec"]["volumes"]}
    for volume in pod.volumes or []:
        wanted = expected_volumes[volume.name]
        if "secret" in wanted and (volume.secret is None or volume.secret.secret_name != wanted["secret"]["secretName"]):
            return False
        if "emptyDir" in wanted and volume.empty_dir is None:
            return False
        if wanted.get("emptyDir", {}).get("sizeLimit"):
            from kubernetes.utils.quantity import parse_quantity
            if parse_quantity(getattr(volume.empty_dir, "size_limit", None) or "0") != parse_quantity(wanted["emptyDir"]["sizeLimit"]):
                return False
        if "persistentVolumeClaim" in wanted and (volume.persistent_volume_claim is None or volume.persistent_volume_claim.claim_name != wanted["persistentVolumeClaim"]["claimName"]):
            return False
    expected_mounts = sorted((item["name"], item["mountPath"], item.get("subPath", ""), bool(item.get("readOnly"))) for item in expected["spec"]["containers"][0]["volumeMounts"])
    actual_mounts = sorted((item.name, item.mount_path, item.sub_path or "", bool(item.read_only)) for item in pod.containers[0].volume_mounts or [])
    if actual_mounts != expected_mounts or any(item.sub_path_expr or item.mount_propagation for item in pod.containers[0].volume_mounts or []):
        return False
    security = pod.containers[0].security_context
    return bool(security and security.privileged is False and security.allow_privilege_escalation is False and security.capabilities and set(security.capabilities.drop or []) == {"ALL"} and set(security.capabilities.add or []) == set(CAPABILITIES) and security.seccomp_profile and security.seccomp_profile.type == "RuntimeDefault")
