#!/bin/bash
# 构建并导入Jupyter测试镜像到K3s

set -e

IMAGE_NAME="jupyter-test"
IMAGE_TAG="latest"
FULL_IMAGE_NAME="${IMAGE_NAME}:${IMAGE_TAG}"

echo "=== 构建/导入Jupyter测试镜像 ==="

# 查找K3s的ctr命令
CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)

# 检查是否有已存在的镜像tar文件
TAR_FILE="/tmp/${IMAGE_NAME}.tar"
if [ -f "$TAR_FILE" ]; then
    echo "发现已存在的镜像文件: ${TAR_FILE}"
    echo "是否直接导入？(y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        if [ -z "$CTR_PATH" ]; then
            echo "错误: 未找到K3s的ctr命令"
            exit 1
        fi
        echo "导入镜像..."
        sudo ${CTR_PATH} images import ${TAR_FILE}
        sudo ${CTR_PATH} images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
        echo "✓ 镜像导入完成"
        sudo ${CTR_PATH} images ls | grep ${IMAGE_NAME} || echo "⚠ 镜像未在列表中显示"
        exit 0
    fi
fi

# 检查Docker中是否已有构建好的镜像
if command -v docker &> /dev/null && docker info &> /dev/null; then
    if docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${FULL_IMAGE_NAME}$"; then
        echo "发现Docker中已存在的镜像: ${FULL_IMAGE_NAME}"
        echo "是否直接导入到K3s？(y/n)"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            echo "从Docker导出镜像..."
            docker save ${FULL_IMAGE_NAME} -o ${TAR_FILE}
            echo "✓ 镜像导出完成"
            
            if [ -z "$CTR_PATH" ]; then
                echo "错误: 未找到K3s的ctr命令"
                echo "镜像文件已保存到: ${TAR_FILE}"
                echo "请手动导入: sudo <CTR_PATH> images import ${TAR_FILE}"
                exit 1
            fi
            
            echo "导入镜像到K3s..."
            sudo ${CTR_PATH} images import ${TAR_FILE}
            sudo ${CTR_PATH} images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
            echo "✓ 镜像导入完成"
            
            # 验证镜像
            echo ""
            echo "=== 验证镜像 ==="
            sudo ${CTR_PATH} images ls | grep ${IMAGE_NAME} || echo "⚠ 镜像未在列表中显示，但可能已导入"
            
            echo ""
            echo "=== 完成 ==="
            echo "镜像名称: ${FULL_IMAGE_NAME}"
            echo "现在可以在系统中使用此镜像创建Pod进行Jupyter测试"
            exit 0
        fi
    fi
fi

# 检查Docker是否可用
if command -v docker &> /dev/null && docker info &> /dev/null; then
    echo "使用Docker构建镜像..."
    cd "$(dirname "$0")"
    
    # 检查是否需要构建（如果镜像不存在）
    if ! docker images --format "{{.Repository}}:{{.Tag}}" | grep -q "^${FULL_IMAGE_NAME}$"; then
        docker build -t ${FULL_IMAGE_NAME} .
        echo "✓ 镜像构建完成"
    else
        echo "✓ 镜像已存在，跳过构建步骤"
    fi
    
    # 保存镜像为tar文件
    TAR_FILE="/tmp/${IMAGE_NAME}.tar"
    echo "导出镜像到 ${TAR_FILE}..."
    docker save ${FULL_IMAGE_NAME} -o ${TAR_FILE}
    echo "✓ 镜像导出完成"
    
    # 查找K3s的ctr命令
    CTR_PATH=$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)
    
    if [ -z "$CTR_PATH" ]; then
        echo "⚠ 未找到K3s的ctr命令，请手动导入镜像"
        echo "镜像文件位置: ${TAR_FILE}"
        echo ""
        echo "手动导入方法："
        echo "1. 找到ctr命令: sudo find /var/lib/rancher -name ctr"
        echo "2. 导入镜像: sudo <CTR_PATH> images import ${TAR_FILE}"
        echo "3. 标记镜像: sudo <CTR_PATH> images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME}"
        exit 1
    fi
    
    echo "找到ctr命令: ${CTR_PATH}"
    echo "导入镜像到K3s..."
    sudo ${CTR_PATH} images import ${TAR_FILE}
    echo "✓ 镜像导入完成"
    
    # 标记镜像（确保K3s能识别）
    echo "标记镜像..."
    sudo ${CTR_PATH} images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
    echo "✓ 镜像标记完成"
    
    # 验证镜像
    echo ""
    echo "=== 验证镜像 ==="
    sudo ${CTR_PATH} images ls | grep ${IMAGE_NAME} || echo "⚠ 镜像未在列表中显示，但可能已导入"
    
    echo ""
    echo "=== 完成 ==="
    echo "镜像名称: ${FULL_IMAGE_NAME}"
    echo "现在可以在系统中使用此镜像创建Pod进行Jupyter测试"
    
elif command -v nerdctl &> /dev/null; then
    echo "使用nerdctl构建镜像（containerd）..."
    cd "$(dirname "$0")"
    sudo nerdctl build -t ${FULL_IMAGE_NAME} .
    echo "✓ 镜像构建完成"
    
    # nerdctl构建的镜像已经在containerd中，直接标记即可
    echo "标记镜像..."
    sudo nerdctl tag ${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
    echo "✓ 镜像已就绪"
    
    # 验证镜像
    echo ""
    echo "=== 验证镜像 ==="
    sudo nerdctl images | grep ${IMAGE_NAME} || echo "⚠ 镜像未在列表中显示"
    
    echo ""
    echo "=== 完成 ==="
    echo "镜像名称: ${FULL_IMAGE_NAME}"
    echo "现在可以在系统中使用此镜像创建Pod进行Jupyter测试"
    
elif command -v podman &> /dev/null; then
    echo "使用Podman构建镜像..."
    cd "$(dirname "$0")"
    podman build -t ${FULL_IMAGE_NAME} .
    echo "✓ 镜像构建完成"
    
    # 保存镜像
    TAR_FILE="/tmp/${IMAGE_NAME}.tar"
    podman save ${FULL_IMAGE_NAME} -o ${TAR_FILE}
    echo "✓ 镜像导出完成"
    
    if [ -z "$CTR_PATH" ]; then
        echo "⚠ 未找到K3s的ctr命令，请手动导入镜像"
        echo "镜像文件位置: ${TAR_FILE}"
        echo ""
        echo "手动导入方法："
        echo "1. 找到ctr命令: sudo find /var/lib/rancher -name ctr"
        echo "2. 导入镜像: sudo <CTR_PATH> images import ${TAR_FILE}"
        echo "3. 标记镜像: sudo <CTR_PATH> images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME}"
        exit 1
    fi
    
    echo "导入镜像到K3s..."
    sudo ${CTR_PATH} images import ${TAR_FILE}
    sudo ${CTR_PATH} images tag docker.io/${FULL_IMAGE_NAME} ${FULL_IMAGE_NAME} || true
    echo "✓ 镜像导入完成"
    
else
    echo "⚠ 未找到Docker、nerdctl或Podman"
    echo ""
    echo "=== 离线导入方法 ==="
    echo ""
    echo "由于系统使用K3s内置的containerd，没有Docker，请使用以下方法之一："
    echo ""
    echo "方法1: 从其他有Docker的机器构建并导入"
    echo "----------------------------------------"
    echo "1. 在有Docker的机器上："
    echo "   cd test-images/jupyter-test"
    echo "   docker build -t jupyter-test:latest ."
    echo "   docker save jupyter-test:latest -o jupyter-test.tar"
    echo ""
    echo "2. 传输到当前服务器："
    echo "   scp jupyter-test.tar control@$(hostname):/tmp/"
    echo ""
    echo "3. 在当前服务器上导入："
    if [ -z "$CTR_PATH" ]; then
        echo "   首先找到ctr命令:"
        echo "   CTR_PATH=\$(sudo find /var/lib/rancher -name ctr 2>/dev/null | head -1)"
        echo "   然后导入:"
        echo "   sudo \$CTR_PATH images import /tmp/jupyter-test.tar"
        echo "   sudo \$CTR_PATH images tag docker.io/jupyter-test:latest jupyter-test:latest"
    else
        echo "   使用以下命令导入："
        echo "   sudo ${CTR_PATH} images import /tmp/jupyter-test.tar"
        echo "   sudo ${CTR_PATH} images tag docker.io/jupyter-test:latest jupyter-test:latest"
    fi
    echo ""
    echo "方法2: 安装nerdctl（推荐）"
    echo "----------------------------------------"
    echo "nerdctl是containerd的Docker兼容CLI，可以直接构建镜像："
    echo "1. 下载nerdctl:"
    echo "   wget https://github.com/containerd/nerdctl/releases/download/v1.5.0/nerdctl-1.5.0-linux-amd64.tar.gz"
    echo "   tar -xzf nerdctl-1.5.0-linux-amd64.tar.gz"
    echo "   sudo mv nerdctl /usr/local/bin/"
    echo ""
    echo "2. 然后重新运行此脚本:"
    echo "   sudo ./build_and_import.sh"
    echo ""
    echo "方法3: 使用buildah（如果可用）"
    echo "----------------------------------------"
    echo "如果系统有buildah，也可以使用它构建镜像"
    echo ""
    exit 1
fi

