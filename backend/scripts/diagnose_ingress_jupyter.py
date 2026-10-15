#!/usr/bin/env python3
"""
Ingress 模式 Jupyter 访问故障诊断脚本

用于排查 Pod 运行但通过 Ingress 无法访问 Jupyter 的问题
"""
import subprocess
import sys
import json
import time
from typing import Optional, Dict, Any, Tuple


def run_command(cmd: str, check: bool = True) -> Tuple[str, str]:
    """执行命令并返回输出"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.CalledProcessError as e:
        return e.stdout.strip(), e.stderr.strip()


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{'='*60}")
    print(f" {title}")
    print('='*60)


def check_pod_status(pod_name: str) -> bool:
    """检查 Pod 状态"""
    print_section("1. 检查 Pod 状态")
    
    stdout, stderr = run_command(f"kubectl get pod {pod_name} -n default -o json", check=False)
    
    if stderr or not stdout:
        print(f"❌ 无法获取 Pod 信息: {stderr}")
        return False
    
    try:
        pod_info = json.loads(stdout)
        status = pod_info.get('status', {})
        spec = pod_info.get('spec', {})
        
        phase = status.get('phase', 'Unknown')
        node_name = spec.get('nodeName', 'Not scheduled')
        
        print(f"Pod 名称: {pod_name}")
        print(f"状态: {phase}")
        print(f"运行节点: {node_name}")
        
        # 检查容器状态
        container_statuses = status.get('containerStatuses', [])
        if container_statuses:
            for cs in container_statuses:
                name = cs.get('name', 'unknown')
                ready = cs.get('ready', False)
                state = cs.get('state', {})
                print(f"\n容器 '{name}':")
                print(f"  Ready: {ready}")
                if 'running' in state:
                    print(f"  状态: Running")
                elif 'waiting' in state:
                    reason = state['waiting'].get('reason', 'Unknown')
                    message = state['waiting'].get('message', '')
                    print(f"  状态: Waiting ({reason})")
                    print(f"  消息: {message}")
                elif 'terminated' in state:
                    reason = state['terminated'].get('reason', 'Unknown')
                    print(f"  状态: Terminated ({reason})")
        
        # 检查 Pod IP
        pod_ip = status.get('podIP', 'Not assigned')
        print(f"\nPod IP: {pod_ip}")
        
        if phase != 'Running':
            print(f"\n⚠️  Pod 未处于 Running 状态，请先检查 Pod 启动问题")
            return False
        
        return True
        
    except json.JSONDecodeError:
        print(f"❌ 无法解析 Pod 信息")
        return False


def check_service(allocation_id: str) -> Optional[Dict[str, Any]]:
    """检查 Service 状态"""
    print_section("2. 检查 Service 状态")
    
    service_name = f"svc-{allocation_id}"
    
    stdout, stderr = run_command(
        f"kubectl get svc {service_name} -n default -o json",
        check=False
    )
    
    if stderr or not stdout:
        print(f"❌ Service {service_name} 不存在或无法访问")
        return None
    
    try:
        svc_info = json.loads(stdout)
        spec = svc_info.get('spec', {})
        ports = spec.get('ports', [])
        
        print(f"Service 名称: {service_name}")
        print(f"类型: {spec.get('type', 'Unknown')}")
        print(f"Selector: {spec.get('selector', {})}")
        
        jupyter_port = None
        for port in ports:
            name = port.get('name', '')
            target_port = port.get('targetPort')
            port_num = port.get('port')
            
            print(f"\n端口 {name}:")
            print(f"  Service Port: {port_num}")
            print(f"  Target Port: {target_port}")
            
            if name == 'jupyter':
                jupyter_port = port_num
        
        if jupyter_port:
            print(f"\n✅ Jupyter Service Port: {jupyter_port}")
        else:
            print(f"\n❌ 未找到 Jupyter 端口")
        
        # 检查 Endpoints
        stdout, stderr = run_command(
            f"kubectl get endpoints {service_name} -n default -o json",
            check=False
        )
        
        if stdout:
            ep_info = json.loads(stdout)
            subsets = ep_info.get('subsets', [])
            
            if not subsets:
                print(f"\n❌ Endpoints 为空 - Service 无法找到 Pod")
                print("   可能原因：Pod 标签与 Service selector 不匹配")
            else:
                print(f"\n✅ Endpoints 正常:")
                for subset in subsets:
                    addresses = subset.get('addresses', [])
                    ports = subset.get('ports', [])
                    for addr in addresses:
                        print(f"  IP: {addr.get('ip')}")
                    for port in ports:
                        print(f"  端口: {port.get('port')} ({port.get('protocol')})")
        
        return {
            'service_name': service_name,
            'jupyter_port': jupyter_port,
            'type': spec.get('type')
        }
    except json.JSONDecodeError:
        print("❌ 无法解析 Service 信息")
        return None


def check_ingress(allocation_id: str) -> Optional[Dict[str, Any]]:
    """检查 Ingress 状态"""
    print_section("3. 检查 Ingress 状态")
    
    ingress_name = f"jupyter-{allocation_id}"
    
    stdout, stderr = run_command(
        f"kubectl get ingress {ingress_name} -n default -o json",
        check=False
    )
    
    if stderr or not stdout:
        print(f"❌ Ingress {ingress_name} 不存在")
        print("   这是主要问题：没有 Ingress 资源暴露服务")
        return None
    
    try:
        ingress_info = json.loads(stdout)
        spec = ingress_info.get('spec', {})
        metadata = ingress_info.get('metadata', {})
        annotations = metadata.get('annotations', {})
        status = ingress_info.get('status', {})
        
        print(f"Ingress 名称: {ingress_name}")
        print(f"Annotations: {annotations}")
        
        # 检查规则
        rules = spec.get('rules', [])
        if not rules:
            print("❌ Ingress 没有配置规则")
            return None
        
        for rule in rules:
            host = rule.get('host', '*')
            http = rule.get('http', {})
            paths = http.get('paths', [])
            
            print(f"\nHost: {host}")
            print(f"Paths:")
            for path in paths:
                path_str = path.get('path', '/')
                path_type = path.get('pathType', 'Prefix')
                backend = path.get('backend', {})
                service = backend.get('service', {})
                
                print(f"  Path: {path_str} (Type: {path_type})")
                print(f"  Backend Service: {service.get('name', 'N/A')}")
                print(f"  Backend Port: {service.get('port', {}).get('number', 'N/A')}")
        
        # 检查 Ingress Controller 状态
        load_balancer = status.get('loadBalancer', {})
        ingress_addresses = load_balancer.get('ingress', [])
        
        if ingress_addresses:
            print(f"\n✅ Ingress Controller 已分配地址:")
            for addr in ingress_addresses:
                print(f"  {addr}")
        else:
            print(f"\n⚠️  Ingress Controller 未分配地址（可能是 Traefik 使用 NodePort）")
        
        # 检查 TLS
        tls = spec.get('tls', [])
        if tls:
            print(f"\nTLS 配置:")
            for tls_config in tls:
                hosts = tls_config.get('hosts', [])
                secret = tls_config.get('secretName', '')
                print(f"  Hosts: {hosts}")
                print(f"  Secret: {secret}")
        
        return {
            'ingress_name': ingress_name,
            'host': rules[0].get('host') if rules else None,
            'path': paths[0].get('path') if paths else None,
            'annotations': annotations
        }
    except json.JSONDecodeError:
        print("❌ 无法解析 Ingress 信息")
        return None


def check_traefik():
    """检查 Traefik Ingress Controller"""
    print_section("4. 检查 Traefik Ingress Controller")
    
    # 检查 Traefik Pod
    stdout, stderr = run_command(
        "kubectl get pods -n kube-system | grep traefik",
        check=False
    )
    
    if stdout:
        print("Traefik Pods:")
        print(stdout)
    else:
        print("❌ 未找到 Traefik Pod")
        return False
    
    # 检查 Traefik Service
    stdout, stderr = run_command(
        "kubectl get svc -n kube-system traefik -o json",
        check=False
    )
    
    if stdout:
        try:
            svc_info = json.loads(stdout)
            spec = svc_info.get('spec', {})
            svc_type = spec.get('type', 'Unknown')
            ports = spec.get('ports', [])
            
            print(f"\nTraefik Service 类型: {svc_type}")
            print("端口:")
            for port in ports:
                name = port.get('name', '')
                port_num = port.get('port')
                node_port = port.get('nodePort')
                print(f"  {name}: {port_num}" + (f" (NodePort: {node_port})" if node_port else ""))
            
            if svc_type == 'ClusterIP':
                print("\n⚠️  Traefik Service 是 ClusterIP 类型")
                print("   需要改为 NodePort 或 LoadBalancer 才能从外部访问")
        except:
            pass
    else:
        print("⚠️  无法获取 Traefik Service 信息")
    
    return True


def check_jupyter_listening(pod_name: str) -> bool:
    """检查 Jupyter 是否在容器内监听 0.0.0.0:8888"""
    print_section("5. 检查 Jupyter 端口监听")
    
    # 检查是否有 ss 命令
    stdout, stderr = run_command(
        f"kubectl exec {pod_name} -n default -- which ss 2>/dev/null",
        check=False
    )
    
    if stdout:
        # 使用 ss 命令
        stdout, stderr = run_command(
            f"kubectl exec {pod_name} -n default -- ss -lntp 2>/dev/null",
            check=False
        )
        print("端口监听情况:")
        print(stdout)
        
        if '0.0.0.0:8888' in stdout or '*:8888' in stdout:
            print("\n✅ Jupyter 正在监听 0.0.0.0:8888（正确）")
            return True
        elif '127.0.0.1:8888' in stdout or 'localhost:8888' in stdout:
            print("\n❌ Jupyter 只监听 127.0.0.1:8888（错误！）")
            print("   这是问题的根本原因：容器外部无法访问")
            return False
        elif ':8888' in stdout:
            print("\n⚠️  检测到 8888 端口，但绑定地址不明确")
            return None
        else:
            print("\n❌ 未检测到 8888 端口监听")
            return False
    else:
        # 尝试使用 netstat
        stdout, stderr = run_command(
            f"kubectl exec {pod_name} -n default -- netstat -tlnp 2>/dev/null || echo 'netstat not available'",
            check=False
        )
        if 'netstat not available' in stdout:
            print("⚠️  容器内没有 ss 或 netstat 命令，跳过端口检查")
            return None
        print(stdout)
        return None


def check_jupyter_logs(pod_name: str):
    """检查 Jupyter 日志"""
    print_section("6. 检查 Jupyter 日志")
    
    stdout, stderr = run_command(
        f"kubectl logs {pod_name} -n default --tail=50",
        check=False
    )
    
    if stdout:
        print(stdout)
        
        # 分析日志
        if '0.0.0.0:8888' in stdout or 'Jupyter Server is running' in stdout:
            print("\n✅ 日志显示 Jupyter 正在运行")
        elif '127.0.0.1' in stdout:
            print("\n⚠️  日志中发现了 127.0.0.1，可能是配置问题")
        elif 'error' in stdout.lower() or 'Error' in stdout:
            print("\n⚠️  日志中发现了错误信息")
        elif 'token=' in stdout:
            print("\n⚠️  日志中包含 token，可能需要在 URL 中使用 token 访问")
    else:
        print("无日志输出")


def test_ingress_access(ingress_info: Optional[Dict[str, Any]]):
    """测试 Ingress 访问"""
    print_section("7. 测试 Ingress 访问")
    
    if not ingress_info:
        print("⚠️  无法测试：Ingress 不存在")
        return
    
    host = ingress_info.get('host')
    path = ingress_info.get('path')
    
    if not host or not path:
        print("⚠️  无法测试：Ingress 配置不完整")
        return
    
    # 测试访问
    url = f"http://{host}{path}"
    print(f"测试 URL: {url}")
    
    # 尝试 curl
    stdout, stderr = run_command(
        f"curl -I -H 'Host: {host}' {url} 2>&1",
        check=False
    )
    
    print("\ncurl 测试结果:")
    print(stdout)
    if stderr:
        print(f"错误: {stderr}")
    
    # 分析结果
    if '200 OK' in stdout or '301' in stdout or '302' in stdout:
        print("\n✅ HTTP 请求成功")
    elif '404' in stdout:
        print("\n❌ 返回 404 - 路径不匹配或后端服务不可用")
    elif 'Connection refused' in stdout or 'Connection refused' in stderr:
        print("\n❌ 连接被拒绝 - 检查 Traefik 是否运行和端口是否开放")
    elif 'Could not resolve host' in stdout or 'Could not resolve host' in stderr:
        print("\n❌ 无法解析主机 - 检查 hosts 文件或 DNS 配置")
    else:
        print("\n⚠️  无法确定访问状态")


def main():
    if len(sys.argv) < 2:
        print("用法: python diagnose_ingress_jupyter.py <pod_name>")
        print("示例: python diagnose_ingress_jupyter.py pod-21-containe")
        sys.exit(1)
    
    pod_name = sys.argv[1]
    
    # 从 Pod 名称提取 allocation ID
    # pod-{id}-{container_id}
    try:
        parts = pod_name.split('-')
        if len(parts) >= 2:
            allocation_id = parts[1]
        else:
            print("❌ 无法从 Pod 名称推断 allocation ID")
            sys.exit(1)
    except:
        print("❌ 无法从 Pod 名称推断 allocation ID")
        sys.exit(1)
    
    print("="*60)
    print(" Ingress 模式 Jupyter 访问故障诊断")
    print("="*60)
    print(f"诊断 Pod: {pod_name}")
    print(f"Allocation ID: {allocation_id}\n")
    
    # 1. 检查 Pod 状态
    pod_running = check_pod_status(pod_name)
    if not pod_running:
        print("\n❌ Pod 未正常运行，请先解决 Pod 启动问题")
        sys.exit(1)
    
    # 2. 检查 Service
    service_info = check_service(allocation_id)
    
    # 3. 检查 Ingress
    ingress_info = check_ingress(allocation_id)
    
    # 4. 检查 Traefik
    traefik_ok = check_traefik()
    
    # 5. 检查 Jupyter 端口监听
    listening_ok = check_jupyter_listening(pod_name)
    
    # 6. 检查 Jupyter 日志
    check_jupyter_logs(pod_name)
    
    # 7. 测试 Ingress 访问
    test_ingress_access(ingress_info)
    
    # 总结
    print_section("诊断总结")
    
    issues = []
    if not ingress_info:
        issues.append("❌ Ingress 不存在 - 这是主要问题")
    if not service_info:
        issues.append("❌ Service 不存在")
    if service_info and not service_info.get('jupyter_port'):
        issues.append("❌ Service 没有配置 Jupyter 端口")
    if listening_ok is False:
        issues.append("❌ Jupyter 只监听 127.0.0.1:8888，需要修改为 0.0.0.0:8888")
    if not traefik_ok:
        issues.append("❌ Traefik Ingress Controller 未运行或配置不正确")
    
    if issues:
        print("发现的问题:")
        for issue in issues:
            print(f"  {issue}")
        
        print("\n修复建议:")
        if not ingress_info:
            print("\n1. 检查后端配置:")
            print("   - 确认 INGRESS_ENABLED=true")
            print("   - 确认 INGRESS_HOST 配置正确")
            print("   - 检查后端日志，查看 Ingress 创建是否失败")
            print("   - 手动创建 Ingress 或重新创建 Pod")
        
        if listening_ok is False:
            print("\n2. 修复 Jupyter 监听地址:")
            print("   - 检查 Dockerfile CMD 是否包含 --ip=0.0.0.0")
            print("   - 如果使用配置文件，确保设置 c.ServerApp.ip = '0.0.0.0'")
            print("   - 重新构建并导入镜像")
        
        if not traefik_ok:
            print("\n3. 检查 Traefik:")
            print("   - 确认 Traefik 正在运行: kubectl get pods -n kube-system | grep traefik")
            print("   - 确认 Traefik Service 类型: kubectl get svc -n kube-system traefik")
            print("   - 如果 Service 是 ClusterIP，需要改为 NodePort")
    else:
        print("✅ 所有检查项都正常")
        print("\n如果仍然无法访问，请尝试:")
        print("  1. 检查 hosts 文件配置（如果使用 platform.local）")
        print("  2. 检查防火墙规则（开放 80 端口）")
        print("  3. 使用 kubectl port-forward 测试:")
        print(f"     kubectl port-forward {pod_name} 8888:8888")
        print("     然后访问 http://localhost:8888")
        print("  4. 检查 Jupyter token（如果需要）")


if __name__ == "__main__":
    main()
