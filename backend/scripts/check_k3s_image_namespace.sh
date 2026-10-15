#!/bin/bash
# 检查K3s镜像命名空间

echo "=========================================="
echo "检查K3s镜像命名空间"
echo "=========================================="
echo ""

NODE="${1:-worker1}"
SSH_USER="${K3S_SSH_USER:-test}"

# 获取节点IP
if [ "$NODE" = "worker1" ]; then
    NODE_IP="REPLACE_NODE_INTERNAL_IP"
elif [ "$NODE" = "control" ]; then
    NODE_IP="localhost"
    SSH_USER=""
else
    NODE_IP=$(kubectl get node $NODE -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
fi

if [ -z "$NODE_IP" ]; then
    echo "❌ 无法获取节点IP"
    exit 1
fi

echo "检查节点: $NODE ($NODE_IP)"
echo ""

if [ "$NODE_IP" = "localhost" ]; then
    # 本地执行
    CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
    if [ -z "$CTR_PATH" ]; then
        echo "❌ 无法找到ctr命令"
        exit 1
    fi
    
    echo "1. 默认命名空间镜像:"
    sudo $CTR_PATH images ls | grep jupyter-test || echo "   未找到"
    
    echo ""
    echo "2. k8s.io命名空间镜像:"
    sudo $CTR_PATH -n k8s.io images ls | grep jupyter-test || echo "   未找到"
else
    # 远程执行
    ssh ${SSH_USER}@${NODE_IP} << 'EOF'
        CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
        if [ -z "$CTR_PATH" ]; then
            echo "❌ 无法找到ctr命令"
            exit 1
        fi
        
        echo "1. 默认命名空间镜像:"
        sudo $CTR_PATH images ls | grep jupyter-test || echo "   未找到"
        
        echo ""
        echo "2. k8s.io命名空间镜像:"
        sudo $CTR_PATH -n k8s.io images ls | grep jupyter-test || echo "   未找到"
EOF
fi

echo ""
echo "=========================================="
echo "说明:"
echo "  K3s使用k8s.io命名空间存储Kubernetes镜像"
echo "  如果镜像在默认命名空间，需要导入到k8s.io"
echo "=========================================="

