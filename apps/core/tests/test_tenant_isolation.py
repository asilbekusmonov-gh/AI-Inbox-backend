"""
Multi-tenant izolyatsiya testlari.

README'dagi "Security model" bo'limi shuni da'vo qiladi: "there is no way
to read or write another tenant's data by passing an ID" — bu testlar aynan
shu kafolatni tekshiradi: bitta do'kon egasi hech qachon boshqa do'konning
buyurtmalarini, mahsulotlarini yoki mijozlarini (na ro'yxatda, na to'g'ridan
-to'g'ri ID orqali) ko'ra olmasligi kerak.

Bu `get_store_from_request()` (apps/core/authentication.py) ustidan
ViewSet.get_queryset() qatlamida ishlaydi — agar kelajakda kimdir
`.first()`/fallback qo'shib qo'ysa yoki `get_queryset()`ni store filtrisiz
qoldirsa, shu testlar sinishi kerak.
"""
from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from apps.customers.models import Customer
from apps.orders.models import Lead
from apps.products.models import Product
from apps.stores.models import Store


class TenantIsolationTestCase(APITestCase):
    def setUp(self):
        self.owner_a = User.objects.create_user(username="owner_a", password="x")
        self.owner_b = User.objects.create_user(username="owner_b", password="x")
        self.store_a = Store.objects.create(owner=self.owner_a, name="Do'kon A")
        self.store_b = Store.objects.create(owner=self.owner_b, name="Do'kon B")

        self.customer_a = Customer.objects.create(
            store=self.store_a, platform=Customer.Platform.TELEGRAM, platform_user_id="111",
            full_name="Mijoz A",
        )
        self.customer_b = Customer.objects.create(
            store=self.store_b, platform=Customer.Platform.TELEGRAM, platform_user_id="222",
            full_name="Mijoz B",
        )

        self.lead_a = Lead.objects.create(
            store=self.store_a, customer=self.customer_a, platform=Lead.Platform.TELEGRAM,
            customer_full_name="Mijoz A", customer_phone="+998900000001",
        )
        self.lead_b = Lead.objects.create(
            store=self.store_b, customer=self.customer_b, platform=Lead.Platform.TELEGRAM,
            customer_full_name="Mijoz B", customer_phone="+998900000002",
        )

        self.product_a = Product.objects.create(store=self.store_a, name="Mahsulot A")
        self.product_b = Product.objects.create(store=self.store_b, name="Mahsulot B")

    # ── Leads ───────────────────────────────────────────────────
    def test_lead_list_only_shows_own_store(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get("/api/v1/orders/?show_all=1")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(str(self.lead_a.id), ids)
        self.assertNotIn(str(self.lead_b.id), ids)

    def test_cannot_retrieve_another_stores_lead_by_id(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(f"/api/v1/orders/{self.lead_b.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── Products ────────────────────────────────────────────────
    def test_product_list_only_shows_own_store(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get("/api/v1/products/")

        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(str(self.product_a.id), ids)
        self.assertNotIn(str(self.product_b.id), ids)

    def test_cannot_retrieve_another_stores_product_by_id(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(f"/api/v1/products/{self.product_b.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_delete_another_stores_product(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.delete(f"/api/v1/products/{self.product_b.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.product_b.refresh_from_db()
        self.assertFalse(self.product_b.is_deleted)

    # ── Customers ───────────────────────────────────────────────
    def test_customer_list_only_shows_own_store(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get("/api/v1/customers/")

        ids = [row["id"] for row in response.data["results"]]
        self.assertIn(str(self.customer_a.id), ids)
        self.assertNotIn(str(self.customer_b.id), ids)

    def test_cannot_retrieve_another_stores_customer_by_id(self):
        self.client.force_authenticate(user=self.owner_a)
        response = self.client.get(f"/api/v1/customers/{self.customer_b.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── Unauthenticated ─────────────────────────────────────────
    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get("/api/v1/orders/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
