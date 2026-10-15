#!/bin/bash
# 从Docker导入已构建的镜像到K3s containerd

set -e

IMAGE_NAME="${1:-jupyter-test}"
IMAGE_TAG="${2:-latest}"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"

echo "=== 从Docker导入镜像到K3s ==="
echo "镜像: ${FULL_IMAGE_NAME}"

# 检查Docker是否可用
if ! command -v docker &> /dev/null; then
    echo "错误: Docker未安装或不可用"
    exit 1
fi

if ! docker info &> /dev/null; then
    echo "错误: Docker守护进程未运行"
    exit 1
fi

# 检查镜像是否存在
if ! docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${FULL_IMAGE_NAME}$"; then
    echo "错误: Docker中不存在镜像 ${FULL_IMAGE_NAME}"
    echo ""
    echo "可用的镜像："
    docker images | head -10
    echo ""
    echo "使用方法: $0 [镜像名称] [标签]"
    echo "示例: $0 jupyter-test latest"
    exit 1
fi

echo "✓ 找到镜像: ${FULL_IMAGE_NAME}"

# 查找K3s的ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo "错误: 未找到K3s的ctr命令"
    echo "请检查K3s是否已安装"
    exit 1
fi

echo "找到ctr命令: ${CTR_PATH}"

# 导出镜像
TAR_FILE="/tmp/${IMAGE_NAME}-${IMAGE_TAG}.tar"
echo "导出镜像到 ${TAR_FILE}..."
docker save ${FULL_IMAGE_NAME} -o ${TAR_FILE}
echo "✓ 镜像导出完成"

# 导入到containerd
echo "导入镜像到K3s containerd..."
sudo ${CTR_PATH} images import ${TAR_FILE}
echo "✓ 镜像导入完成"

# 标记镜像
echo "标记镜像..."
sudo ${CTR_PATH} images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
echo "✓ 镜像标记完成"

# 验证镜像
echo ""
echo "=== 验证镜像 ==="
sudo ${CTR_PATH} images ls | grep ${IMAGE_NAME} || echo "⚠ 镜像未在列表中显示，但可能已导入"

# 清理临时文件（可选）
echo ""
echo "是否删除临时文件 ${TAR_FILE}？(y/n)"
read -r response
if [[ "$response" =~ ^[Yy]$ ]]; then
    rm -f ${TAR_FILE}
    echo "✓ 临时文件已删除"
else
    echo "临时文件保留在: ${TAR_FILE}"
fi

echo ""
echo "=== 完成 ==="
echo "镜像名称: ${FULL_IMAGE_NAME}"
echo "现在可以在系统中使用此镜像创建Pod进行Jupyter测试"
echo ""
echo "下一步: 运行 add_to_database.py 将镜像添加到数据库"

