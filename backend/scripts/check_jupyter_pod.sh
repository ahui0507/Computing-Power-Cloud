#!/bin/bash
# 快速检查Jupyter Pod状态

POD_NAME="pod-9-containe"

echo "=========================================="
echo "检查Jupyter Pod: $POD_NAME"
echo "=========================================="
echo ""

# 1. 检查Pod状态
echo "1. Pod状态:"
kubectl get pod $POD_NAME -n default -o wide 2>/dev/null || echo "Pod不存在"

echo ""
echo "2. Pod详细信息:"
kubectl describe pod $POD_NAME -n default 2>/dev/null | head -50

echo ""
echo "3. Pod事件:"
kubectl describe pod $POD_NAME -n default 2>/dev/null | grep -A 20 "Events:"

echo ""
echo "4. 检查镜像:"
IMAGE=$(kubectl get pod $POD_NAME -n default -o jsonpath='{.spec.containers[0].image}' 2>/dev/null)
if [ -n "$IMAGE" ]; then
    echo "   Pod使用的镜像: $IMAGE"
    echo ""
    echo "   检查镜像是否已导入:"
    CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
    if [ -n "$CTR_PATH" ]; then
        echo "   使用: sudo $CTR_PATH images ls | grep -i jupyter"
        sudo $CTR_PATH images ls | grep -i jupyter || echo "   ⚠️  未找到jupyter镜像"
    else
        echo "   ⚠️  无法找到ctr命令"
    fi
else
    echo "   ⚠️  无法获取镜像信息"
fi

echo ""
echo "5. 检查镜像拉取策略:"
kubectl get pod $POD_NAME -n default -o jsonpath='{.spec.containers[0].imagePullPolicy}' 2>/dev/null

