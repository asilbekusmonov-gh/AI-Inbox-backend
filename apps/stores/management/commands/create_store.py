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
from django.core.management.base import BaseCommand, CommandError

from apps.stores.models import Store
from apps.stores.services import StoreProvisioningError, provision_store


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

        # ⚠️ Yaratish logikasi endi `apps/stores/services.py::provision_store`ga
        # ko'chirilgan — Super Admin panel (API) ham AYNAN shu funksiyani
        # chaqiradi, ikki joyda takrorlanmasin.
        try:
            result = provision_store(name=name, category_type=category, bot_username=bot_username)
        except StoreProvisioningError as e:
            raise CommandError(str(e))

        store = result["store"]
        admin_link = result["admin_link"]
        customer_link = result["customer_link"]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ Do'kon yaratildi: {store.name} (ID: {store.id})"))
        self.stdout.write("")
        self.stdout.write("👑 Admin Havolasi (Do'kon Egasiga Yuboring):")
        self.stdout.write(self.style.WARNING(f"👉 {admin_link}"))
        self.stdout.write("")
        self.stdout.write("🛍️ Mijozlar Havolasi (Xaridorlar Uchun, ixtiyoriy):")
        self.stdout.write(self.style.NOTICE(f"👉 {customer_link}"))
        self.stdout.write("")
