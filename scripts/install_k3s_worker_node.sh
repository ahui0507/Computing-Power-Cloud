#!/bin/bash
# K3s计算节点安装脚本
# 适用于Ubuntu 20.04，支持NVIDIA Tesla K80（驱动470）
# 使用方法: sudo bash scripts/install_k3s_worker_node.sh <CONTROL_NODE_IP> <TOKEN>

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 获取参数
CONTROL_NODE_IP="${1}"
TOKEN="${2}"
USE_MIRROR="${3:-false}"

echo "=========================================="
echo "K3s 计算节点安装脚本"
echo "=========================================="
echo ""

# 检查是否为root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}错误: 请使用sudo运行此脚本${NC}"
    exit 1
fi

# 验证参数
if [ -z "$CONTROL_NODE_IP" ] || [ -z "$TOKEN" ]; then
    echo -e "${RED}错误: 缺少必需参数${NC}"
    echo ""
    echo "使用方法:"
    echo "  sudo bash scripts/install_k3s_worker_node.sh <CONTROL_NODE_IP> <TOKEN> [--mirror]"
    echo ""
    echo "参数说明:"
    echo "  CONTROL_NODE_IP: 控制节点的内网IP地址（例如: REPLACE_NODE_INTERNAL_IP）"
    echo "  TOKEN: 从控制节点获取的token"
    echo "  --mirror: 可选，使用国内镜像源（如果GitHub访问受限）"
    echo ""
    echo "获取token的方法（在控制节点上执行）:"
    echo "  sudo cat /var/lib/rancher/k3s/server/node-token"
    echo ""
    exit 1
fi

# 检查是否使用镜像
if [ "$USE_MIRROR" = "--mirror" ] || [ "$USE_MIRROR" = "mirror" ]; then
    USE_MIRROR=true
    echo -e "${YELLOW}使用国内镜像源${NC}"
fi

echo "控制节点IP: $CONTROL_NODE_IP"
echo "Token: ${TOKEN:0:20}..."
echo ""

# 1. 配置网络（设置网关）
echo -e "\n${BLUE}[1/7] 配置网络...${NC}"
GATEWAY="$CONTROL_NODE_IP"
echo "设置网关为: $GATEWAY"

# 检测当前网络配置
NETPLAN_FILE=$(ls /etc/netplan/*.yaml 2>/dev/null | head -n 1)
if [ -n "$NETPLAN_FILE" ]; then
    echo "检测到netplan配置文件: $NETPLAN_FILE"
    # 备份配置
    cp "$NETPLAN_FILE" "${NETPLAN_FILE}.bak.$(date +%s)"
    
    # 检查是否已配置网关
    if grep -q "gateway4:.*$GATEWAY" "$NETPLAN_FILE" 2>/dev/null; then
        echo -e "${GREEN}✓ 网关已配置为 $GATEWAY${NC}"
    else
        echo -e "${YELLOW}注意: 请手动编辑 $NETPLAN_FILE 设置网关为 $GATEWAY${NC}"
        echo "示例配置:"
        echo "  network:"
        echo "    version: 2"
        echo "    ethernets:"
        echo "      <接口名>:"
        echo "        addresses:"
        echo "          - <当前IP>/24"
        echo "        gateway4: $GATEWAY"
        echo "        nameservers:"
        echo "          addresses: [8.8.8.8, 8.8.4.4]"
        echo ""
        read -p "是否已配置网关? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}请先配置网关，然后重新运行此脚本${NC}"
            exit 0
        fi
    fi
else
    echo -e "${YELLOW}未检测到netplan配置，请手动配置网络${NC}"
fi

# 验证网络连通性
echo "验证网络连通性..."
if ping -c 1 -W 2 "$GATEWAY" &>/dev/null; then
    echo -e "${GREEN}✓ 可以ping通控制节点 $GATEWAY${NC}"
else
    echo -e "${RED}✗ 无法ping通控制节点 $GATEWAY${NC}"
    echo "请检查网络配置"
    exit 1
fi

# 测试外网连接（验证NAT）
if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
    echo -e "${GREEN}✓ 可以访问外网（NAT功能正常）${NC}"
else
    echo -e "${YELLOW}⚠ 无法访问外网，请检查控制节点NAT配置${NC}"
fi

# 2. 更新系统
echo -e "\n${BLUE}[2/7] 更新系统包...${NC}"
apt-get update
apt-get install -y curl wget

# 3. 安装NVIDIA驱动（Tesla K80需要470版本）
echo -e "\n${BLUE}[3/7] 检查并安装NVIDIA驱动...${NC}"

if command -v nvidia-smi &> /dev/null; then
    DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n 1)
    echo -e "${GREEN}✓ NVIDIA驱动已安装，版本: $DRIVER_VERSION${NC}"
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
else
    echo -e "${YELLOW}开始安装NVIDIA驱动（Tesla K80需要470版本）...${NC}"
    
    # 检查GPU硬件
    if ! lspci | grep -i nvidia &>/dev/null; then
        echo -e "${YELLOW}未检测到NVIDIA GPU硬件，跳过驱动安装${NC}"
    else
        echo "检测到NVIDIA GPU，开始安装驱动..."
        
        # 安装内核头文件和编译工具
        CURRENT_KERNEL=$(uname -r)
        echo "安装内核头文件和编译工具（内核版本: $CURRENT_KERNEL）..."
        apt-get install -y linux-headers-${CURRENT_KERNEL} \
                            linux-headers-generic \
                            build-essential \
                            dkms \
                            ubuntu-drivers-common
        
        # 禁用nouveau
        echo "禁用nouveau驱动..."
        cat > /etc/modprobe.d/blacklist-nouveau.conf <<EOF
blacklist nouveau
options nouveau modeset=0
EOF
        modprobe -r nouveau 2>/dev/null || true
        update-initramfs -u
        
        # 安装470驱动
        echo "安装NVIDIA驱动470（Tesla K80 Legacy驱动）..."
        
        # 检查驱动包是否可用
        if apt-cache search nvidia-driver-470 | grep -q "^nvidia-driver-470"; then
            echo "从仓库安装nvidia-driver-470..."
            if apt-get install -y nvidia-driver-470; then
                echo -e "${GREEN}✓ 驱动安装成功${NC}"
            else
                echo -e "${YELLOW}⚠ 从仓库安装失败，尝试其他方法...${NC}"
                INSTALL_FAILED=true
            fi
        else
            echo -e "${YELLOW}⚠ 仓库中未找到nvidia-driver-470包${NC}"
            INSTALL_FAILED=true
        fi
        
        if [ "${INSTALL_FAILED:-false}" = "true" ]; then
            echo -e "${RED}从仓库安装失败，请从NVIDIA官网下载470驱动安装包${NC}"
            echo "下载地址: https://www.nvidia.com/Download/index.aspx"
            echo "选择: Product Type: Tesla, Product Series: K-Series, Product: Tesla K80"
            echo ""
            read -p "是否已下载驱动安装包？(y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                read -p "请输入驱动安装包路径: " DRIVER_PATH
                if [ -f "$DRIVER_PATH" ]; then
                    chmod +x "$DRIVER_PATH"
                    echo "运行驱动安装包..."
                    if "$DRIVER_PATH" --silent --no-opengl-files --dkms; then
                        echo -e "${GREEN}✓ 驱动安装成功${NC}"
                    else
                        echo -e "${RED}✗ 驱动安装失败${NC}"
                        exit 1
                    fi
                else
                    echo -e "${RED}文件不存在: $DRIVER_PATH${NC}"
                    exit 1
                fi
            else
                echo -e "${YELLOW}请稍后手动安装驱动，然后重新运行此脚本${NC}"
                exit 0
            fi
        fi
        
        # 验证驱动模块是否已构建
        echo "检查驱动模块..."
        if lsmod | grep -q nvidia; then
            echo -e "${GREEN}✓ NVIDIA驱动模块已加载${NC}"
            # 尝试运行nvidia-smi
            if nvidia-smi &>/dev/null; then
                echo -e "${GREEN}✓ nvidia-smi可以正常运行，无需重启${NC}"
            else
                echo -e "${YELLOW}⚠ nvidia-smi无法运行，需要重启系统${NC}"
                NEED_REBOOT=true
            fi
        else
            echo -e "${YELLOW}⚠ 驱动模块未加载，需要重启系统${NC}"
            NEED_REBOOT=true
        fi
        
        if [ "${NEED_REBOOT:-false}" = "true" ]; then
            echo ""
            echo -e "${YELLOW}驱动安装完成，需要重启系统才能生效${NC}"
            read -p "是否现在重启系统? (y/N): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                echo "重启系统..."
                reboot
            else
                echo -e "${YELLOW}请稍后手动重启系统，然后继续运行此脚本${NC}"
                exit 0
            fi
        fi
    fi
fi

# 4. 安装K3s Agent
echo -e "\n${BLUE}[4/7] 安装K3s Agent并加入集群...${NC}"

# 检查是否已经安装
if command -v k3s &> /dev/null; then
    echo -e "${YELLOW}检测到K3s已安装，是否重新安装？(y/N)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "已取消"
        exit 0
    fi
    /usr/local/bin/k3s-agent-uninstall.sh || true
fi

# 设置环境变量
export K3S_URL="https://${CONTROL_NODE_IP}:6443"
export K3S_TOKEN="$TOKEN"

# 安装K3s Agent
install_k3s_agent() {
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        if [ "$USE_MIRROR" = "true" ]; then
            echo -e "${YELLOW}尝试使用国内镜像源安装（第 $((retry_count + 1)) 次）...${NC}"
            curl -sfL --connect-timeout 30 --max-time 300 \
                https://get.k3s.io | \
                INSTALL_K3S_MIRROR=cn \
                INSTALL_K3S_EXEC="agent" sh - && return 0
        else
            echo -e "${YELLOW}尝试安装（第 $((retry_count + 1)) 次）...${NC}"
            curl -sfL --connect-timeout 30 --max-time 300 \
                https://get.k3s.io | \
                INSTALL_K3S_EXEC="agent" sh - && return 0
        fi
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $max_retries ]; then
            echo -e "${YELLOW}安装失败，等待5秒后重试...${NC}"
            sleep 5
        fi
    done
    
    echo -e "${RED}安装失败，已重试 $max_retries 次${NC}"
    return 1
}

if ! install_k3s_agent; then
    echo -e "${RED}K3s Agent安装失败${NC}"
    echo "请检查网络连接或使用 --mirror 参数"
    exit 1
fi

# 5. 等待服务启动
echo -e "\n${BLUE}[5/7] 等待K3s Agent服务启动...${NC}"
echo "这可能需要30-60秒，请耐心等待..."

max_wait=120
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    if systemctl is-active --quiet k3s-agent; then
        echo -e "${GREEN}✓ K3s Agent服务已启动${NC}"
        break
    fi
    
    if systemctl is-failed --quiet k3s-agent; then
        echo -e "${RED}✗ K3s Agent服务启动失败${NC}"
        journalctl -u k3s-agent -n 50 --no-pager
        exit 1
    fi
    
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $((elapsed % 15)) -eq 0 ]; then
        echo "  已等待 ${elapsed} 秒..."
    fi
done

if ! systemctl is-active --quiet k3s-agent; then
    echo -e "${RED}✗ K3s Agent服务启动超时${NC}"
    journalctl -u k3s-agent -n 100 --no-pager
    exit 1
fi

# 验证连接（检查日志中是否有连接成功的迹象）
echo "检查连接状态..."
sleep 5
if journalctl -u k3s-agent --since "1 minute ago" | grep -q "Node.*is ready"; then
    echo -e "${GREEN}✓ 节点已成功加入集群${NC}"
elif journalctl -u k3s-agent --since "1 minute ago" | grep -qi "error\|failed"; then
    echo -e "${YELLOW}⚠ 检测到错误信息，请检查日志${NC}"
    journalctl -u k3s-agent -n 20 --no-pager | grep -iE "error|failed" | tail -n 5
else
    echo -e "${YELLOW}⚠ 节点可能仍在连接中，请在控制节点验证: kubectl get nodes${NC}"
fi

# 6. 安装NVIDIA Container Toolkit（如果有GPU）
echo -e "\n${BLUE}[6/7] 安装NVIDIA Container Toolkit...${NC}"

if command -v nvidia-smi &> /dev/null; then
    echo -e "${GREEN}检测到NVIDIA GPU${NC}"
    
    if ! command -v nvidia-container-runtime &> /dev/null; then
        echo "开始安装NVIDIA Container Toolkit..."
        
        # 获取系统版本
        distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
        
        # 安装NVIDIA Container Toolkit的函数
        install_nvidia_toolkit() {
            local max_retries=3
            local retry_count=0
            local success=false
            
            # 如果使用镜像模式，优先使用国内镜像
            if [ "$USE_MIRROR" = "true" ]; then
                echo -e "${YELLOW}使用国内镜像源（中科大镜像）${NC}"
                # 使用中科大镜像源
                local gpg_urls=(
                    "https://mirrors.ustc.edu.cn/libnvidia-container/gpgkey"
                    "https://nvidia.github.io/libnvidia-container/gpgkey"
                )
                
                local repo_urls=(
                    "https://mirrors.ustc.edu.cn/libnvidia-container/stable/deb/nvidia-container-toolkit.list"
                    "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list"
                )
            else
                # GPG密钥URL列表（备用）
                local gpg_urls=(
                    "https://nvidia.github.io/libnvidia-container/gpgkey"
                    "https://mirrors.ustc.edu.cn/libnvidia-container/gpgkey"
                )
                
                # 仓库URL列表（备用，优先使用官方，失败后使用中科大镜像）
                local repo_urls=(
                    "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list"
                    "https://mirrors.ustc.edu.cn/libnvidia-container/stable/deb/nvidia-container-toolkit.list"
                )
            fi
            
            mkdir -p /usr/share/keyrings
            
            # 尝试下载GPG密钥
            echo "下载GPG密钥..."
            for url in "${gpg_urls[@]}"; do
                for ((i=1; i<=max_retries; i++)); do
                    echo "尝试从 $url 下载GPG密钥（第 $i 次）..."
                    if curl -fsSL --connect-timeout 30 --max-time 60 "$url" | \
                        gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null; then
                        echo -e "${GREEN}✓ GPG密钥下载成功${NC}"
                        success=true
                        break 2
                    fi
                    
                    # 尝试备用方法（直接添加到apt-key）
                    if curl -fsSL --connect-timeout 30 --max-time 60 "$url" 2>/dev/null | \
                        apt-key add - 2>/dev/null; then
                        echo -e "${GREEN}✓ GPG密钥添加成功（使用apt-key）${NC}"
                        # 创建一个空文件作为标记
                        touch /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
                        success=true
                        break 2
                    fi
                    
                    if [ $i -lt $max_retries ]; then
                        echo -e "${YELLOW}下载失败，等待5秒后重试...${NC}"
                        sleep 5
                    fi
                done
            done
            
            if [ "$success" != "true" ]; then
                echo -e "${YELLOW}⚠ 无法自动下载GPG密钥${NC}"
                echo ""
                echo "由于网络限制，无法连接到NVIDIA官方仓库。"
                echo "请选择以下方式之一："
                echo ""
                echo "方式1：使用中科大镜像（推荐，适合国内网络）"
                echo "  在有网络访问的机器上运行:"
                echo "  curl -fsSL https://mirrors.ustc.edu.cn/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
                echo "  或者手动下载后传输到当前机器："
                echo "  1. curl -fsSL https://mirrors.ustc.edu.cn/libnvidia-container/gpgkey -o /tmp/nvidia-gpgkey"
                echo "  2. 传输文件到当前机器"
                echo "  3. sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg < /tmp/nvidia-gpgkey"
                echo ""
                echo "方式2：使用NVIDIA官方源（需要网络访问）"
                echo "  1. 在有网络访问的机器上下载:"
                echo "     curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey -o /tmp/nvidia-gpgkey"
                echo "  2. 将文件传输到当前机器"
                echo "  3. 运行: sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg < /tmp/nvidia-gpgkey"
                echo ""
                echo "方式3：跳过GPG验证（不推荐，安全性较低）"
                echo "  使用中科大镜像（推荐）:"
                echo "  echo 'deb [trusted=yes] https://mirrors.ustc.edu.cn/libnvidia-container/stable/deb/\$(ARCH) /' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list"
                echo ""
                read -p "是否已手动下载并配置GPG密钥？(y/N): " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    echo -e "${YELLOW}跳过NVIDIA Container Toolkit安装${NC}"
                    echo "您可以在网络环境改善后手动安装，或稍后使用其他方式安装"
                    return 1
                fi
                
                # 检查用户是否已经配置了密钥
                if [ ! -f /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg ] || \
                   [ ! -s /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg ]; then
                    echo -e "${YELLOW}未检测到有效的GPG密钥，将使用不验证的方式配置仓库${NC}"
                    # 使用trusted=yes的方式
                    USE_UNTRUSTED=true
                fi
            fi
            
            # 添加仓库
            echo "配置APT仓库..."
            if [ "${USE_UNTRUSTED:-false}" = "true" ]; then
                # 使用不验证的方式，优先使用中科大镜像
                if [ "$USE_MIRROR" = "true" ] || echo "${repo_urls[0]}" | grep -q "ustc.edu.cn"; then
                    ARCH=$(dpkg --print-architecture)
                    echo "deb [trusted=yes] https://mirrors.ustc.edu.cn/libnvidia-container/stable/deb/${ARCH} /" | \
                        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                    echo -e "${GREEN}✓ 使用中科大镜像（无GPG验证）${NC}"
                else
                    echo "deb [trusted=yes] https://nvidia.github.io/libnvidia-container/stable/${distribution}/$(dpkg --print-architecture) /" | \
                        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                    echo -e "${YELLOW}⚠ 使用默认仓库（无GPG验证）${NC}"
                fi
            else
                # 尝试下载仓库配置
                success=false
                for url in "${repo_urls[@]}"; do
                    for ((i=1; i<=max_retries; i++)); do
                        echo "尝试从 $url 下载仓库配置（第 $i 次）..."
                        
                        # 下载仓库配置文件
                        repo_config=$(curl -fsSL --connect-timeout 30 --max-time 60 "$url" 2>/dev/null)
                        if [ $? -eq 0 ] && [ -n "$repo_config" ]; then
                            # 检查是否是list文件格式（包含deb行）
                            if echo "$repo_config" | grep -q "^deb "; then
                                # 处理list文件，添加GPG密钥签名
                                echo "$repo_config" | \
                                    sed "s#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g" | \
                                    tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
                                echo -e "${GREEN}✓ 仓库配置成功${NC}"
                                success=true
                                break 2
                            fi
                        fi
                        
                        if [ $i -lt $max_retries ]; then
                            echo -e "${YELLOW}下载失败，等待5秒后重试...${NC}"
                            sleep 5
                        fi
                    done
                done
                
                if [ "$success" != "true" ]; then
                    echo -e "${YELLOW}⚠ 无法自动下载仓库配置，使用默认配置${NC}"
                    ARCH=$(dpkg --print-architecture)
                    # 优先使用中科大镜像
                    if [ "$USE_MIRROR" = "true" ]; then
                        echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://mirrors.ustc.edu.cn/libnvidia-container/stable/deb/${ARCH} /" | \
                            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                    else
                        echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/${distribution}/${ARCH} /" | \
                            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
                    fi
                fi
            fi
            
            # 更新并安装
            echo "更新APT包索引..."
            if ! apt-get update 2>&1 | grep -v "^W:.*InRelease\|^W:.*Release.gpg"; then
                echo -e "${GREEN}✓ APT更新成功${NC}"
            else
                echo -e "${YELLOW}⚠ APT更新时出现警告，继续安装...${NC}"
            fi
            
            echo "安装nvidia-container-toolkit..."
            if apt-get install -y nvidia-container-toolkit; then
                echo -e "${GREEN}✓ NVIDIA Container Toolkit安装成功${NC}"
                return 0
            else
                echo -e "${RED}✗ 安装失败${NC}"
                return 1
            fi
        }
        
        if ! install_nvidia_toolkit; then
            echo -e "${YELLOW}⚠ NVIDIA Container Toolkit安装失败或已跳过${NC}"
            echo ""
            echo "您可以选择："
            echo "1. 检查网络连接后重新运行脚本"
            echo "2. 手动安装（参考: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html）"
            echo "3. 稍后通过其他方式安装"
            echo ""
            read -p "是否继续执行后续步骤（跳过NVIDIA Container Toolkit）？(y/N): " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                echo "安装已取消"
                exit 0
            fi
            TOOLKIT_INSTALLED=false
        else
            TOOLKIT_INSTALLED=true
        fi
        
        # 只有在成功安装Toolkit后才配置containerd
        if [ "$TOOLKIT_INSTALLED" = "true" ] && command -v nvidia-ctk &> /dev/null; then
            # 配置containerd
            echo "配置containerd使用NVIDIA运行时..."
            if nvidia-ctk runtime configure --runtime=containerd 2>/dev/null; then
                echo -e "${GREEN}✓ containerd配置成功${NC}"
            else
                echo -e "${YELLOW}⚠ containerd配置失败，尝试手动配置...${NC}"
                # 尝试手动配置
                if command -v nvidia-container-runtime &> /dev/null; then
                    echo "检测到nvidia-container-runtime，但配置工具失败"
                    echo "请手动运行: sudo nvidia-ctk runtime configure --runtime=containerd"
                fi
            fi
            
            # 重启containerd（如果已安装）
            if systemctl list-units --type=service | grep -q containerd.service; then
                echo "重启containerd..."
                systemctl restart containerd 2>/dev/null || true
                sleep 3
                
                # 验证containerd配置
                if [ -f /etc/containerd/config.toml ] && grep -q "nvidia" /etc/containerd/config.toml 2>/dev/null; then
                    echo -e "${GREEN}✓ containerd已配置NVIDIA运行时${NC}"
                else
                    echo -e "${YELLOW}⚠ 警告: 无法验证containerd配置${NC}"
                fi
            fi
            
            # 重启K3s Agent
            echo "重启K3s Agent以应用GPU配置..."
            systemctl restart k3s-agent
            sleep 5
            
            if systemctl is-active --quiet k3s-agent; then
                echo -e "${GREEN}✓ K3s Agent已重启${NC}"
            else
                echo -e "${YELLOW}⚠ 警告: K3s Agent可能未正常启动${NC}"
                journalctl -u k3s-agent -n 20 --no-pager
            fi
            
            echo -e "${GREEN}✓ NVIDIA Container Toolkit配置完成${NC}"
        else
            echo -e "${YELLOW}⚠ 跳过containerd配置（NVIDIA Container Toolkit未安装）${NC}"
        fi
    else
        echo -e "${GREEN}✓ NVIDIA Container Toolkit已安装${NC}"
    fi
else
    echo "未检测到NVIDIA GPU，跳过Container Toolkit安装"
fi

# 7. 显示节点信息
echo -e "\n${BLUE}[7/7] 节点信息${NC}"
echo ""
echo -e "${GREEN}=========================================="
echo "K3s计算节点安装完成！"
echo "==========================================${NC}"
echo ""
echo "节点信息:"
echo "  节点名称: $(hostname)"
echo "  节点IP: $(hostname -I | awk '{print $1}')"
echo "  CPU核心数: $(nproc)"
echo "  内存: $(free -h | awk '/^Mem:/{print $2}')"

if command -v nvidia-smi &> /dev/null; then
    echo "  GPU数量: $(nvidia-smi -L | wc -l)"
    echo "  GPU信息:"
    nvidia-smi --query-gpu=index,name,driver_version,memory.total --format=csv,noheader | sed 's/^/    /'
fi

echo ""
echo -e "${YELLOW}下一步操作:${NC}"
echo "1. 在控制节点上验证节点状态:"
echo "   kubectl get nodes -o wide"
echo ""
if command -v nvidia-smi &> /dev/null; then
    echo "2. 在控制节点上部署NVIDIA Device Plugin:"
    echo "   kubectl apply -f deploy/kubernetes/cluster/nvidia-device-plugin.yaml"
    echo ""
    echo "3. 等待Device Plugin启动（约30秒）:"
    echo "   kubectl get pods -n kube-system | grep nvidia"
    echo ""
    echo "4. 验证GPU资源可见性:"
    echo "   kubectl describe node $(hostname) | grep nvidia.com/gpu"
    echo ""
fi
echo "5. 测试网络连接（验证NAT功能）:"
echo "   ping -c 3 8.8.8.8"
echo ""
echo "6. 验证DNS解析:"
echo "   nslookup github.com"
echo ""

