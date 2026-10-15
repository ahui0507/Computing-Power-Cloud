#!/bin/bash
# 验证镜像是否已正确导入到所有节点

echo "=========================================="
echo "验证jupyter-test镜像导入状态"
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

# 检查镜像
echo "1. 检查镜像列表:"
sudo $CTR_PATH images ls | grep -i jupyter-test

echo ""
echo "2. 检查镜像详细信息:"
IMAGE_ID=$(sudo $CTR_PATH images ls | grep -i "jupyter-test:latest" | awk '{print $3}')
if [ -n "$IMAGE_ID" ]; then
    echo "   镜像ID: $IMAGE_ID"
    echo ""
    echo "   镜像详情:"
    sudo $CTR_PATH images inspect jupyter-test:latest 2>/dev/null | head -20
else
    echo "   ⚠️  未找到jupyter-test:latest镜像"
    echo ""
    echo "   请运行导入脚本:"
    echo "   cd test-images/jupyter-test"
    echo "   sudo ./build_and_import.sh"
fi

echo ""
echo "3. 验证镜像名称格式:"
echo "   Pod应该使用的镜像名称: jupyter-test:latest"
echo "   实际导入的镜像名称:"
sudo $CTR_PATH images ls | grep -i jupyter | awk '{print "      - " $1}'

echo ""
echo "=========================================="
echo "提示:"
echo "  - 确保镜像名称与Pod中使用的名称完全一致"
echo "  - 如果镜像名称不匹配，需要重新导入或修改Pod配置"
echo "=========================================="

