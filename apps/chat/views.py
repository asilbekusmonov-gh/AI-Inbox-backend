"""
Chat Views — DRF ModelViewSet + ChatThreadListView

Endpoints:
  GET  /api/v1/chat/          → All raw ChatMessage objects (flat list)
  GET  /api/v1/chat/threads/  → Messages grouped into ChatThread objects (frontend format)
  POST /api/v1/chat/<id>/reply/       → Operator sends manual reply
  PATCH /api/v1/chat/<id>/toggle-ai/  → Toggle AI handoff for the store
"""
import uuid

from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from .models import ChatMessage
from .serializers import ChatMessageSerializer
from apps.core.authentication import get_store_from_request


def _message_lookup_q(msg_id):
    """
    Xabarni PK (UUID) yoki platforma message_id bo'yicha qidirish uchun Q quradi.

    ⚠️ BUG FIX: `id` maydoni UUIDField, shuning uchun `Q(id=msg_id)` ga
    UUID formatidagi bo'lmagan qiymat (masalan Telegram/Instagram'ning
    o'z message_id'si yoki "op_xxxxx"/"bc_xxxxx" kabi ID'lar) berilsa,
    Django ORM ValueError/ValidationError ko'tarar va endpoint 500 xato
    bilan qulardi. Endi id= filtri faqat msg_id haqiqiy UUID bo'lsa
    qo'shiladi, aks holda faqat message_id bo'yicha qidiriladi.
    """
    try:
        uuid.UUID(str(msg_id))
        return Q(id=msg_id) | Q(message_id=msg_id)
    except (ValueError, TypeError, AttributeError):
        return Q(message_id=msg_id)


class ChatMessageViewSet(viewsets.ModelViewSet):
    """
    Do'kon xabarlar tarixini ko'rish (Live Inbox), operator javobi hamda AI Handoff.
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
        return get_store_from_request(self.request)

    def get_queryset(self):
        target_store = self._get_target_store()
        if not target_store:
            return ChatMessage.objects.none()

        qs = ChatMessage.objects.filter(store=target_store, is_deleted=False)

        customer_id = self.request.query_params.get("customer")
        if customer_id:
            qs = qs.filter(customer_id=customer_id)

        return qs

    @action(detail=True, methods=["post"], url_path="reply")
    def reply(self, request, pk=None):
        """Operator tomonidan mijozga qo'lda javob yuborish: POST /api/v1/chat/<customer_id>/reply/"""
        target_store = self._get_target_store()
        text = request.data.get("text", "")
        if not text:
            return Response({"error": "Matn kiritilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        # Get the customer directly using customer ID (pk)
        from apps.customers.models import Customer
        try:
            customer = Customer.objects.get(pk=pk, store=target_store)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        # Automatically pause AI for this customer when human operator intervenes
        if customer.ai_active:
            customer.ai_active = False
            customer.save(update_fields=["ai_active", "updated_at"])

        # Send actual outbound message to Telegram/Instagram
        from apps.chat.senders import send_reply
        chat_id = customer.platform_user_id
        
        sent = send_reply(
            store=target_store,
            platform=customer.platform,
            chat_id=chat_id,
            text=text,
            customer=customer,
        )

        if not sent:
            return Response(
                {"error": "Xabarni foydalanuvchiga yuborib bo'lmadi (Platforma xatosi)"}, 
                status=status.HTTP_502_BAD_GATEWAY
            )

        import uuid
        # Create operator chat message in database
        msg = ChatMessage.objects.create(
            store=target_store,
            customer=customer,
            message_id=f"op_{uuid.uuid4().hex[:10]}",
            platform=customer.platform,
            role=ChatMessage.Role.ASSISTANT,
            content=text,
            processing_status=ChatMessage.ProcessingStatus.COMPLETED
        )

        return Response({"success": True, "ai_active": False, "message_id": str(msg.id)}, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="send-voice")
    def send_voice(self, request, pk=None):
        """
        Operator TWA Inbox'dan mijozga real Telegram/Instagram ovozli xabar yuborishi:
        POST /api/v1/chat/<customer_id>/send-voice/
        """
        target_store = self._get_target_store()
        audio_file = request.FILES.get("voice") or request.FILES.get("audio")

        from apps.customers.models import Customer
        try:
            customer = Customer.objects.get(pk=pk, store=target_store)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        if not audio_file:
            return Response({"error": "Ovozli fayl yuklanmadi"}, status=status.HTTP_400_BAD_REQUEST)

        # Automatically pause AI for this customer when human operator sends voice
        if customer.ai_active:
            customer.ai_active = False
            customer.save(update_fields=["ai_active", "updated_at"])

        voice_bytes = audio_file.read()
        from apps.chat.senders import send_voice_reply

        sent = send_voice_reply(
            store=target_store,
            platform=customer.platform,
            chat_id=customer.platform_user_id,
            voice_bytes=voice_bytes,
            caption="🎙️ Ovozli xabar",
            customer=customer,
        )

        if not sent:
            return Response(
                {"error": "Ovozli xabarni foydalanuvchiga yuborib bo'lmadi (Platforma xatosi)"},
                status=status.HTTP_502_BAD_GATEWAY
            )

        import uuid
        msg = ChatMessage.objects.create(
            store=target_store,
            customer=customer,
            message_id=f"op_voice_{uuid.uuid4().hex[:10]}",
            platform=customer.platform,
            role=ChatMessage.Role.ASSISTANT,
            content="[VOICE] 🎙️ Ovozli xabar",
            processing_status=ChatMessage.ProcessingStatus.COMPLETED
        )

        return Response({
            "success": True,
            "ai_active": False,
            "sent_to_telegram": sent,
            "message_id": str(msg.id)
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path="toggle-ai")
    def toggle_ai(self, request, pk=None):
        """Mijoz darajasida AI botni o'chirish/yoqish (Handoff): PATCH /api/v1/chat/<customer_id>/toggle-ai/"""
        ai_active = request.data.get("ai_active", True)
        target_store = self._get_target_store()
        
        from apps.customers.models import Customer
        try:
            customer = Customer.objects.get(pk=pk, store=target_store)
            customer.ai_active = ai_active
            customer.save(update_fields=["ai_active", "updated_at"])
            return Response({"success": True, "ai_active": customer.ai_active}, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["patch"], url_path="toggle-block")
    def toggle_block(self, request, pk=None):
        """Mijozni bloklash/blokdan chiqarish: PATCH /api/v1/chat/<customer_id>/toggle-block/"""
        target_store = self._get_target_store()
        from apps.customers.models import Customer
        try:
            customer = Customer.objects.get(pk=pk, store=target_store)
            customer.is_blocked = not customer.is_blocked
            if customer.is_blocked:
                customer.ai_active = False
            customer.save(update_fields=["is_blocked", "ai_active", "updated_at"])
            return Response({
                "success": True,
                "is_blocked": customer.is_blocked,
                "ai_active": customer.ai_active
            }, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["patch"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        """
        Operator ushbu mijoz bilan suhbatni o'qidi deb belgilaydi:
        PATCH /api/v1/chat/<customer_id>/mark-read/

        ⚠️ Avval bu holat faqat frontend xotirasida saqlanardi va sahifa
        reload qilinganda yo'qolib, unread_count yana eski (noto'g'ri)
        qiymatga qaytib ketardi (jonli holatda aniqlandi). Endi bu yerda
        bazaga yoziladi — ChatThreadListView shu vaqtdan foydalanadi.
        """
        from django.utils import timezone
        target_store = self._get_target_store()
        from apps.customers.models import Customer
        try:
            customer = Customer.objects.get(pk=pk, store=target_store)
            customer.operator_last_read_at = timezone.now()
            customer.save(update_fields=["operator_last_read_at", "updated_at"])
            return Response({"success": True}, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["delete"], url_path="delete-thread")
    def delete_thread(self, request, pk=None):
        """Mijoz bilan barcha chat tarixini o'chirish: DELETE /api/v1/chat/<customer_id>/delete-thread/"""
        target_store = self._get_target_store()
        from apps.customers.models import Customer
        try:
            customer = Customer.objects.get(pk=pk, store=target_store)
            ChatMessage.objects.filter(customer=customer, store=target_store).update(is_deleted=True)
            return Response({"success": True}, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=["patch"], url_path="messages/(?P<msg_id>[^/.]+)/edit")
    def edit_message(self, request, msg_id=None):
        """Bitta xabarni tahrirlash: PATCH /api/v1/chat/messages/<msg_id>/edit/"""
        target_store = self._get_target_store()
        text = (request.data.get("text") or "").strip()
        if not text:
            return Response({"error": "Matn kiritilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        msg = ChatMessage.objects.filter(
            _message_lookup_q(msg_id),
            store=target_store
        ).first()

        if not msg:
            return Response({"error": "Xabar topilmadi"}, status=status.HTTP_404_NOT_FOUND)

        msg.content = text
        msg.save(update_fields=["content", "updated_at"])
        return Response({"success": True, "text": text}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["delete", "post"], url_path="messages/(?P<msg_id>[^/.]+)/delete")
    def delete_single_message(self, request, msg_id=None):
        """Bitta xabarni o'chirish: DELETE /api/v1/chat/messages/<msg_id>/delete/"""
        target_store = self._get_target_store()
        if not msg_id:
            msg_id = request.data.get("msg_id")

        if not msg_id:
            return Response({"error": "O'chiriladigan xabar IDsi ko'rsatilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        # Match by PK (UUID), message_id or voice ID
        updated_count = ChatMessage.objects.filter(
            _message_lookup_q(msg_id) | Q(message_id__icontains=msg_id),
            store=target_store
        ).update(is_deleted=True)

        return Response({"success": True, "deleted_count": updated_count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="messages/bulk-delete")
    def bulk_delete_messages(self, request):
        """Bir nechta xabarlarni tanlab o'chirish: POST /api/v1/chat/messages/bulk-delete/"""
        target_store = self._get_target_store()
        msg_ids = request.data.get("msg_ids", [])
        if not msg_ids or not isinstance(msg_ids, list):
            return Response({"error": "O'chiriladigan xabarlar ko'rsatilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        # ⚠️ BUG FIX: `id__in` UUIDField ustida — ro'yxatda UUID bo'lmagan
        # message_id qiymatlari bo'lsa (masalan Telegram/Instagram xabar
        # ID'lari), Django ValueError ko'tarib 500 xato qaytarardi.
        # Endi faqat haqiqiy UUID qiymatlar `id__in` filtriga qo'shiladi.
        valid_uuids = []
        for mid in msg_ids:
            try:
                valid_uuids.append(uuid.UUID(str(mid)))
            except (ValueError, TypeError, AttributeError):
                continue

        lookup = Q(message_id__in=msg_ids)
        if valid_uuids:
            lookup |= Q(id__in=valid_uuids)

        updated_count = ChatMessage.objects.filter(
            lookup,
            store=target_store
        ).update(is_deleted=True)
        return Response({"success": True, "deleted_count": updated_count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="broadcast")
    def send_broadcast(self, request):
        """
        Do'kon mijozlariga ommaviy reklama xabari yuborish:
        POST /api/v1/chat/broadcast/
        Telegram Rate Limit (25 msgs/sec) bilan Celery navbatiga qo'yiladi.
        """
        target_store = self._get_target_store()
        title = request.data.get("title", "Ommaviy Reklama")
        message_text = (request.data.get("message_text") or "").strip()

        if not message_text:
            return Response({"error": "Xabar matni kiritilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        from apps.customers.models import Customer
        from apps.chat.models import BroadcastCampaign
        from apps.chat.tasks import send_broadcast_message_task

        # ⚠️ XAVFSIZLIK: bot barcha do'konlar uchun BITTA umumiy Telegram
        # bot orqali ishlaydi — agar bitta do'kon haddan tashqari ko'p/
        # tez-tez broadcast yuborsa, mijozlar buni spam deb shikoyat
        # qilishi va Telegram BUTUN botni cheklab qo'yishi mumkin. Bu esa
        # bitta beparvo do'kon tufayli BARCHA do'konlarning mijozlarga
        # yeta olmay qolishiga olib keladi. Shu sabab har bir do'kon uchun
        # kunlik/haftalik qat'iy limit qo'yilgan (ai_inbox_backend/
        # settings.py'dagi BROADCAST_DAILY_LIMIT_PER_STORE/_WEEKLY_).
        from django.conf import settings as dj_settings
        from django.utils import timezone
        from datetime import timedelta

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)

        daily_count = BroadcastCampaign.objects.filter(store=target_store, created_at__gte=today_start).count()
        if daily_count >= dj_settings.BROADCAST_DAILY_LIMIT_PER_STORE:
            return Response(
                {"error": f"Kunlik broadcast limiti ({dj_settings.BROADCAST_DAILY_LIMIT_PER_STORE} ta) tugadi. Ertaga qayta urinib ko'ring."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        weekly_count = BroadcastCampaign.objects.filter(store=target_store, created_at__gte=week_start).count()
        if weekly_count >= dj_settings.BROADCAST_WEEKLY_LIMIT_PER_STORE:
            return Response(
                {"error": f"Haftalik broadcast limiti ({dj_settings.BROADCAST_WEEKLY_LIMIT_PER_STORE} ta) tugadi. Keyinroq qayta urinib ko'ring."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        active_customers = Customer.objects.filter(
            store=target_store,
            is_blocked=False,
            is_deleted=False
        )

        total_count = active_customers.count()
        if total_count == 0:
            return Response({"error": "Xabar yuborish uchun faol mijozlar topilmadi"}, status=status.HTTP_400_BAD_REQUEST)

        campaign = BroadcastCampaign.objects.create(
            store=target_store,
            title=title,
            message_text=message_text,
            status=BroadcastCampaign.Status.SENDING,
            total_recipients=total_count
        )

        for customer in active_customers:
            send_broadcast_message_task.delay(
                campaign_id=str(campaign.id),
                customer_id=str(customer.id),
                platform=customer.platform,
                chat_id=customer.platform_user_id,
                message_text=message_text
            )

        return Response({
            "success": True,
            "campaign_id": str(campaign.id),
            "total_recipients": total_count,
            "rate_limit": "25 msgs/sec",
            "status": "sending"
        }, status=status.HTTP_201_CREATED)


class ChatThreadListView(APIView):
    """
    Frontend uchun ChatThread formati — xabarlarni mijoz bo'yicha guruhlaydi.

    GET /api/v1/chat/threads/
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_target_store(self):
        """Xavfsiz store aniqlash: .first() fallback YO'Q!"""
        return get_store_from_request(self.request)

    def get(self, request):
        target_store = self._get_target_store()
        if not target_store:
            return Response([], status=status.HTTP_200_OK)

        # ⚠️ BUG FIX (scale): avval BUTUN do'kon tarixidagi barcha xabarlar
        # (necha oylik, necha minglab bo'lsa ham) HAR SO'ROVDA — ya'ni
        # frontend'ning 3 soniyalik pollingi tufayli amalda HAR 3 SONIYADA —
        # bazadan o'qib, Python'da qayta guruhlanardi. Mijozlar va xabarlar
        # ko'paygan sari bu so'rov sekinlashib, butun TWA "qotib qolgandek"
        # tuyulishiga olib kelardi. Endi faqat so'nggi N ta xabar (eng faol
        # suhbatlar) olinadi — inbox ro'yxati aylanma emas, "so'nggi faollik"
        # ko'rinishi bo'lgani uchun bu to'g'ri xulq-atvor ham hisoblanadi.
        RECENT_MESSAGE_LIMIT = 500
        # ⚠️ Do'kon egasi so'radi: guruhda yozilgan xabarlar (bot guruhga
        # qo'shilgan bo'lsa, o'sha yerdagi savol-javoblar ham) Inbox'ning
        # "Aktiv suhbatlar" ro'yxatiga chiqmasligi kerak — faqat mijoz
        # botning O'ZIGA (shaxsiy chatda) yozganda shu ro'yxatga qo'shilsin.
        # Guruhdagi suhbat mutlaqo boshqa kontekst (bir nechta odam,
        # ochiq muhokama) va operator uchun "shaxsiy mijoz suhbati" emas.
        threads_qs = ChatMessage.objects.filter(
            store=target_store, is_deleted=False, is_group_message=False,
        )
        # ⚠️ Do'kon EGASINING botga o'zi (test/tekshirish uchun) yozgan
        # xabarlari — bu haqiqiy mijoz emas, shuning uchun Inbox'da
        # ko'rsatilmaydi. Aks holda egasi o'z-o'ziga yozgan "salom",
        # "/start" kabi test xabarlari real mijozlar orasida chalkash
        # ko'rinardi (foydalanuvchi buni jonli aniqladi).
        if target_store.tg_owner_chat_id:
            threads_qs = threads_qs.exclude(
                customer__platform_user_id=str(target_store.tg_owner_chat_id)
            )
        recent_messages = list(
            threads_qs
            .select_related("customer")
            .order_by("-created_at")[:RECENT_MESSAGE_LIMIT]
        )
        messages = reversed(recent_messages)  # guruhlash tartibi eskidan-yangiga bo'lishi kerak

        # Group by customer
        threads_map = {}
        for msg in messages:
            cust = msg.customer
            cid = str(cust.id)

            if cid not in threads_map:
                threads_map[cid] = {
                    "id": cid,
                    "customer_id": cid,
                    "customer_name": (
                        cust.full_name
                        or cust.username
                        or f"Mijoz #{cust.platform_user_id}"
                    ),
                    # Telegram profiliga havola faqat @username orqali
                    # ishlaydi (Telegram maxfiylik siyosati sababli
                    # raqamli ID orqali tashqi havola yaratib bo'lmaydi)
                    "customer_username": cust.username or "",
                    "customer_phone": cust.phone_number or "",
                    "platform": cust.platform,
                    "avatar_url": None,
                    "last_message": "",
                    "last_message_time": "",
                    "_last_datetime": msg.created_at,
                    "unread_count": 0,
                    "ai_active": cust.ai_active,
                    "is_blocked": cust.is_blocked,
                    "messages": [],
                }

            # Map role to frontend sender type
            sender_map = {
                ChatMessage.Role.USER: "customer",
                ChatMessage.Role.ASSISTANT: "ai",
                ChatMessage.Role.SYSTEM: "ai",
            }
            sender = sender_map.get(msg.role, "ai")

            # Format timestamp
            created_local = msg.created_at
            time_str = created_local.strftime("%H:%M") if created_local else ""

            msg_data = {
                "id": str(msg.id),
                "sender": sender,
                "text": msg.content,
                "timestamp": time_str,
            }
            if msg.audio_url:
                msg_data["audio_url"] = msg.audio_url
            if msg.audio_duration:
                msg_data["audio_duration"] = msg.audio_duration
            elif msg.audio_url:
                msg_data["audio_duration"] = "0:15"

            threads_map[cid]["messages"].append(msg_data)

            # Update last_message tracking
            threads_map[cid]["last_message"] = msg.content
            threads_map[cid]["last_message_time"] = time_str
            threads_map[cid]["_last_datetime"] = msg.created_at

            # Count unread: customer messages that came after the last assistant
            # message AND after the operator's last "read" timestamp (whichever
            # is later) — ⚠️ BUG FIX: avval faqat "oxirgi AI javobidan keyingi"
            # mezoni bor edi, operator o'zi suhbatni ochib o'qigani hisobga
            # olinmasdi (bu faqat frontend xotirasida — reload'da yo'qolardi).
            if msg.role == ChatMessage.Role.USER:
                already_read = (
                    cust.operator_last_read_at is not None
                    and msg.created_at <= cust.operator_last_read_at
                )
                if not already_read:
                    threads_map[cid]["unread_count"] += 1
            elif msg.role == ChatMessage.Role.ASSISTANT:
                threads_map[cid]["unread_count"] = 0

        # Return as list, most recently active first (sort by actual datetime)
        thread_list = list(threads_map.values())
        thread_list.sort(key=lambda t: t.pop("_last_datetime"), reverse=True)

        return Response(thread_list, status=status.HTTP_200_OK)
