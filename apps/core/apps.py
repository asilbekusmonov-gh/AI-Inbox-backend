from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Yadro"

    def ready(self):
        # Production konfiguratsiyasi tekshiruvlarini ro'yxatdan
        # o'tkazamiz (apps/core/checks.py) — `manage.py check`,
        # `migrate` va `runserver` vaqtida avtomatik ishlaydi.
        from . import checks  # noqa: F401
