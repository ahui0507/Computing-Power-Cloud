#!/bin/bash
# K3s控制节点安装脚本
# 适用于Ubuntu 20.04
# 使用方法: sudo bash scripts/install_k3s_control_node.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 配置参数
EXTERNAL_IP="REPLACE_NODE_INTERNAL_IP"      # 外网IP
INTERNAL_IP="REPLACE_NODE_INTERNAL_IP"      # 内网IP
INTERNAL_NETWORK="REPLACE_NODE_INTERNAL_IP/24"  # 内网网段

echo "=========================================="
echo "K3s 控制节点安装脚本"
echo "=========================================="
echo ""
echo "配置信息:"
echo "  外网IP: $EXTERNAL_IP"
echo "  内网IP: $INTERNAL_IP"
echo "  内网网段: $INTERNAL_NETWORK"
echo ""

# 检查是否为root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}错误: 请使用sudo运行此脚本${NC}"
    exit 1
fi

# 1. 检测网络接口
echo -e "\n${BLUE}[1/8] 检测网络接口...${NC}"
EXTERNAL_IFACE=$(ip route | grep default | awk '{print $5}' | head -n 1)

# 更准确地检测内网接口
INTERNAL_IFACE=$(ip -4 addr show | grep -B 2 "$INTERNAL_IP" | grep -oP '^\d+: \K[^:]+' | head -n 1)

if [ -z "$INTERNAL_IFACE" ]; then
    echo -e "${YELLOW}警告: 未找到内网IP $INTERNAL_IP 对应的接口${NC}"
    echo "当前网络接口:"
    ip -4 addr show | grep -E '^[0-9]+:' | awk '{print $2}' | sed 's/:$//'
    echo ""
    read -p "请手动指定内网接口名称 (例如: eno2, ens33): " INTERNAL_IFACE
    if [ -z "$INTERNAL_IFACE" ]; then
        echo -e "${RED}错误: 必须指定内网接口名称${NC}"
        exit 1
    fi
fi

# 验证接口存在
if ! ip link show "$INTERNAL_IFACE" &>/dev/null; then
    echo -e "${RED}错误: 接口 $INTERNAL_IFACE 不存在${NC}"
    exit 1
fi

# 验证IP地址在接口上
if ! ip -4 addr show "$INTERNAL_IFACE" | grep -q "$INTERNAL_IP"; then
    echo -e "${YELLOW}警告: 接口 $INTERNAL_IFACE 上未找到IP $INTERNAL_IP${NC}"
    echo "接口 $INTERNAL_IFACE 的IP地址:"
    ip -4 addr show "$INTERNAL_IFACE" | grep 'inet ' || echo "  无IP地址"
fi

echo "外网接口: $EXTERNAL_IFACE"
echo "内网接口: $INTERNAL_IFACE"

# 2. 配置系统NAT转发
echo -e "\n${BLUE}[2/8] 配置系统NAT转发...${NC}"

# 启用IP转发
echo "启用IP转发..."
echo 1 > /proc/sys/net/ipv4/ip_forward
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
sysctl -p > /dev/null

# 配置iptables NAT规则
echo "配置iptables NAT规则..."
iptables -t nat -C POSTROUTING -o "$EXTERNAL_IFACE" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -o "$EXTERNAL_IFACE" -j MASQUERADE

iptables -C FORWARD -i "$INTERNAL_IFACE" -o "$EXTERNAL_IFACE" -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i "$INTERNAL_IFACE" -o "$EXTERNAL_IFACE" -j ACCEPT

iptables -C FORWARD -i "$EXTERNAL_IFACE" -o "$INTERNAL_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i "$EXTERNAL_IFACE" -o "$INTERNAL_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT

# 保存iptables规则（Ubuntu 20.04）
if command -v netfilter-persistent &> /dev/null; then
    netfilter-persistent save
else
    echo "安装iptables-persistent以保存规则..."
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
    netfilter-persistent save
fi

# 验证配置
echo "验证NAT配置..."
if [ "$(cat /proc/sys/net/ipv4/ip_forward)" = "1" ]; then
    echo -e "${GREEN}✓ IP转发已启用${NC}"
else
    echo -e "${RED}✗ IP转发未启用${NC}"
    exit 1
fi

if iptables -t nat -C POSTROUTING -o "$EXTERNAL_IFACE" -j MASQUERADE 2>/dev/null; then
    echo -e "${GREEN}✓ NAT规则已配置${NC}"
else
    echo -e "${RED}✗ NAT规则配置失败${NC}"
    exit 1
fi

echo -e "${GREEN}✓ NAT转发配置完成${NC}"

# 3. 更新系统
echo -e "\n${BLUE}[3/8] 更新系统包...${NC}"
apt-get update
apt-get install -y curl wget

# 4. 安装K3s
echo -e "\n${BLUE}[4/8] 安装K3s...${NC}"

# 创建K3s配置目录
mkdir -p /etc/rancher/k3s

# 创建K3s配置文件
cat > /etc/rancher/k3s/config.yaml <<EOF
node-ip: $INTERNAL_IP
flannel-iface: $INTERNAL_IFACE
disable-network-policy: true
EOF

echo "K3s配置文件内容:"
cat /etc/rancher/k3s/config.yaml

# 安装K3s
echo "开始安装K3s..."
curl -sfL https://get.k3s.io | sh -

# 5. 等待K3s启动
echo -e "\n${BLUE}[5/8] 等待K3s服务启动...${NC}"
echo "这可能需要30-60秒，请耐心等待..."

max_wait=120
elapsed=0
while [ $elapsed -lt $max_wait ]; do
    if systemctl is-active --quiet k3s; then
        echo -e "${GREEN}✓ K3s服务已启动${NC}"
        break
    fi
    
    if systemctl is-failed --quiet k3s; then
        echo -e "${RED}✗ K3s服务启动失败${NC}"
        echo "查看日志:"
        journalctl -u k3s -n 50 --no-pager
        exit 1
    fi
    
    sleep 5
    elapsed=$((elapsed + 5))
    if [ $((elapsed % 15)) -eq 0 ]; then
        echo "  已等待 ${elapsed} 秒..."
    fi
done

if ! systemctl is-active --quiet k3s; then
    echo -e "${RED}✗ K3s服务启动超时${NC}"
    journalctl -u k3s -n 100 --no-pager
    exit 1
fi

# 6. 配置kubectl
echo -e "\n${BLUE}[6/8] 配置kubectl...${NC}"

# 为root用户配置
mkdir -p ~/.kube
cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config

# 修改server地址为内网IP
sed -i "s/127.0.0.1/$INTERNAL_IP/g" ~/.kube/config

# 为当前登录用户配置（如果不是root）
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    USER_HOME=$(eval echo ~$SUDO_USER)
    mkdir -p "$USER_HOME/.kube"
    cp /etc/rancher/k3s/k3s.yaml "$USER_HOME/.kube/config"
    chown "$SUDO_USER:$SUDO_USER" "$USER_HOME/.kube/config"
    chmod 600 "$USER_HOME/.kube/config"
    sed -i "s/127.0.0.1/$INTERNAL_IP/g" "$USER_HOME/.kube/config"
    echo -e "${GREEN}✓ 已为用户 $SUDO_USER 配置kubectl${NC}"
fi

# 验证kubectl配置
if kubectl get nodes &>/dev/null; then
    echo -e "${GREEN}✓ kubectl配置完成并验证成功${NC}"
else
    echo -e "${YELLOW}⚠ kubectl配置完成，但验证失败（可能需要等待K3s完全启动）${NC}"
fi

# 7. 配置防火墙
echo -e "\n${BLUE}[7/8] 配置防火墙...${NC}"
if command -v ufw &> /dev/null; then
    # 检查ufw状态
    if ufw status | grep -q "Status: active"; then
        ufw allow 6443/tcp comment 'K3s API'
        ufw allow 10250/tcp comment 'Kubelet'
        ufw allow 8472/udp comment 'Flannel VXLAN'
        echo -e "${GREEN}✓ 防火墙规则已添加${NC}"
    else
        echo -e "${YELLOW}ufw未激活，跳过防火墙规则配置${NC}"
    fi
else
    # 直接配置iptables规则
    echo "配置iptables规则..."
    iptables -C INPUT -p tcp --dport 6443 -j ACCEPT 2>/dev/null || \
        iptables -I INPUT -p tcp --dport 6443 -j ACCEPT
    iptables -C INPUT -p tcp --dport 10250 -j ACCEPT 2>/dev/null || \
        iptables -I INPUT -p tcp --dport 10250 -j ACCEPT
    iptables -C INPUT -p udp --dport 8472 -j ACCEPT 2>/dev/null || \
        iptables -I INPUT -p udp --dport 8472 -j ACCEPT
    echo -e "${GREEN}✓ iptables规则已添加${NC}"
fi

# 8. 显示节点信息和Token
echo -e "\n${BLUE}[8/8] 节点信息${NC}"
echo ""
echo -e "${GREEN}=========================================="
echo "K3s控制节点安装完成！"
echo "==========================================${NC}"
echo ""
# 等待kubectl可用
echo "等待K3s API就绪..."
for i in {1..12}; do
    if kubectl get nodes &>/dev/null; then
        break
    fi
    sleep 5
done

if kubectl get nodes &>/dev/null; then
    echo "节点信息:"
    kubectl get nodes -o wide
else
    echo -e "${YELLOW}警告: 无法获取节点信息，K3s可能仍在启动中${NC}"
    echo "请稍后运行: kubectl get nodes"
fi

echo ""
echo -e "${YELLOW}重要: 保存以下Token，用于计算节点加入集群${NC}"
echo "Token:"
echo "----------------------------------------"
sudo cat /var/lib/rancher/k3s/server/node-token
echo "----------------------------------------"
echo ""
echo "下一步操作:"
echo "1. 在计算节点上运行安装脚本，使用上述Token"
echo "2. 验证NAT功能: 在计算节点上测试外网连接"
echo "3. 部署NVIDIA Device Plugin（如果计算节点有GPU）:"
echo "   kubectl apply -f deploy/kubernetes/cluster/nvidia-device-plugin.yaml"
echo ""

