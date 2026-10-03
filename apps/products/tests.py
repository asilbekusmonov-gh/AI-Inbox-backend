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
from rest_framework.test import APITestCase

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
