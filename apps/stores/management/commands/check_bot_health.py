"""
Management Command — shaxsiy bot ulagan, aktiv do'konlarning webhook
sog'ligini qo'lda (deploy'dan keyin, yoki tunnel yangilangandan keyin)
tezda tekshirish uchun.

Odatda bu Celery Beat orqali har 20 daqiqada avtomatik ishlaydi
(apps.stores.tasks.check_all_bot_health) — bu buyruq esa shuni darhol,
qo'lda chaqirish uchun.

Ishlatish:
python manage.py check_bot_health
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Shaxsiy bot ulagan do'konlarning webhook sog'ligini darhol tekshiradi."

    def handle(self, *args, **options):
        from apps.stores.tasks import check_all_bot_health

        result = check_all_bot_health.run()
        self.stdout.write(self.style.SUCCESS(
            f"✅ Tekshirildi: {result['checked']} ta | Xato: {result['unhealthy']} ta"
        ))
