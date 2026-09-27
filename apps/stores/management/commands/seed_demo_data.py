"""
Management command to seed initial demo data for an education-center demo.
Usage: python manage.py seed_demo_data --settings=ai_inbox_backend.settings_dev
"""
import os

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.stores.models import Store
from apps.products.models import Product
from apps.customers.models import Customer
from apps.orders.models import Lead
from apps.chat.models import ChatMessage


class Command(BaseCommand):
    help = "Seeds initial demo store, courses, leads, and chats for frontend integration."

    def handle(self, *args, **options):
        self.stdout.write("Seeding demo data...")

        # 1. User & Store
        admin_user, _ = User.objects.get_or_create(username="default_admin")
        if not admin_user.has_usable_password():
            admin_user.set_password("admin123")
            admin_user.save()

        # ⚠️ SECURITY FIX: Avval bu yerda HAQIQIY, ishlaydigan Telegram bot
        # tokeni ochiq matnda (hardcoded) yozilgan edi va Git repository'ga
        # commit qilingan bo'lishi mumkin. Bu tokenni har kim ko'rib, botni
        # o'z nomidan boshqarishi mumkin edi. Endi token .env'dan
        # (DEMO_TG_BOT_TOKEN) o'qiladi va sozlanmagan bo'lsa bo'sh qoldiriladi.
        # ⚠️ Agar eski token ("8667569896:AAG_...") avval commit qilingan
        # bo'lsa, uni @BotFather orqali DARHOL revoke/rotate qiling!
        demo_bot_token = os.environ.get("DEMO_TG_BOT_TOKEN", "")

        store, _ = Store.objects.get_or_create(
            owner=admin_user,
            defaults={
                "name": "Najot Ta'lim Demo",
                "description": "Ingliz tili va IELTS tayyorlov o'quv markazi.",
                "phone_number": "+998948111577",
                "platform": Store.Platform.BOTH,
                "category_type": Store.CategoryType.EDUCATION,
                "ai_system_prompt": "Siz o'quv markazining xushmuomala AI konsultantisiz. Mijozlar bilan muloyim gaplashib, kurslar, narx va Bepul Sinov Darsi shartlarini tushuntiring.",
                "ai_model": "gemini-3.6-flash",
                "ai_active": True,
                "tg_bot_token": demo_bot_token,
                "tg_bot_username": "LeadNodeBot",
            }
        )

        # Update store fields if already exists
        store.name = "Najot Ta'lim Demo"
        store.description = "Ingliz tili va IELTS tayyorlov o'quv markazi."
        store.phone_number = "+998948111577"
        store.category_type = Store.CategoryType.EDUCATION
        store.ai_active = True
        store.save()

        # 2. Kurslar (Products)
        demo_products = [
            {
                "name": "Umumiy Ingliz Tili (Boshlang'ich)",
                "description": "Noldan boshlaydiganlar uchun umumiy ingliz tili kursi. Haftasiga 3 marta, 90 daqiqadan.",
                "price": 350000,
                "stock": 15,
                "category": "Ingliz tili",
                "sku": "ENG-BEGINNER",
                "category_type": Store.CategoryType.EDUCATION,
                "metadata": {"duration_months": 4, "lessons_per_week": 3, "format": "offline"},
                "is_active": True,
            },
            {
                "name": "IELTS Tayyorlov Kursi",
                "description": "IELTS imtihoniga tayyorlov, individual yondashuv va mock testlar bilan.",
                "price": 450000,
                "stock": 8,
                "category": "IELTS",
                "sku": "IELTS-PREP",
                "category_type": Store.CategoryType.EDUCATION,
                "metadata": {"duration_months": 6, "lessons_per_week": 2, "format": "hybrid"},
                "is_active": True,
            },
            {
                "name": "Bolalar uchun Ingliz Tili (7-10 yosh)",
                "description": "O'yin-kulgi asosida qurilgan, bolalarga mos ingliz tili kursi.",
                "price": 280000,
                "stock": 20,
                "category": "Bolalar kursi",
                "sku": "KIDS-ENG",
                "category_type": Store.CategoryType.EDUCATION,
                "metadata": {"duration_months": 12, "lessons_per_week": 2, "format": "offline"},
                "is_active": True,
            },
            {
                "name": "Speaking Klub (Kuzgi mavsum)",
                "description": "Faqat suhbat va nutq amaliyotiga yo'naltirilgan qo'shimcha klub.",
                "price": 150000,
                "stock": 0,
                "category": "Qo'shimcha",
                "sku": "SPEAK-CLUB",
                "category_type": Store.CategoryType.EDUCATION,
                "metadata": {"duration_months": 3, "lessons_per_week": 1, "format": "offline"},
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

        # 4. Leads
        demo_leads = [
            {
                "lead_number": "LEAD-DEMO-88491",
                "customer": c1,
                "customer_full_name": "Asilbek Usmonov",
                "customer_phone": "+998 94 811 15 77",
                "platform": Lead.Platform.TELEGRAM,
                "source": Lead.Source.PRIVATE_CHAT,
                "lead_status": Lead.LeadStatus.UNQUALIFIED,
                "notes": "Umumiy Ingliz Tili kursi haqida so'radi",
            },
            {
                "lead_number": "LEAD-DEMO-88490",
                "customer": c2,
                "customer_full_name": "Madina Rahimova",
                "customer_phone": "+998 90 123 45 67",
                "platform": Lead.Platform.INSTAGRAM,
                "source": Lead.Source.AD,
                "lead_status": Lead.LeadStatus.WARM,
                "notes": "IELTS Tayyorlov Kursi haqida so'radi",
            },
            {
                "lead_number": "LEAD-DEMO-88488",
                "customer": c3,
                "customer_full_name": "Javohir Karimov",
                "customer_phone": "+998 93 555 77 88",
                "platform": Lead.Platform.TELEGRAM,
                "source": Lead.Source.GROUP,
                "lead_status": Lead.LeadStatus.HOT,
            },
        ]

        for l_data in demo_leads:
            Lead.objects.get_or_create(
                store=store,
                lead_number=l_data["lead_number"],
                defaults=l_data
            )

        # 5. Chat Messages
        demo_messages = [
            # Thread 1: Asilbek
            {"customer": c1, "message_id": "m1", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.USER, "content": "Assalomu alaykum! Ingliz tili kurslaringiz noldan boshlaydiganlar uchun ham bormi?"},
            {"customer": c1, "message_id": "m2", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Vaalaykum assalom! Ha, 'Umumiy Ingliz Tili (Boshlang'ich)' kursimiz aynan shu uchun mo'ljallangan. Qaysi vaqt sizga qulay?"},
            {"customer": c1, "message_id": "m3", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.USER, "content": "Narxi qancha va haftasiga necha marta dars bo'ladi?"},
            {"customer": c1, "message_id": "m4", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Kurs narxi oyiga 350,000 so'm, haftasiga 3 marta, 90 daqiqadan. Bepul Sinov Darsiga yozib qo'yaymi?"},

            # Thread 2: Madina
            {"customer": c2, "message_id": "m10", "platform": ChatMessage.Platform.INSTAGRAM, "role": ChatMessage.Role.USER, "content": "Salom, IELTS kursingiz haqida ma'lumot bera olasizmi?"},
            {"customer": c2, "message_id": "m11", "platform": ChatMessage.Platform.INSTAGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Salom! IELTS Tayyorlov Kursimiz 6 oylik, individual yondashuv va mock testlar bilan. Narxi oyiga 450,000 so'm."},
            {"customer": c2, "message_id": "m12", "platform": ChatMessage.Platform.INSTAGRAM, "role": ChatMessage.Role.USER, "content": "Ha, meni yozib qo'ying, keladigan dushanba boraman!"},

            # Thread 3: Javohir
            {"customer": c3, "message_id": "m20", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.USER, "content": "Bolalar uchun kursingiz bormi?"},
            {"customer": c3, "message_id": "m21", "platform": ChatMessage.Platform.TELEGRAM, "role": ChatMessage.Role.ASSISTANT, "content": "Ha, 7-10 yosh uchun 'Bolalar uchun Ingliz Tili' kursimiz bor, o'yin-kulgi asosida qurilgan. Xohlasangiz Bepul Sinov Darsiga yozib qo'yaman."},
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
