#!/usr/bin/env python3
"""
清理分配资源（Pod和Service）

使用方法:
    python scripts/cleanup_allocation.py <container_id>
    python scripts/cleanup_allocation.py --all
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

def cleanup_allocation(container_id: str):
    """清理特定分配的资源"""
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
        
        namespace = "default"
        cleaned = False
        
        # 删除Pod
        if alloc.pod_name:
            try:
                v1.delete_namespaced_pod(name=alloc.pod_name, namespace=namespace)
                print(f"✅ 已删除Pod: {alloc.pod_name}")
                cleaned = True
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    print(f"ℹ️  Pod不存在: {alloc.pod_name}")
                else:
                    print(f"⚠️  删除Pod失败: {e.reason}")
        
        # 删除Service
        service_name = f"svc-{alloc.id}"
        try:
            v1.delete_namespaced_service(name=service_name, namespace=namespace)
            print(f"✅ 已删除Service: {service_name}")
            cleaned = True
        except client.exceptions.ApiException as e:
            if e.status == 404:
                print(f"ℹ️  Service不存在: {service_name}")
            else:
                print(f"⚠️  删除Service失败: {e.reason}")
        
        if not cleaned:
            print("ℹ️  没有需要清理的资源")
        
    finally:
        db.close()

def cleanup_all():
    """清理所有分配的资源"""
    v1 = get_k8s_client()
    if not v1:
        return
    
    db = SessionLocal()
    try:
        allocations = db.query(Allocation).filter(
            Allocation.pod_name.isnot(None)
        ).all()
        
        if not allocations:
            print("ℹ️  没有找到需要清理的资源")
            return
        
        namespace = "default"
        cleaned_count = 0
        
        for alloc in allocations:
            # 删除Pod
            if alloc.pod_name:
                try:
                    v1.delete_namespaced_pod(name=alloc.pod_name, namespace=namespace)
                    print(f"✅ 已删除Pod: {alloc.pod_name}")
                    cleaned_count += 1
                except client.exceptions.ApiException as e:
                    if e.status != 404:
                        print(f"⚠️  删除Pod失败 {alloc.pod_name}: {e.reason}")
            
            # 删除Service
            service_name = f"svc-{alloc.id}"
            try:
                v1.delete_namespaced_service(name=service_name, namespace=namespace)
                print(f"✅ 已删除Service: {service_name}")
            except client.exceptions.ApiException as e:
                if e.status != 404:
                    print(f"⚠️  删除Service失败 {service_name}: {e.reason}")
        
        print(f"\n✅ 清理完成，共处理 {len(allocations)} 个分配")
        
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python scripts/cleanup_allocation.py <container_id>")
        print("  python scripts/cleanup_allocation.py --all")
        sys.exit(1)
    
    if sys.argv[1] == "--all":
        cleanup_all()
    else:
        cleanup_allocation(sys.argv[1])

