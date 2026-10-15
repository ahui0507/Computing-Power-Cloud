import json
import urllib.error
import urllib.request

from app.core.config import settings
from app.core.exceptions import ClusterUnavailableError


class WorkerAgentClient:
    @staticmethod
    def request(node_name, path, body=None, method=None):
        urls = json.loads(settings.WORKER_AGENT_URLS)
        if not settings.WORKER_AGENT_TOKEN or node_name not in urls:
            raise ClusterUnavailableError("此节点尚未配置个人镜像保存服务")
        request = urllib.request.Request(urls[node_name].rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + settings.WORKER_AGENT_TOKEN, "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise ClusterUnavailableError("个人镜像保存服务暂不可用") from exc
        except (OSError, ValueError) as exc:
            raise ClusterUnavailableError("无法连接个人镜像保存服务，请稍后重试") from exc
