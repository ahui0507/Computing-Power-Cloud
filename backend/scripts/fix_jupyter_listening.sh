#!/bin/bash
# 修复 Jupyter 监听地址问题
# 用于临时修复 Pod 中 Jupyter 只监听 127.0.0.1 的问题

set -e

POD_NAME=$1

if [ -z "$POD_NAME" ]; then
    echo "用法: $0 <pod_name>"
    echo "示例: $0 pod-19-containe"
    exit 1
fi

NAMESPACE=${2:-default}

echo "=== 修复 Pod ${POD_NAME} 的 Jupyter 监听地址 ==="
echo ""

# 检查 Pod 是否存在
if ! kubectl get pod ${POD_NAME} -n ${NAMESPACE} &>/dev/null; then
    echo "❌ 错误: Pod ${POD_NAME} 不存在"
    exit 1
fi

# 检查 Pod 状态
POD_STATUS=$(kubectl get pod ${POD_NAME} -n ${NAMESPACE} -o jsonpath='{.status.phase}')
if [ "$POD_STATUS" != "Running" ]; then
    echo "⚠️  警告: Pod 状态为 ${POD_STATUS}，可能无法执行修复"
    echo "是否继续？(y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "步骤 1: 检查当前 Jupyter 监听状态..."
kubectl exec ${POD_NAME} -n ${NAMESPACE} -- ss -lntp 2>/dev/null | grep 8888 || echo "未找到 8888 端口监听"

echo ""
echo "步骤 2: 停止现有 Jupyter 进程..."
kubectl exec ${POD_NAME} -n ${NAMESPACE} -- bash -c "pkill -f jupyter || echo '没有找到运行的 Jupyter 进程'"

echo ""
echo "等待进程结束..."
sleep 2

echo ""
echo "步骤 3: 使用正确的参数启动 Jupyter..."
kubectl exec ${POD_NAME} -n ${NAMESPACE} -- bash -c "
    # 创建日志目录
    mkdir -p /tmp
    
    # 以后台方式启动 Jupyter
    nohup jupyter lab \\
        --ip=0.0.0.0 \\
        --port=8888 \\
        --no-browser \\
        --allow-root \\
        --notebook-dir=/workspace \\
        > /tmp/jupyter.log 2>&1 &
    
    # 等待启动
    sleep 3
    
    # 显示日志
    echo 'Jupyter 启动日志:'
    cat /tmp/jupyter.log 2>/dev/null || echo '日志文件不存在'
    
    # 检查进程
    echo ''
    echo 'Jupyter 进程:'
    ps aux | grep jupyter | grep -v grep || echo '未找到 Jupyter 进程'
"

echo ""
echo "步骤 4: 验证端口监听..."
sleep 2
kubectl exec ${POD_NAME} -n ${NAMESPACE} -- ss -lntp 2>/dev/null | grep 8888 || echo "⚠️  警告: 仍然未检测到 8888 端口"

echo ""
echo "步骤 5: 测试容器内访问..."
HTTP_CODE=$(kubectl exec ${POD_NAME} -n ${NAMESPACE} -- curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8888 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
    echo "✅ Jupyter 可以访问 (HTTP ${HTTP_CODE})"
else
    echo "⚠️  Jupyter 访问测试失败 (HTTP ${HTTP_CODE})"
fi

echo ""
echo "=== 修复完成 ==="
echo ""
echo "验证命令:"
echo "  kubectl exec ${POD_NAME} -n ${NAMESPACE} -- ss -lntp | grep 8888"
echo ""
echo "查看日志:"
echo "  kubectl exec ${POD_NAME} -n ${NAMESPACE} -- tail -f /tmp/jupyter.log"
echo ""
echo "⚠️  注意: 这是一个临时修复，Pod 重启后修改会丢失"
echo "永久修复需要修改 Dockerfile 并重新构建镜像"

