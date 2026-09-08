"""
Gemini Model Lister & Tester
"""
import google.generativeai as genai
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Gemini API'da mavjud bo'lgan barcha modellarni ro'yxatlaydi"

    def handle(self, *args, **options):
        genai.configure(api_key=settings.GEMINI_API_KEY)

        self.stdout.write("--- Gemini API Mavjud Modellar ---")
        try:
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    self.stdout.write(f"Model nomi: {m.name}")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Xato: {e}"))
