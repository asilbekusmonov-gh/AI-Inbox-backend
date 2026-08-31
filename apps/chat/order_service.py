"""
Buyurtma Yaratuvchisi — AI javobidan Order yaratadi.

AI buyurtma ma'lumotlarini JSON formatda yuborsa,
bu modul uni tekshirib, Order modeliga saqlaydi
va egasiga xabar yuboradi.
"""
import logging
from typing import Optional

from django.utils import timezone

logger = logging.getLogger("apps.chat")


def create_order_from_ai_data(
    store,
    customer,
    order_data: dict,
    platform: str,
    source_message=None,
) -> Optional[object]:
    """
    AI'dan kelgan buyurtma ma'lumotlaridan Order yaratadi.

    Args:
        store: Store obyekti
        customer: Customer obyekti
        order_data: AI'dan olingan dict {"full_name", "phone", "address", "items"}
        platform: "telegram" | "instagram"
        source_message: Bu buyurtmani yaratgan ChatMessage (ixtiyoriy)

    Returns:
        Order — muvaffaqiyatli yaratildi
        None — xato yuz berdi
    """
    from apps.orders.models import Order

    try:
        # ── Ma'lumotlarni tozalash va validatsiya ─────────────────
        full_name = str(order_data.get("full_name", "")).strip()
        phone = str(order_data.get("phone", "")).strip()
        address = str(order_data.get("address", "")).strip()
        items = order_data.get("items", [])
        notes = str(order_data.get("notes", "")).strip()

        # Majburiy maydonlarni tekshirish
        if not full_name:
            logger.warning("Buyurtma yaratish: full_name bo'sh!")
            return None
        if not phone:
            logger.warning("Buyurtma yaratish: phone bo'sh!")
            return None
        if not address:
            logger.warning("Buyurtma yaratish: address bo'sh!")
            return None

        # items list bo'lishi kerak
        if not isinstance(items, list):
            items = []

        # Jami summani hisoblash
        def _safe_number(val, default=0):
            try:
                return float(str(val).replace(' ', '').replace(',', ''))
            except (ValueError, TypeError):
                return default

        total_amount = sum(
            _safe_number(item.get("price", 0)) * int(_safe_number(item.get("qty", 1)) or 1)
            for item in items
            if isinstance(item, dict)
        )

        # ── Order yaratish ─────────────────────────────────────────
        order = Order.objects.create(
            store=store,
            customer=customer,
            platform=platform,
            customer_full_name=full_name,
            customer_phone=phone,
            delivery_address=address,
            items=items,
            notes=notes,
            total_amount=total_amount,
            status=Order.Status.NEW,
            source_message=source_message,
        )

        # ── Mijoz ma'lumotlarini yangilash ─────────────────────────
        # Agar birinchi marta ism/raqam olingan bo'lsa — Customer'ga ham yozamiz
        update_fields = []
        if not customer.full_name and full_name:
            customer.full_name = full_name
            update_fields.append("full_name")
        if not customer.phone_number and phone:
            customer.phone_number = phone
            update_fields.append("phone_number")
        if update_fields:
            update_fields.append("updated_at")
            customer.save(update_fields=update_fields)

        # Buyurtma sonini yangilash
        from django.db.models import F
        from apps.customers.models import Customer as CustomerModel
        CustomerModel.objects.filter(id=customer.id).update(
            total_orders=F('total_orders') + 1
        )

        logger.info(
            f"Yangi buyurtma yaratildi: {order.order_number} | "
            f"do'kon={store.name} | mijoz={full_name}"
        )

        return order

    except Exception as e:
        logger.error(
            f"Buyurtma yaratishda xato: {e} | store={store.name}",
            exc_info=True,
        )
        return None


def notify_store_owner(store, order) -> bool:
    """
    Do'kon egasiga yangi buyurtma haqida Telegram xabari yuboradi.

    Returns:
        True — xabar yuborildi
        False — yuborilmadi (token yo'q yoki xato)
    """
    from apps.chat.senders import send_telegram_order_notification

    try:
        if not store.tg_bot_token:
            logger.warning(
                f"Egaga xabarnoma: {store.name} do'konida tg_bot_token yo'q!"
            )
            return False

        if not store.tg_owner_chat_id:
            logger.warning(
                f"Egaga xabarnoma: {store.name} do'konida tg_owner_chat_id yo'q!"
            )
            return False

        success = send_telegram_order_notification(
            bot_token=store.tg_bot_token,
            owner_chat_id=store.tg_owner_chat_id,
            order=order,
        )

        if success:
            # Xabarnoma yuborilganini qayd etamiz
            from apps.orders.models import Order
            Order.objects.filter(id=order.id).update(
                owner_notified=True,
                owner_notified_at=timezone.now(),
            )
            logger.info(
                f"Egaga xabarnoma yuborildi: {order.order_number} → "
                f"{store.tg_owner_chat_id}"
            )
        else:
            logger.warning(
                f"Egaga xabarnoma yuborilmadi: {order.order_number}"
            )

        return success

    except Exception as e:
        logger.error(
            f"Egaga xabarnoma yuborishda xato: {e}",
            exc_info=True,
        )
        return False
