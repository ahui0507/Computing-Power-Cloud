#!/bin/bash
# K3s kubeconfig 配置脚本
# 用于将 K3s 配置文件复制到用户目录，解决权限问题

set -e

echo "=== K3s kubeconfig 配置脚本 ==="
echo ""

# 检查 K3s 配置文件是否存在
K3S_CONFIG="/etc/rancher/k3s/k3s.yaml"
if [ ! -f "$K3S_CONFIG" ]; then
    echo "✗ 未找到 K3s 配置文件: $K3S_CONFIG"
    echo ""
    echo "请确保 K3s 已安装:"
    echo "  curl -sfL https://get.k3s.io | sh -"
    exit 1
fi

# 创建 .kube 目录
KUBE_DIR="$HOME/.kube"
mkdir -p "$KUBE_DIR"

# 复制配置文件
echo "复制配置文件..."
sudo cp "$K3S_CONFIG" "$KUBE_DIR/config"

# 设置权限
echo "设置文件权限..."
sudo chown "$USER:$USER" "$KUBE_DIR/config"
chmod 600 "$KUBE_DIR/config"

# 更新配置文件中的 server 地址（如果需要）
# K3s 默认使用 localhost，如果从其他机器访问需要修改
CURRENT_SERVER=$(grep -oP 'server:\s*\K[^:]+' "$KUBE_DIR/config" || echo "")
if [ "$CURRENT_SERVER" = "127.0.0.1" ] || [ "$CURRENT_SERVER" = "localhost" ]; then
    # 获取控制节点 IP
    CONTROL_IP=$(hostname -I | awk '{print $1}')
    if [ -n "$CONTROL_IP" ]; then
        echo "更新 server 地址为: $CONTROL_IP"
        sed -i "s|server:.*|server: https://$CONTROL_IP:6443|g" "$KUBE_DIR/config"
    fi
fi

echo ""
echo "✓ kubeconfig 配置完成！"
echo ""
echo "配置文件位置: $KUBE_DIR/config"
echo ""
echo "验证配置:"
echo "  kubectl get nodes"
echo ""
