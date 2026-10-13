"""
Product Views — DRF ModelViewSet (Multi-tenant).

Qoidalar:
- Telegram initData yoki JWT bilan autentifikatsiya bo'lgan
  do'kon egasi o'z do'konining mahsulotlarini boshqaradi.
- Autentifikatsiya bo'lmagan so'rovlar 401 bilan rad etiladi.
"""
import logging

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from .models import Product
from .serializers import ProductSerializer
from .ai_service import generate_product_description
from apps.core.authentication import get_store_from_request

logger = logging.getLogger("apps.products")

# "Tezkor qo'shish" (fayl orqali) rejimida qabul qilinadigan fayl turlari —
# Gemini'ga to'g'ridan-to'g'ri (matn ajratib olish kutubxonasisiz) inline
# ma'lumot sifatida yuborsa bo'ladigan turlar bilan cheklangan.
_ANALYZE_FILE_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/plain",
    # ⚠️ .md fayl brauzerda odatda "text/markdown" MIME turi bilan yuklanadi
    # (ba'zida umuman aniqlanmay bo'sh qoladi) — avval bu whitelistda yo'q
    # edi, shuning uchun oddiy matn fayli (mazmunan "text/plain"dan farqi
    # yo'q) ham rad etilardi. Jonli holatda aniqlandi.
    "text/markdown",
}
_ANALYZE_FILE_MAX_SIZE = 10 * 1024 * 1024


class ProductViewSet(viewsets.ModelViewSet):
    """
    Do'kon mahsulotlarini CRUD qilish uchun ViewSet.
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description", "sku", "category"]
    ordering_fields = ["created_at", "price", "stock", "name"]
    ordering = ["-created_at"]

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
        return get_store_from_request(self.request)

    def get_queryset(self):
        """Store va active category_type bo'yicha filterlangan mahsulotlar ro'yxati"""
        target_store = self._get_target_store()
        if not target_store:
            return Product.objects.none()

        cat_type = self.request.query_params.get("category_type") or getattr(target_store, "category_type", "education")
        return Product.objects.filter(store=target_store, category_type=cat_type, is_deleted=False)

    def perform_create(self, serializer):
        """Yangi mahsulot yaratilganda target store va uning category_type biriktiriladi"""
        target_store = self._get_target_store()
        if not target_store:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("Do'kon topilmadi")
        cat_type = self.request.data.get("category_type") or getattr(target_store, "category_type", "education")
        serializer.save(store=target_store, category_type=cat_type)

    def perform_destroy(self, instance):
        """Soft Delete: bazadan o'chirilmaydi, is_deleted=True bo'ladi"""
        instance.soft_delete()

    @action(detail=False, methods=["post"], url_path="generate-description")
    def generate_description(self, request):
        """
        AI orqali mahsulot/kurs/xizmat tavsifini generatsiya qiladi:
        POST /api/v1/products/generate-description/
        Body: {"name": "...", "category": "...", "price": ..., "stock": ...}
        """
        target_store = self._get_target_store()
        if not target_store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "Nomi kiritilmagan"}, status=status.HTTP_400_BAD_REQUEST)

        category = (request.data.get("category") or "").strip()
        category_type = request.data.get("category_type") or getattr(target_store, "category_type", "education")
        price = request.data.get("price")
        stock = request.data.get("stock")

        try:
            description = generate_product_description(
                name=name,
                category_type=category_type,
                category=category,
                price=price,
                stock=stock,
            )
        except Exception as e:
            logger.error(f"[AI Description] Generatsiya xatosi: {e} | store={target_store.name}", exc_info=True)
            return Response(
                {"error": "AI tavsif yaratib bo'lmadi. Birozdan so'ng qayta urinib ko'ring."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"description": description}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="analyze-file", parser_classes=[MultiPartParser])
    def analyze_file(self, request):
        """
        "Tezkor qo'shish" rejimi: egasi Nomi+Narxini kiritib, kurs/xizmat
        haqidagi faylni (rasm/PDF/matn) biriktiradi — AI faylni o'qib,
        formaning qolgan maydonlarini (tavsif, kategoriya, davomiyligi,
        manzil, qo'shimcha ustunlar) avtomatik chiqarib beradi. Natija
        saqlanmaydi — frontend buni formaga to'ldirib ko'rsatadi, owner
        ko'rib chiqib "Saqlash"ni bosgandan keyingina haqiqiy Product
        yozuvi hosil bo'ladi (xuddi generate-description kabi).

        POST /api/v1/products/analyze-file/  (multipart/form-data)
        Body: file=<fayl>, name="..." (ixtiyoriy), price="..." (ixtiyoriy)
        """
        target_store = self._get_target_store()
        if not target_store:
            return Response({"error": "Do'kon topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"error": "Fayl biriktirilmagan"}, status=status.HTTP_400_BAD_REQUEST)

        mime_type = uploaded_file.content_type or ""
        if mime_type not in _ANALYZE_FILE_ALLOWED_MIME_TYPES:
            return Response(
                {"error": f"Fayl turi qo'llab-quvvatlanmaydi ({mime_type or 'nomaʼlum'}). PDF, JPG/PNG/WEBP rasm yoki TXT/MD matn fayl yuklang."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded_file.size > _ANALYZE_FILE_MAX_SIZE:
            return Response({"error": "Fayl hajmi 10 MB dan oshmasligi kerak"}, status=status.HTTP_400_BAD_REQUEST)

        name = (request.data.get("name") or "").strip()
        price = request.data.get("price")
        category_type = request.data.get("category_type") or getattr(target_store, "category_type", "education")

        from .ai_service import analyze_product_file

        try:
            result = analyze_product_file(
                file_bytes=uploaded_file.read(),
                mime_type=mime_type,
                category_type=category_type,
                name=name,
                price=price,
            )
        except Exception as e:
            logger.error(f"[AI File Analyze] Tahlil xatosi: {e} | store={target_store.name}", exc_info=True)
            return Response(
                {"error": "AI faylni tahlil qila olmadi. Birozdan so'ng qayta urinib ko'ring yoki to'liq shaklni ishlating."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        custom_fields = result.get("custom_fields")
        if not isinstance(custom_fields, list):
            custom_fields = []
        cleaned_custom_fields = [
            {"key": str(f.get("key", "")).strip(), "value": str(f.get("value", "")).strip()}
            for f in custom_fields
            if isinstance(f, dict) and str(f.get("key", "")).strip() and str(f.get("value", "")).strip()
        ][:5]

        return Response(
            {
                # ⚠️ Egasi "Nomi"/"Narxi"ni bo'sh qoldirgan bo'lsa ham
                # (endi majburiy emas) formani to'ldirish uchun — AI
                # fayldan aniqlagan nomi/narxi shu yerda qaytariladi,
                # frontend buni ham xuddi boshqa maydonlar kabi
                # "o'zim yozganim bo'lmasa, AI topganini olaman" tartibida
                # qo'llaydi.
                "name": str(result.get("name") or "").strip(),
                "price": result.get("price") or 0,
                "description": str(result.get("description") or "").strip(),
                "category": str(result.get("category") or "").strip(),
                "stock": result.get("stock") or 0,
                "duration": str(result.get("duration") or "").strip(),
                "location": str(result.get("location") or "").strip(),
                # Fayldagi TO'LIQ matn — `Product.full_info`ga saqlanadi va
                # mijoz kontakt qoldirishni rad etib "shu yerda ayting"
                # deganda aynan shu yuboriladi (apps/chat/ai_service.py,
                # SEND_FULL_INFO). Qisqartirilmaydi.
                "full_text": str(result.get("full_text") or "").strip(),
                "custom_fields": cleaned_custom_fields,
            },
            status=status.HTTP_200_OK,
        )

