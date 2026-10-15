"""将平台接入配置转换为工作负载的访问地址。"""
from app.core.config import settings
from app.models.node import Node
from app.models.operation import OperationKind


class AccessService:
    @staticmethod
    def get_jupyter_host(db) -> str:
        if settings.CONTROL_NODE_ID:
            node = db.get(Node, settings.CONTROL_NODE_ID)
            if node and node.ip:
                return node.ip
        return settings.INGRESS_HOST

    @staticmethod
    def get_jupyter_url(db, allocation_id: int, *, node_ip=None, port=None, options=None):
        options = options or {}
        if not options.get("ingress_enabled", settings.INGRESS_ENABLED):
            host = options.get("access_host") or (
                AccessService.get_jupyter_host(db) if settings.CONTROL_NODE_ID else node_ip
            )
            if not host or not port:
                return None
            host = f"[{host}]" if ":" in host and not host.startswith("[") else host
            return f"http://{host}:{port}/"
        protocol = "https" if options.get("use_tls", settings.INGRESS_USE_TLS) else "http"
        host = options.get("ingress_host") or AccessService.get_jupyter_host(db)
        host = f"[{host}]" if ":" in host and not host.startswith("[") else host
        return f"{protocol}://{host}/jupyter/{allocation_id}/"

    @staticmethod
    def allocation_options(allocation):
        created = next(
            (
                operation
                for operation in allocation.operations
                if operation.kind == OperationKind.CREATE
            ),
            None,
        )
        if not created:
            return {}
        return {
            **created.payload.get("options", {}),
            "access_host": created.payload.get("access_host"),
        }
