#!/usr/bin/env python3
"""
诊断Jupyter连接问题的脚本

使用方法:
    python scripts/diagnose_jupyter_connection.py <container_id>
    或
    python scripts/diagnose_jupyter_connection.py --all
"""

import sys
import os
import argparse
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from kubernetes import client, config
    KUBERNETES_AVAILABLE = True
except ImportError:
    KUBERNETES_AVAILABLE = False
    print("❌ kubernetes库未安装，请运行: pip install kubernetes")
    sys.exit(1)

from app.core.database import SessionLocal
from app.models.allocation import Allocation
from app.models.node import Node


def get_k8s_client():
    """获取K8s客户端"""
    try:
        # 尝试加载kubeconfig
        if os.path.exists(os.path.expanduser("~/.kube/config")):
            config.load_kube_config()
        else:
            # 尝试使用集群内配置
            config.load_incluster_config()
        return client.CoreV1Api()
    except Exception as e:
        print(f"❌ 无法连接到K8s集群: {e}")
        return None


def diagnose_pod(pod_name: str, namespace: str = "default"):
    """诊断Pod状态"""
    v1 = get_k8s_client()
    if not v1:
        return False
    
    print(f"\n{'='*60}")
    print(f"诊断Pod: {pod_name}")
    print(f"{'='*60}\n")
    
    try:
        # 获取Pod信息
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        
        # 1. Pod状态
        print(f"📊 Pod状态: {pod.status.phase}")
        if pod.status.phase != "Running":
            print(f"   ⚠️  Pod未运行，当前状态: {pod.status.phase}")
            if pod.status.conditions:
                for condition in pod.status.conditions:
                    print(f"   - {condition.type}: {condition.status} - {condition.message}")
            return False
        
        # 2. 节点信息
        node_name = pod.spec.node_name
        print(f"📍 运行节点: {node_name}")
        
        # 获取节点IP
        try:
            node = v1.read_node(name=node_name)
            node_ip = None
            for address in node.status.addresses:
                if address.type == "InternalIP":
                    node_ip = address.address
                    break
                elif address.type == "ExternalIP" and not node_ip:
                    node_ip = address.address
            
            if node_ip:
                print(f"   IP地址: {node_ip}")
            else:
                print(f"   ⚠️  无法获取节点IP")
        except Exception as e:
            print(f"   ⚠️  获取节点信息失败: {e}")
        
        # 3. 容器定义（从spec中）
        print(f"\n🐳 容器定义:")
        if pod.spec.containers:
            for container in pod.spec.containers:
                print(f"   名称: {container.name}")
                print(f"   镜像: {container.image}")
                if container.ports:
                    print(f"   端口: {[f'{p.name}:{p.container_port}' for p in container.ports]}")
                if container.command:
                    print(f"   启动命令: {' '.join(container.command)}")
                else:
                    print(f"   启动命令: (使用镜像默认CMD)")
        else:
            print("   ❌ Pod中没有定义容器！")
        
        # 4. 容器状态（从status中）
        print(f"\n📊 容器状态:")
        if pod.status.container_statuses:
            for container_status in pod.status.container_statuses:
                print(f"\n   容器: {container_status.name}")
                print(f"   状态: {container_status.state}")
                if container_status.ready:
                    print(f"   ✅ 容器就绪")
                else:
                    print(f"   ⚠️  容器未就绪")
                    if container_status.state.waiting:
                        print(f"   等待原因: {container_status.state.waiting.reason}")
                        print(f"   消息: {container_status.state.waiting.message}")
                    elif container_status.state.terminated:
                        print(f"   终止原因: {container_status.state.terminated.reason}")
                        print(f"   退出码: {container_status.state.terminated.exit_code}")
        else:
            print("   ⚠️  容器状态未更新（Pod可能刚创建，等待调度）")
        
        # 5. 查看日志（最后20行）
        print(f"\n📋 Pod日志（最后20行）:")
        try:
            logs = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=20
            )
            if logs:
                for line in logs.split('\n')[-20:]:
                    if line.strip():
                        print(f"   {line}")
            else:
                print("   (无日志)")
        except Exception as e:
            print(f"   ⚠️  无法获取日志: {e}")
        
        return True
        
    except client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"❌ Pod不存在: {pod_name}")
        else:
            print(f"❌ 获取Pod信息失败: {e.status} - {e.reason}")
        return False
    except Exception as e:
        print(f"❌ 诊断失败: {e}")
        return False


def diagnose_service(service_name: str, namespace: str = "default"):
    """诊断Service状态"""
    v1 = get_k8s_client()
    if not v1:
        return False
    
    print(f"\n{'='*60}")
    print(f"诊断Service: {service_name}")
    print(f"{'='*60}\n")
    
    try:
        # 获取Service信息
        svc = v1.read_namespaced_service(name=service_name, namespace=namespace)
        
        print(f"📊 Service类型: {svc.spec.type}")
        print(f"📍 命名空间: {namespace}")
        
        # 检查端口
        print(f"\n🔌 Service端口:")
        if svc.spec.ports:
            for port in svc.spec.ports:
                node_port = port.node_port if hasattr(port, 'node_port') else None
                print(f"   - {port.name}:")
                print(f"     端口: {port.port}")
                print(f"     目标端口: {port.target_port}")
                if node_port:
                    print(f"     NodePort: {node_port}")
                print(f"     协议: {port.protocol}")
        else:
            print("   ⚠️  Service未定义端口")
        
        # 检查选择器
        print(f"\n🎯 Service选择器: {svc.spec.selector}")
        
        # 检查Endpoints
        print(f"\n🔗 Endpoints:")
        try:
            endpoints = v1.read_namespaced_endpoints(name=service_name, namespace=namespace)
            if endpoints.subsets:
                for subset in endpoints.subsets:
                    if subset.addresses:
                        for address in subset.addresses:
                            print(f"   ✅ {address.ip}")
                            if address.target_ref:
                                print(f"      Pod: {address.target_ref.name}")
                    else:
                        print("   ⚠️  无可用Endpoints（Pod可能未就绪）")
            else:
                print("   ⚠️  无Endpoints（Pod可能未就绪或选择器不匹配）")
        except Exception as e:
            print(f"   ⚠️  无法获取Endpoints: {e}")
        
        return True
        
    except client.exceptions.ApiException as e:
        if e.status == 404:
            print(f"❌ Service不存在: {service_name}")
        else:
            print(f"❌ 获取Service信息失败: {e.status} - {e.reason}")
        return False
    except Exception as e:
        print(f"❌ 诊断失败: {e}")
        return False


def get_allocation_info(container_id: str):
    """从数据库获取分配信息"""
    db = SessionLocal()
    try:
        allocation = db.query(Allocation).filter(
            Allocation.container_id == container_id
        ).first()
        
        if not allocation:
            print(f"❌ 未找到容器ID: {container_id}")
            return None
        
        node_ip = None
        if allocation.node_id:
            node = db.query(Node).filter(Node.id == allocation.node_id).first()
            if node:
                node_ip = node.ip
        
        return {
            "allocation_id": allocation.id,
            "container_id": allocation.container_id,
            "pod_name": f"pod-{allocation.id}-{allocation.container_id[:8]}" if allocation.container_id else None,
            "service_name": f"svc-{allocation.id}",
            "node_id": allocation.node_id,
            "node_ip": node_ip,
            "jupyter_port": allocation.jupyter_port,
            "status": allocation.status.value,
            "image": allocation.image_name
        }
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="诊断Jupyter连接问题")
    parser.add_argument("container_id", nargs="?", help="容器ID")
    parser.add_argument("--all", action="store_true", help="诊断所有实例")
    parser.add_argument("--namespace", default="default", help="K8s命名空间")
    
    args = parser.parse_args()
    
    if not KUBERNETES_AVAILABLE:
        return
    
    if args.all:
        # 诊断所有实例
        db = SessionLocal()
        try:
            allocations = db.query(Allocation).filter(
                Allocation.status.in_(["approved", "running"])
            ).all()
            
            if not allocations:
                print("❌ 没有找到运行中的实例")
                return
            
            for alloc in allocations:
                if alloc.container_id:
                    info = get_allocation_info(alloc.container_id)
                    if info:
                        print(f"\n{'#'*60}")
                        print(f"实例: {info['container_id']}")
                        print(f"{'#'*60}")
                        diagnose_pod(info['pod_name'], args.namespace)
                        diagnose_service(info['service_name'], args.namespace)
        finally:
            db.close()
    elif args.container_id:
        # 诊断指定实例
        info = get_allocation_info(args.container_id)
        if not info:
            return
        
        print(f"\n{'#'*60}")
        print(f"实例信息")
        print(f"{'#'*60}")
        print(f"容器ID: {info['container_id']}")
        print(f"Pod名称: {info['pod_name']}")
        print(f"Service名称: {info['service_name']}")
        print(f"节点ID: {info['node_id']}")
        print(f"节点IP（数据库）: {info['node_ip']}")
        print(f"Jupyter端口: {info['jupyter_port']}")
        print(f"状态: {info['status']}")
        print(f"镜像: {info['image']}")
        
        if info['jupyter_port'] and info['node_ip']:
            print(f"\n🌐 访问地址: http://{info['node_ip']}:{info['jupyter_port']}")
        
        diagnose_pod(info['pod_name'], args.namespace)
        diagnose_service(info['service_name'], args.namespace)
        
        # 提供建议
        print(f"\n{'='*60}")
        print(f"💡 诊断建议")
        print(f"{'='*60}")
        print("1. 确认Pod状态为Running")
        print("2. 确认容器已就绪（Ready）")
        print("3. 确认Service的NodePort已分配")
        print("4. 确认Endpoints中有Pod IP")
        print("5. 检查Pod日志，确认Jupyter已启动")
        print("6. 检查防火墙是否允许NodePort端口访问")
        print("7. 确认访问的节点IP是正确的（Pod实际运行的节点）")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

