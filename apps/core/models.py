"""
Base Model — Barcha app modellari shu classdan meros oladi.

SaaS qoidalari:
- created_at, updated_at — avtomatik
- is_deleted — Soft Delete (hech qachon hard DELETE yo'q)
- Soft delete manager — is_deleted=True bo'lganlarni filtrlab beradi
"""
import uuid
from django.db import models


class SoftDeleteManager(models.Manager):
    """
    Default manager — faqat o'chirilmagan (is_deleted=False) yozuvlarni qaytaradi.
    Bu orqali .all() chaqirilganda deleted yozuvlar ko'rinmaydi.
    """
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class AllObjectsManager(models.Manager):
    """
    Barcha yozuvlarni qaytaradi (o'chirilganlar ham).
    Faqat admin yoki arxiv ko'rish uchun ishlatilsin.
    """
    def get_queryset(self):
        return super().get_queryset()


class BaseModel(models.Model):
    """
    Loyihadagi barcha modellar uchun asosiy abstract klass.

    Xususiyatlar:
    - UUID primary key (taxminlab bo'lmaydigan ID)
    - created_at, updated_at — avtomatik timestamps
    - is_deleted — Soft Delete maydoni
    - objects — faqat aktiv yozuvlar
    - all_objects — barcha yozuvlar (arxiv uchun)
    """
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text="Yagona identifikator (UUID)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Yaratilgan vaqt"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Oxirgi yangilangan vaqt"
    )
    is_deleted = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Soft delete — True bo'lsa yozuv o'chirilgan hisoblanadi"
    )

    # Managerlar
    objects = SoftDeleteManager()        # Default: faqat aktiv yozuvlar
    all_objects = AllObjectsManager()    # Barcha yozuvlar (admin uchun)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def soft_delete(self):
        """
        Yozuvni o'chirish — bazadan o'chmaydi, is_deleted=True bo'ladi.
        Hech qachon .delete() chaqirmang!
        """
        self.is_deleted = True
        self.save(update_fields=["is_deleted", "updated_at"])

    def restore(self):
        """O'chirilgan yozuvni qayta tiklash"""
        self.is_deleted = False
        self.save(update_fields=["is_deleted", "updated_at"])

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id}>"
