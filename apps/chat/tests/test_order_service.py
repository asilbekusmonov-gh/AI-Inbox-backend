"""
create_order_from_ai_data() uchun testlar.

Bu funksiya ustida ikki marta jonli xatolar tasdiqlangan edi
(order_service.py'dagi BUG FIX izohlariga qarang):
1. AI aytgan narxga ishonib buyurtma summasi hisoblangan (narxni AI
   xohlagancha pastlatib/oshirib yuborishi mumkin edi).
2. Mahsulot nomi bo'yicha qidirishda tartib berilmagani uchun bir nomi
   ikkinchisining ichida bo'lgan mahsulotlar orasida noto'g'ri (tasodifiy)
   moslashuv tanlanardi.

Bu testlar aynan shu ikki xatoning qaytib kelmasligini tekshiradi.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from apps.chat.order_service import create_order_from_ai_data
from apps.customers.models import Customer
from apps.orders.models import Order
from apps.products.models import Product
from apps.stores.models import Store


class OrderServiceTestCase(TestCase):
    def setUp(self):
        owner = User.objects.create_user(username="owner1", password="x")
        self.store = Store.objects.create(owner=owner, name="Test Do'kon")
        self.customer = Customer.objects.create(
            store=self.store,
            platform=Customer.Platform.TELEGRAM,
            platform_user_id="12345",
        )

    def _base_order_data(self, **overrides):
        data = {
            "full_name": "Aziz Ismoilov",
            "phone": "+998901234567",
            "address": "Toshkent, Chilonzor",
            "items": [{"name": "Krossovka", "qty": 1, "price": 1}],
        }
        data.update(overrides)
        return data

    def test_catalog_price_overrides_ai_stated_price(self):
        """AI 1 so'm deb aytsa ham, buyurtma haqiqiy katalog narxi bilan yaratilishi kerak."""
        Product.objects.create(store=self.store, name="Krossovka", price=Decimal("500000"), stock=10)

        order = create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Krossovka", "qty": 2, "price": 1}]),
            platform="telegram",
        )

        self.assertIsNotNone(order)
        self.assertEqual(order.total_amount, Decimal("1000000"))
        self.assertEqual(order.items[0]["price"], 500000.0)

    def test_unknown_product_gets_zero_price_not_ai_price(self):
        """Katalogda topilmagan mahsulotga AI aytgan narx emas, 0 beriladi (xavfsizlik uchun)."""
        order = create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Mavjud Emas Mahsulot", "qty": 1, "price": 999999}]),
            platform="telegram",
        )

        self.assertIsNotNone(order)
        self.assertEqual(order.total_amount, Decimal("0"))
        self.assertIsNone(order.items[0]["product_id"])

    def test_exact_name_match_preferred_over_substring_match(self):
        """'Kurtka qora' so'ralganda, uni ichiga olgan 'Kurtka qora XL' emas, aniq mos nomi tanlanishi kerak."""
        exact = Product.objects.create(store=self.store, name="Kurtka qora", price=Decimal("300000"), stock=5)
        Product.objects.create(store=self.store, name="Kurtka qora XL o'lcham", price=Decimal("350000"), stock=5)

        order = create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Kurtka qora", "qty": 1, "price": 300000}]),
            platform="telegram",
        )

        self.assertEqual(order.total_amount, Decimal("300000"))
        self.assertEqual(order.items[0]["product_id"], str(exact.id))

    def test_partial_match_prefers_shortest_candidate(self):
        """Aniq mos kelmasa, qisman mos keluvchilar orasidan eng qisqa (so'ralgan nomga eng yaqin) nomi tanlanadi."""
        closer = Product.objects.create(store=self.store, name="Krossovka Nike 42", price=Decimal("400000"), stock=5)
        Product.objects.create(store=self.store, name="Krossovka Nike 42 qora rang", price=Decimal("450000"), stock=5)

        order = create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Krossovka Nike", "qty": 1, "price": 400000}]),
            platform="telegram",
        )

        self.assertEqual(order.items[0]["product_id"], str(closer.id))

    def test_product_lookup_is_scoped_to_store(self):
        """Boshqa do'kondagi xuddi shu nomli mahsulot bu do'konning buyurtmasiga narx bermasligi kerak."""
        other_owner = User.objects.create_user(username="owner2", password="x")
        other_store = Store.objects.create(owner=other_owner, name="Boshqa Do'kon")
        Product.objects.create(store=other_store, name="Krossovka", price=Decimal("999999"), stock=99)

        order = create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Krossovka", "qty": 1, "price": 1}]),
            platform="telegram",
        )

        self.assertEqual(order.total_amount, Decimal("0"))

    def test_order_creation_deducts_stock(self):
        product = Product.objects.create(store=self.store, name="Krossovka", price=Decimal("100000"), stock=10)

        create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Krossovka", "qty": 3, "price": 100000}]),
            platform="telegram",
        )

        product.refresh_from_db()
        self.assertEqual(product.stock, 7)

    def test_stock_never_goes_below_zero(self):
        product = Product.objects.create(store=self.store, name="Krossovka", price=Decimal("100000"), stock=1)

        create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(items=[{"name": "Krossovka", "qty": 5, "price": 100000}]),
            platform="telegram",
        )

        product.refresh_from_db()
        self.assertEqual(product.stock, 0)

    def test_missing_full_name_is_rejected(self):
        order = create_order_from_ai_data(
            self.store, self.customer, self._base_order_data(full_name=""), platform="telegram",
        )
        self.assertIsNone(order)
        self.assertEqual(Order.objects.count(), 0)

    def test_missing_phone_is_rejected(self):
        order = create_order_from_ai_data(
            self.store, self.customer, self._base_order_data(phone=""), platform="telegram",
        )
        self.assertIsNone(order)

    def test_ecommerce_without_address_is_rejected(self):
        order = create_order_from_ai_data(
            self.store, self.customer, self._base_order_data(address=""), platform="telegram",
        )
        self.assertIsNone(order)

    def test_education_lead_does_not_require_address(self):
        """Ta'lim toifasida 'address' maydoni yo'q — bu yerga bo'sh berilishi buyurtmani rad etmasligi kerak."""
        order = create_order_from_ai_data(
            self.store, self.customer,
            {
                "full_name": "Aziz Ismoilov",
                "phone": "+998901234567",
                "course_name": "Ingliz tili A1",
                "preferred_time": "Dushanba, 18:00",
            },
            platform="telegram",
        )

        self.assertIsNotNone(order)
        self.assertIn("Sinov darsi vaqti", order.notes)

    def test_services_booking_does_not_require_address(self):
        order = create_order_from_ai_data(
            self.store, self.customer,
            {
                "full_name": "Aziz Ismoilov",
                "phone": "+998901234567",
                "service_name": "Soch olish",
                "specialist": "Dilnoza",
                "booking_time": "Seshanba, 15:00",
            },
            platform="telegram",
        )

        self.assertIsNotNone(order)
        self.assertIn("Mutaxassis", order.notes)

    def test_suspicious_phone_is_flagged_but_not_rejected(self):
        order = create_order_from_ai_data(
            self.store, self.customer,
            self._base_order_data(phone="abc123"),
            platform="telegram",
        )

        self.assertIsNotNone(order)
        self.assertIn("shubhali", order.notes)

    def test_customer_stats_updated_on_first_order(self):
        create_order_from_ai_data(
            self.store, self.customer, self._base_order_data(), platform="telegram",
        )

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.full_name, "Aziz Ismoilov")
        self.assertEqual(self.customer.total_orders, 1)
