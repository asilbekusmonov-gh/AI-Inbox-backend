"""
Test Telegram Direct Sender
"""
import httpx
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.chat.senders import send_telegram_message


class Command(BaseCommand):
    help = "Telegram bot orqali bevosita xabar yuborishni sinash"

    def handle(self, *args, **options):
        bot_token = settings.TELEGRAM_BOT_TOKEN
        self.stdout.write("📩 Telegram bot xabar yuborish testi...")

        # Oxirgi chat_id ni Telegram API'dan olish (getUpdates)
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")
                data = res.json()
                results = data.get("result", [])
                if not results:
                    self.stderr.write(self.style.ERROR("Hech qanday chat topilmadi. Avval botga Telegram'dan yozing."))
                    return
                
                last_update = results[-1]
                message = last_update.get("message") or last_update.get("edited_message") or {}
                chat_id = str(message.get("chat", {}).get("id", ""))
                user_name = message.get("from", {}).get("first_name", "Foydalanuvchi")
                
                self.stdout.write(self.style.SUCCESS(f" Chat topildi! User: {user_name} | Chat ID: {chat_id}"))

                # Test xabari yuborish
                success = send_telegram_message(
                    bot_token=bot_token,
                    chat_id=chat_id,
                    text=f"Assalomu alaykum {user_name}! 🤖 Warmix testi muvaffaqiyatli!",
                )

                if success:
                    self.stdout.write(self.style.SUCCESS("✅ Telegram xabari foydalanuvchiga YETIB BORDI!"))
                else:
                    self.stderr.write(self.style.ERROR("❌ Telegram xabarini yuborishda xato!"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Xato: {e}"))
