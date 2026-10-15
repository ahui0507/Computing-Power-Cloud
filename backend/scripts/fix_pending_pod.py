#!/usr/bin/env python3
"""
修复Pending状态的Pod

使用方法:
    python scripts/fix_pending_pod.py <pod-name>
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

def check_and_fix_pod(pod_name: str, namespace: str = "default"):
    """检查并修复Pod"""
    v1 = get_k8s_client()
    if not v1:
        return
    
    print(f"检查Pod: {pod_name} (namespace: {namespace})")
    print("=" * 60)
    print()
    
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        print(f"📊 Pod状态: {pod.status.phase}")
        print()
        
        # 检查镜像信息
        if pod.spec.containers:
            container = pod.spec.containers[0]
            image = container.image
            pull_policy = container.image_pull_policy if hasattr(container, 'image_pull_policy') else "未设置"
            
            print(f"🐳 容器信息:")
            print(f"   镜像: {image}")
            print(f"   拉取策略: {pull_policy}")
            print()
            
            # 检查镜像是否已导入
            print("🔍 检查镜像是否已导入:")
            CTR_PATH = os.popen("sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1").read().strip()
            if CTR_PATH:
                print(f"   使用: {CTR_PATH}")
                # 提取镜像名称（去掉tag）
                image_name = image.split(':')[0] if ':' in image else image
                result = os.popen(f"sudo {CTR_PATH} images ls | grep -i {image_name}").read()
                if result:
                    print(f"   ✅ 找到镜像:")
                    for line in result.strip().split('\n'):
                        if line.strip():
                            print(f"      {line}")
                else:
                    print(f"   ❌ 未找到镜像: {image_name}")
                    print(f"   💡 请运行导入脚本: cd test-images/jupyter-test && sudo ./build_and_import.sh")
            else:
                print("   ⚠️  无法找到ctr命令")
        
        # 检查容器状态
        if pod.status.container_statuses:
            print("\n📊 容器状态:")
            for cs in pod.status.container_statuses:
                print(f"   {cs.name}:")
                if cs.state.waiting:
                    print(f"      状态: Waiting")
                    print(f"      原因: {cs.state.waiting.reason}")
                    print(f"      消息: {cs.state.waiting.message}")
                elif cs.state.running:
                    print(f"      状态: Running ✅")
                elif cs.state.terminated:
                    print(f"      状态: Terminated")
                    print(f"      原因: {cs.state.terminated.reason}")
        
        # 检查事件
        print("\n📰 Pod事件:")
        try:
            events = v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name}"
            )
            if events.items:
                for event in sorted(events.items, key=lambda x: x.last_timestamp or x.first_timestamp, reverse=True)[:5]:
                    print(f"   [{event.type}] {event.reason}: {event.message}")
            else:
                print("   无事件")
        except Exception as e:
            print(f"   无法获取事件: {e}")
        
        # 提供修复建议
        print("\n💡 修复建议:")
        if pod.status.phase == "Pending":
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    if cs.state.waiting:
                        if "ImagePull" in cs.state.waiting.reason:
                            print("   1. 镜像拉取失败，可能原因:")
                            print("      - 镜像未导入到节点")
                            print("      - 镜像名称不匹配")
                            print("      - imagePullPolicy设置错误")
                            print()
                            print("   解决方案:")
                            print("      a) 确认镜像已导入:")
                            print("         sudo ctr images ls | grep jupyter-test")
                            print()
                            print("      b) 如果镜像未导入，运行:")
                            print("         cd test-images/jupyter-test")
                            print("         sudo ./build_and_import.sh")
                            print()
                            print("      c) 删除Pod并重新创建（使用新的imagePullPolicy）:")
                            print(f"         kubectl delete pod {pod_name} -n {namespace}")
                            print("         然后在网页中重新申请资源")
                        elif "ErrImagePull" in cs.state.waiting.reason:
                            print("   1. 镜像拉取错误")
                            print("   2. 检查镜像名称是否正确")
                            print("   3. 确认镜像已导入到所有节点")
            else:
                print("   1. Pod可能正在等待调度")
                print("   2. 检查节点资源是否充足")
                print("   3. 检查节点选择器和容忍度")
        
    except client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"❌ Pod不存在: {pod_name}")
        else:
            print(f"❌ 获取Pod信息失败: {e.status} - {e.reason}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python scripts/fix_pending_pod.py <pod-name> [namespace]")
        sys.exit(1)
    
    pod_name = sys.argv[1]
    namespace = sys.argv[2] if len(sys.argv) > 2 else "default"
    
    check_and_fix_pod(pod_name, namespace)

