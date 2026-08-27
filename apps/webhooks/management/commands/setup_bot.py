"""
Management Command — Telegram Bot Sozlash, Bot Tavsifi, Buyruqlar va TWA Menu Button.

Ishlatish:
python manage.py setup_bot --url https://your-ngrok-url.ngrok-free.app
"""
import httpx
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.stores.models import Store
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Telegram Bot webhook, description, buyruqlar va TWA Menu buttonini o'rnatish"

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            help="HTTPS Public URL (ngrok yoki server domeni)",
        )
        parser.add_argument(
            "--twa-url",
            type=str,
            default="http://localhost:3000",
            help="Telegram Web App (TWA) frontend URL",
        )

    def handle(self, *args, **options):
        bot_token = settings.TELEGRAM_BOT_TOKEN
        if not bot_token or bot_token == "your-telegram-bot-token-here":
            self.stderr.write(self.style.ERROR("TELEGRAM_BOT_TOKEN .env faylida sozlanmagan!"))
            return

        public_url = options.get("url")
        twa_url = options.get("twa_url")

        self.stdout.write(f"🤖 Telegram Bot tekshirilmoqda (Token: {bot_token[:10]}...)...")

        # 1. Bot ma'lumotlarini olish (getMe)
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                data = res.json()
                if not data.get("ok"):
                    self.stderr.write(self.style.ERROR(f"Bot Token xato: {data}"))
                    return
                
                bot_user = data["result"]
                username = bot_user.get("username")
                self.stdout.write(self.style.SUCCESS(f"✅ Bot topildi: @{username} (ID: {bot_user['id']})"))

                # Dev rejimida test do'kon yaratish
                admin_user, _ = User.objects.get_or_create(username="admin", defaults={"email": "admin@example.com"})
                store, created = Store.objects.get_or_create(
                    owner=admin_user,
                    defaults={
                        "name": "AI Store Demo",
                        "platform": Store.Platform.TELEGRAM,
                        "tg_bot_token": bot_token,
                        "tg_bot_username": username,
                    }
                )
                store.ai_model = "gemini-3.6-flash"
                if not created and store.tg_bot_token != bot_token:
                    store.tg_bot_token = bot_token
                    store.tg_bot_username = username
                store.save()
                self.stdout.write(self.style.SUCCESS(f"🏬 Do'kon biriktirildi: {store.name}"))

                # 2. Bot Tavsifi (Dinamik Store Nomi bilan)
                description = (
                    f"🤖 {store.name} rasmiy AI sotuvchisi va yordamchisi.\n\n"
                    f"✨ 24/7 savollaringizga javob beradi va buyurtmalaringizni tezkor qabul qiladi!\n\n"
                    f"Boshlash uchun pastdagi 'START' tugmasini bosing 👇"
                )
                short_desc = f"{store.name} AI Yordamchisi"

                client.post(
                    f"https://api.telegram.org/bot{bot_token}/setMyDescription",
                    json={"description": description}
                )
                client.post(
                    f"https://api.telegram.org/bot{bot_token}/setMyShortDescription",
                    json={"short_description": short_desc}
                )
                self.stdout.write(self.style.SUCCESS(f"✅ Bot haqida dinamik tavsif o'rnatildi ({store.name})!"))

                # 3. Buyruqlar menyusi (/ tugmasini bossa chiqadigan menyu)
                commands = [
                    {"command": "start", "description": "🤖 Botni ishga tushirish"},
                    {"command": "help", "description": "❓ Yordam va ko'rsatmalar"},
                ]
                client.post(
                    f"https://api.telegram.org/bot{bot_token}/setMyCommands",
                    json={"commands": commands}
                )
                self.stdout.write(self.style.SUCCESS("✅ Telegram / buyruqlar menyusi o'rnatildi!"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Telegram API ga ulanishda xato: {e}"))
            return

        # 4. Webhook o'rnatish (agar URL berilgan bo'lsa)
        if public_url:
            webhook_endpoint = f"{public_url.rstrip('/')}/webhook/telegram/{bot_token}/"
            self.stdout.write(f"🔗 Webhook o'rnatilmoqda: {webhook_endpoint}")
            
            payload = {
                "url": webhook_endpoint,
                "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
            }
            with httpx.Client(timeout=10.0) as client:
                res = client.post(f"https://api.telegram.org/bot{bot_token}/setWebhook", json=payload)
                res_data = res.json()
                if res_data.get("ok"):
                    self.stdout.write(self.style.SUCCESS("✅ Webhook muvaffaqiyatli o'rnatildi!"))
                else:
                    self.stderr.write(self.style.ERROR(f"Webhook o'rnatishda xato: {res_data}"))

        # 5. Menu Button tozalash (Oddiy mijozlar uchun standart menyu bo'ladi)
        menu_payload = {"menu_button": {"type": "default"}}
        with httpx.Client(timeout=10.0) as client:
            res = client.post(f"https://api.telegram.org/bot{bot_token}/setChatMenuButton", json=menu_payload)
            if res.json().get("ok"):
                self.stdout.write(self.style.SUCCESS("✅ Telegram menyu tugmasi standart mijoz rejimiga sozlandi!"))

        self.stdout.write(self.style.SUCCESS("🎉 Bot sozlamalari to'liq yakunlandi!"))
