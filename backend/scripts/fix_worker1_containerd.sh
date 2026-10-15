#!/bin/bash
# 修复 worker1 containerd 配置脚本
# 此脚本需要在 worker1 节点上运行

set -e

echo "============================================================"
echo "修复 worker1 containerd NVIDIA 运行时配置"
echo "============================================================"
echo ""

# 1. 检查 NVIDIA Container Runtime
echo "1. 检查 NVIDIA Container Runtime:"
echo ""
if which nvidia-container-runtime &>/dev/null; then
    echo "✓ nvidia-container-runtime 已安装: $(which nvidia-container-runtime)"
    nvidia-container-runtime --version 2>/dev/null || echo "无法获取版本"
else
    echo "✗ nvidia-container-runtime 未安装"
    echo ""
    echo "安装 NVIDIA Container Runtime..."
    distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
    curl -s -L https://nvidia.github.io/nvidia-container-runtime/gpgkey | sudo apt-key add -
    curl -s -L https://nvidia.github.io/nvidia-container-runtime/$distribution/nvidia-container-runtime.list | sudo tee /etc/apt/sources.list.d/nvidia-container-runtime.list
    sudo apt-get update
    sudo apt-get install -y nvidia-container-runtime
fi
echo ""

# 2. 检查 containerd 配置
echo "2. 检查 containerd 配置:"
echo ""
CONFIG_FILE="/etc/containerd/config.toml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "✗ 配置文件不存在，创建默认配置..."
    sudo mkdir -p /etc/containerd
    sudo containerd config default | sudo tee $CONFIG_FILE > /dev/null 2>&1 || {
        echo "无法生成默认配置，手动创建..."
        sudo tee $CONFIG_FILE > /dev/null <<EOF
version = 2
EOF
    }
fi

# 备份配置
sudo cp $CONFIG_FILE ${CONFIG_FILE}.backup.$(date +%Y%m%d_%H%M%S)
echo "✓ 已备份配置文件"
echo ""

# 检查是否已配置 NVIDIA 运行时
if grep -q "runtimes.nvidia" $CONFIG_FILE; then
    echo "✓ 已找到 NVIDIA 运行时配置"
    echo ""
    echo "当前配置:"
    grep -A 5 "runtimes.nvidia" $CONFIG_FILE
    echo ""
else
    echo "⚠ 未找到 NVIDIA 运行时配置，需要添加"
    echo ""
fi

# 3. 提供配置指导
echo "3. 配置指导:"
echo ""
echo "请编辑配置文件: sudo nano $CONFIG_FILE"
echo ""
echo "确保包含以下配置:"
echo ""
cat <<'EOF'
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes]
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
    runtime_type = "io.containerd.runc.v2"
    [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
      SystemdCgroup = true
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia]
    runtime_type = "io.containerd.runc.v2"
    [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.nvidia.options]
      BinaryName = "/usr/bin/nvidia-container-runtime"
      SystemdCgroup = true
EOF
echo ""

# 4. 检查 GPU 设备
echo "4. 检查 GPU 设备:"
echo ""
if ls /dev/nvidia* &>/dev/null; then
    echo "✓ GPU 设备文件存在"
    ls -la /dev/nvidia* | head -5
else
    echo "✗ 未找到 GPU 设备文件"
fi
echo ""

# 5. 检查驱动
echo "5. 检查 NVIDIA 驱动:"
echo ""
if nvidia-smi &>/dev/null; then
    echo "✓ NVIDIA 驱动正常"
    nvidia-smi --query-gpu=count --format=csv,noheader | head -1
    echo "个 GPU"
else
    echo "✗ nvidia-smi 不可用"
fi
echo ""

echo "============================================================"
echo "配置完成后，执行:"
echo "  sudo systemctl restart k3s-agent"
echo "============================================================"













