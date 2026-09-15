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
                "name": "Umumiy Ingliz Tili (Boshlang'ich)",
                "description": "Noldan boshlaydiganlar uchun umumiy ingliz tili kursi. Haftasiga 3 marta, 90 daqiqadan.",
                "price": 350000,
                "stock": 15,
                "category": "Ingliz tili",
                "sku": "ENG-BEGINNER",
            },
            {
                "name": "IELTS Tayyorlov Kursi",
                "description": "IELTS imtihoniga tayyorlov, individual yondashuv va mock testlar bilan.",
                "price": 450000,
                "stock": 8,
                "category": "IELTS",
                "sku": "IELTS-PREP",
            },
            {
                "name": "Bolalar uchun Ingliz Tili (7-10 yosh)",
                "description": "O'yin-kulgi asosida qurilgan, bolalarga mos ingliz tili kursi.",
                "price": 280000,
                "stock": 20,
                "category": "Bolalar kursi",
                "sku": "KIDS-ENG",
            },
            {
                "name": "Speaking Klub (Kuzgi mavsum)",
                "description": "Faqat suhbat va nutq amaliyotiga yo'naltirilgan qo'shimcha klub.",
                "price": 150000,
                "stock": 10,
                "category": "Qo'shimcha",
                "sku": "SPEAK-CLUB",
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
