from django.contrib import admin
from django.db import models
from inventory.models import (
    Category, Unit, Product, ProductBatch, ProductSerial,
    Warehouse, Stock, StockMovement
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ['name']


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ['name', 'symbol']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['sku', 'name', 'category', 'status', 'cost_price', 'selling_price']
    list_filter = ['status', 'category']
    search_fields = ['sku', 'name']


class ExpiringSoonFilter(admin.SimpleListFilter):
    title = 'expiring soon (30 days)'
    parameter_name = 'expiring_soon'

    def lookups(self, request, model_admin):
        return [
            ('yes', 'Expiring within 30 days'),
            ('no', 'Not expiring soon'),
        ]

    def queryset(self, request, queryset):
        from datetime import date, timedelta
        threshold = date.today() + timedelta(days=30)
        if self.value() == 'yes':
            return queryset.filter(expiry_date__lte=threshold, expiry_date__isnull=False)
        if self.value() == 'no':
            return queryset.filter(models.Q(expiry_date__gt=threshold) | models.Q(expiry_date__isnull=True))
        return queryset


@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = ['batch_number', 'product', 'expiry_date']
    list_filter = [ExpiringSoonFilter]


@admin.register(ProductSerial)
class ProductSerialAdmin(admin.ModelAdmin):
    list_display = ['serial_number', 'product', 'warehouse', 'status']
    list_filter = ['status']
    search_fields = ['serial_number']


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'branch_id']


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['product', 'warehouse', 'quantity', 'available_qty']
    list_filter = ['warehouse']


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ['product', 'warehouse', 'movement_type', 'quantity', 'movement_date']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False