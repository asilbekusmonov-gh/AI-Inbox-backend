"""
Management Command — Do'kon egasi uchun UNIKAL Telegram Admin Havolasini generatsiya qilish.

Ishlatish:
python manage.py get_admin_link --store "Zulfiya Fashion"
"""
from django.core.management.base import BaseCommand
from apps.stores.models import Store


class Command(BaseCommand):
    help = "Do'kon egasi uchun UNIKAL Telegram Admin Onboarding havolasini generatsiya qiladi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--store",
            type=str,
            required=True,
            help="Do'kon nomi yoki ID'si (masalan: 'Zulfiya Fashion' yoki 'store-1')",
        )
        parser.add_argument(
            "--bot_username",
            type=str,
            default="Ai_InboxBot",
            help="Telegram Bot username (standart: Ai_InboxBot)",
        )

    def handle(self, *args, **options):
        store_query = options["store"]
        bot_username = options["bot_username"].replace("@", "").strip()

        # Find store
        try:
            if store_query.startswith("store-") or len(store_query) == 36:
                store = Store.objects.get(id=store_query, is_deleted=False)
            else:
                store = Store.objects.filter(name__icontains=store_query, is_deleted=False).first()
                if not store:
                    raise Store.DoesNotExist
        except Store.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"❌ Do'kon topilmadi: '{store_query}'"))
            return

        # Generate unique unguessable token using Store's UUID prefix
        unique_token = str(store.id)[:8]
        admin_link = f"https://t.me/{bot_username}?start=admin_{unique_token}"
        customer_link = f"https://t.me/{bot_username}?start=store_{unique_token}"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"=== 🛍️ DO'KON: {store.name} (ID: {store.id}) ==="))
        self.stdout.write(f"👑 Admin Havolasi (100% UNIKAL — Do'kon Egasiga Yuboring):")
        self.stdout.write(self.style.WARNING(f"👉 {admin_link}"))
        self.stdout.write("")
        self.stdout.write(f"🛍️ Mijozlar Havolasi (Xaridorlar Uchun):")
        self.stdout.write(self.style.NOTICE(f"👉 {customer_link}"))
        self.stdout.write("")
