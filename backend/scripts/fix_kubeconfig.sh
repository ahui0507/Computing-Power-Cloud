#!/bin/bash
# 修复 kubeconfig 配置问题

set -e

echo "============================================================"
echo "修复 kubeconfig 配置"
echo "============================================================"
echo ""

# 1. 检查当前 KUBECONFIG 环境变量
echo "步骤 1: 检查 KUBECONFIG 环境变量..."
if [ -n "$KUBECONFIG" ]; then
    echo "当前 KUBECONFIG: $KUBECONFIG"
    echo "⚠ 环境变量指向了 /etc/rancher/k3s/k3s.yaml，需要取消设置"
    echo ""
    echo "执行以下命令取消环境变量:"
    echo "  unset KUBECONFIG"
    echo "  或者"
    echo "  export KUBECONFIG=~/.kube/config"
    echo ""
else
    echo "✓ 未设置 KUBECONFIG 环境变量"
fi
echo ""

# 2. 检查 ~/.kube/config 文件
echo "步骤 2: 检查 ~/.kube/config 文件..."
if [ -f "$HOME/.kube/config" ]; then
    echo "✓ ~/.kube/config 文件存在"
    echo "文件权限:"
    ls -la ~/.kube/config
    echo ""
    
    # 检查文件内容
    if grep -q "server:" ~/.kube/config; then
        echo "✓ 配置文件内容正常"
        echo ""
        echo "配置文件中的 server 地址:"
        grep "server:" ~/.kube/config | head -1
        echo ""
    else
        echo "✗ 配置文件内容异常"
    fi
else
    echo "✗ ~/.kube/config 文件不存在"
    echo ""
    echo "创建配置文件..."
    mkdir -p ~/.kube
    sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
    sudo chown $USER:$USER ~/.kube/config
    chmod 600 ~/.kube/config
    echo "✓ 配置文件已创建"
    echo ""
fi

# 3. 设置正确的 KUBECONFIG
echo "步骤 3: 设置 KUBECONFIG 环境变量..."
export KUBECONFIG="$HOME/.kube/config"
echo "已设置 KUBECONFIG=$HOME/.kube/config"
echo ""

# 4. 验证 kubectl
echo "步骤 4: 验证 kubectl 连接..."
if kubectl get nodes &>/dev/null; then
    echo "✓ kubectl 连接成功！"
    echo ""
    kubectl get nodes
    echo ""
    echo "============================================================"
    echo "修复完成！"
    echo "============================================================"
    echo ""
    echo "重要提示："
    echo "1. 当前会话中 KUBECONFIG 已设置"
    echo "2. 要在新会话中使用，请将以下命令添加到 ~/.bashrc:"
    echo "   export KUBECONFIG=\$HOME/.kube/config"
    echo ""
    echo "或者执行:"
    echo "   echo 'export KUBECONFIG=\$HOME/.kube/config' >> ~/.bashrc"
    echo "   source ~/.bashrc"
    echo ""
else
    echo "✗ kubectl 连接失败"
    echo ""
    echo "尝试使用 sudo kubectl:"
    sudo kubectl get nodes
    echo ""
    echo "如果 sudo kubectl 可以工作，说明配置文件权限有问题"
    echo "请检查 ~/.kube/config 的权限和内容"
fi

