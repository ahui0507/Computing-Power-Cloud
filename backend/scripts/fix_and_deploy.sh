#!/bin/bash
# 修复 kubeconfig 权限并部署 Device Plugin

set -e

echo "============================================================"
echo "修复 kubeconfig 并部署 Device Plugin"
echo "============================================================"
echo ""

# 1. 修复 kubeconfig 权限
echo "步骤 1: 配置 kubeconfig..."
echo ""

K3S_CONFIG="/etc/rancher/k3s/k3s.yaml"
KUBE_DIR="$HOME/.kube"

if [ ! -f "$K3S_CONFIG" ]; then
    echo "✗ 未找到 K3s 配置文件: $K3S_CONFIG"
    exit 1
fi

# 创建 .kube 目录
mkdir -p "$KUBE_DIR"

# 复制配置文件
echo "复制配置文件到用户目录..."
sudo cp "$K3S_CONFIG" "$KUBE_DIR/config"

# 设置权限
echo "设置文件权限..."
sudo chown "$USER:$USER" "$KUBE_DIR/config"
chmod 600 "$KUBE_DIR/config"

echo "✓ kubeconfig 配置完成"
echo ""

# 2. 验证 kubectl 连接
echo "步骤 2: 验证 kubectl 连接..."
echo ""

if kubectl get nodes &>/dev/null; then
    echo "✓ kubectl 连接正常"
    kubectl get nodes
    echo ""
else
    echo "✗ kubectl 连接失败"
    exit 1
fi

# 3. 检查 Device Plugin 是否已部署
echo "步骤 3: 检查 Device Plugin 状态..."
echo ""

if kubectl get daemonset -n kube-system nvidia-device-plugin-daemonset &>/dev/null; then
    echo "✓ Device Plugin 已部署"
    kubectl get daemonset -n kube-system nvidia-device-plugin-daemonset
    echo ""
    
    echo "Device Plugin Pods 状态:"
    kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
    echo ""
else
    echo "⚠ Device Plugin 未部署，开始部署..."
    echo ""
    
    # 4. 部署 Device Plugin
    # 尝试多个可能的路径
    PLUGIN_YAML=""
    if [ -f "../deploy/kubernetes/cluster/nvidia-device-plugin.yaml" ]; then
        PLUGIN_YAML="../deploy/kubernetes/cluster/nvidia-device-plugin.yaml"
    elif [ -f "../../deploy/kubernetes/cluster/nvidia-device-plugin.yaml" ]; then
        PLUGIN_YAML="../../deploy/kubernetes/cluster/nvidia-device-plugin.yaml"
    elif [ -f "deploy/kubernetes/cluster/nvidia-device-plugin.yaml" ]; then
        PLUGIN_YAML="deploy/kubernetes/cluster/nvidia-device-plugin.yaml"
    fi
    
    if [ -n "$PLUGIN_YAML" ]; then
        echo "部署 Device Plugin..."
        kubectl apply -f "$PLUGIN_YAML"
        echo ""
        
        echo "等待 Device Plugin Pods 启动..."
        sleep 5
        
        echo "Device Plugin Pods 状态:"
        kubectl get pods -n kube-system -l name=nvidia-device-plugin-ds
        echo ""
        
        echo "✓ Device Plugin 部署完成"
    else
        echo "✗ 未找到 Device Plugin 配置文件: deploy/kubernetes/cluster/nvidia-device-plugin.yaml"
        echo ""
        echo "请确保在项目根目录运行此脚本"
        exit 1
    fi
fi

# 5. 检查节点 GPU 资源
echo "步骤 4: 检查节点 GPU 资源..."
echo ""

kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU-CAPACITY:.status.capacity.'nvidia\.com/gpu',GPU-ALLOCATABLE:.status.allocatable.'nvidia\.com/gpu'
echo ""

# 6. 提供后续步骤
echo "============================================================"
echo "完成"
echo "============================================================"
echo ""
echo "如果 worker1 节点仍然显示 GPU 为 0，请在 worker1 节点上执行："
echo ""
echo "1. 检查 containerd 配置:"
echo "   sudo cat /etc/containerd/config.toml | grep -A 10 nvidia"
echo ""
echo "2. 如果未配置，添加 NVIDIA 运行时配置并重启:"
echo "   sudo systemctl restart containerd"
echo "   sudo systemctl restart k3s-agent"
echo ""
echo "3. 检查 Device Plugin Pod 日志:"
echo "   kubectl logs -n kube-system -l name=nvidia-device-plugin-ds --field-selector spec.nodeName=worker1"
echo ""

