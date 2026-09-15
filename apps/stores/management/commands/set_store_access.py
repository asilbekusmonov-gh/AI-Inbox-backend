"""
Management Command — Do'konni to'liq yoqish/o'chirish (masalan, sinov
muddati — trial — tugagach to'lov qilmagan mijozni to'xtatish uchun).

Farqi revoke_store_owner'dan: bu buyruq faqat egani bo'shatib qo'ymaydi —
BUTUN DO'KONNI to'xtatadi:
  - TWA (boshqaruv paneli) — ega kira olmaydi
  - AI bot — mijozlarga umuman javob bermaydi (webhook ham rad etiladi)
Do'konning barcha ma'lumotlari (mahsulotlar, buyurtmalar, mijozlar
tarixi) saqlanib qoladi — keyinchalik qayta yoqish mumkin.

Ishlatish:
python manage.py set_store_access --store "Najot Ta'lim" --active false
python manage.py set_store_access --store "Najot Ta'lim" --active true
"""
from django.core.management.base import BaseCommand

from apps.stores.models import Store


class Command(BaseCommand):
    help = "Do'konni to'liq faollashtiradi yoki to'xtatadi (TWA + AI bot, ikkalasi ham)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--store",
            type=str,
            required=True,
            help="Do'kon nomi yoki UUID'si",
        )
        parser.add_argument(
            "--active",
            type=str,
            required=True,
            choices=["true", "false"],
            help="true — yoqish, false — to'xtatish (TWA va AI bot ikkalasi ham)",
        )

    def handle(self, *args, **options):
        store_query = options["store"].strip()
        new_active = options["active"] == "true"

        try:
            if len(store_query) == 36:
                store = Store.objects.get(id=store_query, is_deleted=False)
            else:
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

        if store.is_active == new_active:
            state = "aktiv" if new_active else "to'xtatilgan"
            self.stdout.write(self.style.WARNING(f"⚠️ '{store.name}' allaqachon {state} holatda."))
            return

        store.is_active = new_active
        store.save(update_fields=["is_active", "updated_at"])

        self.stdout.write("")
        if new_active:
            self.stdout.write(self.style.SUCCESS(f"✅ '{store.name}' qayta faollashtirildi."))
            self.stdout.write("   TWA va AI bot yana ishlaydi.")
        else:
            self.stdout.write(self.style.WARNING(f"⛔ '{store.name}' to'xtatildi."))
            self.stdout.write("   TWA (dashboard) va AI bot ikkalasi ham endi ishlamaydi.")
            self.stdout.write("   Barcha ma'lumotlar (mahsulotlar, buyurtmalar) saqlanib qoladi.")
        self.stdout.write("")
