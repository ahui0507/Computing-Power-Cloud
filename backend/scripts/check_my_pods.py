#!/usr/bin/env python3
"""
检查用户创建的Pod状态

使用方法:
    python scripts/check_my_pods.py
    python scripts/check_my_pods.py <container_id>
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

from app.core.database import SessionLocal
from app.models.allocation import Allocation

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

def check_my_pods():
    """检查所有用户创建的Pod"""
    v1 = get_k8s_client()
    if not v1:
        return
    
    db = SessionLocal()
    try:
        # 获取所有分配记录
        allocations = db.query(Allocation).filter(
            Allocation.pod_name.isnot(None)
        ).all()
        
        if not allocations:
            print("❌ 数据库中没有找到Pod记录")
            return
        
        print("=" * 60)
        print("检查用户创建的Pod")
        print("=" * 60)
        print()
        
        for alloc in allocations:
            print(f"📦 分配ID: {alloc.id}")
            print(f"   容器ID: {alloc.container_id}")
            print(f"   Pod名称: {alloc.pod_name}")
            print(f"   镜像: {alloc.image_name}")
            print(f"   状态: {alloc.status.value}")
            print()
            
            if alloc.pod_name:
                try:
                    # 尝试在default namespace查找
                    try:
                        pod = v1.read_namespaced_pod(name=alloc.pod_name, namespace="default")
                    except client.exceptions.ApiException as e:
                        if e.status == 404:
                            # 尝试在所有namespace查找
                            all_pods = v1.list_pod_for_all_namespaces()
                            pod = None
                            for p in all_pods.items:
                                if p.metadata.name == alloc.pod_name:
                                    pod = v1.read_namespaced_pod(name=alloc.pod_name, namespace=p.metadata.namespace)
                                    break
                            if not pod:
                                print(f"   ❌ Pod不存在: {alloc.pod_name}")
                                continue
                        else:
                            raise
                    
                    print(f"   📊 Pod状态: {pod.status.phase}")
                    print(f"   📍 Namespace: {pod.metadata.namespace}")
                    
                    if pod.spec.node_name:
                        print(f"   📍 运行节点: {pod.spec.node_name}")
                    
                    # 检查容器
                    if pod.spec.containers:
                        print(f"   🐳 容器定义: {len(pod.spec.containers)} 个")
                        for container in pod.spec.containers:
                            print(f"      - {container.name}: {container.image}")
                    else:
                        print(f"   ❌ Pod中没有容器定义！")
                    
                    # 检查容器状态
                    if pod.status.container_statuses:
                        print(f"   📊 容器状态:")
                        for cs in pod.status.container_statuses:
                            print(f"      - {cs.name}: ", end="")
                            if cs.ready:
                                print("✅ Ready")
                            elif cs.state.waiting:
                                print(f"⏳ Waiting - {cs.state.waiting.reason}: {cs.state.waiting.message}")
                            elif cs.state.running:
                                print("✅ Running")
                            elif cs.state.terminated:
                                print(f"❌ Terminated - {cs.state.terminated.reason}")
                    else:
                        print(f"   ⚠️  容器状态未更新")
                    
                    # 检查事件
                    if pod.status.phase != "Running":
                        print(f"   📰 最近事件:")
                        try:
                            events = v1.list_namespaced_event(
                                namespace=pod.metadata.namespace,
                                field_selector=f"involvedObject.name={pod.metadata.name}"
                            )
                            for event in sorted(events.items, key=lambda x: x.last_timestamp or x.first_timestamp, reverse=True)[:3]:
                                print(f"      [{event.type}] {event.reason}: {event.message}")
                        except:
                            pass
                    
                    print()
                    
                except Exception as e:
                    print(f"   ❌ 检查Pod失败: {e}")
                    print()
    finally:
        db.close()

def check_specific_pod(container_id: str):
    """检查特定容器ID的Pod"""
    v1 = get_k8s_client()
    if not v1:
        return
    
    db = SessionLocal()
    try:
        alloc = db.query(Allocation).filter(
            Allocation.container_id == container_id
        ).first()
        
        if not alloc:
            print(f"❌ 未找到容器ID: {container_id}")
            return
        
        if not alloc.pod_name:
            print(f"❌ 容器 {container_id} 没有关联的Pod")
            return
        
        print(f"检查Pod: {alloc.pod_name}")
        print("=" * 60)
        print()
        
        # 导入检查脚本
        from scripts.check_pod_containers import check_pod
        check_pod(alloc.pod_name, "default")
        
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        container_id = sys.argv[1]
        check_specific_pod(container_id)
    else:
        check_my_pods()

