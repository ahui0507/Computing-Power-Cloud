"""纯资源模板：只接收运行参数，不依赖 ORM 或数据库。"""

from dataclasses import dataclass
from base64 import b64encode
import shlex
import json
from urllib.parse import urlsplit
from app.core.workspace import LEGACY_LAYOUT, SEPARATE_LAYOUT, persistent_path
from app.infrastructure.kubernetes.shell_runtime import SHELL_SETUP
from app.infrastructure.kubernetes.ssh_runtime import SSH_PASSWORD_SETUP


SSH_START = r"""set -eu
umask 0002
mkdir -p /run/sshd /run/platform-ssh
if [ ! -f /run/platform-ssh/host_key ]; then
  ssh-keygen -q -t ed25519 -N '' -f /run/platform-ssh/host_key
fi
cat > /run/platform-ssh/sshd_config <<'EOF'
Port 22
ListenAddress 0.0.0.0
HostKey /run/platform-ssh/host_key
PidFile /run/platform-ssh/sshd.pid
AuthorizedKeysFile /run/platform-auth/authorized_keys
PermitRootLogin yes
PubkeyAuthentication yes
PasswordAuthentication yes
KbdInteractiveAuthentication no
UsePAM no
StrictModes no
Subsystem sftp internal-sftp -u 0002
EOF
python -c 'import os; from pathlib import Path; p=Path("/run/platform-ssh/sshd_config"); names=("PATH","LD_LIBRARY_PATH","CUDA_HOME","NVIDIA_VISIBLE_DEVICES","NVIDIA_DRIVER_CAPABILITIES","NCCL_P2P_DISABLE"); p.write_text(p.read_text()+"".join("SetEnv "+n+"="+os.environ[n]+"\n" for n in names if n in os.environ and not any(c.isspace() for c in os.environ[n])))'
/usr/sbin/sshd -f /run/platform-ssh/sshd_config
exec "$@"
"""
LEGACY_SSH_START = SSH_START.replace(
    "PermitRootLogin yes", "PermitRootLogin prohibit-password"
).replace("PasswordAuthentication yes", "PasswordAuthentication no")
SSH_START = SSH_START.replace(
    "mkdir -p /run/sshd /run/platform-ssh\n",
    "mkdir -p /run/sshd /run/platform-ssh\npython -c " + shlex.quote(SSH_PASSWORD_SETUP) + "\n",
)


@dataclass(frozen=True)
class WorkloadSpec:
    allocation_id: int
    user_id: int
    pod_name: str
    image: str
    gpu_count: int
    node_name: str
    namespace: str
    ingress_enabled: bool
    ingress_host: str
    ingress_class: str
    use_tls: bool
    image_pull_policy: str
    jupyter_command: str
    jupyter_token: str
    workspace_claim: str
    workspace_gid: int = 1000
    gpu_runtime_class: str = "nvidia"
    ssh_enabled: bool = False
    ssh_authorized_keys: str = ""
    ssh_password_hash: str = ""
    shared_memory_size: str = "1Gi"
    nccl_p2p_disable: bool = False
    cpu_cores: int | None = None
    cpu_millicores: int | None = None
    ram_mb: int | None = None
    storage_layout: str = LEGACY_LAYOUT

    @property
    def auth_secret_name(self) -> str:
        return f"jupyter-auth-{self.allocation_id}"

    @property
    def service_name(self) -> str:
        return f"svc-{self.allocation_id}"

    @property
    def ingress_name(self) -> str:
        return f"jupyter-{self.allocation_id}"

    @property
    def jupyter_path(self) -> str:
        return f"/jupyter/{self.allocation_id}/"

    @property
    def jupyter_url(self):
        if not self.ingress_enabled:
            return None
        protocol = "https" if self.use_tls else "http"
        return f"{protocol}://{self.ingress_host}{self.jupyter_path}"


def build_pod(spec: WorkloadSpec) -> dict:
    gpu_resources = {"nvidia.com/gpu": str(spec.gpu_count)}
    if spec.cpu_millicores is not None:
        gpu_resources["cpu"] = f"{spec.cpu_millicores}m"
    elif spec.cpu_cores is not None:
        gpu_resources["cpu"] = str(spec.cpu_cores)
    if spec.ram_mb is not None:
        gpu_resources["memory"] = f"{spec.ram_mb}Mi"
    base_url = spec.jupyter_path if spec.ingress_enabled else "/"
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": spec.pod_name,
            "namespace": spec.namespace,
            "labels": {
                "app": spec.pod_name,
                "allocation-id": str(spec.allocation_id),
                "user-id": str(spec.user_id),
            },
        },
        "spec": {
            # 与业务层预留的节点保持一致，具体设备由 NVIDIA device plugin 分配。
            "nodeSelector": {"kubernetes.io/hostname": spec.node_name},
            "restartPolicy": "Always",
            "securityContext": {
                "fsGroup": spec.workspace_gid,
                "fsGroupChangePolicy": "OnRootMismatch",
            },
            "volumes": [
                {
                    "name": "workspace",
                    "persistentVolumeClaim": {
                        "claimName": spec.workspace_claim,
                    },
                },
                {
                    "name": "shared-memory",
                    "emptyDir": {"medium": "Memory", "sizeLimit": spec.shared_memory_size},
                },
                {"name": "jupyter-runtime", "emptyDir": {}},
            ],
            "containers": [
                {
                    "name": "container",
                    "image": spec.image,
                    "imagePullPolicy": spec.image_pull_policy,
                    "workingDir": "/workspace",
                    "volumeMounts": [
                        {
                            "name": "workspace",
                            "mountPath": "/workspace",
                            "subPath": f"user_{spec.user_id}",
                        },
                        {"name": "shared-memory", "mountPath": "/dev/shm"},
                        {"name": "jupyter-runtime", "mountPath": "/run/platform-jupyter"},
                    ],
                    "env": [
                        {
                            "name": "JUPYTER_TOKEN",
                            "valueFrom": {
                                "secretKeyRef": {
                                    "name": spec.auth_secret_name,
                                    "key": "token",
                                }
                            },
                        },
                        {"name": "NVIDIA_DRIVER_CAPABILITIES", "value": "compute,utility"},
                        {"name": "JUPYTER_RUNTIME_DIR", "value": "/run/platform-jupyter"},
                    ],
                    "ports": [
                        {"containerPort": port, "name": name, "protocol": "TCP"}
                        for name, port in (("jupyter", 8888), ("vnc", 5901), ("ssh", 22))
                    ],
                    "resources": {"requests": gpu_resources, "limits": gpu_resources},
                    "command": [spec.jupyter_command],
                    "args": [
                        f"--ServerApp.base_url={base_url}",
                        "--IdentityProvider.token=$(JUPYTER_TOKEN)",
                        "--ServerApp.root_dir=/workspace",
                        "--ip=0.0.0.0",
                        "--port=8888",
                        "--no-browser",
                        "--allow-root",
                        "--ServerApp.log_level=WARN",
                    ],
                    "readinessProbe": {
                        "tcpSocket": {"port": 8888},
                        "initialDelaySeconds": 3,
                        "periodSeconds": 5,
                    },
                }
            ],
        },
    }
    if spec.nccl_p2p_disable:
        manifest["spec"]["containers"][0]["env"].append(
            {"name": "NCCL_P2P_DISABLE", "value": "1"}
        )
    if spec.storage_layout not in (LEGACY_LAYOUT, SEPARATE_LAYOUT):
        raise ValueError("Unknown storage layout")
    if spec.storage_layout == SEPARATE_LAYOUT:
        container = manifest["spec"]["containers"][0]
        container["volumeMounts"][0]["mountPath"] = persistent_path(
            {"storage_layout": spec.storage_layout}
        )
        manifest["spec"]["volumes"].append({"name": "platform-shell", "emptyDir": {}})
        container["volumeMounts"].append(
            {"name": "platform-shell", "mountPath": "/run/platform-shell"}
        )
        container["env"].extend(
            [{"name": "SHELL", "value": "/bin/bash"}, {"name": "TERM", "value": "xterm-256color"}]
        )
        container["args"][2] = "--ServerApp.root_dir=/"
        container["args"].extend(
            [
                "--ServerApp.preferred_dir=/workspace",
                "--FileContentsManager.preferred_dir=/workspace",
                "--ServerApp.default_url=/lab/tree/workspace",
                "--ServerApp.terminado_settings="
                + json.dumps({"shell_command": ["/bin/bash", "-il"]}, separators=(",", ":")),
            ]
        )
        start = "set -eu\numask 0002\npython -c " + shlex.quote(SHELL_SETUP) + '\nexec "$@"\n'
        container["command"] = ["/bin/bash", "-c", start, "platform-start", spec.jupyter_command]
    if spec.gpu_runtime_class:
        manifest["spec"]["runtimeClassName"] = spec.gpu_runtime_class
    if spec.ssh_enabled:
        manifest["spec"]["volumes"].extend(
            [
                {
                    "name": "platform-auth",
                    "secret": {"secretName": spec.auth_secret_name, "defaultMode": 0o400},
                },
                {"name": "platform-ssh", "emptyDir": {}},
            ]
        )
        container = manifest["spec"]["containers"][0]
        container["securityContext"] = {"runAsUser": 0, "runAsGroup": spec.workspace_gid}
        container["volumeMounts"].extend(
            [
                {"name": "platform-auth", "mountPath": "/run/platform-auth", "readOnly": True},
                {"name": "platform-ssh", "mountPath": "/run/platform-ssh"},
            ]
        )
        start = SSH_START
        if spec.storage_layout == SEPARATE_LAYOUT:
            enhanced = SSH_START.replace(
                "/usr/sbin/sshd -f /run/platform-ssh/sshd_config",
                "printf 'ForceCommand /run/platform-shell/ssh-session\\n' >> /run/platform-ssh/sshd_config\n/usr/sbin/sshd -f /run/platform-ssh/sshd_config",
            )
            start = "set -eu\npython -c " + shlex.quote(SHELL_SETUP) + "\n" + enhanced
        container["command"] = ["/bin/bash", "-c", start, "platform-start", spec.jupyter_command]
    return manifest


def build_service(spec: WorkloadSpec) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": spec.service_name,
            "namespace": spec.namespace,
            "labels": {"allocation-id": str(spec.allocation_id), "user-id": str(spec.user_id)},
        },
        "spec": {
            "type": "NodePort" if spec.ssh_enabled or not spec.ingress_enabled else "ClusterIP",
            "selector": {"app": spec.pod_name},
            "ports": [
                {"name": name, "port": port, "targetPort": port, "protocol": "TCP"}
                for name, port in (
                    (("jupyter", 8888), ("ssh", 22))
                    if spec.ssh_enabled
                    else (("jupyter", 8888), ("vnc", 5901), ("ssh", 22))
                )
            ],
        },
    }


def build_auth_secret(spec: WorkloadSpec) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": spec.auth_secret_name,
            "namespace": spec.namespace,
            "labels": {"allocation-id": str(spec.allocation_id), "user-id": str(spec.user_id)},
        },
        "data": {
            "token": b64encode(spec.jupyter_token.encode("utf-8")).decode("ascii"),
            **(
                {"password_hash": b64encode(spec.ssh_password_hash.encode()).decode()}
                if spec.ssh_enabled
                else {}
            ),
            "authorized_keys": b64encode(spec.ssh_authorized_keys.encode("utf-8")).decode("ascii"),
        },
    }


def build_ingress(spec: WorkloadSpec) -> dict:
    ingress_spec = {
        "rules": [
            {
                # Kubernetes Ingress 的 host 必须是域名；按 IP 访问时使用无 host 的规则。
                "http": {
                    "paths": [
                        {
                            "path": spec.jupyter_path,
                            "pathType": "Prefix",
                            "backend": {
                                "service": {"name": spec.service_name, "port": {"number": 8888}}
                            },
                        }
                    ]
                },
            }
        ],
    }
    import ipaddress

    # Public URLs may include a mapped port; Ingress host/TLS names cannot.
    ingress_host = spec.ingress_host
    try:
        ipaddress.ip_address(ingress_host)
    except ValueError:
        ingress_host = urlsplit("//" + ingress_host).hostname or ingress_host

    is_domain = False
    try:
        ipaddress.ip_address(ingress_host)
    except ValueError:
        is_domain = True
        ingress_spec["rules"][0]["host"] = ingress_host
    if spec.ingress_class:
        ingress_spec["ingressClassName"] = spec.ingress_class
    if spec.use_tls:
        ingress_spec["tls"] = [
            {
                "hosts": [ingress_host] if is_domain else [],
                "secretName": f"{spec.ingress_name}-tls",
            }
        ]
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": spec.ingress_name,
            "namespace": spec.namespace,
            "labels": {"allocation-id": str(spec.allocation_id), "user-id": str(spec.user_id)},
            "annotations": {
                "traefik.ingress.kubernetes.io/proxy-read-timeout": "3600",
                "traefik.ingress.kubernetes.io/proxy-send-timeout": "3600",
            },
        },
        "spec": ingress_spec,
    }
