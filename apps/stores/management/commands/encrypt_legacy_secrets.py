"""
Bir martalik migratsiya komandasi — apps/core/fields.py'ga o'tishdan
OLDIN oddiy matn (plaintext) holida saqlangan maxfiy maydonlarni
(tg_bot_token, ig_access_token, bitrix24_webhook_url,
google_sheets_webhook_url) shifrlangan holatga o'tkazadi.

Xavfsiz qayta ishga tushiriladi (idempotent): allaqachon shifrlangan
qiymatlar `EncryptedFieldMixin.from_db_value` orqali muvaffaqiyatli
ochiladi va o'zgarishsiz qayta saqlanadi (yana bir marta shifrlanadi,
zarari yo'q).

Ishlatish: python manage.py encrypt_legacy_secrets
"""
from django.core.management.base import BaseCommand

from apps.stores.models import Store


class Command(BaseCommand):
    help = "Maxfiy maydonlarni (bot token, CRM webhook va h.k.) shifrlangan holatga o'tkazadi"

    def handle(self, *args, **options):
        count = 0
        # ⚠️ `Store.objects` — is_deleted=False yozuvlarni filtrlaydigan
        # SoftDeleteManager. Bekor qilingan do'konlarning tokeni ham
        # bazada qolib ketadi (hard DELETE yo'q), shuning uchun ULARNI
        # HAM shifrlash uchun `all_objects` ishlatiladi.
        for store in Store.all_objects.all():
            # `.save()` chaqirilishi kifoya — get_prep_value shifrlaydi,
            # Store.save() esa tg_bot_token_hash'ni ham yangilaydi.
            store.save(update_fields=[
                "tg_bot_token",
                "tg_bot_token_hash",
                "tg_bot_username",
                "ig_access_token",
                "bitrix24_webhook_url",
                "google_sheets_webhook_url",
                "updated_at",
            ])
            count += 1

        self.stdout.write(self.style.SUCCESS(f"✅ {count} ta do'kon qayta saqlandi (maxfiy maydonlar shifrlandi)."))
