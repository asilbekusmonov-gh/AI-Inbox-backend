#!/bin/bash
set -e

echo "PostgreSQL tayyor bo'lishini kutamiz..."
until python -c "
import psycopg
import os
try:
    conn = psycopg.connect(
        dbname=os.environ.get('DB_NAME'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD'),
        host=os.environ.get('DB_HOST'),
        port=os.environ.get('DB_PORT', 5432)
    )
    conn.close()
    print('PostgreSQL muvaffaqiyatli ulandi!')
except Exception as e:
    exit(1)
"; do
  echo "PostgreSQL hali tayyor emas, 2 soniya kutilmoqda..."
  sleep 2
done

echo "Migratsiyalarni bajarish..."
python manage.py migrate --noinput

echo "Static fayllarni yig'ish..."
python manage.py collectstatic --noinput || true

echo "Konteyner buyrug'i ishga tushmoqda: $@"
exec "$@"
