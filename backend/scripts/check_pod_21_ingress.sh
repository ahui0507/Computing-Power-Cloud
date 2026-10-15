#!/bin/bash
# 快速检查 pod-21 的 Ingress 访问问题

POD_NAME="pod-21-containe"
ALLOCATION_ID="21"
NAMESPACE="default"

echo "=========================================="
echo "检查 Pod-21 Ingress 访问问题"
echo "=========================================="
echo ""

# 1. 检查 Pod 状态
echo "1. 检查 Pod 状态:"
kubectl get pod $POD_NAME -n $NAMESPACE
echo ""

# 2. 检查 Service
echo "2. 检查 Service:"
kubectl get svc svc-$ALLOCATION_ID -n $NAMESPACE
echo ""

# 3. 检查 Ingress
echo "3. 检查 Ingress:"
kubectl get ingress jupyter-$ALLOCATION_ID -n $NAMESPACE
echo ""

# 4. 查看 Ingress 详情
echo "4. Ingress 详情:"
kubectl describe ingress jupyter-$ALLOCATION_ID -n $NAMESPACE
echo ""

# 5. 检查 Service Endpoints
echo "5. Service Endpoints:"
kubectl get endpoints svc-$ALLOCATION_ID -n $NAMESPACE
echo ""

# 6. 检查 Traefik
echo "6. 检查 Traefik Ingress Controller:"
kubectl get pods -n kube-system | grep traefik
kubectl get svc -n kube-system traefik
echo ""

# 7. 检查 Pod 日志（最后20行）
echo "7. Pod 日志（最后20行）:"
kubectl logs $POD_NAME -n $NAMESPACE --tail=20
echo ""

# 8. 检查 Jupyter 是否监听
echo "8. 检查 Jupyter 端口监听:"
kubectl exec $POD_NAME -n $NAMESPACE -- ss -lntp 2>/dev/null | grep 8888 || \
kubectl exec $POD_NAME -n $NAMESPACE -- netstat -tlnp 2>/dev/null | grep 8888 || \
echo "无法检查端口监听（容器内可能没有 ss 或 netstat）"
echo ""

# 9. 测试容器内访问
echo "9. 测试容器内访问 Jupyter:"
kubectl exec $POD_NAME -n $NAMESPACE -- curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://127.0.0.1:8888 2>&1 || echo "curl 测试失败"
echo ""

echo "=========================================="
echo "检查完成"
echo "=========================================="
echo ""
echo "如果 Ingress 不存在，请检查："
echo "1. 后端配置 INGRESS_ENABLED=true"
echo "2. 后端配置 INGRESS_HOST=platform.local"
echo "3. 后端日志中是否有 Ingress 创建错误"
echo ""
echo "如果 Ingress 存在但无法访问，请检查："
echo "1. Traefik Service 类型（应该是 NodePort 或 LoadBalancer）"
echo "2. 防火墙是否开放 80 端口"
echo "3. hosts 文件是否配置正确（如果使用 platform.local）"
echo "4. Jupyter 是否监听 0.0.0.0:8888（不是 127.0.0.1:8888）"
