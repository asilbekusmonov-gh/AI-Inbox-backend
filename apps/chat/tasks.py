"""
Chat Celery Tasks — Ommaviy Reklama (Broadcast) va Anti-Spam (25 msgs/sec Rate Limit).

Telegram SPAM va Bot Ban bo'lishining oldini olish uchun:
- rate_limit="25/s" (1 soniyada maksimal 25 ta xabar)
- acks_late=True
- automatic campaign status tracking
"""
import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("apps.chat")


@shared_task(
    bind=True,
    name="apps.chat.tasks.send_broadcast_message_task",
    rate_limit="25/s",  # TELEGRAM SPAM PROTECTION: 25 MSGS/SEC STRICT LIMIT!
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def send_broadcast_message_task(
    self,
    campaign_id: str,
    customer_id: str,
    platform: str,
    chat_id: str,
    message_text: str,
):
    """
    Har bir mijozga ommaviy xabarni 25 msgs/sec tezlikda yuborish taski.
    Telegram Bot ban bo'lishidan 100% himoyalangan!
    """
    from apps.customers.models import Customer
    from apps.chat.models import BroadcastCampaign, ChatMessage
    from apps.chat.senders import send_reply

    try:
        campaign = BroadcastCampaign.objects.get(id=campaign_id)
        store = campaign.store
        customer = Customer.objects.get(id=customer_id)

        sent = send_reply(
            store=store,
            platform=platform,
            chat_id=chat_id,
            text=message_text,
        )

        from django.db.models import F

        if sent:
            BroadcastCampaign.objects.filter(id=campaign_id).update(
                sent_count=F('sent_count') + 1
            )
            import uuid
            ChatMessage.objects.create(
                store=store,
                customer=customer,
                message_id=f"bc_{uuid.uuid4().hex[:10]}",
                platform=platform,
                role=ChatMessage.Role.ASSISTANT,
                content=f"📢 [OMMAVIY REKLAMA]: {message_text}",
                processing_status=ChatMessage.ProcessingStatus.COMPLETED
            )
        else:
            BroadcastCampaign.objects.filter(id=campaign_id).update(
                failed_count=F('failed_count') + 1
            )

        # Refresh from DB to get accurate counts
        campaign.refresh_from_db()

        # Kampaniya yakunlanganini tekshirish
        if campaign.sent_count + campaign.failed_count >= campaign.total_recipients:
            campaign.status = BroadcastCampaign.Status.COMPLETED
            campaign.completed_at = timezone.now()
            campaign.save(update_fields=["status", "completed_at", "updated_at"])
            logger.info(f"[Broadcast] Kampaniya yakunlandi: campaign_id={campaign.id} | sent={campaign.sent_count}")

    except (BroadcastCampaign.DoesNotExist, Customer.DoesNotExist) as e:
        logger.error(f"[Broadcast] Record topilmadi: {e}")
    except Exception as e:
        logger.error(f"[Broadcast Task Error] {e}", exc_info=True)
        raise self.retry(exc=e)
