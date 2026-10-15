#!/usr/bin/env python
"""
从 Kubernetes 集群同步节点到数据库
"""
import sys
import subprocess
import json
import os
import re
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from sqlalchemy import text
from app.core.database import SessionLocal
from app.models.node import Node, NodeStatus, GPU, GPUStatus
from app.models.gpu_type import GPUType


def find_kubeconfig():
    """查找可用的 kubeconfig 文件"""
    # 1. 检查环境变量
    kubeconfig = os.environ.get("KUBECONFIG")
    if kubeconfig and os.path.exists(kubeconfig):
        return kubeconfig
    
    # 2. 检查用户目录下的 config
    user_config = Path.home() / ".kube" / "config"
    if user_config.exists():
        return str(user_config)
    
    # 3. 检查 K3s 默认配置文件
    k3s_config = "/etc/rancher/k3s/k3s.yaml"
    if os.path.exists(k3s_config):
        return k3s_config
    
    return None


def get_k8s_nodes():
    """从 Kubernetes 获取节点列表"""
    # 尝试多种方式执行 kubectl
    kubeconfig = find_kubeconfig()
    
    # 构建 kubectl 命令
    kubectl_cmd = ["kubectl", "get", "nodes", "-o", "json"]
    
    # 优先使用用户目录下的配置文件
    env = os.environ.copy()
    user_config = str(Path.home() / ".kube" / "config")
    if os.path.exists(user_config):
        env["KUBECONFIG"] = user_config
        print(f"  使用 kubeconfig: {user_config}")
    elif kubeconfig:
        env["KUBECONFIG"] = kubeconfig
        print(f"  使用 kubeconfig: {kubeconfig}")
    
    # 首先尝试普通权限
    try:
        result = subprocess.run(
            kubectl_cmd,
            capture_output=True,
            text=True,
            check=True,
            env=env
        )
    except (subprocess.CalledProcessError, PermissionError) as e:
        # 如果失败，尝试使用 sudo
        print(f"  普通权限失败，尝试使用 sudo...")
        try:
            sudo_cmd = ["sudo"] + kubectl_cmd
            result = subprocess.run(
                sudo_cmd,
                capture_output=True,
                text=True,
                check=True,
                env=env
            )
        except subprocess.CalledProcessError as sudo_e:
            print(f"✗ 执行 kubectl 命令失败")
            print(f"  普通权限错误: {e}")
            print(f"  sudo 权限错误: {sudo_e}")
            if sudo_e.stderr:
                print(f"  错误输出: {sudo_e.stderr}")
            
            # 提供解决方案提示
            print("\n💡 解决方案：")
            print("  方法1: 复制 kubeconfig 到用户目录（推荐）")
            print("    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config")
            print("    sudo chown $USER:$USER ~/.kube/config")
            print("    mkdir -p ~/.kube")
            print("")
            print("  方法2: 使用 sudo 运行脚本")
            print("    sudo python scripts/sync_nodes_from_k8s.py")
            print("")
            print("  方法3: 设置 KUBECONFIG 环境变量")
            print("    export KUBECONFIG=/etc/rancher/k3s/k3s.yaml")
            print("    sudo python scripts/sync_nodes_from_k8s.py")
            return None
    
    # 解析 kubectl 输出
    try:
        data = json.loads(result.stdout)
        nodes = []
        
        for item in data.get("items", []):
            node_info = {
                "name": item["metadata"]["name"],
                "ip": None,
                "roles": [],
                "status": None,
            }
            
            # 获取内部IP
            for addr in item.get("status", {}).get("addresses", []):
                if addr["type"] == "InternalIP":
                    node_info["ip"] = addr["address"]
                    break
            
            # 获取角色
            labels = item.get("metadata", {}).get("labels", {})
            if "node-role.kubernetes.io/control-plane" in labels or "node-role.kubernetes.io/master" in labels:
                node_info["roles"].append("control-plane")
            else:
                node_info["roles"].append("worker")
            
            # 获取状态
            conditions = item.get("status", {}).get("conditions", [])
            for condition in conditions:
                if condition["type"] == "Ready":
                    if condition["status"] == "True":
                        node_info["status"] = "Ready"
                    else:
                        node_info["status"] = "NotReady"
                    break
            
            # 获取资源信息
            capacity = item.get("status", {}).get("capacity", {})
            allocatable = item.get("status", {}).get("allocatable", {})
            
            # CPU (格式可能是 "4" 或 "4000m")
            cpu_str = capacity.get("cpu", "0")
            if cpu_str.endswith("m"):
                node_info["cpu_cores"] = int(cpu_str[:-1]) // 1000
            else:
                node_info["cpu_cores"] = int(cpu_str) if cpu_str.isdigit() else 0
            
            # 内存 (格式可能是 "8Gi" 或 "8192Mi")
            memory_str = capacity.get("memory", "0")
            if memory_str.endswith("Gi"):
                node_info["memory_gb"] = float(memory_str[:-2])
            elif memory_str.endswith("Mi"):
                node_info["memory_gb"] = float(memory_str[:-2]) / 1024
            else:
                node_info["memory_gb"] = 0.0
            
            # GPU 数量 (从 nvidia.com/gpu 资源获取)
            gpu_str = capacity.get("nvidia.com/gpu", "0")
            node_info["gpus_total"] = int(gpu_str) if gpu_str.isdigit() else 0
            
            nodes.append(node_info)
        
        return nodes
    
    except FileNotFoundError:
        print("✗ 未找到 kubectl 命令")
        print("  请确保 kubectl 已安装并在 PATH 中")
        return None
    except json.JSONDecodeError as e:
        print(f"✗ 解析 kubectl 输出失败: {e}")
        return None
    except Exception as e:
        print(f"✗ 获取 Kubernetes 节点失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_node_gpu_details_via_ssh(node_ip: str) -> list:
    """
    通过 SSH 直接访问节点获取 GPU 信息
    """
    gpu_details = []
    
    try:
        # 尝试通过 SSH 运行 nvidia-smi
        # 假设使用 root 用户或当前用户，可以通过环境变量配置
        ssh_user = os.environ.get("SSH_USER", "root")
        
        ssh_cmd = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            f"{ssh_user}@{node_ip}",
            "nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv,noheader,nounits"
        ]
        
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        
        # 解析 nvidia-smi 输出
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 4:
                try:
                    gpu_index = int(parts[0])
                    gpu_uuid = parts[1]
                    gpu_name = parts[2]
                    memory_mb = int(parts[3])
                    memory_gb = memory_mb / 1024.0
                    
                    gpu_type_code = extract_gpu_type(gpu_name)
                    
                    gpu_details.append({
                        "index": gpu_index,
                        "uuid": gpu_uuid,
                        "name": gpu_name,
                        "type_code": gpu_type_code,
                        "memory_gb": memory_gb
                    })
                except (ValueError, IndexError) as e:
                    continue
        
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        # SSH 失败，返回空列表
        pass
    except Exception:
        pass
    
    return gpu_details


def get_node_gpu_details(node_name: str, node_ip: str, env: dict) -> list:
    """
    获取节点的详细GPU信息
    优先尝试通过 SSH，如果失败则尝试通过 kubectl exec
    """
    gpu_details = []
    
    # 方法1: 尝试通过 SSH 直接访问节点（最快最可靠）
    print(f"    尝试通过 SSH 获取 GPU 信息...")
    gpu_details = get_node_gpu_details_via_ssh(node_ip)
    
    if gpu_details:
        print(f"    ✓ 通过 SSH 获取到 {len(gpu_details)} 个 GPU 信息")
        return gpu_details
    
    # 方法2: 通过 kubectl exec 到节点上的 Pod 运行 nvidia-smi
    print(f"    SSH 失败，尝试通过 kubectl exec...")
    try:
        # 查找节点上的 nvidia-device-plugin Pod（最有可能有 nvidia-smi）
        get_pod_cmd = [
            "kubectl", "get", "pods", "-n", "kube-system",
            "-o", "json", "--field-selector", f"spec.nodeName={node_name}",
            "-l", "name=nvidia-device-plugin-ds"
        ]
        
        pod_result = subprocess.run(
            get_pod_cmd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=10
        )
        
        pod_data = json.loads(pod_result.stdout)
        pods = pod_data.get("items", [])
        
        # 如果没有找到 nvidia-device-plugin，尝试找其他 Pod
        if not pods:
            get_pod_cmd = [
                "kubectl", "get", "pods", "-n", "kube-system",
                "-o", "json", "--field-selector", f"spec.nodeName={node_name}"
            ]
            pod_result = subprocess.run(
                get_pod_cmd,
                capture_output=True,
                text=True,
                check=True,
                env=env,
                timeout=10
            )
            pod_data = json.loads(pod_result.stdout)
            pods = pod_data.get("items", [])
        
        if not pods:
            print(f"    ⚠ 节点上没有找到可用的 Pod")
            return gpu_details
        
        # 使用第一个可用的 Pod
        pod_name = pods[0]["metadata"]["name"]
        pod_namespace = pods[0]["metadata"]["namespace"]
        
        # 通过 kubectl exec 运行 nvidia-smi
        nvidia_smi_cmd = [
            "kubectl", "exec", "-n", pod_namespace, pod_name, "--",
            "nvidia-smi", "--query-gpu=index,uuid,name,memory.total", "--format=csv,noheader,nounits"
        ]
        
        result = subprocess.run(
            nvidia_smi_cmd,
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=30
        )
        
        # 解析 nvidia-smi 输出
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 4:
                try:
                    gpu_index = int(parts[0])
                    gpu_uuid = parts[1]
                    gpu_name = parts[2]
                    memory_mb = int(parts[3])
                    memory_gb = memory_mb / 1024.0
                    
                    gpu_type_code = extract_gpu_type(gpu_name)
                    
                    gpu_details.append({
                        "index": gpu_index,
                        "uuid": gpu_uuid,
                        "name": gpu_name,
                        "type_code": gpu_type_code,
                        "memory_gb": memory_gb
                    })
                except (ValueError, IndexError) as e:
                    continue
        
        if gpu_details:
            print(f"    ✓ 通过 kubectl exec 获取到 {len(gpu_details)} 个 GPU 信息")
        
    except subprocess.CalledProcessError as e:
        print(f"    ⚠ kubectl exec 失败: {e.stderr[:100] if e.stderr else '未知错误'}")
    except subprocess.TimeoutExpired:
        print(f"    ⚠ 获取 GPU 信息超时")
    except Exception as e:
        print(f"    ⚠ 获取 GPU 信息时出错: {str(e)[:100]}")
    
    return gpu_details


def extract_gpu_type(gpu_name: str) -> str:
    """
    从 GPU 名称提取类型代码
    例如: "Tesla K80" -> "K80", "NVIDIA A100" -> "A100"
    """
    # 常见的 GPU 类型模式
    patterns = [
        r'K80', r'K40', r'K20',
        r'V100', r'P100', r'P40',
        r'A100', r'A40', r'A30', r'A10',
        r'RTX\s*(\d+)', r'GTX\s*(\d+)',
        r'T4', r'T10', r'T16'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, gpu_name, re.IGNORECASE)
        if match:
            if match.groups():
                return f"{match.group(0)}{match.group(1)}"
            return match.group(0)
    
    # 如果没有匹配到，尝试提取最后的大写字母+数字组合
    match = re.search(r'([A-Z]\d+)', gpu_name)
    if match:
        return match.group(1)
    
    # 默认返回 "UNKNOWN"
    return "UNKNOWN"


def get_or_create_gpu_type(db: Session, gpu_type_code: str, gpu_name: str = None) -> GPUType:
    """
    获取或创建 GPU 类型
    """
    gpu_type = db.query(GPUType).filter(GPUType.code == gpu_type_code).first()
    
    if not gpu_type:
        # 创建新的 GPU 类型
        gpu_type = GPUType(
            code=gpu_type_code,
            name=gpu_name or gpu_type_code,
            remark=f"自动创建于节点同步"
        )
        db.add(gpu_type)
        db.flush()  # 获取 ID 但不提交
    
    return gpu_type


def sync_nodes_to_db():
    """同步节点到数据库"""
    print("=" * 60)
    print("从 Kubernetes 同步节点到数据库")
    print("=" * 60)
    
    # 获取 Kubernetes 节点
    print("\n1. 从 Kubernetes 获取节点信息...")
    k8s_nodes = get_k8s_nodes()
    
    if k8s_nodes is None:
        print("✗ 无法获取 Kubernetes 节点信息")
        return
    
    if not k8s_nodes:
        print("⚠ Kubernetes 集群中没有节点")
        return
    
    print(f"✓ 找到 {len(k8s_nodes)} 个 Kubernetes 节点")
    for node in k8s_nodes:
        print(f"  - {node['name']} ({node['ip']}) - {node['status']}")
    
    # 同步到数据库
    print("\n2. 同步节点到数据库...")
    db: Session = SessionLocal()
    
    # 准备环境变量（用于 kubectl 命令）
    env = os.environ.copy()
    user_config = str(Path.home() / ".kube" / "config")
    kubeconfig = find_kubeconfig()
    if os.path.exists(user_config):
        env["KUBECONFIG"] = user_config
    elif kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    
    try:
        synced_count = 0
        updated_count = 0
        
        for k8s_node in k8s_nodes:
            # 检查节点是否已存在
            existing_node = db.query(Node).filter(
                Node.hostname == k8s_node["name"]
            ).first()
            
            if existing_node:
                # 更新现有节点
                existing_node.ip = k8s_node["ip"]
                existing_node.cpu_cores = k8s_node["cpu_cores"]
                existing_node.memory_gb = k8s_node["memory_gb"]
                existing_node.gpus_total = k8s_node.get("gpus_total", 0)
                
                # 更新状态
                if k8s_node["status"] == "Ready":
                    existing_node.status = NodeStatus.ONLINE
                else:
                    existing_node.status = NodeStatus.OFFLINE
                
                # 更新标签（角色信息）
                labels = existing_node.labels or {}
                labels["roles"] = k8s_node["roles"]
                existing_node.labels = labels
                
                node_obj = existing_node
                updated_count += 1
                print(f"  ✓ 更新节点: {k8s_node['name']} (GPU: {k8s_node.get('gpus_total', 0)})")
            else:
                # 创建新节点
                new_node = Node(
                    hostname=k8s_node["name"],
                    ip=k8s_node["ip"],
                    cpu_cores=k8s_node["cpu_cores"],
                    memory_gb=k8s_node["memory_gb"],
                    gpus_total=k8s_node.get("gpus_total", 0),
                    gpus_free=k8s_node.get("gpus_total", 0),
                    status=NodeStatus.ONLINE if k8s_node["status"] == "Ready" else NodeStatus.OFFLINE,
                    labels={"roles": k8s_node["roles"]}
                )
                db.add(new_node)
                db.flush()  # 获取节点 ID
                node_obj = new_node
                synced_count += 1
                print(f"  ✓ 添加节点: {k8s_node['name']} (GPU: {k8s_node.get('gpus_total', 0)})")
            
            # 如果节点有 GPU，尝试获取详细 GPU 信息
            if k8s_node.get("gpus_total", 0) > 0 and k8s_node["status"] == "Ready":
                print(f"  获取节点 {k8s_node['name']} 的 GPU 详细信息...")
                gpu_details = get_node_gpu_details(k8s_node["name"], k8s_node["ip"], env)
                
                if gpu_details:
                    # 更新或创建 GPU 记录
                    existing_gpus = {gpu.gpu_index: gpu for gpu in node_obj.gpus}
                    
                    for gpu_detail in gpu_details:
                        gpu_type = get_or_create_gpu_type(
                            db, 
                            gpu_detail["type_code"], 
                            gpu_detail["name"]
                        )
                        
                        if gpu_detail["index"] in existing_gpus:
                            # 更新现有 GPU（保留状态，只更新信息）
                            gpu = existing_gpus[gpu_detail["index"]]
                            gpu.gpu_type_id = gpu_type.id
                            gpu.uuid = gpu_detail["uuid"]
                            gpu.memory_gb = gpu_detail["memory_gb"]
                            # 注意：不更新状态，保持原有状态（可能已被分配）
                        else:
                            # 创建新 GPU
                            new_gpu = GPU(
                                node_id=node_obj.id,
                                gpu_index=gpu_detail["index"],
                                gpu_type_id=gpu_type.id,
                                uuid=gpu_detail["uuid"],
                                memory_gb=gpu_detail["memory_gb"],
                                status=GPUStatus.FREE
                            )
                            db.add(new_gpu)
                    
                    # 刷新节点关系以获取最新的 GPU 列表
                    db.refresh(node_obj, ["gpus"])
                    # 更新节点的 gpus_free 计数
                    node_obj.gpus_free = len([gpu for gpu in node_obj.gpus if gpu.status == GPUStatus.FREE])
                    print(f"    ✓ 已同步 {len(gpu_details)} 个 GPU")
                else:
                    print(f"    ⚠ 无法获取 GPU 详细信息，但已记录 GPU 数量: {k8s_node.get('gpus_total', 0)}")
        
        db.commit()
        
        print(f"\n✓ 同步完成！")
        print(f"  - 新增节点: {synced_count}")
        print(f"  - 更新节点: {updated_count}")
        print(f"  - 总计: {synced_count + updated_count}")
        
        # 显示数据库中的节点
        print("\n3. 数据库中的节点列表:")
        nodes = db.query(Node).all()
        for node in nodes:
            gpu_info = f"GPU: {node.gpus_total} (空闲: {node.gpus_free})" if node.gpus_total > 0 else "无 GPU"
            print(f"  - {node.hostname} ({node.ip}) - {node.status.value} - {gpu_info}")
        
    except Exception as e:
        db.rollback()
        print(f"✗ 同步失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    sync_nodes_to_db()

