"""
Gemini Model Lister & Tester
"""
import google.generativeai as genai
from django.conf import settings

api_key = settings.GEMINI_API_KEY
genai.configure(api_key=api_key)

print("--- Gemini API Mavjud Modellar ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Model nomi: {m.name}")
except Exception as e:
    print(f"Xato: {e}")
