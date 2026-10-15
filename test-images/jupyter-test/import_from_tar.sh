#!/bin/bash
# 从tar文件导入Jupyter测试镜像到K3s

set -e

IMAGE_NAME="jupyter-test"
IMAGE_TAG="latest"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"

echo "=== 导入Jupyter测试镜像 ==="

# 查找K3s的ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo "错误: 未找到K3s的ctr命令"
    echo "请检查K3s是否已安装"
    exit 1
fi

echo "找到ctr命令: ${CTR_PATH}"

# 检查tar文件
TAR_FILE="${1:-/tmp/${IMAGE_NAME}.tar}"

if [ ! -f "$TAR_FILE" ]; then
    echo "错误: 镜像文件不存在: ${TAR_FILE}"
    echo ""
    echo "使用方法:"
    echo "  $0 [镜像tar文件路径]"
    echo ""
    echo "示例:"
    echo "  $0 /tmp/jupyter-test.tar"
    echo "  $0 /path/to/jupyter-test.tar"
    exit 1
fi

echo "镜像文件: ${TAR_FILE}"

# 导入镜像
echo "导入镜像到K3s..."
sudo ${CTR_PATH} images import ${TAR_FILE}
echo "✓ 镜像导入完成"

# 标记镜像（确保K3s能识别）
echo "标记镜像..."
sudo ${CTR_PATH} images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
echo "✓ 镜像标记完成"

# 验证镜像
echo ""
echo "=== 验证镜像 ==="
sudo ${CTR_PATH} images ls | grep ${IMAGE_NAME} || echo "⚠ 镜像未在列表中显示，但可能已导入"

echo ""
echo "=== 完成 ==="
echo "镜像名称: ${FULL_IMAGE_NAME}"
echo "现在可以在系统中使用此镜像创建Pod进行Jupyter测试"
echo ""
echo "下一步: 运行 add_to_database.py 将镜像添加到数据库"

