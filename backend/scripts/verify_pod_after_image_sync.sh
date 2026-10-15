#!/bin/bash
# 验证镜像同步后Pod是否能正常工作

echo "=========================================="
echo "验证Pod状态（镜像同步后）"
echo "=========================================="
echo ""

# 检查所有Pod
echo "1. 检查所有Pod状态:"
kubectl get pods -n default | grep pod-

echo ""
echo "2. 检查最新的Pod:"
LATEST_POD=$(kubectl get pods -n default -o jsonpath='{.items[?(@.metadata.name=~"pod-.*")].metadata.name}' | tr ' ' '\n' | sort -r | head -1)

if [ -n "$LATEST_POD" ]; then
    echo "   最新Pod: $LATEST_POD"
    echo ""
    echo "   Pod状态:"
    kubectl get pod $LATEST_POD -n default -o wide
    
    echo ""
    echo "   Pod详细信息:"
    kubectl describe pod $LATEST_POD -n default | grep -A 20 "Events:"
    
    echo ""
    echo "   容器状态:"
    kubectl get pod $LATEST_POD -n default -o jsonpath='{.status.containerStatuses[*].state}' | jq '.' 2>/dev/null || \
    kubectl get pod $LATEST_POD -n default -o jsonpath='{.status.containerStatuses[0].state}'
    
    echo ""
    echo ""
    echo "3. 如果Pod状态不是Running，检查镜像:"
    NODE=$(kubectl get pod $LATEST_POD -n default -o jsonpath='{.spec.nodeName}')
    echo "   Pod运行在节点: $NODE"
    
    if [ "$NODE" = "worker1" ]; then
        echo "   在worker1节点上检查镜像:"
        ssh test@REPLACE_NODE_INTERNAL_IP "CTR_PATH=\$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1); \
                                sudo \$CTR_PATH images ls | grep jupyter-test"
    fi
else
    echo "   ⚠️  未找到Pod"
fi

echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo ""
echo "如果Pod仍然无法启动，请检查:"
echo "1. 镜像是否在所有节点上都已导入"
echo "2. Pod使用的镜像名称是否与导入的镜像名称一致"
echo "3. imagePullPolicy是否正确设置"
echo ""

