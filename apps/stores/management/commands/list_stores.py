"""
Management Command — Barcha do'konlarni UUID va boshqa farqlovchi
belgilari (soha, holat, ega bor-yo'qligi, yaratilgan sana, mahsulot/
buyurtma soni) bilan ro'yxat qiladi.

Bir xil nomli do'konlar bo'lganda (masalan revoke_store_owner yoki
set_store_access "2 ta do'kon mos keldi" deb UUID so'raganda), qaysi
UUID qaysi do'konga tegishli ekanini shu buyruq orqali bilib olasiz.

Ishlatish:
python manage.py list_stores
python manage.py list_stores --name "Zulfiya"
"""
from django.core.management.base import BaseCommand

from apps.stores.models import Store


class Command(BaseCommand):
    help = "Barcha do'konlarni UUID va farqlovchi belgilari bilan ro'yxat qiladi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="Faqat shu nomga mos keluvchi do'konlarni ko'rsatish (ixtiyoriy filter)",
        )

    def handle(self, *args, **options):
        from apps.products.models import Product
        from apps.orders.models import Order

        qs = Store.objects.filter(is_deleted=False).order_by("name", "-created_at")
        name_filter = options.get("name")
        if name_filter:
            qs = qs.filter(name__icontains=name_filter)

        stores = list(qs)
        if not stores:
            self.stdout.write(self.style.WARNING("Hech qanday do'kon topilmadi."))
            return

        self.stdout.write("")
        for store in stores:
            product_count = Product.objects.filter(store=store, is_deleted=False).count()
            order_count = Order.objects.filter(store=store, is_deleted=False).count()
            owner_status = (
                f"✅ ega bor (tg_id={store.tg_owner_chat_id})"
                if store.tg_owner_chat_id
                else "⚠️ ega yo'q (hali hech kim ulanmagan)"
            )
            active_status = "🟢 faol" if store.is_active else "🔴 to'xtatilgan"

            self.stdout.write(self.style.SUCCESS(f"=== {store.name} ==="))
            self.stdout.write(f"   UUID: {store.id}")
            self.stdout.write(f"   Soha: {store.get_category_type_display()}")
            self.stdout.write(f"   Holat: {active_status}")
            self.stdout.write(f"   Ega: {owner_status}")
            self.stdout.write(f"   Yaratilgan: {store.created_at.strftime('%Y-%m-%d %H:%M')}")
            self.stdout.write(f"   Mahsulot/kurs soni: {product_count} | Buyurtma soni: {order_count}")
            self.stdout.write("")
