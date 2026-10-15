"""创建独立的 Kubernetes API 客户端。"""
import os

from kubernetes import client, config

from app.core.config import settings
from app.core.exceptions import ClusterUnavailableError


def create_clients():
    configuration = client.Configuration()
    try:
        kubeconfig = settings.K8S_CONFIG_PATH or os.environ.get("KUBECONFIG")
        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig, client_configuration=configuration)
        elif os.path.exists(os.path.expanduser("~/.kube/config")):
            config.load_kube_config(client_configuration=configuration)
        else:
            config.load_incluster_config(client_configuration=configuration)
    except Exception as exc:
        raise ClusterUnavailableError("无法加载 Kubernetes 连接配置") from exc

    if settings.K8S_API_SERVER:
        configuration.host = settings.K8S_API_SERVER
    api_client = client.ApiClient(configuration)
    return client.CoreV1Api(api_client), client.NetworkingV1Api(api_client)
