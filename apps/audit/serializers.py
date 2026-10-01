from rest_framework import serializers

from apps.audit.models import AuditLog, PlatformError


class AuditLogSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)
    target_store_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "actor_display",
            "action",
            "action_display",
            "target_store_id",
            "target_store_name",
            "metadata",
            "created_at",
        ]


class PlatformErrorSerializer(serializers.ModelSerializer):
    source_display = serializers.CharField(source="get_source_display", read_only=True)
    store_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = PlatformError
        fields = [
            "id",
            "source",
            "source_display",
            "message",
            "store_id",
            "store_name",
            "metadata",
            "created_at",
        ]
