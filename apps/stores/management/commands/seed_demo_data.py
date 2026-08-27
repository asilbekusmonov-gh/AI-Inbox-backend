"""
Management command to seed initial demo data for Zulfiya Fashion Demo.
Usage: python manage.py seed_demo_data --settings=ai_inbox_backend.settings_dev
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.stores.models import Store
from apps.products.models import Product
from apps.customers.models import Customer
from apps.orders.models import Order
from apps.chat.models import ChatMessage


class Command(BaseCommand):
    help = "Seeds initial demo store, products, orders, and chats for frontend integration."

    def handle(self, *args, **options):
        self.stdout.write("Seeding demo data...")

        # 1. User & Store
        admin_user, _ = User.objects.get_or_create(username="default_admin")
        if not admin_user.has_usable_password():
            admin_user.set_password("admin123")
            admin_user.save()

        store, _ = Store.objects.get_or_create(
            owner=admin_user,
            defaults={
                "name": "AI Store Demo",
                "description": "Rasmiy AI sotuvchisi va yordamchisi do'koni.",
                "phone_number": "+998948111577",
                "platform": Store.Platform.BOTH,
                "ai_system_prompt": "Siz do'konning xushmuomala AI sotuvchisiz. Mijozlar bilan muloyim gaplashib, mahsulotlar, narx va yetkazib berish shartlarini tushuntiring.",
                "ai_model": "gemini-2.5-flash",
                "ai_active": True,
                "tg_bot_token": "8667569896:AAG_AhRUvBqwQNqMtkBbozs7hxiqyfPP9r8",
                "tg_bot_username": "Ai_InboxBot",
            }
        )

        # Update store fields if already exists
        store.name = "AI Store Demo"
        store.description = "Rasmiy AI sotuvchisi va yordamchisi do'koni."
        store.phone_number = "+998948111577"
        store.ai_active = True
        store.save()

        # 2. Products
        demo_products = [
            {
                "name": "Nike Air Max 270 (Qora)",
                "description": "[IMG: https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=500&auto=format&fit=crop&q=60]\nOriginal Nike sport poyabzali. Yuqori havo yostiqchali taglik.",
                "price": 250000,
                "stock": 12,
                "category": "Poyabzal",
                "sku": "NIKE-270-BLK",
                "is_active": True,
            },
            {
                "name": "Adidas Ultraboost 5.0 (Oq)",
                "description": "[IMG: https://images.unsplash.com/photo-1584735935682-2f2b69dff9d2?w=500&auto=format&fit=crop&q=60]\nYugurish va kunlik kiyish uchun nihoyatda qulay premium poyabzal.",
                "price": 320000,
                "stock": 4,
                "category": "Poyabzal",
                "sku": "ADI-UB5-WHT",
                "is_active": True,
            },
            {
                "name": "Nike Sport Futbolkasi (Kulrang)",
                "description": "[IMG: https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=500&auto=format&fit=crop&q=60]\n100% paxtadan tayyorlangan yuqori sifatli va nafas oluvchi futbolka.",
                "price": 95000,
                "stock": 25,
                "category": "Kiyim",
                "sku": "NIKE-TSHIRT-GRY",
                "is_active": True,
            },
            {
                "name": "Puma Unisex Hudisi (Qora)",
                "description": "[IMG: https://images.unsplash.com/photo-1556905055-8f358a7a47b2?w=500&auto=format&fit=crop&q=60]\nQulay va issiq ushlab turuvchi kuz-qish mavsumi uchun hudi.",
                "price": 180000,
                "stock": 0,
                "category": "Kiyim",
                "sku": "PUMA-HOODIE-BLK",
                "is_active": False,
            },
        ]

        for p_data in demo_products:
            Product.objects.get_or_create(
                store=store,
                name=p_data["name"],
                defaults=p_data
            )

        # 3. Customers
        c1, _ = Customer.objects.get_or_create(
            store=store,
            platform=Customer.Platform.TELEGRAM,
            platform_user_id="88491",
            defaults={
                "full_name": "Asilbek Usmonov",
                "phone_number": "+998948111577",
                "username": "asilbek",
            }
        )

        c2, _ = Customer.objects.get_or_create(
            store=store,
            platform=Customer.Platform.INSTAGRAM,
            platform_user_id="ig_madina_r",
            defaults={
                "full_name": "Madina Rahimova",
                "phone_number": "+998901234567",
                "username": "madina_r",
            }
        )

        c3, _ = Customer.objects.get_or_create(
            store=store,
            platform=Customer.Platform.TELEGRAM,
            platform_user_id="tg_javohir_k",
            defaults={
                "full_name": "Javohir Karimov",
                "phone_number": "+998935557788",
                "username": "javohir_k",
            }
        )

        # 4. Orders
        demo_orders = [
            {
                "order_number": "#ORD-88491",
                "customer": c1,
                "customer_full_name": "Asilbek Usmonov",
                "customer_phone": "+998 94 811 15 77",
                "platform": Order.Platform.TELEGRAM,
                "delivery_address": "Toshkent shahri, Chilonzor tumani, 19-mavze, 45-uy",
                "items": [
                    {"id": "item-1", "product_name": "Nike Air Max 270 (Qora)", "quantity": 1, "unit_price": 250000, "total_price": 250000}
                ],
                "total_amount": 250000,
                "status": Order.Status.NEW,
                "notes": "Razmer 42 so'raldi",
            },
            {
                "order_number": "#ORD-88490",
                "customer": c2,
                "customer_full_name": "Madina Rahimova",
                "customer_phone": "+998 90 123 45 67",
                "platform": Order.Platform.INSTAGRAM,
                "delivery_address": "Toshkent shahri, Yunusobod tumani, 11-mavze",
                "items": [
                    {"id": "item-2", "product_name": "Adidas Ultraboost 5.0 (Oq)", "quantity": 1, "unit_price": 320000, "total_price": 320000},
                    {"id": "item-3", "product_name": "Nike Sport Futbolkasi", "quantity": 1, "unit_price": 95000, "total_price": 95000}
                ],
                "total_amount": 415000,
                "status": Order.Status.CONFIRMED,
            },
            {
                "order_number": "#ORD-88488",
                "customer": c3,
                "customer_full_name": "Javohir Karimov",
                "customer_phone": "+998 93 555 77 88",
                "platform": Order.Platform.TELEGRAM,
                "delivery_address": "Samarqand shahri, Mirzo Ulug'bek ko'chasi 12",
                "items": [
                    {"id": "item-4", "product_name": "Nike Sport Futbolkasi", "quantity": 2, "unit_price": 95000, "total_price": 190000}
                ],
                "total_amount": 190000,
                "status": Order.Status.DELIVERED,
            },
        ]

        for o_data in demo_orders:
            Order.objects.get_or_create(
                store=store,
                order_number=o_data["order_number"],
                defaults=o_data
            )

        # 5. Chat Messages
        demo_messages = [
            # Thread 1: Asilbek
            {"customer": c1, "message_id": "m1", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.USER, "content": "Assalomu alaykum! Do'kondagi poyabzallar originalmi?"},
            {"customer": c1, "message_id": "m2", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Vaalaykum assalom! Ha, barcha mahsulotlarimiz 100% original va kafolatga ega! Qaysi model sizni qiziqtiryapti?"},
            {"customer": c1, "message_id": "m3", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.USER, "content": "Nike Air Max 270 razmeri 42 bormi?"},
            {"customer": c1, "message_id": "m4", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Ha, 42 razmer stokda mavjud (12 dona). Narxi 250,000 so'm. Buyurtma rasmiylashtiraylikmi?"},
            
            # Thread 2: Madina
            {"customer": c2, "message_id": "m10", "platform": ChatMessage.Platform.INSTAGRAM, "role": ChatMessage.Role.USER, "content": "Salom, Ultraboost oq krossovka razmer 38 bormi?"},
            {"customer": c2, "message_id": "m11", "platform": ChatMessage.Platform.INSTAGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Salom! Ha, Adidas Ultraboost 5.0 Oq rangdagisi 38 razmerda 4 dona qolgan. Narxi: 320,000 so'm."},
            {"customer": c2, "message_id": "m12", "platform": ChatMessage.Platform.INSTAGRAM, "role": ChatMessage.Role.USER, "content": "Katta rahmat, buyurtmani tasdiqlayman!"},

            # Thread 3: Javohir
            {"customer": c3, "message_id": "m20", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.USER, "content": "Mening buyurtmam tasdiqlandimi?"},
            {"customer": c3, "message_id": "m21", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Salom Javohir! Ha, buyurtmangiz #ORD-88488 tasdiqlandi va yetkazib berildi."},
        ]

        for m_data in demo_messages:
            ChatMessage.objects.get_or_create(
                store=store,
                message_id=m_data["message_id"],
                platform=m_data["platform"],
                defaults={
                    "customer": m_data["customer"],
                    "role": m_data["role"],
                    "content": m_data["content"],
                    "processing_status": ChatMessage.ProcessingStatus.COMPLETED,
                }
            )

        self.stdout.write(self.style.SUCCESS("Successfully seeded demo data!"))
