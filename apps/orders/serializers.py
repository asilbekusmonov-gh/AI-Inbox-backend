"""
Lead Serializers — DRF
"""
from rest_framework import serializers
from .models import Lead


class LeadSerializer(serializers.ModelSerializer):
    """
    Lidlarni ko'rish serializeri. Faqat o'qish uchun mo'ljallangan (holat
    boshqaruvi yo'q — lead_status'ni AI belgilaydi, egasi qo'lda o'zgartirmaydi).
    """
    interested_course_name = serializers.CharField(source="interested_course.name", read_only=True, default=None)

    class Meta:
        model = Lead
        fields = [
            "id",
            "lead_number",
            "platform",
            "source",
            "customer",
            "customer_full_name",
            "customer_phone",
            "interested_course",
            "interested_course_name",
            "lead_status",
            "exported_to",
            "exported_at",
            "notes",
            "owner_notified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
