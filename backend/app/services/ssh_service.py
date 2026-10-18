from base64 import b64encode
import ipaddress
from urllib.parse import urlsplit

from app.core.exceptions import ResourceConflictError
from app.core.config import settings
from app.core.exceptions import ClusterOperationError
from app.core.instance_credentials import ssh_password, ssh_password_hash
from app.core.workspace import persistent_path
from app.infrastructure.kubernetes.ssh_runtime import SSH_PASSWORD_SETUP
from app.infrastructure.kubernetes.client import create_clients
from app.infrastructure.kubernetes.gateway import KubernetesGateway
from app.models.ssh_key import SSHKey
from app.services.access_service import AccessService
from app.services.job_service import JobService
from app.services.ssh_gateway_service import SSHGatewayService


class SSHService:
    @staticmethod
    def connection(db, user_id, container_id):
        allocation = JobService.allocation(db, user_id, container_id, running=True)
        options = AccessService.allocation_options(allocation)
        if not options.get("ssh_enabled") or not allocation.ssh_port:
            raise ResourceConflictError(
                "此实例镜像不支持 SSH，请使用支持 SSH 的公共环境或个人镜像创建实例"
            )
        keys = db.query(SSHKey).filter_by(user_id=user_id).all()
        password_hash = ssh_password_hash(allocation.id, user_id)
        core, network = create_clients()
        namespace = options.get("namespace")
        try:
            pod = core.read_namespaced_pod(allocation.pod_name, namespace)
            KubernetesGateway._check_owner(pod, allocation.id, user_id)
            secret_name = f"jupyter-auth-{allocation.id}"
            secret = core.read_namespaced_secret(secret_name, namespace)
            KubernetesGateway._check_owner(secret, allocation.id, user_id)
            core.patch_namespaced_secret(
                secret_name,
                namespace,
                {
                    "data": {
                        "password_hash": b64encode(password_hash.encode()).decode(),
                        "authorized_keys": b64encode(
                            ("\n".join(row.public_key for row in keys) + "\n").encode()
                        ).decode(),
                    }
                },
            )
        finally:
            core.api_client.close()
            if network.api_client is not core.api_client:
                network.api_client.close()
        output = JobService.execute(
            allocation, "PASSWORD_HASH=" + repr(password_hash) + "\n" + SSH_PASSWORD_SETUP
        )
        if "SSH_PASSWORD_READY" not in output:
            raise ClusterOperationError("SSH 密码配置暂未完成，请重试连接信息")
        host = options.get("access_host") or AccessService.get_jupyter_host(db)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # The HTTP publishing port is independent of the instance SSH NodePort.
            host = urlsplit("//" + host).hostname or host
        jump_host = settings.SSH_JUMP_HOST
        if settings.SSH_GATEWAY_ENABLED:
            if not settings.SSH_GATEWAY_ENDPOINT:
                raise ClusterOperationError("实例 SSH 转发入口尚未配置")
            gateway_user = SSHGatewayService.ensure(allocation)
            jump_host = f"{gateway_user}@{settings.SSH_GATEWAY_ENDPOINT}"
        if jump_host:
            host = "127.0.0.1"
        command = f"ssh -p {allocation.ssh_port} root@{host}"
        if jump_host:
            command = f"ssh -J {jump_host} -p {allocation.ssh_port} root@{host}"
        return {
            "host": host,
            "port": allocation.ssh_port,
            "username": "root",
            "auth_type": "password",
            "password": ssh_password(allocation.id, user_id),
            "key_count": len(keys),
            "tunnel_enabled": settings.SSH_TUNNEL_ENABLED,
            "jump_host": jump_host,
            "jump_uses_instance_password": bool(settings.SSH_GATEWAY_ENABLED),
            "command": command,
            "workspace_path": "/workspace",
            "persistent_path": persistent_path(options),
        }
