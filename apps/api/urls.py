"""
API v1 Router — Social-Commerce AI Inbox

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
]
