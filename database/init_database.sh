#!/bin/bash
# 一键部署MySQL数据库脚本
# 使用方法: sudo bash database/init_database.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "算力云平台数据库初始化脚本"
echo "=========================================="

# 检查是否为root用户
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}请使用sudo运行此脚本${NC}"
    exit 1
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# 1. 检查MySQL是否安装
echo -e "\n${YELLOW}[1/4] 检查MySQL...${NC}"
if ! command -v mysql &> /dev/null; then
    echo -e "${RED}MySQL未安装，请先安装MySQL${NC}"
    exit 1
fi

# 检查MySQL服务是否运行
if ! systemctl is-active --quiet mysql && ! systemctl is-active --quiet mysqld; then
    echo "启动MySQL服务..."
    systemctl start mysql || systemctl start mysqld
fi

echo -e "${GREEN}MySQL已安装并运行${NC}"

# 2. 获取数据库配置
echo -e "\n${YELLOW}[2/4] 配置数据库...${NC}"
read -p "请输入MySQL root密码: " MYSQL_ROOT_PASS
read -p "请输入要创建的数据库名称 [computing_platform]: " DB_NAME
DB_NAME=${DB_NAME:-computing_platform}

read -p "请输入要创建的数据库用户 [platform_user]: " DB_USER
DB_USER=${DB_USER:-platform_user}

read -sp "请输入数据库用户密码: " DB_PASS
echo ""

# 3. 验证MySQL root密码
echo -e "\n${YELLOW}[3/5] 验证MySQL root密码...${NC}"
if ! mysql -u root -p"$MYSQL_ROOT_PASS" -e "SELECT 1;" &>/dev/null; then
    echo -e "${RED}错误: MySQL root密码不正确或无法连接${NC}"
    echo "请检查："
    echo "1. MySQL服务是否运行: sudo systemctl status mysql"
    echo "2. root密码是否正确"
    echo "3. 如果使用sudo mysql，可能需要使用: sudo mysql -u root"
    exit 1
fi
echo -e "${GREEN}✓ MySQL root密码验证成功${NC}"

# 4. 创建数据库和用户
echo -e "\n${YELLOW}[4/5] 创建数据库和用户...${NC}"
mysql -u root -p"$MYSQL_ROOT_PASS" <<EOF
CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON $DB_NAME.* TO '$DB_USER'@'%';
FLUSH PRIVILEGES;
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ 数据库和用户创建成功${NC}"
else
    echo -e "${RED}✗ 数据库创建失败${NC}"
    exit 1
fi

# 验证用户是否可以连接
if mysql -u "$DB_USER" -p"$DB_PASS" -e "SELECT 1;" &>/dev/null; then
    echo -e "${GREEN}✓ 数据库用户连接验证成功${NC}"
else
    echo -e "${YELLOW}⚠ 警告: 数据库用户连接验证失败，但继续执行...${NC}"
fi

# 表结构由 Alembic 维护，不再导入历史 schema.sql。
echo "数据库与账户已创建。请在 backend/.env 配置 DATABASE_URL，然后运行："
echo "  cd backend"
echo "  python scripts/init_db.py"
echo "已有业务表的数据库请先参考 docs/数据库迁移.md 完成基线核对。"
