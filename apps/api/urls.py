"""
API v1 Router — LeadNode

Endpoints:
- /api/v1/schema/ -> OpenAPI 3 Schema (JSON)
- /api/v1/docs/ -> Swagger UI Documentation
- /api/v1/redoc/ -> Redoc UI Documentation
- /api/v1/token/ -> JWT Access & Refresh token olish
- /api/v1/token/refresh/ -> JWT Token yangilash
- /api/v1/store/ -> Do'kon profil va AI prompt sozlamalari (GET/PATCH)
- /api/v1/products/ -> Mahsulotlar katalogi (CRUD)
- /api/v1/orders/ -> Buyurtmalar ro'yxati va status o'zgartirish
- /api/v1/customers/ -> Mijozlar ro'yxati
- /api/v1/chat/ -> Yozishmalar va Inbox tarixi
"""
from django.urls import path, include
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from apps.stores.views import (
    SuperAdminStatsView,
    SuperAdminMeView,
    SuperAdminBusinessListCreateView,
    SuperAdminBusinessDetailView,
    SuperAdminBusinessDisableView,
    SuperAdminBusinessReactivateView,
    SuperAdminTWAAccessRevokeView,
    SuperAdminTWAAccessRestoreView,
    SuperAdminTWAAccessChangeOwnerView,
    SuperAdminTokenConnectView,
    SuperAdminTokenDisconnectView,
    SuperAdminSubscriptionPlanView,
    SuperAdminBusinessStatisticsView,
    SuperAdminBusinessDeleteView,
    SuperAdminTelegramLoginView,
    SuperAdminTelegramLogoutView,
)
from apps.audit.views import SuperAdminAuditLogListView, SuperAdminPlatformErrorListView
from apps.webhooks.views import webhook_health

app_name = "api_v1"

urlpatterns = [
    # OpenAPI 3 Schema & Swagger UI
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="v1:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="v1:schema"), name="redoc"),

    # JWT Auth
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # App routes
    path("store/", include("apps.stores.urls", namespace="stores")),
    path("products/", include("apps.products.urls")),
    path("orders/", include("apps.orders.urls")),
    path("customers/", include("apps.customers.urls")),
    path("chat/", include("apps.chat.urls")),
    path("webhooks/health/", webhook_health, name="webhooks_health"),
    path("superadmin/stats/", SuperAdminStatsView.as_view(), name="superadmin_stats"),
    path("superadmin/me/", SuperAdminMeView.as_view(), name="superadmin_me"),
    path("superadmin/businesses/", SuperAdminBusinessListCreateView.as_view(), name="superadmin_businesses"),
    path("superadmin/businesses/<uuid:pk>/", SuperAdminBusinessDetailView.as_view(), name="superadmin_business_detail"),
    path("superadmin/businesses/<uuid:pk>/disable/", SuperAdminBusinessDisableView.as_view(), name="superadmin_business_disable"),
    path("superadmin/businesses/<uuid:pk>/reactivate/", SuperAdminBusinessReactivateView.as_view(), name="superadmin_business_reactivate"),
    path("superadmin/businesses/<uuid:pk>/access/revoke/", SuperAdminTWAAccessRevokeView.as_view(), name="superadmin_access_revoke"),
    path("superadmin/businesses/<uuid:pk>/access/restore/", SuperAdminTWAAccessRestoreView.as_view(), name="superadmin_access_restore"),
    path("superadmin/businesses/<uuid:pk>/access/change-owner/", SuperAdminTWAAccessChangeOwnerView.as_view(), name="superadmin_access_change_owner"),
    path("superadmin/businesses/<uuid:pk>/token/connect/", SuperAdminTokenConnectView.as_view(), name="superadmin_token_connect"),
    path("superadmin/businesses/<uuid:pk>/token/disconnect/", SuperAdminTokenDisconnectView.as_view(), name="superadmin_token_disconnect"),
    path("superadmin/businesses/<uuid:pk>/subscription/", SuperAdminSubscriptionPlanView.as_view(), name="superadmin_subscription"),
    path("superadmin/businesses/<uuid:pk>/statistics/", SuperAdminBusinessStatisticsView.as_view(), name="superadmin_business_statistics"),
    path("superadmin/businesses/<uuid:pk>/delete/", SuperAdminBusinessDeleteView.as_view(), name="superadmin_business_delete"),
    path("superadmin/audit-log/", SuperAdminAuditLogListView.as_view(), name="superadmin_audit_log"),
    path("superadmin/platform-errors/", SuperAdminPlatformErrorListView.as_view(), name="superadmin_platform_errors"),
    path("superadmin/telegram-login/", SuperAdminTelegramLoginView.as_view(), name="superadmin_telegram_login"),
    path("superadmin/telegram-logout/", SuperAdminTelegramLogoutView.as_view(), name="superadmin_telegram_logout"),
]

