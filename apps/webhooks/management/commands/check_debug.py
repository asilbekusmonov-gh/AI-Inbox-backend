"""
Diagnostic Script — Webhook va AI xatolarini aniqlash.
"""
import httpx
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.stores.models import Store
from apps.chat.ai_service import get_ai_response
from apps.customers.models import Customer


class Command(BaseCommand):
    help = "Telegram va Gemini API diagnozini o'tkazadi"

    def handle(self, *args, **options):
        bot_token = settings.TELEGRAM_BOT_TOKEN
        self.stdout.write("🔍 Diagnostika boshlandi...")

        # 1. Telegram Webhook Holati (getWebhookInfo)
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"https://api.telegram.org/bot{bot_token}/getWebhookInfo")
                data = res.json()
                self.stdout.write(self.style.SUCCESS(f"1. Telegram Webhook Info:\n   {data.get('result')}"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"1. Telegram getWebhookInfo xatosi: {e}"))

        # 2. Do'konlarni tekshirish
        stores = Store.objects.filter(is_deleted=False)
        self.stdout.write(self.style.SUCCESS(f"2. Bazada do'konlar soni: {stores.count()}"))
        for s in stores:
            self.stdout.write(f"   • Do'kon: {s.name} | Token: {s.tg_bot_token[:10] if s.tg_bot_token else 'YOQUVCHI'}... | Active: {s.is_active}")

        # 3. Gemini API testi
        self.stdout.write("3. Gemini API sinovi o'tkazilmoqda...")
        try:
            store = stores.first()
            if store:
                customer, _ = Customer.objects.get_or_create(
                    store=store,
                    platform="telegram",
                    platform_user_id="test_user_99",
                    defaults={"username": "testuser"}
                )
                ai_resp = get_ai_response(store, customer, "Salom, do'koningizda nima bor?")
                self.stdout.write(self.style.SUCCESS(f"   ✅ Gemini API Javobi: {ai_resp.text[:100]}..."))
            else:
                self.stderr.write(self.style.ERROR("   Do'kon topilmadi!"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"   ❌ Gemini API xatosi: {e}"))

        self.stdout.write("🏁 Diagnostika yakunlandi!")
