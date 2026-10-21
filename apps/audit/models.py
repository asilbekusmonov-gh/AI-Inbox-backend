"""
AuditLog — Super Admin / Ops panelidagi muhim (sezilarli) amallarning tarixi.

Qasddan `BaseModel`dan meros OLMAYDI: audit yozuvi o'zgarmas (immutable)
bo'lishi kerak — unda "soft delete"/"restore" tushunchasi bo'lishi shart
emas, aks holda kim audit yozuvini "o'chirdi" degan yangi savol tug'iladi.
"""
import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    class Action(models.TextChoices):
        BUSINESS_CREATED = "business_created", "Biznes yaratildi"
        BUSINESS_DISABLED = "business_disabled", "Biznes to'xtatildi"
        BUSINESS_REACTIVATED = "business_reactivated", "Biznes qayta faollashtirildi"
        BUSINESS_DELETED = "business_deleted", "Biznes butunlay o'chirildi"
        TWA_ACCESS_REVOKED = "twa_access_revoked", "TWA kirish huquqi bekor qilindi"
        TWA_ACCESS_RESTORED = "twa_access_restored", "TWA kirish huquqi tiklandi"
        TWA_ACCESS_CHANGED = "twa_access_changed", "TWA foydalanuvchisi almashtirildi"
        # ⚠️ Yuqoridagi uchtasi — SUPER ADMIN amallari. Bu esa Telegram'da
        # `/start admin_<uuid>` bosilganda egalik HAQIQATAN kimga o'tganini
        # yozadi (avval bu yozilmasdi: "kim ega bo'ldi?" savoliga javob yo'q edi).
        TWA_OWNER_ASSIGNED = "twa_owner_assigned", "TWA egasi biriktirildi"
        TOKEN_CONNECTED = "token_connected", "Bot tokeni ulandi"
        TOKEN_DISCONNECTED = "token_disconnected", "Bot tokeni uzildi"
        SUBSCRIPTION_PLAN_CHANGED = "subscription_plan_changed", "Obuna rejasi o'zgartirildi"
        SUBSCRIPTION_DATE_CHANGED = "subscription_date_changed", "Obuna tugash sanasi o'zgartirildi"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
        help_text="Amalni bajargan admin (User o'chirilsa ham yozuv qoladi)",
    )
    actor_display = models.CharField(
        max_length=255,
        help_text="Amal bajarilgan vaqtdagi ko'rinadigan ism — tarixiy 'surat'",
    )
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)

    target_store = models.ForeignKey(
        "stores.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    target_store_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Amal bajarilgan vaqtdagi do'kon nomi — tarixiy 'surat'",
    )

    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_store", "created_at"], name="audit_store_created_idx"),
            models.Index(fields=["action", "created_at"], name="audit_action_created_idx"),
        ]

    def __repr__(self):
        return f"<AuditLog id={self.id} action={self.action} store={self.target_store_name!r}>"


class PlatformError(models.Model):
    """
    Platforma darajasidagi TEXNIK xatolar jurnali (Celery task yiqilishi,
    AI javob berolmaganda, lid saqlashda nosozlik) — "Tizim" sahifasidagi
    xato monitoring paneli uchun. `AuditLog`dan farqi: bu inson bajargan
    AMAL emas, tizimning o'zida yuz bergan kutilmagan holat.
    Yozish har doim best-effort (`apps.audit.services.log_platform_error`
    orqali) — xato logging'ning o'zi hech qachon asosiy oqimni to'xtatmasin.
    """

    class Source(models.TextChoices):
        CELERY_TASK = "celery_task", "Celery vazifasi"
        AI_SERVICE = "ai_service", "AI javobi"
        LEAD_CREATION = "lead_creation", "Lid saqlash"
        CRM_SYNC = "crm_sync", "CRM sinxronizatsiyasi"
        OWNER_NOTIFICATION = "owner_notification", "Egaga xabarnoma"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=40, choices=Source.choices, db_index=True)
    message = models.TextField()

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="platform_errors",
    )
    store_name = models.CharField(max_length=255, blank=True, default="")

    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["source", "created_at"], name="plaerr_source_created_idx"),
        ]

    def __repr__(self):
        return f"<PlatformError id={self.id} source={self.source} store={self.store_name!r}>"
