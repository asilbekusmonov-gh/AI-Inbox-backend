"""
Management Command — Do'kon egasini bo'shatish (revoke) yoki almashtirish.

Ishlatiladigan holatlar:
  1. Egani do'kondan olib tashlash kerak (masalan, shartnoma tugagan)
  2. Ega Telegram akkauntini almashtirmoqchi (eskisini bo'shatib, yangi
     akkaunt bilan SHU AYNI admin havolasini qayta bosishi mumkin)

Bu buyruq faqat tg_owner_chat_id'ni tozalaydi — do'konning o'zi, uning
mahsulotlari, buyurtmalari va sozlamalari o'zgarmaydi. Bo'shatilgandan
so'ng, avval generatsiya qilingan admin havolasi (get_admin_link yoki
create_store orqali olingan) yana ishlatilishi mumkin — yangi link kerak
emas, chunki u do'kon ID'siga bog'langan, eski egaga emas.

Ishlatish:
python manage.py revoke_store_owner --store "Najot Ta'lim"
python manage.py revoke_store_owner --store "<store-uuid>"
"""
from django.core.management.base import BaseCommand

from apps.stores.models import Store
from apps.stores.services import revoke_store_owner


class Command(BaseCommand):
    help = "Do'kon egasini bo'shatadi (tg_owner_chat_id'ni tozalaydi) — do'konning o'zi o'chirilmaydi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--store",
            type=str,
            required=True,
            help="Do'kon nomi yoki UUID'si",
        )

    def handle(self, *args, **options):
        store_query = options["store"].strip()

        try:
            if len(store_query) == 36:
                store = Store.objects.get(id=store_query, is_deleted=False)
            else:
                # ⚠️ Bir nechta do'kon bir xil/o'xshash nomga ega bo'lishi mumkin —
                # avval shunchaki birinchisini (eng so'nggi yaratilganini) jimgina
                # tanlar edi, bu esa noto'g'ri do'kondan egani bo'shatib qo'yish
                # xavfini tug'dirardi. Endi bir nechta moslik topilsa, hech narsa
                # qilmay ro'yxatini chiqaradi va UUID bilan aniq ko'rsatishni so'raydi.
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

        result = revoke_store_owner(store)
        if not result["changed"]:
            self.stdout.write(self.style.WARNING(f"⚠️ '{store.name}' do'konida hozir ega biriktirilmagan."))
            return

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"✅ Ega bo'shatildi: {store.name} (ID: {store.id})"))
        self.stdout.write(f"   Eski Telegram chat_id: {result['old_chat_id']}")
        self.stdout.write(
            "   Do'kon endi 'ega yo'q' holatida — avvalgi admin havolasi "
            "(get_admin_link / create_store'dan olingan) yangi egaga qayta yuborilishi mumkin."
        )
        self.stdout.write(
            self.style.WARNING(
                "   ⚠️ Eski ega hali ham TWA'ni ochib turgan bo'lishi mumkin — u yangi "
                "so'rovlar yubormaguncha (masalan sahifani yangilaguncha) darhol bilmaydi."
            )
        )
        self.stdout.write("")
