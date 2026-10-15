#!/bin/bash
# 将镜像同步到所有K3s节点

echo "=========================================="
echo "同步conda-pytorch-jupyter镜像到所有节点"
echo "=========================================="
echo ""

# 查找ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

if [ -z "$CTR_PATH" ]; then
    echo "❌ 无法找到ctr命令"
    exit 1
fi

echo "1. 检查当前节点镜像:"
sudo $CTR_PATH -n k8s.io images ls | grep -i jinglever

echo ""
echo "2. 获取所有节点列表:"
NODES=$(kubectl get nodes -o jsonpath='{.items[*].metadata.name}')
echo "   节点: $NODES"

echo ""
echo "3. 检查镜像文件:"
TAR_FILE="/tmp/conda-pytorch-jupyter-mmcv-20240518.tar"
if [ ! -f "$TAR_FILE" ]; then
    echo "   镜像文件不存在，正在导出..."
    sudo $CTR_PATH -n k8s.io images export $TAR_FILE docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518 2>/dev/null || \
    sudo $CTR_PATH -n k8s.io images export $TAR_FILE jinglever/conda-pytorch-jupyter:mmcv-20240518
    
    if [ ! -f "$TAR_FILE" ]; then
        echo "   ❌ 无法导出镜像"
        echo "   请手动导出:"
        echo "   sudo $CTR_PATH -n k8s.io images export $TAR_FILE docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518"
        exit 1
    fi
    echo "   ✅ 镜像已导出到: $TAR_FILE"
else
    echo "   ✅ 镜像文件已存在: $TAR_FILE"
fi

echo ""
echo "4. 同步到其他节点:"
for node in $NODES; do
    if [ "$node" != "$(hostname)" ] && [ "$node" != "control" ]; then
        echo "   同步到节点: $node"
        
        # 获取节点IP
        NODE_IP=$(kubectl get node $node -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}')
        if [ -z "$NODE_IP" ]; then
            NODE_IP=$(kubectl get node $node -o jsonpath='{.status.addresses[?(@.type=="ExternalIP")].address}')
        fi
        
        if [ -z "$NODE_IP" ]; then
            echo "      ⚠️  无法获取节点IP，跳过"
            continue
        fi
        
        echo "      节点IP: $NODE_IP"
        
        # 检测SSH用户（尝试常见用户名）
        SSH_USER=""
        for user in test control $USER root; do
            if ssh -o ConnectTimeout=2 -o BatchMode=yes ${user}@${NODE_IP} "echo test" 2>/dev/null; then
                SSH_USER=$user
                break
            fi
        done
        
        if [ -z "$SSH_USER" ]; then
            # 如果无法自动检测，使用环境变量或默认值
            SSH_USER="${K3S_SSH_USER:-test}"
            echo "      使用SSH用户: $SSH_USER (可通过K3S_SSH_USER环境变量设置)"
        else
            echo "      检测到SSH用户: $SSH_USER"
        fi
        
        # 复制镜像文件到节点
        echo "      复制镜像文件到 ${SSH_USER}@${NODE_IP}..."
        scp $TAR_FILE ${SSH_USER}@${NODE_IP}:/tmp/ 2>/dev/null || {
            echo "      ⚠️  无法复制文件到 ${SSH_USER}@${NODE_IP}"
            echo "      请手动执行:"
            echo "        scp $TAR_FILE ${SSH_USER}@${NODE_IP}:/tmp/"
            echo "        然后在 ${NODE_IP} 上运行:"
            echo "        CTR_PATH=\$(sudo find /var/lib/rancher -name ctr | head -1)"
            echo "        sudo \$CTR_PATH -n k8s.io images import /tmp/conda-pytorch-jupyter-mmcv-20240518.tar"
            echo "        sudo \$CTR_PATH -n k8s.io images tag docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518 jinglever/conda-pytorch-jupyter:mmcv-20240518"
            continue
        }
        
        # 在远程节点导入镜像
        echo "      在节点上导入镜像..."
        ssh ${SSH_USER}@${NODE_IP} "CTR_PATH=\$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1); \
                      if [ -z \"\$CTR_PATH\" ]; then \
                          echo '无法找到ctr命令'; \
                      else \
                          sudo \$CTR_PATH -n k8s.io images import /tmp/conda-pytorch-jupyter-mmcv-20240518.tar && \
                          sudo \$CTR_PATH -n k8s.io images tag docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518 jinglever/conda-pytorch-jupyter:mmcv-20240518 && \
                          echo '镜像导入成功' && \
                          sudo \$CTR_PATH -n k8s.io images ls | grep jinglever; \
                      fi" 2>/dev/null || {
            echo "      ⚠️  无法在远程节点执行命令"
            echo "      请手动在 ${SSH_USER}@${NODE_IP} 上执行:"
            echo "        CTR_PATH=\$(sudo find /var/lib/rancher -name ctr | head -1)"
            echo "        sudo \$CTR_PATH -n k8s.io images import /tmp/conda-pytorch-jupyter-mmcv-20240518.tar"
            echo "        sudo \$CTR_PATH -n k8s.io images tag docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518 jinglever/conda-pytorch-jupyter:mmcv-20240518"
        }
    fi
done

echo ""
echo "=========================================="
echo "完成！"
echo "=========================================="
echo ""
echo "如果自动同步失败，请手动在每个节点上执行:"
echo "1. 复制镜像文件: scp /tmp/conda-pytorch-jupyter-mmcv-20240518.tar <user>@<node-ip>:/tmp/"
echo "   例如: scp /tmp/conda-pytorch-jupyter-mmcv-20240518.tar test@REPLACE_NODE_INTERNAL_IP:/tmp/"
echo ""
echo "2. 在节点上导入:"
echo "   ssh <user>@<node-ip>"
echo "   CTR_PATH=\$(sudo find /var/lib/rancher -name ctr | head -1)"
echo "   sudo \$CTR_PATH -n k8s.io images import /tmp/conda-pytorch-jupyter-mmcv-20240518.tar"
echo "   sudo \$CTR_PATH -n k8s.io images tag docker.io/jinglever/conda-pytorch-jupyter:mmcv-20240518 jinglever/conda-pytorch-jupyter:mmcv-20240518"
echo ""
echo "提示: 可以通过环境变量设置SSH用户:"
echo "   export K3S_SSH_USER=test"
echo "   sudo ./scripts/sync_image_to_all_nodes.sh"
echo ""

