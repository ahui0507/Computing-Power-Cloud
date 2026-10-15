#!/bin/bash
# 强制K3s使用本地镜像的解决方案

echo "=========================================="
echo "强制K3s使用本地jupyter-test镜像"
echo "=========================================="
echo ""

# 查找ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo "❌ 无法找到ctr命令"
    exit 1
fi

echo "1. 检查当前镜像:"
sudo $CTR_PATH images ls | grep -i jupyter-test

echo ""
echo "2. 问题分析:"
echo "   即使设置了 imagePullPolicy: IfNotPresent，"
echo "   K3s/containerd 可能仍然尝试拉取镜像，如果："
echo "   - 镜像名称格式不匹配"
echo "   - containerd 缓存问题"
echo "   - 需要重启服务"

echo ""
echo "3. 解决方案A: 重启K3s服务（推荐）"
echo "   这会刷新 containerd 的镜像缓存"
read -p "   是否重启K3s服务？(y/n): " restart_choice
if [[ "$restart_choice" =~ ^[Yy]$ ]]; then
    echo "   重启K3s..."
    sudo systemctl restart k3s
    echo "   ✅ K3s已重启"
    echo "   等待10秒让服务完全启动..."
    sleep 10
else
    echo "   跳过重启"
fi

echo ""
echo "4. 解决方案B: 确保镜像标签完全匹配"
echo "   检查镜像的所有标签:"
sudo $CTR_PATH images ls | grep -i jupyter-test | awk '{print $1}'

echo ""
echo "5. 解决方案C: 使用完整镜像名称"
echo "   如果短名称不工作，可以修改代码使用完整名称:"
echo "   docker.io/library/jupyter-test:latest"
echo "   或者: docker.io/jupyter-test:latest"

echo ""
echo "6. 验证镜像可用性:"
if sudo $CTR_PATH images inspect jupyter-test:latest >/dev/null 2>&1; then
    echo "   ✅ 镜像 jupyter-test:latest 可以正常访问"
else
    echo "   ❌ 镜像 jupyter-test:latest 无法访问"
    echo "   尝试使用完整名称:"
    if sudo $CTR_PATH images inspect docker.io/library/jupyter-test:latest >/dev/null 2>&1; then
        echo "   ✅ docker.io/library/jupyter-test:latest 可以访问"
        echo "   💡 建议：修改代码使用完整镜像名称"
    fi
fi

echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 如果重启了K3s，删除Pod并重新创建:"
echo "   kubectl delete pod pod-11-containe -n default"
echo "   然后在网页中重新申请资源"
echo ""
echo "2. 如果仍然失败，可能需要修改代码使用完整镜像名称"
echo "   或者检查 containerd 配置"

