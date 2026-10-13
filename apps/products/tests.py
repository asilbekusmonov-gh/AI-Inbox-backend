"""
POST /api/v1/products/analyze-file/ ("Tezkor qo'shish" — fayl orqali AI
tahlil) uchun testlar. Gemini haqiqiy chaqirilmaydi — bu Gemini'ning
kunlik bepul limitiga (20/kun) bog'liq bo'lmasligi va tezkor ishlashi
uchun ataylab mock qilingan.
"""
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.products.models import Product, transliterate_uz_cyrillic_to_latin
from apps.stores.models import Store


class AnalyzeProductFileTestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="analyze_owner", password="x")
        self.store = Store.objects.create(owner=self.owner, name="Test Markaz", category_type="education")

    def _upload(self, **extra):
        payload = {
            "file": SimpleUploadedFile("brochure.png", b"fake-image-bytes", content_type="image/png"),
        }
        payload.update(extra)
        return self.client.post("/api/v1/products/analyze-file/", payload, format="multipart")

    def test_unauthenticated_request_is_rejected(self):
        response = self._upload()
        self.assertEqual(response.status_code, 401)

    def test_missing_file_returns_400(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post("/api/v1/products/analyze-file/", {}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_unsupported_mime_type_returns_400(self):
        self.client.force_authenticate(user=self.owner)
        response = self._upload(
            file=SimpleUploadedFile("brochure.docx", b"fake-bytes", content_type="application/msword")
        )
        self.assertEqual(response.status_code, 400)

    @patch("apps.products.ai_service.analyze_product_file")
    def test_success_returns_parsed_fields_trimmed_to_five_custom_fields(self, mock_analyze):
        mock_analyze.return_value = {
            "description": "IELTS uchun tayyorlov kursi.",
            "category": "Chet tillari",
            "stock": 12,
            "duration": "3 oy",
            "location": "Chilonzor",
            "custom_fields": [
                {"key": f"Maydon{i}", "value": f"Qiymat{i}"} for i in range(7)
            ],
        }
        self.client.force_authenticate(user=self.owner)
        response = self._upload(name="IELTS kursi", price="450000")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["description"], "IELTS uchun tayyorlov kursi.")
        self.assertEqual(data["category"], "Chet tillari")
        self.assertEqual(data["stock"], 12)
        self.assertEqual(data["duration"], "3 oy")
        self.assertEqual(data["location"], "Chilonzor")
        self.assertEqual(len(data["custom_fields"]), 5)

        mock_analyze.assert_called_once()
        call_kwargs = mock_analyze.call_args.kwargs
        self.assertEqual(call_kwargs["name"], "IELTS kursi")
        self.assertEqual(call_kwargs["category_type"], "education")

    @patch("apps.products.ai_service.analyze_product_file")
    def test_ai_error_returns_502(self, mock_analyze):
        mock_analyze.side_effect = ValueError("AI javobi to'g'ri JSON emas")
        self.client.force_authenticate(user=self.owner)
        response = self._upload()
        self.assertEqual(response.status_code, 502)

    @patch("apps.products.ai_service.analyze_product_file")
    def test_markdown_file_is_accepted(self, mock_analyze):
        # ⚠️ Jonli holatda .md fayl "text/markdown" MIME turi bilan
        # yuklangani uchun avval rad etilgan edi — endi whitelistga
        # qo'shilgan, text/plain bilan bir xil ishlov beriladi.
        mock_analyze.return_value = {"description": "Tavsif", "category": "", "stock": 0, "duration": "", "location": "", "custom_fields": []}
        self.client.force_authenticate(user=self.owner)
        response = self._upload(
            file=SimpleUploadedFile("kurs.md", b"# IELTS kursi\nNarxi 900000 som", content_type="text/markdown"),
        )
        self.assertEqual(response.status_code, 200)
        mock_analyze.assert_called_once()
        self.assertEqual(mock_analyze.call_args.kwargs["mime_type"], "text/markdown")

    @patch("apps.products.ai_service.analyze_product_file")
    def test_name_and_price_not_required_and_returned_from_ai(self, mock_analyze):
        # ⚠️ Nomi/narxi endi "Fayl orqali" rejimida majburiy emas — AI
        # fayldan topgan nomi/narxi javobda qaytariladi, frontend buni
        # bo'sh maydonlarni to'ldirish uchun ishlatadi.
        mock_analyze.return_value = {
            "name": "IELTS tayyorlov kursi",
            "price": 900000,
            "description": "Tavsif", "category": "", "stock": 0, "duration": "", "location": "", "custom_fields": [],
        }
        self.client.force_authenticate(user=self.owner)
        response = self._upload()  # name/price berilmagan

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "IELTS tayyorlov kursi")
        self.assertEqual(data["price"], 900000)
        call_kwargs = mock_analyze.call_args.kwargs
        self.assertEqual(call_kwargs["name"], "")
        self.assertIsNone(call_kwargs["price"])


class AnalyzeFileFullTextTestCase(APITestCase):
    """
    Fayldagi TO'LIQ matn javobda qaytishi kerak — u `Product.full_info`ga
    saqlanadi va mijoz kontakt qoldirishni rad etganda AYNAN shu matn
    yuboriladi (apps/chat/ai_service.py, SEND_FULL_INFO).
    """

    def setUp(self):
        self.owner = User.objects.create_user(username="fulltext_owner", password="x")
        self.store = Store.objects.create(
            owner=self.owner, name="Full Text Markaz", category_type="education",
        )

    @patch("apps.products.ai_service.analyze_product_file")
    def test_full_text_is_returned_in_response(self, mock_analyze):
        full = "🌟 Foundation 🌟\n\n📅 Davomiyligi: 3 oy\n💵 Narxi: 1 500 000 so'm"
        mock_analyze.return_value = {
            "name": "Foundation", "price": 1500000, "description": "Qisqa tavsif",
            "category": "", "stock": 0, "duration": "", "location": "",
            "full_text": full, "custom_fields": [],
        }
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/v1/products/analyze-file/",
            {"file": SimpleUploadedFile("kurs.md", b"# Foundation", content_type="text/markdown")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        # Matn qisqartirilmasdan, aynan o'zi qaytishi kerak
        self.assertEqual(response.json()["full_text"], full)

    @patch("apps.products.ai_service.analyze_product_file")
    def test_missing_full_text_becomes_empty_string(self, mock_analyze):
        mock_analyze.return_value = {
            "name": "Foundation", "price": 0, "description": "", "category": "",
            "stock": 0, "duration": "", "location": "", "custom_fields": [],
        }
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/v1/products/analyze-file/",
            {"file": SimpleUploadedFile("kurs.md", b"matn", content_type="text/markdown")},
            format="multipart",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_text"], "")


class ProductFullInfoSerializerTestCase(APITestCase):
    """`full_info` serializer oq ro'yxatida bo'lishi kerak, aks holda
    frontend yuborgan to'liq matn jimgina tashlab yuborilardi."""

    def setUp(self):
        self.owner = User.objects.create_user(username="fullinfo_api_owner", password="x")
        self.store = Store.objects.create(
            owner=self.owner, name="API Markaz", category_type="education",
        )

    def test_full_info_is_saved_through_api(self):
        self.client.force_authenticate(user=self.owner)
        full = "To'liq kurs ma'lumoti\nNarxi: 1 500 000 so'm"
        response = self.client.post(
            "/api/v1/products/",
            {"name": "Foundation", "price": 1500000, "stock": 10, "full_info": full},
            format="json",
        )

        self.assertIn(response.status_code, (200, 201), response.content)
        product = Product.objects.get(store=self.store, name="Foundation")
        self.assertEqual(product.full_info, full)


class CyrillicTransliterationTestCase(TestCase):
    def test_basic_word_transliterated(self):
        self.assertEqual(transliterate_uz_cyrillic_to_latin("нолдан"), "noldan")

    def test_special_uzbek_letters(self):
        self.assertEqual(transliterate_uz_cyrillic_to_latin("ғўқҳ"), "g'o'qh")

    def test_latin_text_passes_through_unchanged(self):
        self.assertEqual(transliterate_uz_cyrillic_to_latin("noldan"), "noldan")


class SearchForAiCyrillicMatchTestCase(TestCase):
    """
    Jonli holatda aniqlangan xato: mijoz Kirillda ("нолдан") yozganda,
    katalogda Lotin alifbosida ("noldan") yozilgan kurs TOPILMASLIGI
    kerak emas edi — bu test aynan shu regressiyani ushlab qoladi.
    """

    def setUp(self):
        owner = User.objects.create_user(username="cyr_search_owner", password="x")
        self.store = Store.objects.create(owner=owner, name="Til Markazi", category_type="education")
        self.beginner = Product.objects.create(
            store=self.store, category_type="education",
            name="English for Beginners", price=500000,
            description="Ingliz tilini noldan mukammal o'rganib, erkin so'zlashish",
        )
        self.ielts = Product.objects.create(
            store=self.store, category_type="education",
            name="Professional IELTS Preparation", price=750000,
            description="IELTS'dan 7.0+ ball olishni xohlaysizmi?",
        )

    def test_cyrillic_query_matches_latin_catalog_entry(self):
        results = Product.search_for_ai(self.store, "менга нолдан керак", limit=5)
        self.assertIn(self.beginner, results)

    def test_cyrillic_query_does_not_lose_match_when_combined_with_other_history(self):
        # Suhbat tarixida "IELTS" so'zi haqiqiy moslik topib, oldin
        # fallback'ni (hamma narsani ko'rsatish) ishga tushirmay qo'yardi
        # — shu sabab "Beginner" kursi butunlay yo'qolib qolardi.
        combined = "менга нолдан керак IELTS курсди нархини айтиб бериб оласизми"
        results = Product.search_for_ai(self.store, combined, limit=5)
        names = [p.name for p in results]
        self.assertIn(self.beginner.name, names)
        self.assertIn(self.ielts.name, names)


class SearchForAiSmallCatalogNoFilterTestCase(TestCase):
    """
    Jonli holatda aniqlangan xato (2026-10-06, PDP Academy): do'konda
    5 ta mahsulot bor (limit bilan AYNAN teng), mijoz umumiy ("kurs
    haqida ma'lumot bering") so'rov yuborganda, so'z-moslik filtri
    TASODIFIY ravishda 2 tasini (nomi/tavsifi so'rov so'zlari bilan mos
    kelmagani uchun) natijadan olib tashlagan — garchi hammasi limitga
    sig'sa ham. Endi katalog hajmi limitdan kam/teng bo'lsa, filtr
    umuman qo'llanmaydi.
    """

    def setUp(self):
        owner = User.objects.create_user(username="small_catalog_owner", password="x")
        self.store = Store.objects.create(owner=owner, name="Kichik Katalog Markazi", category_type="education")
        self.products = [
            Product.objects.create(
                store=self.store, category_type="education",
                name=name, price=500000, description=desc,
            )
            for name, desc in [
                ("Java Backend & Spring Boot Development", "Enterprise darajasidagi Java va Spring Boot kursi"),
                ("C++ Foundation (Dasturlash Asoslari va Algoritmlar)", "Dasturlashni noldan puxta o'rganing"),
                ("Practical Cybersecurity & Ethical Hacking", "Kiberxavfsizlik va etik hakerlik bo'yicha amaliyot"),
                ("Frontend Development (HTML, CSS, JavaScript & React)", "Noldan Junior Frontend dasturchi bo'ling"),
                ("Python Backend Development", "Noldan Python Backend va Django'ni professional o'rganing"),
            ]
        ]

    def test_generic_query_returns_all_products_when_catalog_fits_limit(self):
        results = Product.search_for_ai(
            self.store, "Ассаламу алейкум курс хакида малумот беринг", limit=5,
        )
        names = {p.name for p in results}
        self.assertEqual(names, {p.name for p in self.products})

    def test_catalog_larger_than_limit_still_filters(self):
        Product.objects.create(
            store=self.store, category_type="education",
            name="Qo'shimcha Oltinchi Kurs", price=500000, description="Boshqa kurs",
        )
        results = Product.search_for_ai(self.store, "Python backend", limit=5)
        names = {p.name for p in results}
        self.assertIn("Python Backend Development", names)
