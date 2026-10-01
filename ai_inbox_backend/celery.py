"""
Celery konfiguratsiyasi — Social-Commerce AI Inbox
"""
import os
from celery import Celery
from celery.signals import task_failure

# Django settings'ni Celery'ga ko'rsatamiz
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_inbox_backend.settings")

app = Celery("ai_inbox_backend")

# settings.py'dagi CELERY_ boshlanadigan o'zgaruvchilarni oladi
app.config_from_object("django.conf:settings", namespace="CELERY")

# Barcha app'lardagi tasks.py fayllarini avtomatik topadi
app.autodiscover_tasks()


@task_failure.connect
def _on_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    # ⚠️ Faqat TO'LIQ yiqilgan (uncaught exception) vazifalarni ushlaydi —
    # task ichidagi try/except bilan jimgina yutilgan xatolar bu yerga
    # kirmaydi, ular o'z chaqiruv joyida alohida log_platform_error bilan
    # yoziladi ("Tizim" sahifasi, "Platforma xatolari" paneli).
    from apps.audit.services import log_platform_error

    task_name = getattr(sender, "name", "noma'lum vazifa")
    log_platform_error(
        source="celery_task",
        message=f"{task_name}: {exception}",
        metadata={"task_id": task_id},
    )


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Celery ishlayotganini tekshirish uchun test task"""
    print(f"Request: {self.request!r}")
