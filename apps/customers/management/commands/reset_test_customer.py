"""
Management Command — Test uchun ishlatilgan mijozni (Customer) va unga
tegishli barcha ma'lumotlarni (xabarlar, buyurtmalar, sessiya) BUTUNLAY
(hard delete) o'chiradi — qayta toza test qilish uchun.

⚠️ Bu haqiqiy mijozlar uchun EMAS — faqat test/sinov paytida yaratilgan
mijozlarni tozalash uchun. Haqiqiy mijozni o'chirish kerak bo'lsa,
soft-delete (is_deleted=True) qilingan boshqa yechim kerak bo'ladi.

Ishlatish:
python manage.py reset_test_customer --store "Pdp academy" --username f6jbq
python manage.py reset_test_customer --store "Pdp academy" --platform-user-id 8669524197
"""
from django.core.management.base import BaseCommand, CommandError

from apps.stores.models import Store


class Command(BaseCommand):
    help = "Test mijozini (xabarlar, buyurtmalar, sessiya bilan birga) butunlay o'chiradi."

    def add_arguments(self, parser):
        parser.add_argument("--store", type=str, required=True, help="Do'kon nomi yoki UUID'si")
        parser.add_argument("--username", type=str, default=None, help="Mijozning Telegram @username'i")
        parser.add_argument("--platform-user-id", type=str, default=None, help="Mijozning Telegram raqamli ID'si")

    def handle(self, *args, **options):
        store_query = options["store"].strip()
        username = (options.get("username") or "").strip()
        platform_user_id = (options.get("platform_user_id") or "").strip()

        if not username and not platform_user_id:
            raise CommandError("--username yoki --platform-user-id dan birini bering.")

        try:
            if len(store_query) == 36:
                store = Store.objects.get(id=store_query, is_deleted=False)
            else:
                matches = list(Store.objects.filter(name__icontains=store_query, is_deleted=False))
                if len(matches) > 1:
                    self.stderr.write(self.style.ERROR(f"❌ '{store_query}' nomiga {len(matches)} ta do'kon mos keldi — UUID bering:"))
                    for m in matches:
                        self.stderr.write(f"   {m.name} → {m.id}")
                    return
                store = matches[0] if matches else None
                if not store:
                    raise Store.DoesNotExist
        except Store.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"❌ Do'kon topilmadi: '{store_query}'"))
            return

        from apps.customers.models import Customer, CustomerSession
        from apps.chat.models import ChatMessage
        from apps.orders.models import Lead

        qs = Customer.objects.filter(store=store)
        if username:
            qs = qs.filter(username__iexact=username)
        elif platform_user_id:
            qs = qs.filter(platform_user_id=platform_user_id)

        customer = qs.first()
        if not customer:
            self.stderr.write(self.style.ERROR("❌ Bunday mijoz topilmadi."))
            return

        msg_count = ChatMessage.all_objects.filter(store=store, customer=customer).count()
        lead_count = Lead.objects.filter(store=store, customer=customer).count()

        ChatMessage.all_objects.filter(store=store, customer=customer).delete()
        Lead.objects.filter(store=store, customer=customer).delete()
        CustomerSession.objects.filter(platform_user_id=customer.platform_user_id).delete()
        customer_display = customer.full_name or customer.username or customer.platform_user_id
        customer.delete()

        self.stdout.write(self.style.SUCCESS(
            f"✅ '{customer_display}' butunlay o'chirildi: "
            f"{msg_count} ta xabar, {lead_count} ta lid, sessiya tozalandi."
        ))
        self.stdout.write("Endi shu odam qaytadan /start bosishi bilan butunlay yangi mijoz sifatida ro'yxatga olinadi.")
