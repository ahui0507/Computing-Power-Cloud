#!/bin/bash
# MySQL配置脚本

set -e

echo "=== MySQL配置脚本 ==="

# 检查MySQL是否安装
if ! command -v mysql &> /dev/null; then
    echo "错误: MySQL客户端未安装"
    echo "请先安装MySQL:"
    echo "  Ubuntu/Debian: sudo apt-get install mysql-server"
    echo "  CentOS/RHEL: sudo yum install mysql-server"
    exit 1
fi

# 提示输入MySQL root密码
read -sp "请输入MySQL root密码: " MYSQL_ROOT_PASSWORD
echo ""

# 提示输入数据库用户信息
read -p "请输入数据库用户名 [platform_user]: " DB_USER
DB_USER=${DB_USER:-platform_user}

read -sp "请输入数据库用户密码: " DB_PASSWORD
echo ""

read -p "请输入数据库名称 [computing_platform]: " DB_NAME
DB_NAME=${DB_NAME:-computing_platform}

# 创建数据库
echo "创建数据库..."
mysql -u root -p"$MYSQL_ROOT_PASSWORD" <<EOF
CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'%' IDENTIFIED BY '${DB_PASSWORD}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${DB_USER}'@'%';
FLUSH PRIVILEGES;
EOF

if [ $? -eq 0 ]; then
    echo "✓ 数据库创建成功"
else
    echo "✗ 数据库创建失败"
    exit 1
fi

# 测试连接
echo "测试数据库连接..."
mysql -u "$DB_USER" -p"$DB_PASSWORD" "$DB_NAME" -e "SELECT 1;" &> /dev/null

if [ $? -eq 0 ]; then
    echo "✓ 数据库连接测试成功"
else
    echo "✗ 数据库连接测试失败"
    exit 1
fi

# 生成连接字符串
echo ""
echo "=== 配置信息 ==="
echo "数据库名称: $DB_NAME"
echo "用户名: $DB_USER"
echo "连接字符串:"
echo "mysql+pymysql://${DB_USER}:${DB_PASSWORD}@localhost:3306/${DB_NAME}"
echo ""
echo "请将以上信息添加到 backend/.env 文件中:"
echo "DATABASE_URL=mysql+pymysql://${DB_USER}:${DB_PASSWORD}@localhost:3306/${DB_NAME}"

echo ""
echo "=== 下一步操作 ==="
echo "1. 运行数据库迁移:"
echo "   cd backend"
echo "   alembic upgrade head"
echo ""
echo "2. 初始化数据:"
echo "   python scripts/init_db.py"

echo ""
echo "=== 配置完成 ==="

