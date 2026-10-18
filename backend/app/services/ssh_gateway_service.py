"""Provision an instance-scoped SSH forwarding identity through a root helper."""
import json
import subprocess

from app.core.config import settings
from app.core.exceptions import ClusterOperationError


class SSHGatewayService:
    @staticmethod
    def ensure(allocation):
        try:
            result = subprocess.run(
                ["sudo", "-n", settings.SSH_GATEWAY_HELPER, "ensure", str(allocation.id)],
                capture_output=True, text=True, timeout=30,
            )
            result.check_returncode()
            value = json.loads(result.stdout)
            if (
                value.get("username") != f"cpjump-{allocation.id}"
                or value.get("port") != allocation.ssh_port
                or value.get("target_host") != "127.0.0.1"
                or value.get("ready") is not True
            ):
                raise ValueError("Unexpected gateway identity")
            return value["username"]
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ClusterOperationError("实例 SSH 转发正在准备，请稍后刷新连接信息") from error
