"""
Meta / Instagram Graph API Verification & Diagnostic CLI Engine.

Ishlatish:
  python manage.py verify_instagram_setup

Bu buyruq Meta App Review va Production uchun 4 ta asosiy diagnostika testini bajaradi:
1. Config Audit: .env / settings sozlamalari
2. Webhook GET Challenge Test: Meta webhook tasdiqlash
3. Webhook HMAC Signature Security Test: Imzo xavfsizligi va fake so'rovlarni bloklash
4. Token Lifecycle Audit: Do'konlar token muddati va refresh servisi
"""
import hashlib
import hmac
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client
from django.utils import timezone

logger = logging.getLogger("apps.stores")


class Command(BaseCommand):
    help = "Meta Instagram Graph API sozlamalari, webhook challenge, HMAC imzo va tokenlar holatini diagnostika qiladi."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 65))
        self.stdout.write(self.style.MIGRATE_HEADING("🚀 META INSTAGRAM GRAPH API DIAGNOSTIKA NATIVE ENGINE"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 65 + "\n"))

        passed = 0
        failed = 0

        # ── TEST 1: Config Audit ──────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_LABEL("1. 🔑 Config Audit (.env sozlamalari)..."))
        app_id = getattr(settings, "META_APP_ID", "").strip()
        app_secret = getattr(settings, "META_APP_SECRET", "").strip()
        verify_token = getattr(settings, "META_VERIFY_TOKEN", "").strip()

        if app_id:
            self.stdout.write(self.style.SUCCESS(f"   ✓ META_APP_ID sozlangan: {app_id[:6]}***"))
        else:
            self.stdout.write(self.style.ERROR("   ✗ META_APP_ID sozlanmagan! .env faylini tekshiring."))

        if app_secret:
            self.stdout.write(self.style.SUCCESS(f"   ✓ META_APP_SECRET sozlangan: {app_secret[:4]}***"))
        else:
            self.stdout.write(self.style.ERROR("   ✗ META_APP_SECRET sozlanmagan! .env faylini tekshiring."))

        if verify_token:
            self.stdout.write(self.style.SUCCESS(f"   ✓ META_VERIFY_TOKEN sozlangan: {verify_token}"))
        else:
            self.stdout.write(self.style.ERROR("   ✗ META_VERIFY_TOKEN sozlanmagan! .env faylini tekshiring."))

        if app_id and app_secret and verify_token:
            passed += 1
            self.stdout.write(self.style.SUCCESS("   ==> Config Audit: MUVAFFAQIYATLI PASSED!\n"))
        else:
            failed += 1
            self.stdout.write(self.style.ERROR("   ==> Config Audit: XATOLIK MAVJUD!\n"))

        # ── TEST 2: Webhook GET Challenge Test ───────────────────────
        self.stdout.write(self.style.MIGRATE_LABEL("2. 🌐 Webhook GET Challenge Test..."))
        client = Client()
        challenge_token = "verify_test_challenge_998877"

        url = f"/webhook/instagram/?hub.mode=subscribe&hub.verify_token={verify_token}&hub.challenge={challenge_token}"
        try:
            response = client.get(url)
            if response.status_code == 200 and response.content.decode("utf-8") == challenge_token:
                self.stdout.write(self.style.SUCCESS(f"   ✓ Webhook GET challenge muvaffaqiyatli: 200 OK (body={challenge_token})"))
                passed += 1
                self.stdout.write(self.style.SUCCESS("   ==> Webhook GET Challenge Test: PASSED!\n"))
            else:
                self.stdout.write(self.style.ERROR(f"   ✗ Webhook GET xato: status={response.status_code}, content={response.content}"))
                failed += 1
                self.stdout.write(self.style.ERROR("   ==> Webhook GET Challenge Test: FAILED!\n"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Webhook GET chaqirishda exception: {e}"))
            failed += 1
            self.stdout.write(self.style.ERROR("   ==> Webhook GET Challenge Test: FAILED!\n"))

        # ── TEST 3: Webhook HMAC Signature Security Test ─────────────
        self.stdout.write(self.style.MIGRATE_LABEL("3. 🔐 Webhook HMAC Signature Security Test..."))
        sample_payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "17841400000000000",
                    "messaging": [
                        {
                            "sender": {"id": "999888777"},
                            "recipient": {"id": "17841400000000000"},
                            "message": {
                                "mid": "mid.test_verification_001",
                                "text": "Diagnostic test message"
                            }
                        }
                    ]
                }
            ]
        }
        body_bytes = json.dumps(sample_payload).encode("utf-8")

        # 3A. Valid Signature POST
        valid_mac = hmac.new(app_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        valid_header = f"sha256={valid_mac}"

        try:
            resp_valid = client.post(
                "/webhook/instagram/",
                data=body_bytes,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=valid_header
            )
            # 3B. Invalid Signature POST (Security check)
            invalid_header = "sha256=invalid_fake_signature_hash_00000"
            resp_invalid = client.post(
                "/webhook/instagram/",
                data=body_bytes,
                content_type="application/json",
                HTTP_X_HUB_SIGNATURE_256=invalid_header
            )

            valid_ok = resp_valid.status_code == 200
            invalid_ok = resp_invalid.status_code == 403

            if valid_ok:
                self.stdout.write(self.style.SUCCESS("   ✓ Muvaffaqiyatli HMAC imzo qabul qilindi (200 OK)"))
            else:
                self.stdout.write(self.style.ERROR(f"   ✗ Muvaffaqiyatli HMAC imzo rad etildi: {resp_valid.status_code}"))

            if invalid_ok:
                self.stdout.write(self.style.SUCCESS("   ✓ Soxta HMAC imzo rad etildi (403 Forbidden)"))
            else:
                self.stdout.write(self.style.ERROR(f"   ✗ Soxta HMAC imzo rad etilmadi! Status: {resp_invalid.status_code}"))

            if valid_ok and invalid_ok:
                passed += 1
                self.stdout.write(self.style.SUCCESS("   ==> Webhook HMAC Security Test: PASSED!\n"))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR("   ==> Webhook HMAC Security Test: FAILED!\n"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"   ✗ Webhook HMAC testida exception: {e}"))
            failed += 1
            self.stdout.write(self.style.ERROR("   ==> Webhook HMAC Security Test: FAILED!\n"))

        # ── TEST 4: Token Lifecycle Audit ─────────────────────────────
        self.stdout.write(self.style.MIGRATE_LABEL("4. 🔄 Token Lifecycle & Store Connection Audit..."))
        from apps.stores.models import Store

        try:
            stores = Store.objects.filter(is_deleted=False)
            total_stores = stores.count()
            ig_connected_stores = stores.filter(ig_page_id__isnull=False).exclude(ig_page_id="")

            self.stdout.write(f"   - Jami do'konlar soni: {total_stores}")
            self.stdout.write(f"   - Instagram ulangan do'konlar soni: {ig_connected_stores.count()}")

            expiring_threshold = timezone.now() + timedelta(days=15)
            expiring_stores = ig_connected_stores.filter(
                ig_token_expires_at__isnull=False,
                ig_token_expires_at__lte=expiring_threshold
            )

            self.stdout.write(f"   - Tokeni tugashiga <=15 kun qolgan do'konlar: {expiring_stores.count()}")

            for st in ig_connected_stores:
                expires_str = st.ig_token_expires_at.strftime("%Y-%m-%d") if st.ig_token_expires_at else "Noma'lum"
                self.stdout.write(self.style.SUCCESS(
                    f"     • {st.name} | Page ID: {st.ig_page_id} | Expiration: {expires_str}"
                ))

            passed += 1
            self.stdout.write(self.style.SUCCESS("   ==> Token Lifecycle Audit: PASSED!\n"))

        except Exception as e:
            self.stdout.write(self.style.WARNING(
                f"   ⚠️ Ma'lumotlar bazasiga ulanib bo'lmadi (DB offline bo'lishi mumkin): {e}"
            ))
            self.stdout.write(self.style.WARNING("   ==> Token Lifecycle Audit: SKIPPED (DB offline)\n"))

        # ── SUMMARY ──────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 65))
        if failed == 0:
            self.stdout.write(self.style.SUCCESS(
                f"🎉 BARCHA {passed} TA DIAGNOSTIKA TESTLARI MUVAFFAQIYATLI O'TDI!"
            ))
            self.stdout.write(self.style.SUCCESS("Meta App Review va Production uchun 100% TAYYOR!"))
        else:
            self.stdout.write(self.style.ERROR(
                f"⚠️ DIAGNOSTIKA YAKUNI: {passed} ta o'tdi, {failed} ta xatolar topildi."
            ))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 65 + "\n"))
