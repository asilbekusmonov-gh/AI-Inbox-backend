#!/usr/bin/env bash
#
# Ma'lumotlar bazasining (PostgreSQL) to'liq nusxasini (backup) oladi.
#
# ⚠️ Nima uchun kerak: hozir hech qanday backup yo'q edi — agar DB
# konteyneri buzilsa yoki disk yo'qolsa, barcha lidlar/mijozlar/suhbatlar
# butunlay qaytarib bo'lmas tarzda yo'qoladi. Bu skript har kuni (cron
# orqali) `pg_dump` bilan to'liq nusxa oladi, siqadi va eski nusxalarni
# (14 kundan ortiq) avtomatik tozalaydi.
#
# Qo'lda ishga tushirish:
#   bash scripts/backup_db.sh
#
# Har kuni avtomatik ishga tushirish uchun (crontab -e):
#   0 3 * * * /usr/bin/bash /home/asilbek/PycharmProjects/AI-Inbox-backend/scripts/backup_db.sh >> /home/asilbek/PycharmProjects/AI-Inbox-backend/backups/backup.log 2>&1
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=14

# .env'dan DB nomi/foydalanuvchisini o'qiymiz (docker-compose.yml bilan bir xil default'lar)
DB_NAME=$(grep -E "^DB_NAME=" "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)
DB_USER=$(grep -E "^DB_USER=" "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- || true)
DB_NAME="${DB_NAME:-ai_inbox_db}"
DB_USER="${DB_USER:-ai_inbox_user}"

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUT_FILE="$BACKUP_DIR/db_${TIMESTAMP}.sql.gz"

echo "[$(date)] Backup boshlandi: $OUT_FILE"

docker exec ai_inbox_db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$OUT_FILE"

SIZE=$(du -h "$OUT_FILE" | cut -f1)
echo "[$(date)] Backup tugadi: $OUT_FILE ($SIZE)"

# ⚠️ Eski (RETENTION_DAYS kundan ortiq) nusxalarni tozalash — disk
# to'lib ketmasligi uchun.
find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime "+$RETENTION_DAYS" -delete
echo "[$(date)] $RETENTION_DAYS kundan eski nusxalar tozalandi."
