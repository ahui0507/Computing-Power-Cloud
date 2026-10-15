#!/bin/bash
# 修复镜像标签，确保K3s能识别

echo "=========================================="
echo "修复jupyter-test镜像标签"
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

# 检查当前镜像
echo "1. 当前镜像列表:"
sudo $CTR_PATH images ls | grep -i jupyter-test

echo ""
echo "2. 修复镜像标签:"
echo "   确保有 jupyter-test:latest 标签（不带docker.io前缀）"

# 获取镜像ID
IMAGE_ID=$(sudo $CTR_PATH images ls | grep -i "jupyter-test:latest" | awk '{print $3}' | head -1)

if [ -n "$IMAGE_ID" ]; then
    echo "   找到镜像ID: $IMAGE_ID"
    echo ""
    echo "   添加标签: jupyter-test:latest"
    sudo $CTR_PATH images tag docker.io/library/jupyter-test:latest jupyter-test:latest 2>/dev/null || \
    sudo $CTR_PATH images tag docker.io/jupyter-test:latest jupyter-test:latest 2>/dev/null || \
    echo "   ⚠️  标签已存在或无法添加"
    
    echo ""
    echo "3. 验证标签:"
    sudo $CTR_PATH images ls | grep -i jupyter-test
    
    echo ""
    echo "✅ 完成！现在Pod应该能够使用 jupyter-test:latest 找到镜像"
else
    echo "   ❌ 未找到jupyter-test镜像"
    echo "   请先运行导入脚本:"
    echo "   cd test-images/jupyter-test"
    echo "   sudo ./build_and_import.sh"
fi

