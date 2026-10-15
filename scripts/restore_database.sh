#!/bin/bash
# 数据库恢复脚本
# 使用方法: bash scripts/restore_database.sh <backup_file>

set -e

if [ -z "$1" ]; then
    echo "使用方法: $0 <backup_file>"
    echo "示例: $0 /opt/backups/computing-platform/db_backup_20240101_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "错误: 备份文件不存在: $BACKUP_FILE"
    exit 1
fi

# 从.env文件读取数据库配置
if [ -f backend/.env ]; then
    source backend/.env
    DB_USER=$(echo $DATABASE_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
    DB_PASS=$(echo $DATABASE_URL | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')
    DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\):.*/\1/p')
    DB_NAME=$(echo $DATABASE_URL | sed -n 's/.*\/\([^?]*\).*/\1/p')
else
    echo "错误: 找不到 .env 文件"
    exit 1
fi

echo "警告: 此操作将覆盖现有数据库！"
read -p "确认恢复数据库? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "操作已取消"
    exit 0
fi

echo "开始恢复数据库..."

# 解压（如果是压缩文件）
TEMP_FILE="/tmp/restore_$$.sql"
if [[ "$BACKUP_FILE" == *.gz ]]; then
    gunzip -c "$BACKUP_FILE" > "$TEMP_FILE"
else
    cp "$BACKUP_FILE" "$TEMP_FILE"
fi

# 恢复数据库
mysql -u "$DB_USER" -p"$DB_PASS" -h "$DB_HOST" "$DB_NAME" < "$TEMP_FILE"

# 清理临时文件
rm "$TEMP_FILE"

echo "数据库恢复完成！"

