#!/usr/bin/env python3
"""
快速检查Pod中的容器定义

使用方法:
    python scripts/check_pod_containers.py <pod-name>
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

def check_pod(pod_name: str, namespace: str = "default"):
    """检查Pod中的容器"""
    v1 = get_k8s_client()
    if not v1:
        return
    
    print(f"检查Pod: {pod_name} (namespace: {namespace})\n")
    print("=" * 60)
    
    try:
        # 先尝试在指定namespace查找
        try:
            pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                # 如果在default找不到，尝试在所有namespace查找
                print(f"在 {namespace} namespace 中未找到，尝试在所有namespace查找...")
                all_pods = v1.list_pod_for_all_namespaces()
                found = False
                for p in all_pods.items:
                    if p.metadata.name == pod_name:
                        pod = v1.read_namespaced_pod(name=pod_name, namespace=p.metadata.namespace)
                        namespace = p.metadata.namespace
                        print(f"✅ 在 {namespace} namespace 中找到Pod\n")
                        found = True
                        break
                if not found:
                    raise client.exceptions.ApiException(status=404, reason="NotFound")
            else:
                raise
        
        # 1. 检查Pod spec中的容器定义
        print("\n📋 Pod Spec中的容器定义:")
        if pod.spec.containers:
            print(f"   找到 {len(pod.spec.containers)} 个容器定义:")
            for i, container in enumerate(pod.spec.containers, 1):
                print(f"\n   容器 {i}:")
                print(f"     名称: {container.name}")
                print(f"     镜像: {container.image}")
                if container.ports:
                    print(f"     端口:")
                    for port in container.ports:
                        print(f"       - {port.name}: {port.container_port}/{port.protocol}")
                else:
                    print(f"     端口: 未定义")
                
                if container.command:
                    print(f"     启动命令: {' '.join(container.command)}")
                else:
                    print(f"     启动命令: (使用镜像默认CMD)")
                
                if container.args:
                    print(f"     启动参数: {' '.join(container.args)}")
        else:
            print("   ❌ Pod中没有定义容器！")
        
        # 2. 检查Pod status中的容器状态
        print("\n📊 Pod Status中的容器状态:")
        if pod.status.container_statuses:
            print(f"   找到 {len(pod.status.container_statuses)} 个容器状态:")
            for container_status in pod.status.container_statuses:
                print(f"\n   容器: {container_status.name}")
                print(f"     就绪: {container_status.ready}")
                print(f"     重启次数: {container_status.restart_count}")
                if container_status.state.running:
                    print(f"     状态: Running")
                    print(f"     启动时间: {container_status.state.running.started_at}")
                elif container_status.state.waiting:
                    print(f"     状态: Waiting")
                    print(f"     原因: {container_status.state.waiting.reason}")
                    print(f"     消息: {container_status.state.waiting.message}")
                elif container_status.state.terminated:
                    print(f"     状态: Terminated")
                    print(f"     退出码: {container_status.state.terminated.exit_code}")
                    print(f"     原因: {container_status.state.terminated.reason}")
        else:
            print("   ⚠️  容器状态未更新")
            print("   可能原因:")
            print("     - Pod刚创建，还未被调度")
            print("     - Pod正在等待资源")
            print("     - Pod创建失败")
        
        # 3. 检查Pod事件
        print("\n📰 Pod事件（最近5条）:")
        try:
            events = v1.list_namespaced_event(
                namespace=namespace,
                field_selector=f"involvedObject.name={pod_name}"
            )
            if events.items:
                # 修复时间比较问题
                def get_event_time(event):
                    return event.last_timestamp if event.last_timestamp else (event.first_timestamp if event.first_timestamp else None)
                
                sorted_events = sorted(
                    events.items,
                    key=lambda x: get_event_time(x) or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc),
                    reverse=True
                )[:5]
                
                for event in sorted_events:
                    print(f"   [{event.type}] {event.reason}: {event.message}")
            else:
                print("   无事件")
        except Exception as e:
            print(f"   无法获取事件: {e}")
            import traceback
            traceback.print_exc()
        
        # 4. 对比spec和status
        print("\n🔍 对比分析:")
        spec_containers = {c.name for c in pod.spec.containers} if pod.spec.containers else set()
        status_containers = {c.name for c in pod.status.container_statuses} if pod.status.container_statuses else set()
        
        if spec_containers == status_containers:
            print("   ✅ Spec和Status中的容器名称匹配")
        else:
            print("   ⚠️  Spec和Status中的容器名称不匹配:")
            print(f"      Spec: {spec_containers}")
            print(f"      Status: {status_containers}")
        
        if not spec_containers:
            print("\n❌ 问题: Pod spec中没有定义容器！")
            print("   这可能是代码问题，请检查k8s_service.py中的Pod定义")
        
    except client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"❌ Pod不存在: {pod_name}")
            print(f"\n💡 提示:")
            print(f"   - 确认Pod名称是否正确")
            print(f"   - 尝试在所有namespace查找: python scripts/test_k8s_connection.py")
            print(f"   - 使用kubectl查看: kubectl get pods --all-namespaces | grep {pod_name}")
        else:
            print(f"❌ 获取Pod信息失败: {e.status} - {e.reason}")
            print(f"\n💡 提示:")
            print(f"   - 检查K8s连接: python scripts/test_k8s_connection.py")
            print(f"   - 检查kubeconfig配置: ~/.kube/config")
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法: python scripts/check_pod_containers.py <pod-name> [namespace]")
        sys.exit(1)
    
    pod_name = sys.argv[1]
    namespace = sys.argv[2] if len(sys.argv) > 2 else "default"
    
    check_pod(pod_name, namespace)

