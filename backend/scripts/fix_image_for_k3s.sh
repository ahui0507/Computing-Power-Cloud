#!/bin/bash
# 修复镜像标签，确保K3s能正确识别jupyter-test:latest

echo "=========================================="
echo "修复jupyter-test镜像标签（K3s专用）"
echo "=========================================="
echo ""

# 查找ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo "❌ 无法找到ctr命令"
    exit 1
fi

echo "使用ctr路径: $CTR_PATH"
echo ""

# 1. 检查当前镜像
echo "1. 检查当前镜像:"
sudo $CTR_PATH images ls | grep -i jupyter-test

echo ""
echo "2. 修复镜像标签:"

# 尝试多种可能的源镜像名称
SOURCE_IMAGES=(
    "docker.io/library/jupyter-test:latest"
    "docker.io/jupyter-test:latest"
    "jupyter-test:latest"
)

TARGET_IMAGE="jupyter-test:latest"

# 查找实际存在的镜像
FOUND_SOURCE=""
for src in "${SOURCE_IMAGES[@]}"; do
    if sudo $CTR_PATH images ls | grep -q "$src"; then
        FOUND_SOURCE="$src"
        echo "   找到源镜像: $src"
        break
    fi
done

if [ -z "$FOUND_SOURCE" ]; then
    echo "   ❌ 未找到jupyter-test镜像"
    echo "   请先运行导入脚本:"
    echo "   cd test-images/jupyter-test"
    echo "   sudo ./build_and_import.sh"
    exit 1
fi

# 添加短名称标签
echo "   添加标签: $TARGET_IMAGE"
if sudo $CTR_PATH images tag "$FOUND_SOURCE" "$TARGET_IMAGE" 2>/dev/null; then
    echo "   ✅ 标签添加成功"
else
    echo "   ⚠️  标签可能已存在，继续..."
fi

# 3. 验证所有标签
echo ""
echo "3. 验证镜像标签:"
echo "   所有jupyter-test相关镜像:"
sudo $CTR_PATH images ls | grep -i jupyter-test

echo ""
echo "4. 测试镜像是否可用:"
# 检查镜像是否可以inspect
if sudo $CTR_PATH images inspect "$TARGET_IMAGE" >/dev/null 2>&1; then
    echo "   ✅ 镜像 $TARGET_IMAGE 可以正常访问"
else
    echo "   ⚠️  镜像 $TARGET_IMAGE 无法访问，尝试使用完整名称"
    echo "   可能需要使用: $FOUND_SOURCE"
fi

echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo ""
echo "如果Pod仍然无法找到镜像，可能需要："
echo "1. 检查Pod使用的镜像名称是否与标签一致"
echo "2. 确保镜像在所有节点上都已导入（如果是多节点集群）"
echo "3. 重启kubelet（如果需要）: sudo systemctl restart k3s"
echo ""

