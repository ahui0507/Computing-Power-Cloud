"""同步 Kubernetes 操作；异步业务入口将其放到线程中执行。"""

import logging
import time

from kubernetes.client.exceptions import ApiException

from app.core.config import settings
from app.core.exceptions import ClusterOperationError, ClusterUnavailableError
from app.core.time import utc_naive
from app.core.workspace import SEPARATE_LAYOUT, persistent_path
from app.infrastructure.kubernetes.status import PodStatus
from app.infrastructure.kubernetes.client import create_clients
from app.infrastructure.kubernetes.manifests import (
    WorkloadSpec,
    LEGACY_SSH_START,
    build_pod,
    build_service,
    build_ingress,
    build_auth_secret,
)

logger = logging.getLogger(__name__)


class KubernetesGateway:
    def __init__(self, core_api=None, networking_api=None):
        if core_api is None:
            core_api, networking_api = create_clients()
        self.core = core_api
        self.networking = networking_api
        self.namespace = settings.K8S_NAMESPACE
        self.timeout = settings.K8S_REQUEST_TIMEOUT_SECONDS

    @staticmethod
    def _check_owner(resource, allocation_id, user_id, *, kind=None, pod_name=None):
        labels = resource.metadata.labels or {}
        if labels.get("allocation-id") == str(allocation_id) and (
            user_id is None or labels.get("user-id") == str(user_id)
        ):
            return
        # 旧版 Service/Ingress 可能只带 allocation-id/app，没有 user-id。
        # 已有归属标签不得冲突，再通过明确的目标工作负载核对。
        legacy_owner = (
            labels.get("allocation-id") in (None, str(allocation_id))
            and labels.get("user-id") is None
        )
        if (
            legacy_owner
            and kind == "service"
            and (resource.spec.selector or {}).get("app") == pod_name
        ):
            return
        if legacy_owner and kind == "ingress":
            backends = [
                path.backend.service.name
                for rule in (resource.spec.rules or [])
                for path in (rule.http.paths if rule.http else [])
            ]
            if backends and all(name == f"svc-{allocation_id}" for name in backends):
                return
        raise ClusterOperationError("集群对象归属不匹配，保留资源等待核对", cleanup_attempted=True)

    def _ensure(self, create, read, manifest, spec, kind):
        try:
            return create(namespace=self.namespace, body=manifest, _request_timeout=self.timeout)
        except ApiException as exc:
            if exc.status != 409:
                raise
            resource = read(
                name=manifest["metadata"]["name"],
                namespace=self.namespace,
                _request_timeout=self.timeout,
            )
            self._check_owner(
                resource,
                spec.allocation_id,
                spec.user_id,
                kind=kind,
                pod_name=spec.pod_name,
            )
            if kind == "secret" and (resource.data or {}).get("token") != manifest["data"]["token"]:
                raise ClusterOperationError("已有实例凭证与当前配置不同", cleanup_attempted=True)
            if kind == "pod":
                container = resource.spec.containers[0]
                count = (container.resources.limits or {}).get("nvidia.com/gpu")
                if (
                    container.image != spec.image
                    or (resource.spec.node_selector or {}).get("kubernetes.io/hostname")
                    != spec.node_name
                    or str(count) != str(spec.gpu_count)
                ):
                    raise ClusterOperationError("已有 Pod 与申请参数不同", cleanup_attempted=True)
                env = next(
                    (item for item in (container.env or []) if item.name == "JUPYTER_TOKEN"),
                    None,
                )
                mounts = container.volume_mounts or []
                if (
                    spec.cpu_millicores is not None
                    or spec.cpu_cores is not None
                    or spec.ram_mb is not None
                ):
                    from decimal import Decimal
                    from kubernetes.utils.quantity import parse_quantity

                    expected_cpu = (
                        Decimal(spec.cpu_millicores) / 1000
                        if spec.cpu_millicores is not None
                        else spec.cpu_cores
                    )
                    for resources in (
                        container.resources.requests or {},
                        container.resources.limits or {},
                    ):
                        if (
                            expected_cpu is not None
                            and parse_quantity(resources.get("cpu", "0")) != expected_cpu
                        ) or (
                            spec.ram_mb is not None
                            and parse_quantity(resources.get("memory", "0"))
                            != spec.ram_mb * 1024**2
                        ):
                            raise ClusterOperationError(
                                "已有 Pod 的 CPU/内存配额与申请不同",
                                cleanup_attempted=True,
                            )
                legacy_command = spec.ssh_enabled and container.command == [
                    "/bin/bash",
                    "-c",
                    LEGACY_SSH_START,
                    "platform-start",
                    spec.jupyter_command,
                ]
                if (
                    (
                        container.command != manifest["spec"]["containers"][0]["command"]
                        and not legacy_command
                    )
                    or container.args != manifest["spec"]["containers"][0]["args"]
                    or env is None
                    or env.value_from is None
                    or env.value_from.secret_key_ref is None
                    or env.value_from.secret_key_ref.name != spec.auth_secret_name
                    or env.value_from.secret_key_ref.key != "token"
                    or not any(
                        volume.name == "workspace"
                        and volume.persistent_volume_claim is not None
                        and volume.persistent_volume_claim.claim_name == spec.workspace_claim
                        for volume in (resource.spec.volumes or [])
                    )
                    or not any(
                        item.mount_path == persistent_path({"storage_layout": spec.storage_layout})
                        and item.sub_path == f"user_{spec.user_id}"
                        for item in mounts
                    )
                ):
                    raise ClusterOperationError(
                        "已有 Pod 缺少所需的鉴权或工作目录配置", cleanup_attempted=True
                    )
                if spec.storage_layout == SEPARATE_LAYOUT and (
                    any(item.mount_path == "/workspace" for item in mounts)
                    or not any(
                        item.mount_path == "/run/platform-shell" and item.name == "platform-shell"
                        for item in mounts
                    )
                    or not any(
                        volume.name == "platform-shell" and volume.empty_dir is not None
                        for volume in (resource.spec.volumes or [])
                    )
                ):
                    raise ClusterOperationError(
                        "已有 Pod 的临时工作目录或终端配置不同", cleanup_attempted=True
                    )
            return resource

    def create(self, spec: WorkloadSpec) -> dict:
        self.namespace = spec.namespace
        try:
            claim = self.core.read_namespaced_persistent_volume_claim(
                name=spec.workspace_claim,
                namespace=self.namespace,
                _request_timeout=self.timeout,
            )
        except Exception as exc:
            raise ClusterUnavailableError("共享工作目录 PVC 不存在或不可访问") from exc
        if claim.status.phase != "Bound" or "ReadWriteMany" not in (claim.spec.access_modes or []):
            raise ClusterUnavailableError("共享工作目录 PVC 必须已绑定并支持 ReadWriteMany")
        try:
            self._ensure(
                self.core.create_namespaced_secret,
                self.core.read_namespaced_secret,
                build_auth_secret(spec),
                spec,
                "secret",
            )
            self._ensure(
                self.core.create_namespaced_pod,
                self.core.read_namespaced_pod,
                build_pod(spec),
                spec,
                "pod",
            )
            service = self._ensure(
                self.core.create_namespaced_service,
                self.core.read_namespaced_service,
                build_service(spec),
                spec,
                "service",
            )
            if spec.ingress_enabled:
                self._ensure(
                    self.networking.create_namespaced_ingress,
                    self.networking.read_namespaced_ingress,
                    build_ingress(spec),
                    spec,
                    "ingress",
                )
            ports = {"ssh_port": None, "vnc_port": None, "jupyter_port": None}
            if not spec.ingress_enabled or spec.ssh_enabled:
                for port in service.spec.ports or []:
                    ports[f"{port.name}_port"] = port.node_port
                if (spec.ssh_enabled and not ports["ssh_port"]) or (
                    not spec.ssh_enabled and not all(ports.values())
                ):
                    raise ValueError("NodePort 未完整分配")
        except ClusterOperationError:
            raise
        except Exception as exc:
            # 回收意图由业务执行器落库。适配层不在创建失败时盲目删除已有对象。
            raise ClusterOperationError("创建 Kubernetes 工作负载失败") from exc
        try:
            phase = self.status(spec.pod_name)
        except ClusterOperationError:
            phase = "pending"
        return {
            "pod_name": spec.pod_name,
            "status": phase or "pending",
            "jupyter_url": spec.jupyter_url,
            "started_at": getattr(phase, "started_at", None),
            "finished_at": getattr(phase, "finished_at", None),
            "status_message": getattr(phase, "message", None),
            **ports,
        }

    def delete(self, pod_name: str, allocation_id=None, user_id=None) -> None:
        if allocation_id is None:
            parts = pod_name.split("-")
            if len(parts) < 2 or not parts[1].isdigit():
                raise ClusterOperationError("无法识别工作负载所属的资源申请")
            allocation_id = parts[1]
        try:
            pod = self.core.read_namespaced_pod(
                name=pod_name, namespace=self.namespace, _request_timeout=self.timeout
            )
        except ApiException as exc:
            if exc.status != 404:
                raise ClusterOperationError("无法核对 Pod 所属申请") from exc
        except Exception as exc:
            raise ClusterOperationError("无法核对 Pod 所属申请") from exc
        else:
            labels = pod.metadata.labels or {}
            if labels.get("allocation-id") != str(allocation_id) or (
                user_id is not None and labels.get("user-id") != str(user_id)
            ):
                raise ClusterOperationError("Pod 归属不匹配，未删除集群资源")
        operations = [
            (
                self.networking.read_namespaced_ingress,
                self.networking.delete_namespaced_ingress,
                f"jupyter-{allocation_id}",
                "ingress",
            ),
            (
                self.core.read_namespaced_service,
                self.core.delete_namespaced_service,
                f"svc-{allocation_id}",
                "service",
            ),
            (
                self.core.read_namespaced_pod,
                self.core.delete_namespaced_pod,
                pod_name,
                "pod",
            ),
            (
                self.core.read_namespaced_secret,
                self.core.delete_namespaced_secret,
                f"jupyter-auth-{allocation_id}",
                "secret",
            ),
        ]
        errors = []
        for read, delete, name, kind in operations:
            try:
                resource = read(name=name, namespace=self.namespace, _request_timeout=self.timeout)
                self._check_owner(resource, allocation_id, user_id, kind=kind, pod_name=pod_name)
                delete(name=name, namespace=self.namespace, _request_timeout=self.timeout)
            except ApiException as exc:
                if exc.status != 404:
                    errors.append(exc)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise ClusterOperationError("删除 Kubernetes 资源失败，资源预留已保留") from errors[0]

        deadline = time.monotonic() + settings.K8S_DELETE_TIMEOUT_SECONDS
        while True:
            try:
                self.core.read_namespaced_pod(
                    name=pod_name,
                    namespace=self.namespace,
                    _request_timeout=self.timeout,
                )
            except ApiException as exc:
                if exc.status == 404:
                    return
                raise ClusterOperationError("无法确认 Pod 已删除") from exc
            except Exception as exc:
                raise ClusterOperationError("无法确认 Pod 已删除") from exc
            if time.monotonic() >= deadline:
                raise ClusterOperationError("Pod 删除超时，资源预留已保留")
            time.sleep(0.2)

    def status(self, pod_name: str):
        try:
            pod = self.core.read_namespaced_pod(
                name=pod_name, namespace=self.namespace, _request_timeout=self.timeout
            )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise ClusterOperationError("读取 Pod 状态失败") from exc
        except Exception as exc:
            raise ClusterOperationError("读取 Pod 状态失败") from exc

        phase = pod.status.phase
        starts, finishes, reasons, exits = [], [], [], []
        containers = getattr(pod.status, "container_statuses", None) or []
        for container in containers:
            for state in (container.state, container.last_state):
                if state is None:
                    continue
                running = state.running
                terminated = state.terminated
                if running and running.started_at:
                    starts.append(utc_naive(running.started_at))
                if terminated:
                    if getattr(terminated, "reason", None) == "OOMKilled":
                        exits.append(
                            "内存达到实例分配额度（OOMKilled），请减小批量或申请更多 GPU 份额"
                        )
                    if terminated.started_at:
                        starts.append(utc_naive(terminated.started_at))
                    if terminated.finished_at:
                        finishes.append(utc_naive(terminated.finished_at))
            waiting = container.state.waiting if container.state else None
            if waiting and waiting.reason in (
                "CrashLoopBackOff",
                "ImagePullBackOff",
                "ErrImagePull",
                "InvalidImageName",
                "CreateContainerConfigError",
                "CreateContainerError",
            ):
                reasons.append(f"{waiting.reason}: {waiting.message or ''}")
        details = {
            "started_at": min(starts) if starts else None,
            "finished_at": max(finishes) if finishes else None,
            "message": (
                "; ".join(dict.fromkeys(reasons + exits))
                or getattr(pod.status, "message", None)
                or ""
            )[:512]
            or None,
            "admission_rejected": phase == "Failed"
            and getattr(pod.status, "reason", None) == "UnexpectedAdmissionError"
            and not containers,
        }
        if reasons:
            return PodStatus("failed", **details)
        if phase == "Running":
            ready = any(
                condition.type == "Ready" and condition.status == "True"
                for condition in (pod.status.conditions or [])
            )
            if ready:
                details["finished_at"] = None
            return PodStatus("running" if ready else "pending", **details)
        return PodStatus(
            {"Pending": "pending", "Failed": "failed", "Succeeded": "stopped"}.get(
                phase, "pending"
            ),
            **details,
        )

    def close(self):
        self.core.api_client.close()
