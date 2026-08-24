"""
Test Mahsulotlarini Bazaga Qo'shish (Seed Products) Command
"""
from django.core.management.base import BaseCommand
from apps.stores.models import Store
from apps.products.models import Product


class Command(BaseCommand):
    help = "Baza uchun sinov mahsulotlarini yaratadi"

    def handle(self, *args, **options):
        store = Store.objects.filter(is_deleted=False).first()
        if not store:
            self.stderr.write(self.style.ERROR("Do'kon topilmadi!"))
            return

        sample_products = [
            {
                "name": "Nike Air Max 270 (Qora)",
                "description": "Erkaklar va ayollar uchun original Nike sport poyabzali. O'lchamlar: 40, 41, 42, 43.",
                "price": 250000,
                "stock": 12,
                "category": "Poyabzal",
                "sku": "NIKE-270-BLK",
            },
            {
                "name": "Adidas Ultraboost 5.0 (Oq)",
                "description": "Yugurish va kundalik kiyish uchun qulay sport poyabzali. O'lchamlar: 39, 40, 41.",
                "price": 320000,
                "stock": 8,
                "category": "Poyabzal",
                "sku": "ADI-UB-WHT",
            },
            {
                "name": "Zamonaviy Shoyi Ko'ylak (Havorang)",
                "description": "Ayollar uchun zamonaviy va bejirim shoyi ko'ylak. Razmer: S, M, L.",
                "price": 180000,
                "stock": 15,
                "category": "Kiyim",
                "sku": "DRESS-BLU",
            },
            {
                "name": "Nike Sport Futbolkasi (Kulrang)",
                "description": "100% paxta, premium sifatli erkaklar futbolkasi. Razmer: M, L, XL.",
                "price": 95000,
                "stock": 25,
                "category": "Kiyim",
                "sku": "NIKE-TEE-GRY",
            },
        ]

        created_count = 0
        for p in sample_products:
            prod, created = Product.objects.get_or_create(
                store=store,
                name=p["name"],
                defaults={
                    "description": p["description"],
                    "price": p["price"],
                    "stock": p["stock"],
                    "category": p["category"],
                    "sku": p["sku"],
                    "is_active": True,
                }
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"✅ {created_count} ta yangi mahsulot '{store.name}' do'koniga qo'shildi!"))
