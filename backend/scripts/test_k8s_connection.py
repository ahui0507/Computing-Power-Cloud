#!/usr/bin/env python3
"""
测试K8s连接和配置

使用方法:
    python scripts/test_k8s_connection.py
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
    print("   请运行: pip install kubernetes")
    sys.exit(1)

def test_k8s_connection():
    """测试K8s连接"""
    print("=" * 60)
    print("测试K8s连接")
    print("=" * 60)
    print()
    
    # 1. 检查kubeconfig文件
    print("1. 检查kubeconfig配置:")
    kubeconfig_path = os.path.expanduser("~/.kube/config")
    if os.path.exists(kubeconfig_path):
        print(f"   ✅ 找到kubeconfig: {kubeconfig_path}")
    else:
        print(f"   ⚠️  kubeconfig不存在: {kubeconfig_path}")
        print("   将尝试使用集群内配置（ServiceAccount）")
    
    # 2. 尝试加载配置
    print("\n2. 加载K8s配置:")
    try:
        if os.path.exists(kubeconfig_path):
            config.load_kube_config()
            print("   ✅ 成功加载kubeconfig")
        else:
            try:
                config.load_incluster_config()
                print("   ✅ 成功加载集群内配置（ServiceAccount）")
            except config.ConfigException:
                print("   ❌ 无法加载K8s配置")
                print("   请确保:")
                print("     - kubeconfig文件存在: ~/.kube/config")
                print("     - 或者后端运行在K8s集群内")
                return False
    except Exception as e:
        print(f"   ❌ 加载配置失败: {e}")
        return False
    
    # 3. 测试API连接
    print("\n3. 测试API连接:")
    try:
        v1 = client.CoreV1Api()
        
        # 获取版本信息
        try:
            version = v1.get_code()
            print(f"   ✅ API连接成功")
            print(f"   版本: {version.git_version if hasattr(version, 'git_version') else 'N/A'}")
        except Exception as e:
            print(f"   ⚠️  获取版本信息失败: {e}")
        
        # 获取节点列表
        print("\n4. 获取节点列表:")
        try:
            nodes = v1.list_node()
            print(f"   ✅ 找到 {len(nodes.items)} 个节点:")
            for node in nodes.items:
                status = "Ready" if any(c.type == "Ready" and c.status == "True" for c in node.status.conditions) else "NotReady"
                print(f"      - {node.metadata.name}: {status}")
        except Exception as e:
            print(f"   ❌ 获取节点列表失败: {e}")
            return False
        
        # 获取所有namespace的Pod列表
        print("\n5. 获取Pod列表（所有namespace）:")
        try:
            pods = v1.list_pod_for_all_namespaces()
            print(f"   ✅ 找到 {len(pods.items)} 个Pod")
            
            # 按namespace分组
            pods_by_ns = {}
            for pod in pods.items:
                ns = pod.metadata.namespace
                if ns not in pods_by_ns:
                    pods_by_ns[ns] = []
                pods_by_ns[ns].append(pod)
            
            print(f"\n   按namespace分组:")
            for ns, pod_list in sorted(pods_by_ns.items()):
                print(f"      {ns}: {len(pod_list)} 个Pod")
                # 显示前5个Pod
                for pod in pod_list[:5]:
                    phase = pod.status.phase
                    print(f"         - {pod.metadata.name}: {phase}")
                if len(pod_list) > 5:
                    print(f"         ... 还有 {len(pod_list) - 5} 个Pod")
        except Exception as e:
            print(f"   ❌ 获取Pod列表失败: {e}")
            return False
        
        # 测试读取特定Pod
        print("\n6. 测试读取Pod:")
        test_pods = [
            ("coredns-6d668d687-bnwqx", "kube-system"),
            ("local-path-provisioner-869c44bfbd-g97ms", "kube-system"),
        ]
        
        for pod_name, namespace in test_pods:
            try:
                pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                print(f"   ✅ 成功读取: {pod_name} (namespace: {namespace})")
                print(f"      状态: {pod.status.phase}")
                print(f"      容器数: {len(pod.spec.containers) if pod.spec.containers else 0}")
            except client.exceptions.ApiException as e:
                if e.status == 404:
                    print(f"   ⚠️  Pod不存在: {pod_name} (namespace: {namespace})")
                else:
                    print(f"   ❌ 读取失败: {pod_name} - {e.status} - {e.reason}")
            except Exception as e:
                print(f"   ❌ 读取失败: {pod_name} - {e}")
        
        print("\n" + "=" * 60)
        print("✅ K8s连接测试完成")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"   ❌ API连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_k8s_connection()
    sys.exit(0 if success else 1)

