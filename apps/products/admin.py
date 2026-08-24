from django.contrib import admin
from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "store", "price", "stock", "category", "is_active", "created_at"]
    list_filter = ["is_active", "category", "store"]
    search_fields = ["name", "description", "sku"]
    readonly_fields = ["id", "created_at", "updated_at"]
    ordering = ["-created_at"]

    def get_queryset(self, request):
        return self.model.all_objects.all()
