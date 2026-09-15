"""
Management Command — Do'kon egasi uchun UNIKAL Telegram Admin Havolasini generatsiya qilish.

Ishlatish:
python manage.py get_admin_link --store "Najot Ta'lim"
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
            help="Do'kon nomi yoki ID'si (masalan: 'Najot Ta'lim' yoki 'store-1')",
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
                # Bir nechta do'kon bir xil/o'xshash nomga ega bo'lishi mumkin — shunday
                # holatda jimgina birinchisini tanlamay, ro'yxatini ko'rsatib UUID
                # bilan aniqlashtirishni so'raymiz (revoke_store_owner bilan bir xil qoida).
                matches = list(Store.objects.filter(name__icontains=store_query, is_deleted=False))
                if len(matches) > 1:
                    self.stderr.write(
                        self.style.ERROR(
                            f"❌ '{store_query}' nomiga {len(matches)} ta do'kon mos keldi — "
                            f"aniq bittasini tanlash uchun --store'ga UUID bering:"
                        )
                    )
                    for m in matches:
                        self.stderr.write(f"   {m.name} → {m.id}")
                    return
                store = matches[0] if matches else None
                if not store:
                    raise Store.DoesNotExist
        except Store.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"❌ Do'kon topilmadi: '{store_query}'"))
            return

        # ⚠️ BUG FIX: Avval faqat UUID'ning birinchi 8 ta belgisi ishlatilardi.
        # webhooks/tasks.py._resolve_store_for_message() bu tokenni to'g'ridan-to'g'ri
        # Store.id (UUIDField) bilan solishtiradi — qisqartirilgan (8 belgili) qiymat
        # haqiqiy UUID emasligi sababli Django ORM ValidationError ko'tarardi, u esa
        # keng `except Exception: pass` bilan jimgina yutib yuborilardi. Natijada
        # admin_/store_ deep-link orqali do'konga ulanish HECH QACHON ishlamas edi.
        # Endi to'liq UUID ishlatiladi (64 belgilik Telegram start_parameter
        # chegarasiga ham to'liq sig'adi: "admin_" + 36 belgili UUID = 42 belgi).
        unique_token = str(store.id)
        admin_link = f"https://t.me/{bot_username}?start=admin_{unique_token}"
        customer_link = f"https://t.me/{bot_username}?start=store_{unique_token}"

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"=== 🛍️ DO'KON: {store.name} (ID: {store.id}) ==="))
        self.stdout.write("👑 Admin Havolasi (100% UNIKAL — Do'kon Egasiga Yuboring):")
        self.stdout.write(self.style.WARNING(f"👉 {admin_link}"))
        self.stdout.write("")
        self.stdout.write("🛍️ Mijozlar Havolasi (Xaridorlar Uchun):")
        self.stdout.write(self.style.NOTICE(f"👉 {customer_link}"))
        self.stdout.write("")
