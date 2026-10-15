#!/bin/bash
# 快速同步镜像到worker1节点

echo "=========================================="
echo "快速同步jupyter-test镜像到worker1"
echo "=========================================="
echo ""

# 查找ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo "❌ 无法找到ctr命令"
    exit 1
fi

# 设置参数
WORKER1_IP="REPLACE_NODE_INTERNAL_IP"
SSH_USER="${K3S_SSH_USER:-test}"
TAR_FILE="/tmp/jupyter-test.tar"

echo "目标节点: ${SSH_USER}@${WORKER1_IP}"
echo ""

# 1. 检查镜像文件
if [ ! -f "$TAR_FILE" ]; then
    echo "1. 导出镜像..."
    sudo $CTR_PATH images export $TAR_FILE jupyter-test:latest 2>/dev/null || \
    sudo $CTR_PATH images export $TAR_FILE docker.io/library/jupyter-test:latest
    
    if [ ! -f "$TAR_FILE" ]; then
        echo "   ❌ 无法导出镜像"
        exit 1
    fi
    echo "   ✅ 镜像已导出"
else
    echo "1. ✅ 镜像文件已存在: $TAR_FILE"
fi

# 2. 复制到worker1
echo ""
echo "2. 复制镜像文件到 ${SSH_USER}@${WORKER1_IP}..."
scp $TAR_FILE ${SSH_USER}@${WORKER1_IP}:/tmp/ || {
    echo "   ❌ 复制失败"
    echo ""
    echo "   请手动执行:"
    echo "   scp $TAR_FILE ${SSH_USER}@${WORKER1_IP}:/tmp/"
    exit 1
}
echo "   ✅ 文件已复制"

# 3. 在worker1上导入
echo ""
echo "3. 在worker1节点上导入镜像..."
ssh ${SSH_USER}@${WORKER1_IP} "CTR_PATH=\$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1); \
                  if [ -z \"\$CTR_PATH\" ]; then \
                      echo '❌ 无法找到ctr命令'; \
                      exit 1; \
                  else \
                      echo '导入镜像...'; \
                      sudo \$CTR_PATH images import /tmp/jupyter-test.tar && \
                      echo ''; \
                      echo '检查镜像标签...'; \
                      if sudo \$CTR_PATH images ls | grep -q 'docker.io/library/jupyter-test:latest'; then \
                          echo '添加短名称标签...'; \
                          sudo \$CTR_PATH images tag docker.io/library/jupyter-test:latest jupyter-test:latest 2>/dev/null || echo '标签可能已存在'; \
                      else \
                          echo '镜像已导入为短名称，无需添加标签'; \
                      fi && \
                      echo ''; \
                      echo '✅ 镜像导入成功！'; \
                      echo ''; \
                      echo '验证镜像:'; \
                      sudo \$CTR_PATH images ls | grep jupyter-test; \
                  fi" || {
    echo "   ❌ 导入失败"
    echo ""
    echo "   请手动在worker1节点上执行:"
    echo "   ssh ${SSH_USER}@${WORKER1_IP}"
    echo "   CTR_PATH=\$(sudo find /var/lib/rancher -name ctr | head -1)"
    echo "   sudo \$CTR_PATH images import /tmp/jupyter-test.tar"
    echo "   sudo \$CTR_PATH images tag docker.io/library/jupyter-test:latest jupyter-test:latest"
    exit 1
}

echo ""
echo "=========================================="
echo "✅ 同步完成！"
echo "=========================================="
echo ""
echo "现在可以删除Pod让它重新调度:"
echo "  kubectl delete pod <pod-name> -n default"
echo ""

