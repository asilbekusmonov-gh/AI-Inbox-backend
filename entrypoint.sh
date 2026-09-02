#!/bin/bash
set -e

echo "PostgreSQL tayyor bo'lishini kutamiz..."
until python manage.py check --database default > /dev/null 2>&1; do
  echo "PostgreSQL hali tayyor emas, 2 soniya kutilmoqda..."
  sleep 2
done
echo "PostgreSQL muvaffaqiyatli ulandi!"

# DB to'liq tayyor bo'lishi uchun qo'shimcha 3 soniya
sleep 3

echo "Migratsiyalarni bajarish..."
MAX_RETRIES=5
RETRY=0
until python manage.py migrate --noinput; do
  RETRY=$((RETRY+1))
  if [ $RETRY -ge $MAX_RETRIES ]; then
    echo "Migratsiya $MAX_RETRIES marta urinishdan keyin ham muvaffaqiyatsiz!"
    exit 1
  fi
  echo "Migratsiya muvaffaqiyatsiz, $RETRY/$MAX_RETRIES. 5 soniya kutilmoqda..."
  sleep 5
done
echo "Migratsiyalar muvaffaqiyatli bajarildi!"

echo "Static fayllarni yig'ish..."
python manage.py collectstatic --noinput || true

echo "Konteyner buyrug'i ishga tushmoqda: $@"
exec "$@"
