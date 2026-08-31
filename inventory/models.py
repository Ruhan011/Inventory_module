from django.db import models
from django.conf import settings


class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )

    class Meta:
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=10)

    def __str__(self):
        return f"{self.name} ({self.symbol})"


class Product(models.Model):
    TRACKING_NONE = 'NONE'
    TRACKING_BATCH = 'BATCH'
    TRACKING_SERIAL = 'SERIAL'
    TRACKING_CHOICES = [
        (TRACKING_NONE, 'None'),
        (TRACKING_BATCH, 'Batch'),
        (TRACKING_SERIAL, 'Serial'),
    ]

    STATUS_ACTIVE = 'ACTIVE'
    STATUS_INACTIVE = 'INACTIVE'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    sku = models.CharField(max_length=50, unique=True)
    barcode = models.CharField(max_length=50, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='products')
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2)
    reorder_level = models.IntegerField(default=10)
    tracking_mode = models.CharField(max_length=10, choices=TRACKING_CHOICES, default=TRACKING_NONE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    def __str__(self):
        return f"{self.sku} - {self.name}"


class ProductBatch(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=50)
    manufacture_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = ['product', 'batch_number']

    def __str__(self):
        return f"{self.product.sku} - {self.batch_number}"

    @property
    def is_expiring_soon(self):
        from datetime import date, timedelta
        if self.expiry_date:
            return self.expiry_date <= date.today() + timedelta(days=30)
        return False


class ProductSerial(models.Model):
    STATUS_IN_STOCK = 'IN_STOCK'
    STATUS_SOLD = 'SOLD'
    STATUS_DEFECTIVE = 'DEFECTIVE'
    STATUS_CHOICES = [
        (STATUS_IN_STOCK, 'In Stock'),
        (STATUS_SOLD, 'Sold'),
        (STATUS_DEFECTIVE, 'Defective'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='serials')
    warehouse = models.ForeignKey('Warehouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='serials')
    serial_number = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_IN_STOCK)

    def __str__(self):
        return f"{self.product.sku} - {self.serial_number}"


class Warehouse(models.Model):
    branch_id = models.IntegerField()
    name = models.CharField(max_length=100)
    location = models.CharField(max_length=200)

    def __str__(self):
        return self.name


class Stock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    batch = models.ForeignKey(ProductBatch, on_delete=models.CASCADE, null=True, blank=True, related_name='stock_records')
    quantity = models.IntegerField(default=0)
    reserved_qty = models.IntegerField(default=0)

    class Meta:
        unique_together = ['product', 'warehouse', 'batch']

    def __str__(self):
        batch_info = f" ({self.batch.batch_number})" if self.batch else ""
        return f"{self.product.sku} @ {self.warehouse.name}{batch_info}: {self.quantity}"

    @property
    def available_qty(self):
        if self.product.tracking_mode == Product.TRACKING_SERIAL:
            return self.product.serials.filter(
                warehouse=self.warehouse,
                status=ProductSerial.STATUS_IN_STOCK
            ).count()
        return self.quantity - self.reserved_qty


class StockMovement(models.Model):
    MOVEMENT_PURCHASE_IN = 'PURCHASE_IN'
    MOVEMENT_SALES_OUT = 'SALES_OUT'
    MOVEMENT_TRANSFER = 'TRANSFER'
    MOVEMENT_DAMAGE_LOSS = 'DAMAGE_LOSS'
    MOVEMENT_CHOICES = [
        (MOVEMENT_PURCHASE_IN, 'Purchase In'),
        (MOVEMENT_SALES_OUT, 'Sales Out'),
        (MOVEMENT_TRANSFER, 'Transfer'),
        (MOVEMENT_DAMAGE_LOSS, 'Damage/Loss'),
    ]

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='movements')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES)
    quantity = models.IntegerField()
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=50, blank=True)
    movement_date = models.DateTimeField(auto_now_add=True)
    batch = models.ForeignKey(ProductBatch, on_delete=models.PROTECT, null=True, blank=True, related_name='movements')

    class Meta:
        ordering = ['-movement_date']

    def __str__(self):
        return f"{self.movement_type} - {self.product.sku} - {self.quantity} @ {self.warehouse.name}"