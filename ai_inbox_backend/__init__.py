# Celery'ni Django bilan birga ishga tushirish uchun
try:
    from .celery import app as celery_app
    __all__ = ("celery_app",)
except ImportError:
    pass
