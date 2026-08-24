"""
Celery konfiguratsiyasi — Social-Commerce AI Inbox
"""
import os
from celery import Celery

# Django settings'ni Celery'ga ko'rsatamiz
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ai_inbox_backend.settings")

app = Celery("ai_inbox_backend")

# settings.py'dagi CELERY_ boshlanadigan o'zgaruvchilarni oladi
app.config_from_object("django.conf:settings", namespace="CELERY")

# Barcha app'lardagi tasks.py fayllarini avtomatik topadi
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Celery ishlayotganini tekshirish uchun test task"""
    print(f"Request: {self.request!r}")
