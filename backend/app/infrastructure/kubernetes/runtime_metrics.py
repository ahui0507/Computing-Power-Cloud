"""Owned pod metrics; missing samples stay missing instead of becoming zero."""

from kubernetes import client
from kubernetes.utils.quantity import parse_quantity
from app.core.config import settings
from app.infrastructure.kubernetes.client import create_clients
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.ephemeral_storage import storage_from_pod


def pod_usage(allocation, namespace):
    core, network = create_clients()
    try:
        pod = core.read_namespaced_pod(
            allocation.pod_name,
            namespace,
            _request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS,
        )
        KubernetesGateway._check_owner(pod, allocation.id, allocation.user_id)
        statuses = pod.status.container_statuses or []
        terminated = [
            state.terminated
            for status in statuses
            for state in (status.state, status.last_state)
            if state and state.terminated
        ]
        reasons = [state.reason for state in terminated if state.reason]
        result = {
            "ephemeral_storage": storage_from_pod(core, pod, namespace),
            "state": "missing",
            "cpu_percent": None,
            "memory_percent": None,
            "restart_count": sum(status.restart_count for status in statuses),
            "last_exit_reason": ", ".join(sorted(set(reasons))) or None,
        }
        try:
            metric = client.CustomObjectsApi(
                api_client=core.api_client
            ).get_namespaced_custom_object(
                "metrics.k8s.io",
                "v1beta1",
                namespace,
                "pods",
                allocation.pod_name,
                _request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS,
            )
            usages = [container["usage"] for container in metric["containers"]]
            cpu = sum(float(parse_quantity(usage["cpu"])) for usage in usages)
            memory = sum(int(parse_quantity(usage["memory"])) for usage in usages)
            result.update(
                state="live",
                cpu_percent=cpu / allocation.cpu_quota_cores * 100
                if allocation.cpu_quota_cores
                else None,
                memory_percent=memory / (allocation.ram_mb * 1024**2) * 100
                if allocation.ram_mb
                else None,
            )
        except client.exceptions.ApiException:
            pass
        return result
    finally:
        core.api_client.close()
        if core.api_client is not network.api_client:
            network.api_client.close()
