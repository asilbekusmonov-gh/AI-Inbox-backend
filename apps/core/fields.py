"""
Bazada shifrlangan holda saqlanadigan maydonlar (Telegram bot tokeni,
Instagram access token, CRM webhook manzillari kabi maxfiy qiymatlar
uchun).

⚠️ Nega kerak: bu qiymatlar avval oddiy matn (plaintext) holida
saqlanardi — agar kimdir bazaga to'g'ridan-to'g'ri kirish huquqiga ega
bo'lsa (masalan server buzilsa), barcha mijozlarning Telegram
botlarini, Instagram akkauntlarini va CRM ulanishlarini to'liq
egallab olishi mumkin edi. Endi bu qiymatlar Fernet (AES-128,
imzolangan) bilan shifrlanadi — ORM orqali o'qish/yozishda shaffof
tarzda avtomatik ochiladi/yopiladi, chaqiruvchi kod hech narsani
bilishi shart emas.

Kalit: settings.FIELD_ENCRYPTION_KEY (.env'da FIELD_ENCRYPTION_KEY) —
Fernet.generate_key() bilan yaratiladi. Bu kalit yo'qolsa, shifrlangan
barcha ma'lumot QAYTARIB BO'LMAYDIGAN darajada yo'qoladi — zaxira
nusxasini xavfsiz joyda saqlang.
"""
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _get_fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise ImproperlyConfigured(
            "FIELD_ENCRYPTION_KEY sozlanmagan! .env fayliga qo'shing "
            "(yaratish: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\")"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def sha256_hex(value: str) -> str:
    """
    Qidiruv uchun ishlatiladigan bir tomonlama (qaytarib bo'lmaydigan)
    hash — shifrlangan maydonni ORM'da `.filter(x=...)` bilan to'g'ridan
    -to'g'ri qidirib bo'lmaydi (Fernet har safar boshqa natija beradi),
    shuning uchun aniq (deterministik) qidiruv uchun ALOHIDA hash ustuni
    ishlatiladi (masalan `tg_bot_token_hash`).
    """
    return hashlib.sha256(value.encode()).hexdigest()


class _EncryptedFieldMixin:
    """CharField/TextField'ga shifrlashni qo'shadigan mixin."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _get_fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # ⚠️ Eski (migratsiyadan oldingi) qiymat hali shifrlanmagan
            # bo'lishi mumkin — buzilmasligi uchun xom holda qaytariladi.
            # `encrypt_legacy_secrets` komandasi buni bir martalik
            # qayta saqlab, shifrlab qo'yadi.
            return value


class EncryptedCharField(_EncryptedFieldMixin, models.CharField):
    pass


class EncryptedTextField(_EncryptedFieldMixin, models.TextField):
    pass
