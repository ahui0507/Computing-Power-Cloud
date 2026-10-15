#!/bin/bash
# 修复K3s无法识别镜像的问题

echo "=========================================="
echo "修复K3s镜像识别问题"
echo "=========================================="
echo ""

NODE_IP="${1:-REPLACE_NODE_INTERNAL_IP}"
SSH_USER="${K3S_SSH_USER:-test}"

echo "目标节点: ${SSH_USER}@${NODE_IP}"
echo ""

# 在worker1节点上执行
ssh ${SSH_USER}@${NODE_IP} << 'EOF'
    echo "1. 检查ctr命令:"
    CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
    if [ -z "$CTR_PATH" ]; then
        echo "   ❌ 无法找到ctr命令"
        exit 1
    fi
    echo "   使用: $CTR_PATH"
    
    echo ""
    echo "2. 检查K3s containerd命名空间:"
    # K3s使用k8s.io命名空间
    echo "   列出k8s.io命名空间的镜像:"
    sudo $CTR_PATH -n k8s.io images ls | grep jupyter-test || echo "   未找到镜像"
    
    echo ""
    echo "3. 检查默认命名空间的镜像:"
    sudo $CTR_PATH images ls | grep jupyter-test || echo "   未找到镜像"
    
    echo ""
    echo "4. 如果镜像在默认命名空间，需要导入到k8s.io命名空间:"
    if sudo $CTR_PATH images ls | grep -q "jupyter-test:latest"; then
        echo "   找到镜像在默认命名空间，导入到k8s.io..."
        # 导出镜像
        sudo $CTR_PATH images export /tmp/jupyter-test-k8s.tar jupyter-test:latest
        # 导入到k8s.io命名空间
        sudo $CTR_PATH -n k8s.io images import /tmp/jupyter-test-k8s.tar
        # 标记镜像
        sudo $CTR_PATH -n k8s.io images tag jupyter-test:latest jupyter-test:latest 2>/dev/null || true
        echo "   ✅ 镜像已导入到k8s.io命名空间"
    fi
    
    echo ""
    echo "5. 验证k8s.io命名空间的镜像:"
    sudo $CTR_PATH -n k8s.io images ls | grep jupyter-test
    
    echo ""
    echo "6. 重启kubelet（如果需要）:"
    echo "   在control节点上执行: sudo systemctl restart k3s"
    echo "   或者在worker节点上: sudo systemctl restart k3s-agent"
EOF

echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo ""
echo "如果镜像已导入到k8s.io命名空间，请:"
echo "1. 重启K3s服务（在worker1节点）:"
echo "   ssh test@REPLACE_NODE_INTERNAL_IP"
echo "   sudo systemctl restart k3s-agent"
echo ""
echo "2. 或者删除Pod让它重新创建:"
echo "   kubectl delete pod pod-14-containe -n default"
echo ""

