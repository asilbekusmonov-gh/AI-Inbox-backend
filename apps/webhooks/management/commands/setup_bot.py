"""
Management Command — Telegram Bot Sozlash, Bot Tavsifi, Buyruqlar va TWA Menu Button.

Ishlatish:
python manage.py setup_bot --url https://your-ngrok-url.ngrok-free.app
"""
import httpx
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.stores.models import Store
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = "Telegram Bot webhook, description, buyruqlar va TWA Menu buttonini o'rnatish"

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            type=str,
            help="HTTPS Public URL (ngrok yoki server domeni)",
        )
        parser.add_argument(
            "--twa-url",
            type=str,
            default="http://localhost:3000",
            help="Telegram Web App (TWA) frontend URL",
        )

    def handle(self, *args, **options):
        bot_token = settings.TELEGRAM_BOT_TOKEN
        if not bot_token or bot_token == "your-telegram-bot-token-here":
            self.stderr.write(self.style.ERROR("TELEGRAM_BOT_TOKEN .env faylida sozlanmagan!"))
            return

        public_url = options.get("url")

        self.stdout.write(f"🤖 Telegram Bot tekshirilmoqda (Token: {bot_token[:10]}...)...")

        # 1. Bot ma'lumotlarini olish (getMe)
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                data = res.json()
                if not data.get("ok"):
                    self.stderr.write(self.style.ERROR(f"Bot Token xato: {data}"))
                    return
                
                bot_user = data["result"]
                username = bot_user.get("username")
                self.stdout.write(self.style.SUCCESS(f"✅ Bot topildi: @{username} (ID: {bot_user['id']})"))

                # ⚠️ BUG FIX: avval bu yerda `admin` foydalanuvchiga tegishli
                # do'kon topilmasa, "AI Store Demo" nomli YANGI do'kon
                # AVTOMATIK yaratilardi (eski, ilk dev-sozlash bosqichi uchun
                # yozilgan qulaylik). Loyiha endi haqiqiy test do'konlar bilan
                # ishlaydi — bu tunnel har yangilanganda (ya'ni `setup_bot`
                # har safar qayta ishga tushirilganda) keraksiz "demo"
                # do'konni jimgina qayta yaratib, tozalab tashlangan
                # do'konlar ro'yxatini yana ifloslantirardi (foydalanuvchi
                # buni jonli holatda aniqladi). Endi faqat MAVJUD bo'lsa
                # tokeni yangilanadi — yangisi yaratilmaydi.
                admin_user = User.objects.filter(username="admin").first()
                store = Store.objects.filter(owner=admin_user).first() if admin_user else None
                if store:
                    if store.tg_bot_token != bot_token:
                        store.tg_bot_token = bot_token
                        store.tg_bot_username = username
                        store.save()
                    self.stdout.write(self.style.SUCCESS(f"🏬 Do'kon biriktirildi: {store.name}"))

                # ⚠️ BUG FIX: bu yerda avval botning ko'rinadigan ismi
                # (DISPLAY NAME) har safar setup_bot ishga tushganda
                # majburan "Warmix"ga qaytarib qo'yilardi — bu esa do'kon
                # egasi BotFather orqali o'z biznesi uchun boshqa nom
                # qo'ygan bo'lsa (masalan "LeadNode"), webhook tuzatish
                # uchun setup_bot qayta ishga tushirilganda o'sha maxsus
                # nomni jimgina o'chirib yuborardi. Bot ismi endi bu
                # skriptga umuman tegishli emas — egasi buni BotFather
                # orqali o'zi xohlagancha o'zgartira oladi va bu doimiy
                # qoladi.

                # 2. Bot Tavsifi
                # ⚠️ Bu — bir nechta do'konga xizmat qiladigan BITTA umumiy
                # bot (README'dagi "Single shared bot, many tenants"), shuning
                # uchun tavsif hech qachon bitta do'kon nomiga bog'lanmasligi
                # kerak — aks holda barcha boshqa do'konlarning mijozlari
                # ham noto'g'ri (masalan "Pdp academy rasmiy...") matnni
                # ko'radi. Avval shu xato bor edi, jonli tekshirishda
                # aniqlandi va tuzatildi.
                # ⚠️ Bundan tashqari, avval bu yerda "buyurtmalarni tezkor
                # qabul qiladi" (e-commerce/order olish) degan matn bor edi —
                # loyiha endi faqat education/services, "buyurtma" emas
                # "lid" tushunchasi ishlatiladi.
                # ⚠️ BUG FIX: do'kon egasi tavsifni BotFather orqali qo'lda
                # o'zgartirib qo'ysa ham, keyingi safar `setup_bot` qayta
                # ishga tushirilganda (masalan Cloudflare tunnel yangilanganda —
                # bu muntazam sodir bo'ladi) uning o'zgartirishi bekor qilib,
                # shu yerdagi qattiq yozilgan matn bilan almashtirib
                # yuborilardi — "har safar eski holatiga qaytib qolayabdi"
                # degan shikoyat aynan shundan edi. Tuzatish qo'lda
                # o'zgartirishni saqlab qolish emas (bu ATAYLAB — bitta
                # umumiy bot ko'p do'konga xizmat qilgani uchun tavsif
                # HAR DOIM shu umumiy platforma darajasida, bironta ham
                # do'konga bog'lanmasdan qolishi kerak), balki shu qattiq
                # yozilgan matnning O'ZINI xohlagan holatga ("AI Lead
                # Generation & Sales Automation Platform"ning o'zbekchasi)
                # yangilash — shunda keyingi har qanday avtomatik qayta
                # o'rnatishda ham aynan shu, to'g'ri matn qoladi.
                # ⚠️ BUG FIX: avval bu yerda "AI asosidagi..." deb yozilardi —
                # foydalanuvchi buni odamlar botni ochganda darhol "bu shunchaki
                # AI" deb o'ylab qolishiga sabab bo'lyapti deb topdi (xohlagan
                # taassurot — jonli, professional sotuv xizmati, robot emas).
                # Shu sababli "AI" so'zi butunlay olib tashlandi.
                # ⚠️ BUG FIX: avval bu yerda 🤖/✨/👇 kabi emoji bor edi —
                # bozorga chiqadigan, jiddiy biznes mijozlariga
                # mo'ljallangan mahsulot uchun bu "o'yinchoq"/"sticker"
                # taassurotini berardi (foydalanuvchi buni aniq
                # ta'kidladi). Endi toza, professional matn.
                description = (
                    "LeadNode — lead generatsiyasi va sotuvni "
                    "avtomatlashtirish platformasi.\n\n"
                    "Mijozlarga 24/7 javob berib, ularni saralab (qualification) "
                    "va ro'yxatdan o'tkazishgacha olib boradi.\n\n"
                    "Savolingizga darhol, aniq javob beradi.\n\n"
                    "Boshlash uchun sizga yuborilgan shaxsiy havola orqali kiring."
                )
                short_desc = "Lead generatsiyasi va sotuvni avtomatlashtirish platformasi"

                client.post(
                    f"https://api.telegram.org/bot{bot_token}/setMyDescription",
                    json={"description": description}
                )
                client.post(
                    f"https://api.telegram.org/bot{bot_token}/setMyShortDescription",
                    json={"short_description": short_desc}
                )
                self.stdout.write(self.style.SUCCESS("✅ Bot haqida umumiy (barcha do'konlar uchun) tavsif o'rnatildi!"))

                # 3. Buyruqlar menyusi (/ tugmasini bossa chiqadigan menyu)
                commands = [
                    {"command": "start", "description": "Botni ishga tushirish"},
                    {"command": "help", "description": "Yordam va ko'rsatmalar"},
                ]
                client.post(
                    f"https://api.telegram.org/bot{bot_token}/setMyCommands",
                    json={"commands": commands}
                )
                self.stdout.write(self.style.SUCCESS("✅ Telegram / buyruqlar menyusi o'rnatildi!"))

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Telegram API ga ulanishda xato: {e}"))
            return

        # 4. Webhook o'rnatish (agar URL berilgan bo'lsa)
        if public_url:
            webhook_endpoint = f"{public_url.rstrip('/')}/webhook/telegram/{bot_token}/"
            self.stdout.write(f"🔗 Webhook o'rnatilmoqda: {webhook_endpoint}")
            
            payload = {
                "url": webhook_endpoint,
                "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
            }
            with httpx.Client(timeout=10.0) as client:
                res = client.post(f"https://api.telegram.org/bot{bot_token}/setWebhook", json=payload)
                res_data = res.json()
                if res_data.get("ok"):
                    self.stdout.write(self.style.SUCCESS("✅ Webhook muvaffaqiyatli o'rnatildi!"))
                else:
                    self.stderr.write(self.style.ERROR(f"Webhook o'rnatishda xato: {res_data}"))

        # 5. Menu Button tozalash (Oddiy mijozlar uchun standart menyu bo'ladi)
        menu_payload = {"menu_button": {"type": "default"}}
        with httpx.Client(timeout=10.0) as client:
            res = client.post(f"https://api.telegram.org/bot{bot_token}/setChatMenuButton", json=menu_payload)
            if res.json().get("ok"):
                self.stdout.write(self.style.SUCCESS("✅ Telegram menyu tugmasi standart mijoz rejimiga sozlandi!"))

        self.stdout.write(self.style.SUCCESS("🎉 Bot sozlamalari to'liq yakunlandi!"))
