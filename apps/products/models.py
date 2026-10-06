"""
Product (Mahsulot) modeli — Multi-tenant, Soft Delete.

Har bir mahsulot bitta Do'konga (Store) tegishli.
AI mijoz savol berganida DB'dan mahsulotlarni qidiradi
va real narx, stock hamda ma'lumotlarni kontekstga qo'shadi.
"""
from django.db import models
from django.db.models import Q
from apps.core.models import BaseModel

# ⚠️ Jonli holatda aniqlangan jiddiy xato: mijozlar ko'pincha Kirill
# alifbosida yozadi ("нолдан"), lekin do'kon egalari katalogni deyarli
# doim Lotin alifbosida to'ldiradi ("noldan"). `icontains` matn qidiruvi
# ikki alifboni bir-biriga mos deb bilmaydi — natijada mijoz Kirillda
# yozsa, haqiqiy mos kurs (masalan "Beginner" kursi) HECH QACHON
# topilmaydi. Avval bu "ishlayotganga" o'xshardi, chunki mos kelmaganda
# pastdagi FALLBACK ("hech narsa topilmasa — barcha aktiv mahsulotlarni
# qaytar") ishga tushib, tasodifan barchasi ko'rsatilardi — lekin suhbat
# tarixida biror LOTIN/umumiy so'z (masalan "IELTS") haqiqiy moslik
# topsa, fallback ishga tushmay, FAQAT shu (noto'g'ri) natija qaytardi,
# va AI haqiqatda mavjud "Beginner" kursini "mavjud emas" deb aytib
# qo'ydi. Shuning uchun qidiruv so'zi Kirilldan Lotinga ham
# transliteratsiya qilinib, ikkalasi bo'yicha ham qidiriladi.
_UZ_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'",
    "ы": "i", "э": "e", "ю": "yu", "я": "ya", "ь": "",
    "ғ": "g'", "қ": "q", "ў": "o'", "ҳ": "h",
}


def transliterate_uz_cyrillic_to_latin(text: str) -> str:
    """O'zbek Kirill matnini (taxminiy, qidiruv uchun yetarli aniqlikda) Lotinga o'giradi."""
    return "".join(_UZ_CYRILLIC_TO_LATIN.get(ch.lower(), ch) for ch in text)


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
        default="education",
        db_index=True,
        help_text="Mahsulot/Kurs/Xizmat sohasi (education, services)"
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

        cat_type = getattr(store, "category_type", "education") or "education"
        base_qs = cls.objects.filter(
            store=store,
            category_type=cat_type,
            is_active=True,
            is_deleted=False
        )

        # ⚠️ BUG FIX: agar do'konning BARCHA aktiv mahsulotlari soni
        # `limit`dan kam yoki teng bo'lsa, so'z-moslik filtri umuman
        # KERAK EMAS — baribir hammasi sig'adi. Jonli holatda aniqlangan
        # xato: mijoz umumiy ("kurs haqida ma'lumot bering") so'rov
        # yuborganda, filtr mijoz so'zlari bilan TASODIFIY mos kelmagan
        # mahsulotlarni (masalan "Frontend Development", "Python Backend
        # Development") natijadan butunlay OLIB TASHLAR edi — garchi
        # ularning soni limitga sig'sa ham. Katalog kichik bo'lsa, filtr
        # o'rniga to'g'ridan-to'g'ri HAMMASINI qaytarish xavfsizroq.
        total_active = base_qs.count()
        if total_active <= limit:
            return base_qs[:limit]

        if not query_text or not query_text.strip():
            return base_qs[:limit]

        words = [w.strip() for w in query_text.split() if len(w.strip()) > 2]
        if not words:
            return base_qs[:limit]

        # Name yoki description bo'yicha qidiruv — har bir so'z UCHUN,
        # Kirillcha bo'lsa Lotincha transliteratsiyasi bo'yicha HAM
        # qidiriladi (katalog deyarli doim Lotinda to'ldirilgani uchun).
        q_objects = Q()
        for word in words:
            q_objects |= Q(name__icontains=word) | Q(description__icontains=word) | Q(category__icontains=word)
            translit = transliterate_uz_cyrillic_to_latin(word)
            if translit.lower() != word.lower():
                q_objects |= (
                    Q(name__icontains=translit) | Q(description__icontains=translit) | Q(category__icontains=translit)
                )

        results = base_qs.filter(q_objects).distinct()[:limit]

        # Topilmasa eng so'nggi aktiv mahsulotlarni qaytaradi
        if not results.exists():
            return base_qs[:limit]

        return results
