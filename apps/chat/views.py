"""
Chat Views — DRF ModelViewSet + ChatThreadListView

Endpoints:
  GET  /api/v1/chat/          → All raw ChatMessage objects (flat list)
  GET  /api/v1/chat/threads/  → Messages grouped into ChatThread objects (frontend format)
  POST /api/v1/chat/<id>/reply/       → Operator sends manual reply
  PATCH /api/v1/chat/<id>/toggle-ai/  → Toggle AI handoff for the store
"""
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Max, Count, Q
from .models import ChatMessage
from .serializers import ChatMessageSerializer
from apps.stores.models import Store


class ChatMessageViewSet(viewsets.ModelViewSet):
    """
    Do'kon xabarlar tarixini ko'rish (Live Inbox), operator javobi hamda AI Handoff.
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def _get_target_store(self):
        user = self.request.user
        if hasattr(user, "store") and user.store:
            return user.store
        return Store.objects.filter(is_active=True, is_deleted=False).first()

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

        # Send actual outbound message to Telegram/Instagram
        from apps.chat.senders import send_reply
        chat_id = customer.platform_user_id
        
        sent = send_reply(
            store=target_store,
            platform=customer.platform,
            chat_id=chat_id,
            text=text
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

        return Response({"success": True, "message_id": str(msg.id)}, status=status.HTTP_201_CREATED)

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
            return Response({"success": True, "ai_active": ai_active}, status=status.HTTP_200_OK)
        except Customer.DoesNotExist:
            return Response({"error": "Mijoz topilmadi"}, status=status.HTTP_404_NOT_FOUND)


class ChatThreadListView(APIView):
    """
    Frontend uchun ChatThread formati — xabarlarni mijoz bo'yicha guruhlaydi.

    GET /api/v1/chat/threads/

    Qaytariladigan format (frontend ChatThread type):
    [
      {
        "id": "<customer_id>",
        "customer_id": "<customer_id>",
        "customer_name": "Asilbek Usmonov",
        "customer_phone": "+998901234567",
        "platform": "telegram",
        "avatar_url": null,
        "last_message": "Nike Air Max 270 razmeri 42 bormi?",
        "last_message_time": "14:30",
        "unread_count": 1,
        "ai_active": true,
        "messages": [
          {"id": "<msg_id>", "sender": "customer", "text": "...", "timestamp": "14:28"},
          {"id": "<msg_id>", "sender": "ai",       "text": "...", "timestamp": "14:30"}
        ]
      },
      ...
    ]
    """
    permission_classes = [permissions.AllowAny]

    def _get_target_store(self):
        user = self.request.user
        if hasattr(user, "store") and user.store:
            return user.store
        return Store.objects.filter(is_active=True, is_deleted=False).first()

    def get(self, request):
        target_store = self._get_target_store()
        if not target_store:
            return Response([], status=status.HTTP_200_OK)

        # All non-deleted messages for this store, ordered chronologically
        messages = (
            ChatMessage.objects
            .filter(store=target_store, is_deleted=False)
            .select_related("customer")
            .order_by("created_at")
        )

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
                    "customer_phone": cust.phone_number or "",
                    "platform": cust.platform,
                    "avatar_url": None,
                    "last_message": "",
                    "last_message_time": "",
                    "unread_count": 0,
                    "ai_active": cust.ai_active,
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

            threads_map[cid]["messages"].append({
                "id": str(msg.id),
                "sender": sender,
                "text": msg.content,
                "timestamp": time_str,
            })

            # Update last_message tracking
            threads_map[cid]["last_message"] = msg.content
            threads_map[cid]["last_message_time"] = time_str

            # Count unread: customer messages that came after the last assistant message
            if msg.role == ChatMessage.Role.USER:
                threads_map[cid]["unread_count"] += 1
            elif msg.role == ChatMessage.Role.ASSISTANT:
                threads_map[cid]["unread_count"] = 0

        # Return as list, most recently active first
        thread_list = list(threads_map.values())
        thread_list.sort(key=lambda t: t["last_message_time"], reverse=True)

        return Response(thread_list, status=status.HTTP_200_OK)
