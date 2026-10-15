#!/bin/bash
# 算力云平台快速部署脚本
# 使用方法: sudo bash scripts/deploy.sh

set -e

echo "=========================================="
echo "算力云平台部署脚本"
echo "=========================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}请使用sudo运行此脚本${NC}"
    exit 1
fi

# 获取项目路径
PROJECT_DIR=$(cd "$(dirname "$0")/.." && pwd)
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

echo -e "${GREEN}项目目录: $PROJECT_DIR${NC}"

# 1. 检查并安装MySQL
echo -e "\n${YELLOW}[1/8] 检查MySQL...${NC}"
if ! command -v mysql &> /dev/null; then
    echo "MySQL未安装，正在安装..."
    if [ -f /etc/debian_version ]; then
        apt update
        apt install -y mysql-server
    elif [ -f /etc/redhat-release ]; then
        yum install -y mysql-server
    fi
    systemctl start mysql
    systemctl enable mysql
else
    echo "MySQL已安装"
fi

# 2. 检查并安装Redis
echo -e "\n${YELLOW}[2/9] 检查Redis...${NC}"
if ! command -v redis-cli &> /dev/null; then
    echo "Redis未安装，正在安装..."
    if [ -f /etc/debian_version ]; then
        apt install -y redis-server
    elif [ -f /etc/redhat-release ]; then
        yum install -y redis
    fi
    systemctl start redis
    systemctl enable redis
    sleep 2
else
    echo "Redis已安装"
fi

# 验证Redis连接
if redis-cli ping &>/dev/null; then
    echo -e "${GREEN}✓ Redis连接正常${NC}"
else
    echo -e "${YELLOW}⚠ 警告: Redis连接失败，请检查服务状态${NC}"
    systemctl status redis --no-pager -l | head -n 5
fi

# 3. 配置MySQL数据库
echo -e "\n${YELLOW}[3/9] 配置MySQL数据库...${NC}"
read -p "请输入MySQL root密码: " MYSQL_ROOT_PASS
read -p "请输入平台数据库用户密码: " PLATFORM_DB_PASS

# 验证MySQL root密码
echo "验证MySQL root密码..."
if ! mysql -u root -p"$MYSQL_ROOT_PASS" -e "SELECT 1;" &>/dev/null; then
    echo -e "${RED}错误: MySQL root密码不正确或无法连接${NC}"
    echo "请检查："
    echo "1. MySQL服务是否运行: sudo systemctl status mysql"
    echo "2. root密码是否正确"
    exit 1
fi
echo -e "${GREEN}✓ MySQL root密码验证成功${NC}"

# 创建数据库和用户
mysql -u root -p"$MYSQL_ROOT_PASS" <<EOF
CREATE DATABASE IF NOT EXISTS computing_platform CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'platform_user'@'localhost' IDENTIFIED BY '$PLATFORM_DB_PASS';
CREATE USER IF NOT EXISTS 'platform_user'@'%' IDENTIFIED BY '$PLATFORM_DB_PASS';
GRANT ALL PRIVILEGES ON computing_platform.* TO 'platform_user'@'localhost';
GRANT ALL PRIVILEGES ON computing_platform.* TO 'platform_user'@'%';
FLUSH PRIVILEGES;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ 数据库配置完成${NC}"
    
    # 验证数据库用户连接
    if mysql -u platform_user -p"$PLATFORM_DB_PASS" -e "SELECT 1;" &>/dev/null; then
        echo -e "${GREEN}✓ 数据库用户连接验证成功${NC}"
    else
        echo -e "${YELLOW}⚠ 警告: 数据库用户连接验证失败${NC}"
    fi
else
    echo -e "${RED}✗ 数据库配置失败${NC}"
    exit 1
fi

# 4. 检查并安装构建工具（用于编译Python C扩展）
echo -e "\n${YELLOW}[4/10] 检查构建工具...${NC}"
if ! command -v gcc &> /dev/null; then
    echo "检测到缺少C编译器，正在安装构建工具..."
    if [ -f /etc/debian_version ]; then
        apt update
        apt install -y build-essential python3-dev
    elif [ -f /etc/redhat-release ]; then
        yum groupinstall -y "Development Tools"
        yum install -y python3-devel
    fi
    echo -e "${GREEN}构建工具安装完成${NC}"
else
    echo -e "${GREEN}构建工具已安装${NC}"
fi

# 5. 检查并安装Python依赖
echo -e "\n${YELLOW}[5/10] 配置Python环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo "Python3未安装，正在安装..."
    if [ -f /etc/debian_version ]; then
        apt install -y python3 python3-pip python3-venv
    elif [ -f /etc/redhat-release ]; then
        yum install -y python3 python3-pip
    fi
fi

# 确保python3-venv已安装（Ubuntu/Debian需要）
if [ -f /etc/debian_version ] && ! dpkg -l | grep -q python3-venv; then
    echo "安装python3-venv..."
    apt install -y python3-venv
fi

cd "$BACKEND_DIR" || {
    echo -e "${RED}错误: 无法进入后端目录 $BACKEND_DIR${NC}"
    exit 1
}

# 创建虚拟环境（如果不存在或损坏）
if [ ! -d "venv" ] || [ ! -f "venv/bin/activate" ]; then
    echo "创建Python虚拟环境..."
    python3 -m venv venv || {
        echo -e "${RED}错误: 虚拟环境创建失败${NC}"
        echo "请确保已安装 python3-venv 包: sudo apt install python3-venv"
        exit 1
    }
fi

# 验证虚拟环境是否创建成功
if [ ! -f "venv/bin/activate" ]; then
    echo -e "${RED}错误: 虚拟环境激活脚本不存在${NC}"
    echo "尝试重新创建虚拟环境..."
    rm -rf venv
    python3 -m venv venv || {
        echo -e "${RED}错误: 重新创建虚拟环境失败${NC}"
        exit 1
    }
fi

# 激活虚拟环境
source venv/bin/activate || {
    echo -e "${RED}错误: 无法激活虚拟环境${NC}"
    exit 1
}

echo "更新pip..."
pip install --upgrade pip setuptools wheel

echo "安装Python依赖..."
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}错误: 找不到 requirements.txt 文件${NC}"
    exit 1
fi

pip install -r requirements.txt || {
    echo -e "${YELLOW}⚠ 警告: 部分依赖安装失败，请检查${NC}"
}

echo -e "${GREEN}Python依赖安装完成${NC}"

# 6. 配置后端环境变量
echo -e "\n${YELLOW}[6/10] 配置后端环境变量...${NC}"
if [ ! -f "$BACKEND_DIR/.env" ]; then
    # 生成随机SECRET_KEY
    SECRET_KEY=$(openssl rand -hex 32)
    
    # 如果.env.example存在，则复制它；否则直接创建.env
    if [ -f "$BACKEND_DIR/.env.example" ]; then
        cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    else
        # 创建默认的.env文件
        cat > "$BACKEND_DIR/.env" <<EOF
# 应用基础配置
DEBUG=False
LOG_LEVEL=INFO

# 数据库配置
DATABASE_URL=mysql+pymysql://platform_user:$PLATFORM_DB_PASS@localhost:3306/computing_platform
DATABASE_ECHO=False

# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# JWT配置
SECRET_KEY=$SECRET_KEY
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# 邮件服务配置（用于发送验证码）
SMTP_HOST=smtp.exmail.qq.com
SMTP_PORT=465
SMTP_USE_SSL=True
SMTP_USERNAME=REPLACE_SMTP_EMAIL
SMTP_PASSWORD=
SMTP_FROM_EMAIL=REPLACE_SMTP_EMAIL

# MinIO/S3配置
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=REPLACE_MINIO_CREDENTIAL
MINIO_SECRET_KEY=REPLACE_MINIO_CREDENTIAL
MINIO_BUCKET=computing-platform
MINIO_SECURE=False

# Kubernetes配置
K8S_CONFIG_PATH=
K8S_NAMESPACE=default

# Harbor配置
HARBOR_URL=
HARBOR_USERNAME=
HARBOR_PASSWORD=
HARBOR_PROJECT=computing-platform

# CORS配置（逗号分隔）
CORS_ORIGINS=http://localhost:3000,http://localhost:8080

# 计费配置
BILLING_ENABLED=True
DEFAULT_GPU_PRICE_V100=10.0
DEFAULT_GPU_PRICE_A100=20.0
DEFAULT_GPU_PRICE_RTX4090=15.0
EOF
    fi
    
    # 更新.env文件中的关键配置（如果是从.example复制的）
    if [ -f "$BACKEND_DIR/.env.example" ]; then
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=mysql+pymysql://platform_user:$PLATFORM_DB_PASS@localhost:3306/computing_platform|" "$BACKEND_DIR/.env"
    sed -i "s|SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" "$BACKEND_DIR/.env"
    fi
    
    echo -e "${GREEN}环境变量配置完成${NC}"
    echo -e "${YELLOW}请检查并修改 $BACKEND_DIR/.env 中的其他配置${NC}"
else
    echo -e "${YELLOW}.env文件已存在，跳过配置${NC}"
fi

# 7. 版本迁移与种子数据
 echo -e "\n${YELLOW}[7/10] 初始化数据库...${NC}"
cd "$BACKEND_DIR"
source venv/bin/activate
python scripts/init_db.py || {
    echo -e "${RED}数据库迁移失败，停止部署。已有数据库请先参考 docs/数据库迁移.md。${NC}"
    exit 1
}

# 8. 检查K3s（可选）
echo -e "\n${YELLOW}[8/10] 检查K3s...${NC}"
if command -v k3s &> /dev/null || [ -f /etc/rancher/k3s/k3s.yaml ]; then
    echo "K3s已安装"
    if [ ! -f /etc/kubernetes/admin.conf ]; then
        mkdir -p /etc/kubernetes
        if [ -f /etc/rancher/k3s/k3s.yaml ]; then
            cp /etc/rancher/k3s/k3s.yaml /etc/kubernetes/admin.conf
            chmod 644 /etc/kubernetes/admin.conf
            echo -e "${GREEN}✓ K3s配置已复制${NC}"
        else
            echo -e "${YELLOW}⚠ 警告: 未找到K3s配置文件${NC}"
        fi
    else
        echo -e "${GREEN}✓ K3s配置文件已存在${NC}"
    fi
    
    # 验证K3s服务状态
    if systemctl is-active --quiet k3s; then
        echo -e "${GREEN}✓ K3s服务运行正常${NC}"
    else
        echo -e "${YELLOW}⚠ 警告: K3s服务未运行${NC}"
    fi
else
    echo -e "${YELLOW}K3s未安装，跳过（可选）${NC}"
fi

# 9. 验证数据库初始化
echo -e "\n${YELLOW}[9/10] 验证数据库初始化...${NC}"

# 验证数据库连接
if mysql -u platform_user -p"$PLATFORM_DB_PASS" -D computing_platform -e "SELECT 1;" &>/dev/null; then
    echo -e "${GREEN}✓ 数据库连接正常${NC}"
else
    echo -e "${RED}✗ 数据库连接失败${NC}"
    exit 1
fi

# 检查表数量
TABLE_COUNT=$(mysql -u platform_user -p"$PLATFORM_DB_PASS" -D computing_platform -se "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='computing_platform';" 2>/dev/null || echo "0")

if [ "$TABLE_COUNT" -ge 20 ]; then
    echo -e "${GREEN}✓ 数据库验证成功：共 $TABLE_COUNT 个表${NC}"
    
    # 检查关键表是否存在
    KEY_TABLES=("users" "roles" "gpu_types" "nodes" "instances")
    MISSING_TABLES=()
    for table in "${KEY_TABLES[@]}"; do
        if ! mysql -u platform_user -p"$PLATFORM_DB_PASS" -D computing_platform -e "SHOW TABLES LIKE '$table';" 2>/dev/null | grep -q "$table"; then
            MISSING_TABLES+=("$table")
        fi
    done
    
    if [ ${#MISSING_TABLES[@]} -eq 0 ]; then
        echo -e "${GREEN}✓ 关键表检查通过${NC}"
    else
        echo -e "${YELLOW}⚠ 警告：缺少以下关键表: ${MISSING_TABLES[*]}${NC}"
    fi
else
    echo -e "${YELLOW}⚠ 警告：表数量为 $TABLE_COUNT，可能未完全初始化（预期21个表）${NC}"
fi

# 10. 验证环境变量配置
echo -e "\n${YELLOW}[10/11] 验证环境变量配置...${NC}"
if [ -f "$BACKEND_DIR/.env" ]; then
    # 检查关键环境变量
    if grep -q "DATABASE_URL=mysql+pymysql://platform_user:$PLATFORM_DB_PASS@localhost:3306/computing_platform" "$BACKEND_DIR/.env"; then
        echo -e "${GREEN}✓ DATABASE_URL配置正确${NC}"
    else
        echo -e "${YELLOW}⚠ 警告: DATABASE_URL可能未正确配置${NC}"
    fi
    
    if grep -q "SECRET_KEY=" "$BACKEND_DIR/.env" && ! grep -q "SECRET_KEY=$" "$BACKEND_DIR/.env"; then
        echo -e "${GREEN}✓ SECRET_KEY已配置${NC}"
    else
        echo -e "${YELLOW}⚠ 警告: SECRET_KEY可能未配置${NC}"
    fi
    
    if grep -q "REDIS_HOST=" "$BACKEND_DIR/.env"; then
        echo -e "${GREEN}✓ Redis配置存在${NC}"
    else
        echo -e "${YELLOW}⚠ 警告: Redis配置可能缺失${NC}"
    fi
else
    echo -e "${RED}✗ .env文件不存在${NC}"
fi

# 11. 创建systemd服务（可选）
echo -e "\n${YELLOW}[11/11] 配置systemd服务...${NC}"
read -p "是否创建systemd服务？(y/n): " CREATE_SERVICE

if [ "$CREATE_SERVICE" = "y" ]; then
    SERVICE_USER=$(whoami)
    SERVICE_FILE="/etc/systemd/system/computing-platform-backend.service"
    
    cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Computing Platform Backend
After=network.target mysql.service redis.service

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$BACKEND_DIR/venv/bin"
ExecStart=$BACKEND_DIR/venv/bin/python $BACKEND_DIR/scripts/start_backend.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable computing-platform-backend
    echo -e "${GREEN}systemd服务已创建${NC}"
    echo -e "${YELLOW}使用以下命令管理服务:${NC}"
    echo "  启动: sudo systemctl start computing-platform-backend"
    echo "  停止: sudo systemctl stop computing-platform-backend"
    echo "  状态: sudo systemctl status computing-platform-backend"
fi

echo -e "\n${GREEN}=========================================="
echo "部署完成！"
echo "==========================================${NC}"
echo ""
echo "数据库信息:"
echo "  数据库名: computing_platform"
echo "  用户名: platform_user"
echo "  连接字符串: mysql+pymysql://platform_user:$PLATFORM_DB_PASS@localhost:3306/computing_platform"
echo ""
echo "下一步操作："
echo "1. 检查后端配置: nano $BACKEND_DIR/.env"
echo "   - 确认 DATABASE_URL 已正确配置"
echo "   - 检查其他配置项（Redis、K8s等）"
echo ""
echo "2. 测试数据库连接:"
echo "   cd $BACKEND_DIR && source venv/bin/activate"
echo "   python -c \"from app.core.database import engine; engine.connect(); print('Database connected!')\""
echo ""
echo "3. 启动后端服务:"
echo "   - 开发模式: cd $BACKEND_DIR && source venv/bin/activate && python run.py"
echo "   - 生产模式: sudo systemctl start computing-platform-backend"
echo ""
echo "4. 验证服务:"
echo "   - 健康检查: curl http://localhost:8000/health"
echo "   - API文档: http://localhost:8000/docs"
echo ""
echo "5. 默认管理员账户:"
echo "   - 邮箱: REPLACE_ADMIN_EMAIL"
echo "   - 初始密码: 查阅本地凭据记录，不在输出中显示"
echo "   - ⚠️  请在生产环境中立即修改密码！"
echo ""
echo "6. 账号开通:"
echo "   - 所有账号由管理员在用户管理中创建，初始密码通过受限配置提供"
echo "   - 普通用户可在账户设置中修改密码，无需邮箱验证码"
echo ""
echo "7. 数据库表结构:"
echo "   - 已创建 $TABLE_COUNT 个表（roles, users, nodes, gpus, images等）"
echo "   - 默认角色: admin, user, auditor"
echo "   - 默认GPU类型: V100, A100, RTX4090, K80"
echo ""

