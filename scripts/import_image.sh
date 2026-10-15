#!/bin/bash
# 通用镜像导入脚本 - 将tar格式的镜像文件导入到K3s节点
# 使用方法: sudo bash scripts/import_image.sh <镜像tar文件路径> [镜像名称:标签] [--sync-all]

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查参数
if [ $# -lt 1 ]; then
    echo -e "${RED}错误: 缺少参数${NC}"
    echo ""
    echo "使用方法:"
    echo "  sudo bash scripts/import_image.sh <镜像tar文件路径> [镜像名称:标签] [--sync-all]"
    echo ""
    echo "参数说明:"
    echo "  <镜像tar文件路径>  - 镜像压缩包的完整路径（必需）"
    echo "  [镜像名称:标签]   - 镜像名称和标签，如: myimage:latest（可选，会自动检测）"
    echo "  [--sync-all]       - 是否同步到所有节点（可选）"
    echo ""
    echo "示例:"
    echo "  sudo bash scripts/import_image.sh /tmp/myimage.tar"
    echo "  sudo bash scripts/import_image.sh /tmp/myimage.tar myimage:latest"
    echo "  sudo bash scripts/import_image.sh /tmp/myimage.tar myimage:latest --sync-all"
    exit 1
fi

TAR_FILE="$1"
IMAGE_NAME_TAG="$2"
SYNC_ALL=false

# 检查是否要同步到所有节点
if [ "$2" == "--sync-all" ] || [ "$3" == "--sync-all" ]; then
    SYNC_ALL=true
    if [ "$2" == "--sync-all" ]; then
        IMAGE_NAME_TAG=""
    fi
fi

# 检查tar文件是否存在
if [ ! -f "$TAR_FILE" ]; then
    echo -e "${RED}错误: 镜像文件不存在: ${TAR_FILE}${NC}"
    exit 1
fi

echo -e "${BLUE}==========================================${NC}"
echo -e "${BLUE}镜像导入工具${NC}"
echo -e "${BLUE}==========================================${NC}"
echo ""

# 查找K3s的ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo -e "${RED}错误: 未找到K3s的ctr命令${NC}"
    echo "请检查K3s是否已安装"
    exit 1
fi

echo -e "${GREEN}✓ 找到ctr命令: ${CTR_PATH}${NC}"
echo -e "${GREEN}✓ 镜像文件: ${TAR_FILE}${NC}"
echo ""

# 导入镜像
echo -e "${YELLOW}[1/4] 导入镜像到K3s containerd...${NC}"
sudo ${CTR_PATH} -n k8s.io images import "${TAR_FILE}" 2>&1 | grep -v "unpacking" || true
echo -e "${GREEN}✓ 镜像导入完成${NC}"
echo ""

# 如果提供了镜像名称和标签，进行标记
if [ -n "$IMAGE_NAME_TAG" ]; then
    echo -e "${YELLOW}[2/4] 标记镜像为: ${IMAGE_NAME_TAG}...${NC}"
    # 尝试不同的标记方式
    sudo ${CTR_PATH} -n k8s.io images tag "docker.io/${IMAGE_NAME_TAG}" "${IMAGE_NAME_TAG}" 2>/dev/null || \
    sudo ${CTR_PATH} -n k8s.io images tag "${IMAGE_NAME_TAG}" "${IMAGE_NAME_TAG}" 2>/dev/null || \
    echo -e "${YELLOW}⚠ 自动标记失败，请手动标记镜像${NC}"
    echo -e "${GREEN}✓ 镜像标记完成${NC}"
    echo ""
else
    echo -e "${YELLOW}[2/4] 跳过标记（未指定镜像名称:标签）${NC}"
    echo -e "${BLUE}提示: 可以使用以下命令查看导入的镜像:${NC}"
    echo "  sudo ${CTR_PATH} -n k8s.io images ls"
    echo ""
fi

# 验证镜像
echo -e "${YELLOW}[3/4] 验证镜像...${NC}"
if [ -n "$IMAGE_NAME_TAG" ]; then
    IMAGE_NAME=$(echo "$IMAGE_NAME_TAG" | cut -d: -f1)
    sudo ${CTR_PATH} -n k8s.io images ls | grep -i "$IMAGE_NAME" || echo -e "${YELLOW}⚠ 镜像未在列表中显示，但可能已导入${NC}"
else
    echo -e "${BLUE}已导入的镜像列表:${NC}"
    sudo ${CTR_PATH} -n k8s.io images ls | tail -5
fi
echo ""

# 同步到所有节点
if [ "$SYNC_ALL" = true ]; then
    echo -e "${YELLOW}[4/4] 同步镜像到所有节点...${NC}"
    
    # 获取所有节点列表
    if ! command -v kubectl &> /dev/null; then
        echo -e "${YELLOW}⚠ kubectl命令不可用，跳过节点同步${NC}"
    else
        NODES=$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || echo "")
        
        if [ -z "$NODES" ]; then
            echo -e "${YELLOW}⚠ 无法获取节点列表，跳过节点同步${NC}"
        else
            CURRENT_NODE=$(hostname)
            echo "当前节点: $CURRENT_NODE"
            echo "所有节点: $NODES"
            echo ""
            
            for node in $NODES; do
                if [ "$node" != "$CURRENT_NODE" ]; then
                    echo -e "${BLUE}同步到节点: $node${NC}"
                    
                    # 获取节点IP
                    NODE_IP=$(kubectl get node "$node" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || \
                             kubectl get node "$node" -o jsonpath='{.status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null || echo "")
                    
                    if [ -z "$NODE_IP" ]; then
                        echo -e "${YELLOW}  ⚠ 无法获取节点IP，跳过${NC}"
                        continue
                    fi
                    
                    echo "  节点IP: $NODE_IP"
                    
                    # 检测SSH用户
                    SSH_USER=""
                    for user in test control $USER root; do
                        if ssh -o ConnectTimeout=2 -o BatchMode=yes ${user}@${NODE_IP} "echo test" 2>/dev/null; then
                            SSH_USER=$user
                            break
                        fi
                    done
                    
                    if [ -z "$SSH_USER" ]; then
                        SSH_USER="${K3S_SSH_USER:-test}"
                        echo "  使用SSH用户: $SSH_USER (可通过K3S_SSH_USER环境变量设置)"
                    else
                        echo "  检测到SSH用户: $SSH_USER"
                    fi
                    
                    # 复制镜像文件到节点
                    echo "  复制镜像文件..."
                    if scp "$TAR_FILE" ${SSH_USER}@${NODE_IP}:/tmp/ 2>/dev/null; then
                        # 在远程节点导入镜像
                        echo "  在节点上导入镜像..."
                        ssh ${SSH_USER}@${NODE_IP} "
                            CTR_PATH=\$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
                            if [ -z \"\$CTR_PATH\" ]; then
                                echo '    错误: 无法找到ctr命令'
                            else
                                sudo \$CTR_PATH -n k8s.io images import /tmp/$(basename $TAR_FILE) 2>&1 | grep -v 'unpacking' || true
                                if [ -n \"$IMAGE_NAME_TAG\" ]; then
                                    sudo \$CTR_PATH -n k8s.io images tag docker.io/$IMAGE_NAME_TAG $IMAGE_NAME_TAG 2>/dev/null || true
                                fi
                                echo '    ✓ 镜像导入成功'
                            fi
                        " 2>/dev/null || echo -e "${YELLOW}  ⚠ 无法在远程节点执行命令${NC}"
                    else
                        echo -e "${YELLOW}  ⚠ 无法复制文件到节点${NC}"
                        echo "  请手动执行:"
                        echo "    scp $TAR_FILE ${SSH_USER}@${NODE_IP}:/tmp/"
                        echo "    ssh ${SSH_USER}@${NODE_IP}"
                        echo "    CTR_PATH=\$(sudo find /var/lib/rancher -name ctr | head -1)"
                        echo "    sudo \$CTR_PATH -n k8s.io images import /tmp/$(basename $TAR_FILE)"
                    fi
                    echo ""
                fi
            done
        fi
    fi
else
    echo -e "${YELLOW}[4/4] 跳过节点同步（未指定 --sync-all 参数）${NC}"
    echo -e "${BLUE}提示: 如需同步到所有节点，请使用 --sync-all 参数${NC}"
    echo ""
fi

echo -e "${GREEN}==========================================${NC}"
echo -e "${GREEN}镜像导入完成！${NC}"
echo -e "${GREEN}==========================================${NC}"
echo ""

if [ -n "$IMAGE_NAME_TAG" ]; then
    echo -e "${BLUE}镜像信息:${NC}"
    echo "  名称: $IMAGE_NAME_TAG"
    echo "  文件: $TAR_FILE"
    echo ""
    echo -e "${BLUE}下一步:${NC}"
    echo "  1. 验证镜像: sudo ${CTR_PATH} -n k8s.io images ls | grep $(echo $IMAGE_NAME_TAG | cut -d: -f1)"
    echo "  2. 如需同步到其他节点，运行: sudo bash scripts/import_image.sh $TAR_FILE $IMAGE_NAME_TAG --sync-all"
    echo "  3. 将镜像添加到数据库（如需要）"
else
    echo -e "${BLUE}提示:${NC}"
    echo "  查看已导入的镜像: sudo ${CTR_PATH} -n k8s.io images ls"
    echo "  如需标记镜像，运行: sudo ${CTR_PATH} -n k8s.io images tag <源镜像名> <目标镜像名:标签>"
fi
echo ""
