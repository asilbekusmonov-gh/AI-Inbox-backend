"""
Product (Mahsulot) modeli — Multi-tenant, Soft Delete.

Har bir mahsulot bitta Do'konga (Store) tegishli.
AI mijoz savol berganida DB'dan mahsulotlarni qidiradi
va real narx, stock hamda ma'lumotlarni kontekstga qo'shadi.
"""
from django.db import models
from django.db.models import Q
from apps.core.models import BaseModel


class Product(BaseModel):
    """
    Do'kon mahsuloti.
    """

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="products",
        help_text="Qaysi do'konga tegishli mahsulot"
    )
    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Mahsulot nomi (masalan: 'Nike Air Max 270')"
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Mahsulot tavsifi, rangi, o'lchamlari va xususiyatlari"
    )
    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Mahsulot narxi (so'm)"
    )
    stock = models.IntegerField(
        default=0,
        help_text="Ombordagi soni (stock count)"
    )
    sku = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Mahsulot artikuli / SKU"
    )
    category = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Kategoriya (masalan: 'Poyabzal', 'Kiyim')"
    )
    category_type = models.CharField(
        max_length=30,
        default="e_commerce",
        db_index=True,
        help_text="Mahsulot/Kurs/Xizmat sohasi (e_commerce, education, services)"
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Turli xil sohalarga mos dinamik ma'lumotlar (JSONB)"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Mahsulot sotuvda bormi"
    )

    class Meta:
        verbose_name = "Mahsulot"
        verbose_name_plural = "Mahsulotlar"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "is_active"], name="prod_store_active_idx"),
            models.Index(fields=["store", "name"], name="prod_store_name_idx"),
            models.Index(fields=["store", "price"], name="prod_store_price_idx"),
        ]

    def __str__(self):
        return f"{self.name} - {self.price:,.0f} so'm ({self.store.name})"

    @classmethod
    def search_for_ai(cls, store, query_text: str, limit: int = 5):
        """
        Mijoz xabaridagi so'zlardan kelib chiqib tegishli mahsulotlarni qidiradi.
        Agar mos mahsulot topilmasa, aktiv mahsulotlardan saralab beradi.
        """
        if not store:
            return cls.objects.none()

        cat_type = getattr(store, "category_type", "e_commerce") or "e_commerce"
        base_qs = cls.objects.filter(
            store=store,
            category_type=cat_type,
            is_active=True,
            is_deleted=False
        )

        if not query_text or not query_text.strip():
            return base_qs[:limit]

        words = [w.strip() for w in query_text.split() if len(w.strip()) > 2]
        if not words:
            return base_qs[:limit]

        # Name yoki description bo'yicha qidiruv
        q_objects = Q()
        for word in words:
            q_objects |= Q(name__icontains=word) | Q(description__icontains=word) | Q(category__icontains=word)

        results = base_qs.filter(q_objects).distinct()[:limit]

        # Topilmasa eng so'nggi aktiv mahsulotlarni qaytaradi
        if not results.exists():
            return base_qs[:limit]

        return results
