"""
Management Command — Yangi do'kon (tenant) yaratish va unga UNIKAL
Telegram Admin Onboarding havolasini generatsiya qilish.

Har bir yangi biznes egasi uchun shu buyruqni ishlating — birinchi navbatda
Store yozuvini yaratadi (hozircha ochiq/public ro'yxatdan o'tish sahifasi
yo'q, shuning uchun bu operator tomonidan bajariladi), so'ng darhol
egasiga yuboriladigan tayyor admin havolasini chiqaradi.

Ishlatish:
python manage.py create_store --name "Najot Ta'lim" --category education
python manage.py create_store --name "Beauty Studio" --category services
"""
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.stores.models import Store


class Command(BaseCommand):
    help = "Yangi do'kon yaratadi va uning admin/mijoz Telegram havolalarini chiqaradi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            required=True,
            help="Do'kon nomi (masalan: 'Najot Ta'lim')",
        )
        parser.add_argument(
            "--category",
            type=str,
            choices=[c.value for c in Store.CategoryType],
            default=Store.CategoryType.EDUCATION,
            help="Biznes sohasi: education | services (standart: education)",
        )
        parser.add_argument(
            "--bot_username",
            type=str,
            default="LeadNodeBot",
            help="Telegram Bot username (standart: LeadNodeBot)",
        )

    def handle(self, *args, **options):
        name = options["name"].strip()
        category = options["category"]
        bot_username = options["bot_username"].replace("@", "").strip()

        if not name:
            raise CommandError("--name bo'sh bo'lishi mumkin emas.")

        if not settings.TELEGRAM_BOT_TOKEN:
            raise CommandError(
                "TELEGRAM_BOT_TOKEN .env faylida sozlanmagan! "
                "Master bot tokenisiz do'kon yaratib bo'lmaydi."
            )

        # Har bir Store bitta Django User'ga bog'lanadi (OneToOneField) —
        # shuning uchun har safar yangi, nomi bilan bog'liq unikal User yaratamiz.
        base_username = slugify(name).replace("-", "_")[:20] or "store"
        username = f"{base_username}_{uuid.uuid4().hex[:6]}"
        owner = User.objects.create(
            username=username,
            email=f"{username}@placeholder.local",
        )

        store = Store.objects.create(
            owner=owner,
            name=name,
            category_type=category,
            platform=Store.Platform.TELEGRAM,
            tg_bot_token=settings.TELEGRAM_BOT_TOKEN,
        )

        admin_link = f"https://t.me/{bot_username}?start=admin_{store.id}"
        customer_link = f"https://t.me/{bot_username}?start=store_{store.id}"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ Do'kon yaratildi: {store.name} (ID: {store.id})"))
        self.stdout.write("")
        self.stdout.write("👑 Admin Havolasi (Do'kon Egasiga Yuboring):")
        self.stdout.write(self.style.WARNING(f"👉 {admin_link}"))
        self.stdout.write("")
        self.stdout.write("🛍️ Mijozlar Havolasi (Xaridorlar Uchun, ixtiyoriy):")
        self.stdout.write(self.style.NOTICE(f"👉 {customer_link}"))
        self.stdout.write("")
