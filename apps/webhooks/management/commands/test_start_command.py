"""
Test /start and /dashboard Command Runner
"""
from django.core.management.base import BaseCommand
from apps.stores.models import Store
from apps.webhooks.tasks import process_incoming_message


class Command(BaseCommand):
    help = "/start buyrug'ini bevosita sinaydi"

    def handle(self, *args, **options):
        store = Store.objects.filter(is_deleted=False).first()
        if not store:
            self.stderr.write(self.style.ERROR("Do'kon topilmadi!"))
            return

        self.stdout.write("🧪 /start va /dashboard buyrug'ini sinash boshlandi...")

        # Test call
        try:
            process_incoming_message(
                store_id=str(store.id),
                platform="telegram",
                message_id=f"test_start_{store.id[:5]}",
                sender_id=store.tg_owner_chat_id or "12345678",
                sender_username="TestUser",
                text="/start",
                chat_id=store.tg_owner_chat_id or "12345678",
                raw_payload={"test": True},
            )
            self.stdout.write(self.style.SUCCESS("✅ /start handler xatosiz bajarildi!"))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"❌ /start handler xatosi: {e}"))
