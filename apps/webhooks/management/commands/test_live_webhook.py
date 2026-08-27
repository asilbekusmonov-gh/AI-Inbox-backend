"""
Synthetic Telegram Webhook Test Runner
"""
import time
import httpx
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.stores.models import Store
from apps.webhooks.tasks import process_incoming_message


class Command(BaseCommand):
    help = "Telegram Webhook va AI xabar oqimini to'g'ridan-to'g mezoniy sinaydi"

    def handle(self, *args, **options):
        bot_token = settings.TELEGRAM_BOT_TOKEN
        self.stdout.write("🧪 Webhook xabar oqimi sinovi boshlanmoqda...")

        # 1. Store ni olish
        store = Store.objects.filter(is_deleted=False).first()
        if not store:
            self.stderr.write(self.style.ERROR("Do'kon topilmadi!"))
            return

        # 2. Telegram API'dan oxirgi chat_id ni olish
        chat_id = None
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")
                results = res.json().get("result", [])
                for update in reversed(results):
                    msg = update.get("message") or update.get("edited_message")
                    if msg and "chat" in msg:
                        chat_id = str(msg["chat"]["id"])
                        break
        except Exception as e:
            self.stdout.write(f"getUpdates: {e}")

        if not chat_id:
            # Agar chat_id bo'lmasa — Do'kon egasining chat_id sindan foydalanamiz
            chat_id = store.tg_owner_chat_id or "12345678"

        self.stdout.write(f"📱 Chat ID: {chat_id} | Store: {store.name}")

        test_msg_id = f"test_msg_{int(time.time())}"
        test_text = "Salom, do'konda qanday mahsulotlar bor?"

        self.stdout.write(f"🤖 Task ishga tushirilmoqda: '{test_text}'")

        # 3. Taskni to'g'ridan-to'g'ri chaqirish
        try:
            res = process_incoming_message(
                store_id=str(store.id),
                platform="telegram",
                message_id=test_msg_id,
                sender_id=chat_id,
                sender_username="AsilbekTest",
                text=test_text,
                chat_id=chat_id,
                raw_payload={"test": True},
            )
            self.stdout.write(self.style.SUCCESS("✅ Task muvaffaqiyatli yakunlandi! Telegram ilovangizni tekshiring!"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"❌ Task bajarishda xato: {e}"))
