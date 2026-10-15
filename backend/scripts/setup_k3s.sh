#!/bin/bash
# K3s配置脚本

set -e

echo "=== K3s配置脚本 ==="

# 检查kubectl是否可用
if ! command -v kubectl &> /dev/null; then
    echo "错误: kubectl未安装"
    echo "请先安装K3s: curl -sfL https://get.k3s.io | sh -"
    exit 1
fi

# 检查K3s连接
echo "检查K3s连接..."
if ! kubectl get nodes &> /dev/null; then
    echo "错误: 无法连接到K3s集群"
    echo "请检查:"
    echo "1. K3s服务是否运行: sudo systemctl status k3s"
    echo "2. kubeconfig配置: ~/.kube/config"
    exit 1
fi

echo "✓ K3s连接正常"

# 显示节点信息
echo ""
echo "=== 节点信息 ==="
kubectl get nodes

# 检查NVIDIA Device Plugin（如果使用GPU）
echo ""
echo "=== 检查GPU支持 ==="
if kubectl get daemonset -n kube-system nvidia-device-plugin-daemonset &> /dev/null; then
    echo "✓ NVIDIA Device Plugin已安装"
else
    echo "⚠ NVIDIA Device Plugin未安装"
    echo "如果需要GPU支持，请运行:"
    echo "kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.14.1/nvidia-device-plugin.yml"
fi

# 创建命名空间（如果需要）
echo ""
echo "=== 创建命名空间 ==="
kubectl create namespace default --dry-run=client -o yaml | kubectl apply -f -
echo "✓ 命名空间已准备"

# 提示创建Secret
echo ""
echo "=== 下一步操作 ==="
echo "1. 创建数据库Secret:"
echo "   kubectl create secret generic db-secret \\"
echo "     --from-literal=url='mysql+pymysql://user:pass@host:3306/db' \\"
echo "     -n default"
echo ""
echo "2. 创建JWT Secret:"
echo "   kubectl create secret generic jwt-secret \\"
echo "     --from-literal=key='your-secret-key' \\"
echo "     -n default"
echo ""
echo "3. 部署后端服务:"
echo "   kubectl apply -f deploy/kubernetes/backend/backend-deployment.yaml"

echo ""
echo "=== 配置完成 ==="

