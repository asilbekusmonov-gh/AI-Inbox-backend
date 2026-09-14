"""
Management Command — Har bir do'konning tanlangan Gemini modeli haqiqatan
javob berayotganini tekshiradi.

Nima uchun kerak: bir marta "gemini-2.5-flash" va "gemini-2.0-flash" bu
loyihaning API kaliti uchun jimgina o'chib qolgan edi (apps/chat/ai_service.py
dagi WORKING_FALLBACK_MODEL izohiga qarang) — bu birinchi marta faqat
mijozlar shikoyat qilganda payqaldi. Bu buyruq shu holatni oldindan
(masalan har kuni cron orqali, yoki deploy oldidan qo'lda) aniqlash uchun:
har bir aktiv do'konning `ai_model`iga chindan ham 1 tokenlik so'rov
yuboradi va javob bera olmagan do'konlarni ro'yxatlaydi.

Ishlatish:
python manage.py check_ai_health
"""
from django.core.management.base import BaseCommand

from apps.stores.models import Store


class Command(BaseCommand):
    help = "Har bir aktiv do'konning Gemini modeli haqiqatan ishlayotganini tekshiradi."

    def handle(self, *args, **options):
        import google.generativeai as genai
        from django.conf import settings

        api_key = settings.GEMINI_API_KEY
        if not api_key:
            self.stderr.write(self.style.ERROR("GEMINI_API_KEY sozlanmagan!"))
            return

        genai.configure(api_key=api_key)

        stores = Store.objects.filter(is_active=True, ai_active=True)
        checked_models = {}
        failures = []

        for store in stores:
            model_name = store.ai_model
            if model_name in checked_models:
                if not checked_models[model_name]:
                    failures.append((store, model_name, checked_models[model_name + "_error"]))
                continue

            try:
                model = genai.GenerativeModel(model_name)
                model.generate_content(
                    "ping",
                    generation_config=genai.types.GenerationConfig(max_output_tokens=5),
                )
                checked_models[model_name] = True
                self.stdout.write(self.style.SUCCESS(f"OK  {model_name} (do'kon: {store.name})"))
            except Exception as e:
                checked_models[model_name] = False
                checked_models[model_name + "_error"] = str(e)
                failures.append((store, model_name, str(e)))
                self.stdout.write(self.style.ERROR(f"XATO {model_name} (do'kon: {store.name}): {e}"))

        if failures:
            self.stderr.write(
                self.style.ERROR(
                    f"\n{len(failures)} ta do'konning AI modeli javob bermadi — "
                    f"ushbu do'konlarning mijozlari FALLBACK_RESPONSE oladi, jonli AI javobini emas."
                )
            )
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(f"\nHammasi joyida — {stores.count()} ta do'kon tekshirildi."))
