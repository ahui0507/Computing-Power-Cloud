#!/bin/bash
# 数据库备份脚本
# 使用方法: bash scripts/backup_database.sh

set -e

BACKUP_DIR="/opt/backups/computing-platform"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/db_backup_$DATE.sql"
RETENTION_DAYS=7

# 创建备份目录
mkdir -p "$BACKUP_DIR"

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

echo "开始备份数据库..."
echo "数据库: $DB_NAME"
echo "备份文件: $BACKUP_FILE"

# 执行备份
mysqldump -u "$DB_USER" -p"$DB_PASS" -h "$DB_HOST" "$DB_NAME" > "$BACKUP_FILE"

# 压缩备份文件
gzip "$BACKUP_FILE"
BACKUP_FILE="${BACKUP_FILE}.gz"

echo "备份完成: $BACKUP_FILE"

# 删除旧备份（保留最近N天）
find "$BACKUP_DIR" -name "db_backup_*.sql.gz" -mtime +$RETENTION_DAYS -delete

echo "已删除 $RETENTION_DAYS 天前的备份文件"

# 显示备份文件列表
echo -e "\n当前备份文件:"
ls -lh "$BACKUP_DIR"/db_backup_*.sql.gz 2>/dev/null || echo "无备份文件"

