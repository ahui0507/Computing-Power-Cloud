#!/usr/bin/env python3
"""
检查Pod的imagePullPolicy设置

使用方法:
    python scripts/check_pod_image_policy.py <pod-name>
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from kubernetes import client, config
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    print("❌ kubernetes库未安装")
    sys.exit(1)

def get_k8s_client():
    """获取K8s客户端"""
    try:
        if os.path.exists(os.path.expanduser("~/.kube/config")):
            config.load_kube_config()
        else:
            config.load_incluster_config()
        return client.CoreV1Api()
    except Exception as e:
        print(f"❌ 无法连接到K8s集群: {e}")
        return None

def check_pod_policy(pod_name: str, namespace: str = "default"):
    """检查Pod的imagePullPolicy"""
    v1 = get_k8s_client()
    if not v1:
        return
    
    print(f"检查Pod: {pod_name} (namespace: {namespace})")
    print("=" * 60)
    print()
    
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        if pod.spec.containers:
            for container in pod.spec.containers:
                print(f"容器: {container.name}")
                print(f"  镜像: {container.image}")
                print(f"  imagePullPolicy: {container.image_pull_policy if hasattr(container, 'image_pull_policy') and container.image_pull_policy else '未设置（默认: Always）'}")
                print()
                
                # 检查镜像是否已导入
                print("检查镜像是否已导入:")
                CTR_PATH = os.popen("sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1").read().strip()
                if CTR_PATH:
                    # 提取镜像名称（去掉tag）
                    image_name = container.image.split(':')[0] if ':' in container.image else container.image
                    result = os.popen(f"sudo {CTR_PATH} images ls | grep -i {image_name}").read()
                    if result:
                        print(f"   ✅ 找到镜像:")
                        for line in result.strip().split('\n'):
                            if line.strip():
                                print(f"      {line}")
                    else:
                        print(f"   ❌ 未找到镜像: {image_name}")
                else:
                    print("   ⚠️  无法找到ctr命令")
        
        # 检查容器状态
        print("\n容器状态:")
        if pod.status.container_statuses:
            for cs in pod.status.container_statuses:
                print(f"   {cs.name}:")
                if cs.state.waiting:
                    print(f"      状态: Waiting")
                    print(f"      原因: {cs.state.waiting.reason}")
                    print(f"      消息: {cs.state.waiting.message}")
                    
                    if "ImagePull" in cs.state.waiting.reason:
                        print(f"\n   💡 问题分析:")
                        pull_policy = pod.spec.containers[0].image_pull_policy if hasattr(pod.spec.containers[0], 'image_pull_policy') and pod.spec.containers[0].image_pull_policy else "未设置"
                        print(f"      - imagePullPolicy: {pull_policy}")
                        print(f"      - 如果策略是 'Always' 或未设置，K8s会尝试拉取镜像")
                        print(f"      - 如果策略是 'IfNotPresent'，应该使用本地镜像")
                        print(f"\n   🔧 解决方案:")
                        print(f"      1. 删除Pod: kubectl delete pod {pod_name} -n {namespace}")
                        print(f"      2. 确保后端服务已重启（使用新代码）")
                        print(f"      3. 在网页中重新申请资源")
                        print(f"      4. 或者手动修复镜像标签:")
                        print(f"         sudo ./scripts/fix_image_for_k3s.sh")
        
    except client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"❌ Pod不存在: {pod_name}")
        else:
            print(f"❌ 获取Pod信息失败: {e.status} - {e.reason}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python scripts/check_pod_image_policy.py <pod-name> [namespace]")
        sys.exit(1)
    
    pod_name = sys.argv[1]
    namespace = sys.argv[2] if len(sys.argv) > 2 else "default"
    
    check_pod_policy(pod_name, namespace)

