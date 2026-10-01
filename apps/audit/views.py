from rest_framework import generics, permissions

from apps.audit.models import AuditLog, PlatformError
from apps.audit.serializers import AuditLogSerializer, PlatformErrorSerializer


class SuperAdminAuditLogListView(generics.ListAPIView):
    """
    Super Admin — muhim platforma amallarining tarixi ("Tizim" sahifasi).
    GET /api/v1/superadmin/audit-log/?store_id=<uuid>&action=<action>
    """
    permission_classes = [permissions.IsAdminUser]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.all()

        store_id = self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(target_store_id=store_id)

        action = self.request.query_params.get("action")
        if action:
            qs = qs.filter(action=action)

        return qs


class SuperAdminPlatformErrorListView(generics.ListAPIView):
    """
    Super Admin — tizim darajasidagi texnik xatolar jurnali ("Tizim" sahifasi,
    "Platforma xatolari" paneli).
    GET /api/v1/superadmin/platform-errors/?store_id=<uuid>&source=<source>
    """
    permission_classes = [permissions.IsAdminUser]
    serializer_class = PlatformErrorSerializer

    def get_queryset(self):
        qs = PlatformError.objects.all()

        store_id = self.request.query_params.get("store_id")
        if store_id:
            qs = qs.filter(store_id=store_id)

        source = self.request.query_params.get("source")
        if source:
            qs = qs.filter(source=source)

        return qs
