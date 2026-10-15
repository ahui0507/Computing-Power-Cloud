#!/bin/bash
# 快速检查Jupyter连接问题的脚本

if [ -z "$1" ]; then
    echo "使用方法: $0 <container_id>"
    echo "示例: $0 container-123-abc"
    exit 1
fi

CONTAINER_ID=$1

echo "=========================================="
echo "快速检查Jupyter连接问题"
echo "=========================================="
echo ""

# 1. 从数据库获取信息（需要Python环境）
echo "1. 获取实例信息..."
python3 << EOF
import sys
sys.path.insert(0, '$(pwd)')
from app.core.database import SessionLocal
from app.models.allocation import Allocation
from app.models.node import Node

db = SessionLocal()
try:
    alloc = db.query(Allocation).filter(Allocation.container_id == "$CONTAINER_ID").first()
    if alloc:
        pod_name = f"pod-{alloc.id}-{alloc.container_id[:8]}"
        service_name = f"svc-{alloc.id}"
        node_ip = None
        if alloc.node_id:
            node = db.query(Node).filter(Node.id == alloc.node_id).first()
            if node:
                node_ip = node.ip
        
        print(f"容器ID: {alloc.container_id}")
        print(f"Pod名称: {pod_name}")
        print(f"Service名称: {service_name}")
        print(f"节点IP（数据库）: {node_ip}")
        print(f"Jupyter端口: {alloc.jupyter_port}")
        echo "访问地址: http://${node_ip}:${alloc.jupyter_port}"
    else:
        print("未找到容器ID: $CONTAINER_ID")
        sys.exit(1)
finally:
    db.close()
EOF

POD_NAME=$(python3 << EOF
import sys
sys.path.insert(0, '$(pwd)')
from app.core.database import SessionLocal
from app.models.allocation import Allocation
db = SessionLocal()
try:
    alloc = db.query(Allocation).filter(Allocation.container_id == "$CONTAINER_ID").first()
    if alloc:
        print(f"pod-{alloc.id}-{alloc.container_id[:8]}")
finally:
    db.close()
EOF
)

if [ -z "$POD_NAME" ]; then
    echo "无法获取Pod名称"
    exit 1
fi

echo ""
echo "2. 检查Pod状态..."
kubectl get pod $POD_NAME -n default 2>/dev/null || echo "Pod不存在或无法访问K8s"

echo ""
echo "3. 检查Service状态..."
SERVICE_NAME=$(echo $POD_NAME | sed 's/pod-/svc-/')
kubectl get svc $SERVICE_NAME -n default 2>/dev/null || echo "Service不存在"

echo ""
echo "4. 检查Pod日志（最后10行）..."
kubectl logs $POD_NAME -n default --tail=10 2>/dev/null || echo "无法获取日志"

echo ""
echo "5. 检查Endpoints..."
kubectl get endpoints $SERVICE_NAME -n default 2>/dev/null || echo "无法获取Endpoints"

echo ""
echo "=========================================="
echo "检查完成"
echo "=========================================="
echo ""
echo "如果Pod状态不是Running，请检查Pod事件:"
echo "  kubectl describe pod $POD_NAME -n default"
echo ""
echo "如果Service无Endpoints，请检查Pod标签:"
echo "  kubectl get pod $POD_NAME -n default --show-labels"
echo ""
echo "详细诊断请运行:"
echo "  python3 scripts/diagnose_jupyter_connection.py $CONTAINER_ID"

