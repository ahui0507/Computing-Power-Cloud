"""Kubelet accounting for owned pods; persistent volumes and memory emptyDir are excluded."""
from datetime import datetime, timezone
import threading
import time

from kubernetes.utils.quantity import parse_quantity
from app.core.config import settings
from app.infrastructure.kubernetes.client import create_clients
from app.infrastructure.kubernetes.gateway import KubernetesGateway

_cache = {}
_lock = threading.Lock()


def empty_storage(limit=None):
    return dict(state='missing', used_bytes=None, limit_bytes=limit, remaining_bytes=None,
                used_percent=None, sampled_at=None, warning='unknown')


def pod_limit(pod):
    try:
        values = [int(parse_quantity(c.resources.limits['ephemeral-storage'])) for c in pod.spec.containers]
        return sum(values) if values and all(v > 0 for v in values) else None
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def node_summary(core, node):
    key = (core.api_client.configuration.host, node)
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < 15:
            return cached[1]
        try:
            data = core.api_client.call_api(
                '/api/v1/nodes/{name}/proxy/stats/summary', 'GET', path_params={'name': node},
                response_type='object', auth_settings=['BearerToken'], _return_http_data_only=True,
                _request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS,
            )
            if not isinstance(data, dict):
                data = None
        except Exception:
            data = None  # Cache failures too, so a node outage does not stall every allocation.
        _cache[key] = (time.monotonic(), data)
        if len(_cache) > 64:
            for stale in list(_cache):
                if time.monotonic() - _cache[stale][0] > 120:
                    _cache.pop(stale, None)
        return data


def storage_from_pod(core, pod, namespace, *, now=None):
    result = empty_storage(pod_limit(pod))
    uid = getattr(pod.metadata, 'uid', None)
    node = getattr(getattr(pod, 'spec', None), 'node_name', None)
    if not isinstance(uid, str) or not uid or not isinstance(node, str) or not node:
        return result
    try:
        data = node_summary(core, node)
        samples = data.get('pods', []) if data else []
        sample = next((p for p in samples if p.get('podRef') == {
            'name': pod.metadata.name, 'namespace': namespace, 'uid': uid}), None)
        usage = (sample or {}).get('ephemeral-storage', {})
        used, stamp = usage.get('usedBytes'), usage.get('time')
        if isinstance(used, bool) or not isinstance(used, int) or used < 0 or not isinstance(stamp, str):
            return result
        at = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if at.tzinfo is None:
            return result
        age = ((now or datetime.now(timezone.utc)) - at).total_seconds()
        if not -30 <= age <= 120:
            result.update(state='stale', sampled_at=stamp)
            return result
        limit = result['limit_bytes']
        percent = used / limit * 100 if limit else None
        result.update(state='live', used_bytes=used, sampled_at=stamp,
                      remaining_bytes=max(0, limit-used) if limit else None,
                      used_percent=percent,
                      warning='critical' if percent is not None and percent >= 90 else
                              'warning' if percent is not None and percent >= 80 else 'none')
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        pass
    return result


def pod_storage_usage(allocation, namespace):
    core, network = create_clients()
    try:
        pod = core.read_namespaced_pod(allocation.pod_name, namespace, _request_timeout=settings.K8S_REQUEST_TIMEOUT_SECONDS)
        KubernetesGateway._check_owner(pod, allocation.id, allocation.user_id)
        return storage_from_pod(core, pod, namespace)
    finally:
        core.api_client.close()
        if network.api_client is not core.api_client:
            network.api_client.close()
