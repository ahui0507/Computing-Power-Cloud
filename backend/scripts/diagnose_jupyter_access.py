#!/usr/bin/env python3
"""
Jupyter访问故障诊断脚本

用于排查 Pod 运行但 JupyterLab 无法访问的问题
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


def check_jupyter_listening(pod_name: str) -> bool:
    """检查 Jupyter 是否在容器内监听 0.0.0.0:8888"""
    print_section("2. 检查 Jupyter 端口监听")
    
    # 检查是否有 ss 命令
    stdout, stderr = run_command(
        f"kubectl exec {pod_name} -n default -- which ss",
        check=False
    )
    
    if stdout:
        # 使用 ss 命令
        stdout, stderr = run_command(
            f"kubectl exec {pod_name} -n default -- ss -lntp",
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
    print_section("3. 检查 Jupyter 日志")
    
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


def check_service(pod_name: str) -> Optional[Dict[str, Any]]:
    """检查 Service 和端口"""
    print_section("4. 检查 Service 和端口")
    
    # 从 Pod 名称提取 allocation ID
    # pod-{id}-{container_id}
    try:
        parts = pod_name.split('-')
        if len(parts) >= 2:
            allocation_id = parts[1]
            service_name = f"svc-{allocation_id}"
        else:
            print("⚠️  无法从 Pod 名称推断 Service 名称")
            return None
    except:
        print("⚠️  无法从 Pod 名称推断 Service 名称")
        return None
    
    # 检查 Service
    stdout, stderr = run_command(
        f"kubectl get svc {service_name} -n default -o json",
        check=False
    )
    
    if stderr or not stdout:
        print(f"❌ Service {service_name} 不存在或无法访问")
        print("   这是问题之一：没有 Service 暴露端口")
        return None
    
    try:
        svc_info = json.loads(stdout)
        spec = svc_info.get('spec', {})
        ports = spec.get('ports', [])
        
        print(f"Service 名称: {service_name}")
        print(f"类型: {spec.get('type', 'Unknown')}")
        
        jupyter_port = None
        for port in ports:
            name = port.get('name', '')
            node_port = port.get('nodePort')
            target_port = port.get('targetPort')
            port_num = port.get('port')
            
            print(f"\n端口 {name}:")
            print(f"  Service Port: {port_num}")
            print(f"  Target Port: {target_port}")
            print(f"  NodePort: {node_port}")
            
            if name == 'jupyter' and node_port:
                jupyter_port = node_port
        
        if jupyter_port:
            print(f"\n✅ Jupyter NodePort: {jupyter_port}")
        else:
            print(f"\n❌ 未找到 Jupyter NodePort")
        
        return {
            'service_name': service_name,
            'jupyter_port': jupyter_port,
            'type': spec.get('type')
        }
    except json.JSONDecodeError:
        print("❌ 无法解析 Service 信息")
        return None


def check_endpoints(pod_name: str, service_name: str):
    """检查 Service Endpoints"""
    print_section("5. 检查 Service Endpoints")
    
    stdout, stderr = run_command(
        f"kubectl get endpoints {service_name} -n default -o json",
        check=False
    )
    
    if stdout:
        try:
            ep_info = json.loads(stdout)
            subsets = ep_info.get('subsets', [])
            
            if not subsets:
                print("❌ Endpoints 为空 - Service 无法找到 Pod")
                print("   可能原因：Pod 标签与 Service selector 不匹配")
                return False
            
            for subset in subsets:
                addresses = subset.get('addresses', [])
                ports = subset.get('ports', [])
                
                print(f"Endpoints: {len(addresses)} 个")
                for addr in addresses:
                    print(f"  IP: {addr.get('ip')}")
                for port in ports:
                    print(f"  端口: {port.get('port')} ({port.get('protocol')})")
            
            print("\n✅ Endpoints 正常")
            return True
            
        except json.JSONDecodeError:
            print("无法解析 Endpoints 信息")
    else:
        print("❌ 无法获取 Endpoints")
    
    return False


def check_node_access(pod_name: str, service_info: Optional[Dict[str, Any]]):
    """检查节点访问"""
    print_section("6. 检查节点访问信息")
    
    # 获取 Pod 运行的节点
    stdout, stderr = run_command(
        f"kubectl get pod {pod_name} -n default -o jsonpath='{{.spec.nodeName}}'",
        check=False
    )
    
    if not stdout:
        print("⚠️  无法获取 Pod 运行节点")
        return
    
    node_name = stdout
    print(f"Pod 运行节点: {node_name}")
    
    # 获取节点 IP
    stdout, stderr = run_command(
        f"kubectl get node {node_name} -o jsonpath='{{.status.addresses[?(@.type==\"InternalIP\")].address}}'",
        check=False
    )
    
    if stdout:
        node_ip = stdout
        print(f"节点 IP: {node_ip}")
        
        if service_info and service_info.get('jupyter_port'):
            jupyter_port = service_info['jupyter_port']
            print(f"\n✅ 访问地址应该是:")
            print(f"   http://{node_ip}:{jupyter_port}")
            print(f"\n⚠️  如果无法访问，请检查:")
            print(f"   1. 防火墙是否开放端口 {jupyter_port}")
            print(f"   2. Jupyter 是否监听了 0.0.0.0:8888（见步骤 2）")
            print(f"   3. Service Endpoints 是否正常（见步骤 5）")


def test_container_access(pod_name: str):
    """测试容器内访问"""
    print_section("7. 测试容器内访问")
    
    # 尝试在容器内 curl Jupyter
    stdout, stderr = run_command(
        f"kubectl exec {pod_name} -n default -- curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:8888 2>&1 || echo 'curl failed'",
        check=False
    )
    
    if stdout and stdout.isdigit():
        status_code = int(stdout)
        if status_code == 200:
            print("✅ 容器内可以访问 Jupyter (HTTP 200)")
        elif status_code in [301, 302]:
            print(f"✅ 容器内可以访问 Jupyter (HTTP {status_code} - 重定向)")
        else:
            print(f"⚠️  容器内访问返回 HTTP {status_code}")
    elif 'curl failed' in stdout or 'command not found' in stdout:
        print("⚠️  容器内没有 curl 命令，跳过测试")
    else:
        print(f"⚠️  无法测试容器内访问: {stdout}")


def main():
    if len(sys.argv) < 2:
        print("用法: python diagnose_jupyter_access.py <pod_name>")
        print("示例: python diagnose_jupyter_access.py pod-19-containe")
        sys.exit(1)
    
    pod_name = sys.argv[1]
    
    print("="*60)
    print(" Jupyter 访问故障诊断")
    print("="*60)
    print(f"诊断 Pod: {pod_name}\n")
    
    # 1. 检查 Pod 状态
    pod_running = check_pod_status(pod_name)
    if not pod_running:
        print("\n❌ Pod 未正常运行，请先解决 Pod 启动问题")
        sys.exit(1)
    
    # 2. 检查 Jupyter 端口监听
    listening_ok = check_jupyter_listening(pod_name)
    
    # 3. 检查 Jupyter 日志
    check_jupyter_logs(pod_name)
    
    # 4. 检查 Service
    service_info = check_service(pod_name)
    
    # 5. 检查 Endpoints
    if service_info:
        check_endpoints(pod_name, service_info['service_name'])
    
    # 6. 检查节点访问
    check_node_access(pod_name, service_info)
    
    # 7. 测试容器内访问
    test_container_access(pod_name)
    
    # 总结
    print_section("诊断总结")
    
    issues = []
    if listening_ok is False:
        issues.append("❌ Jupyter 只监听 127.0.0.1:8888，需要修改为 0.0.0.0:8888")
    if not service_info:
        issues.append("❌ 没有 Service 暴露端口")
    if service_info and not service_info.get('jupyter_port'):
        issues.append("❌ Service 没有分配 NodePort")
    
    if issues:
        print("发现的问题:")
        for issue in issues:
            print(f"  {issue}")
        
        print("\n修复建议:")
        if listening_ok is False:
            print("\n1. 修复 Jupyter 监听地址:")
            print("   - 检查 Dockerfile CMD 是否包含 --ip=0.0.0.0")
            print("   - 如果使用配置文件，确保设置 c.ServerApp.ip = '0.0.0.0'")
            print("   - 重新构建并导入镜像")
        
        if not service_info:
            print("\n2. 创建 Service:")
            print("   - 检查后端日志，确认 Service 创建是否失败")
            print("   - 手动创建 Service 或重新创建 Pod")
    else:
        print("✅ 所有检查项都正常")
        print("\n如果仍然无法访问，请尝试:")
        print("  1. 使用 kubectl port-forward 测试:")
        print(f"     kubectl port-forward {pod_name} 8888:8888")
        print("     然后访问 http://localhost:8888")
        print("  2. 检查防火墙规则")
        print("  3. 检查 Jupyter token（如果需要）")


if __name__ == "__main__":
    main()

