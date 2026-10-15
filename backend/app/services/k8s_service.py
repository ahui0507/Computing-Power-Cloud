"""兼容业务调用的异步入口；集群实现位于 infrastructure/kubernetes。"""
import asyncio

from app.core.config import settings
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.infrastructure.kubernetes.manifests import WorkloadSpec
from app.services.jupyter_service import JupyterService


def _execute(operation, *args, namespace=None, **kwargs):
    gateway = KubernetesGateway()
    if namespace:
        gateway.namespace = namespace
    try:
        return getattr(gateway, operation)(*args, **kwargs)
    finally:
        gateway.close()


class K8sService:
    @staticmethod
    async def create_pod(
        allocation,
        image: str,
        gpu_count: int,
        *,
        node_name: str,
        host: str,
        command=None,
        options=None,
    ):
        values = dict(
            allocation_id=allocation.id,
            user_id=allocation.user_id,
            pod_name=allocation.pod_name,
            image=image,
            gpu_count=gpu_count,
            node_name=node_name,
            namespace=settings.K8S_NAMESPACE,
            ingress_enabled=settings.INGRESS_ENABLED,
            ingress_host=host,
            ingress_class=settings.INGRESS_CLASS,
            use_tls=settings.INGRESS_USE_TLS,
            image_pull_policy=settings.K8S_IMAGE_PULL_POLICY,
            jupyter_command=command or settings.JUPYTER_COMMAND,
            jupyter_token=JupyterService.token(allocation.id, allocation.user_id),
            workspace_claim=settings.WORKSPACE_PVC_NAME,
            workspace_gid=settings.WORKSPACE_GID,
            gpu_runtime_class=settings.K8S_GPU_RUNTIME_CLASS,
            shared_memory_size=settings.WORKLOAD_SHM_SIZE_LIMIT,
            cpu_cores=getattr(allocation, "cpu_cores", None),
            cpu_millicores=getattr(allocation, "cpu_millicores", None),
            ram_mb=getattr(allocation, "ram_mb", None),
        )
        values.update(options or {})
        if values.get("ssh_enabled"):
            from app.core.instance_credentials import ssh_password_hash
            values["ssh_password_hash"] = ssh_password_hash(allocation.id, allocation.user_id)
        spec = WorkloadSpec(**values)
        return await asyncio.to_thread(_execute, "create", spec)

    @staticmethod
    async def delete_pod(pod_name: str, *, user_id=None, namespace=None) -> None:
        await asyncio.to_thread(_execute, "delete", pod_name, user_id=user_id, namespace=namespace)

    @staticmethod
    async def get_pod_status(pod_name: str, *, namespace=None):
        return await asyncio.to_thread(_execute, "status", pod_name, namespace=namespace)
