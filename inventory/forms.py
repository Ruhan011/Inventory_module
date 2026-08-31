from django import forms
from django.db import transaction, models
from django.core.exceptions import ValidationError
from inventory.models import (
    Product, ProductBatch, ProductSerial, Stock, StockMovement, Warehouse
)


class TrackingSelect(forms.Select):
    def __init__(self, tracking_map=None, attrs=None, choices=()):
        super().__init__(attrs=attrs, choices=choices)
        self.tracking_map = tracking_map or {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        tracking_mode = self.tracking_map.get(str(value))
        if tracking_mode is not None:
            option['attrs']['data-tracking'] = tracking_mode
        return option


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'sku', 'barcode', 'name', 'description', 'category', 'unit',
            'cost_price', 'selling_price', 'reorder_level', 'tracking_mode', 'status'
        ]


class StockMovementForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(status=Product.STATUS_ACTIVE))
    warehouse = forms.ModelChoiceField(queryset=Stock.objects.none())
    movement_type = forms.ChoiceField(choices=StockMovement.MOVEMENT_CHOICES)
    quantity = forms.IntegerField(min_value=1)
    reference_type = forms.CharField(max_length=50, required=False, initial='MANUAL')
    reference_id = forms.CharField(max_length=50, required=False)

    batch_number = forms.CharField(max_length=50, required=False)
    manufacture_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    expiry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    serial_numbers = forms.CharField(widget=forms.Textarea, required=False, help_text='One serial number per line')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['warehouse'].queryset = Stock.objects.none()

        # Attach data-tracking attribute to each product option so the JS
        # can toggle batch/serial fields dynamically without breaking
        # ModelChoiceField's 2-tuple choice validation.
        tracking_map = {
            str(p.pk): p.tracking_mode
            for p in self.fields['product'].queryset
        }
        self.fields['product'].widget = TrackingSelect(
            tracking_map=tracking_map,
            attrs=self.fields['product'].widget.attrs,
            choices=self.fields['product'].choices,
        )

        product_id = None
        if 'product' in self.data:
            try:
                product_id = int(self.data.get('product'))
            except (ValueError, TypeError):
                pass
        elif self.initial.get('product'):
            product_id = self.initial['product'].id if hasattr(self.initial['product'], 'id') else self.initial['product']

        movement_type = self.data.get('movement_type') or self.initial.get('movement_type')
        depleting_types = [
            StockMovement.MOVEMENT_SALES_OUT,
            StockMovement.MOVEMENT_DAMAGE_LOSS,
            StockMovement.MOVEMENT_TRANSFER,
        ]

        if product_id:
            if movement_type in depleting_types:
                self.fields['warehouse'].queryset = Warehouse.objects.filter(
                    stock_records__product_id=product_id
                ).distinct()
            else:
                self.fields['warehouse'].queryset = Warehouse.objects.all()

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get('product')
        warehouse = cleaned_data.get('warehouse')
        movement_type = cleaned_data.get('movement_type')
        quantity = cleaned_data.get('quantity')

        if not product or not warehouse or not movement_type or quantity is None:
            return cleaned_data

        if quantity <= 0:
            raise ValidationError({'quantity': 'Quantity must be greater than 0.'})

        if movement_type == StockMovement.MOVEMENT_PURCHASE_IN:
            if product.tracking_mode == Product.TRACKING_BATCH:
                batch_number = cleaned_data.get('batch_number')
                manufacture_date = cleaned_data.get('manufacture_date')
                expiry_date = cleaned_data.get('expiry_date')
                if not batch_number:
                    raise ValidationError({'batch_number': 'Batch number is required for batch-tracked products.'})
                if not manufacture_date:
                    raise ValidationError({'manufacture_date': 'Manufacture date is required for batch-tracked products.'})
                if not expiry_date:
                    raise ValidationError({'expiry_date': 'Expiry date is required for batch-tracked products.'})
                if expiry_date <= manufacture_date:
                    raise ValidationError({'expiry_date': 'Expiry date must be after manufacture date.'})

            elif product.tracking_mode == Product.TRACKING_SERIAL:
                serial_input = cleaned_data.get('serial_numbers', '').strip()
                if not serial_input:
                    raise ValidationError({'serial_numbers': 'Serial numbers are required for serial-tracked products.'})
                serials = [s.strip() for s in serial_input.splitlines() if s.strip()]
                if len(serials) != quantity:
                    raise ValidationError({
                        'serial_numbers': f'Entered {len(serials)} serial numbers, but quantity is {quantity}. They must match.'
                    })
                existing = ProductSerial.objects.filter(serial_number__in=serials).exists()
                if existing:
                    raise ValidationError({'serial_numbers': 'One or more serial numbers already exist.'})
                cleaned_data['_serials_list'] = serials

        elif movement_type in (StockMovement.MOVEMENT_SALES_OUT, StockMovement.MOVEMENT_DAMAGE_LOSS, StockMovement.MOVEMENT_TRANSFER):
            stock_qs = Stock.objects.filter(product=product, warehouse=warehouse)
            total_available = sum(s.available_qty for s in stock_qs)

            if quantity > total_available:
                raise ValidationError({
                    'quantity': f'Only {total_available} available in this warehouse. Cannot move {quantity}.'
                })

        return cleaned_data

    @transaction.atomic
    def save(self):
        cleaned = self.cleaned_data
        product = cleaned['product']
        warehouse = cleaned['warehouse']
        movement_type = cleaned['movement_type']
        quantity = cleaned['quantity']
        reference_type = cleaned.get('reference_type', 'MANUAL')
        reference_id = cleaned.get('reference_id', '')

        if movement_type == StockMovement.MOVEMENT_PURCHASE_IN:
            if product.tracking_mode == Product.TRACKING_BATCH:
                batch, _ = ProductBatch.objects.get_or_create(
                    product=product,
                    batch_number=cleaned['batch_number'],
                    defaults={
                        'manufacture_date': cleaned['manufacture_date'],
                        'expiry_date': cleaned['expiry_date'],
                    }
                )
                stock, _ = Stock.objects.get_or_create(
                    product=product, warehouse=warehouse, batch=batch,
                    defaults={'quantity': 0, 'reserved_qty': 0}
                )
                stock.quantity += quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse, batch=batch,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            elif product.tracking_mode == Product.TRACKING_SERIAL:
                serials = cleaned['_serials_list']
                stock, _ = Stock.objects.get_or_create(
                    product=product, warehouse=warehouse, batch=None,
                    defaults={'quantity': 0, 'reserved_qty': 0}
                )
                for sn in serials:
                    ProductSerial.objects.create(
                        product=product, warehouse=warehouse,
                        serial_number=sn, status=ProductSerial.STATUS_IN_STOCK
                    )
                stock.quantity += len(serials)
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            else:
                stock, _ = Stock.objects.get_or_create(
                    product=product, warehouse=warehouse, batch=None,
                    defaults={'quantity': 0, 'reserved_qty': 0}
                )
                stock.quantity += quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

        elif movement_type == StockMovement.MOVEMENT_SALES_OUT:
            if product.tracking_mode == Product.TRACKING_SERIAL:
                serials = ProductSerial.objects.filter(
                    product=product, warehouse=warehouse,
                    status=ProductSerial.STATUS_IN_STOCK
                ).order_by('id')[:quantity]
                if serials.count() < quantity:
                    raise ValidationError('Not enough serials in stock.')
                for s in serials:
                    s.status = ProductSerial.STATUS_SOLD
                    s.save()
                stock = Stock.objects.get(product=product, warehouse=warehouse, batch=None)
                stock.quantity -= quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            elif product.tracking_mode == Product.TRACKING_BATCH:
                stock = Stock.objects.filter(product=product, warehouse=warehouse).order_by('batch__expiry_date')
                remaining = quantity
                for s in stock:
                    take = min(s.quantity, remaining)
                    s.quantity -= take
                    s.save()
                    remaining -= take
                    if remaining == 0:
                        break
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            else:
                stock = Stock.objects.get(product=product, warehouse=warehouse, batch=None)
                stock.quantity -= quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

        elif movement_type == StockMovement.MOVEMENT_DAMAGE_LOSS:
            if product.tracking_mode == Product.TRACKING_SERIAL:
                serials = ProductSerial.objects.filter(
                    product=product, warehouse=warehouse,
                    status=ProductSerial.STATUS_IN_STOCK
                ).order_by('id')[:quantity]
                if serials.count() < quantity:
                    raise ValidationError('Not enough serials in stock.')
                for s in serials:
                    s.status = ProductSerial.STATUS_DEFECTIVE
                    s.save()
                stock = Stock.objects.get(product=product, warehouse=warehouse, batch=None)
                stock.quantity -= quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            elif product.tracking_mode == Product.TRACKING_BATCH:
                stock = Stock.objects.filter(product=product, warehouse=warehouse).order_by('batch__expiry_date')
                remaining = quantity
                for s in stock:
                    take = min(s.quantity, remaining)
                    s.quantity -= take
                    s.save()
                    remaining -= take
                    if remaining == 0:
                        break
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            else:
                stock = Stock.objects.get(product=product, warehouse=warehouse, batch=None)
                stock.quantity -= quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

        elif movement_type == StockMovement.MOVEMENT_TRANSFER:
            # Decrement source warehouse only (per confirmed simplification)
            if product.tracking_mode == Product.TRACKING_SERIAL:
                serials = ProductSerial.objects.filter(
                    product=product, warehouse=warehouse,
                    status=ProductSerial.STATUS_IN_STOCK
                ).order_by('id')[:quantity]
                if serials.count() < quantity:
                    raise ValidationError('Not enough serials in stock.')
                for s in serials:
                    # Per simplification: mark as sold/defective? Or leave as IN_STOCK?
                    # The requirement says "decrement source warehouse's Stock only"
                    # For serials, we just remove them from this warehouse (set warehouse=None or mark SOLD?)
                    # Since TRANSFER doesn't create destination stock, we'll mark SOLD for simplicity
                    # but this is a simplification noted in the plan.
                    s.warehouse = None
                    s.status = ProductSerial.STATUS_SOLD
                    s.save()
                stock = Stock.objects.get(product=product, warehouse=warehouse, batch=None)
                stock.quantity -= quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            elif product.tracking_mode == Product.TRACKING_BATCH:
                stock = Stock.objects.filter(product=product, warehouse=warehouse).order_by('batch__expiry_date')
                remaining = quantity
                for s in stock:
                    take = min(s.quantity, remaining)
                    s.quantity -= take
                    s.save()
                    remaining -= take
                    if remaining == 0:
                        break
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

            else:
                stock = Stock.objects.get(product=product, warehouse=warehouse, batch=None)
                stock.quantity -= quantity
                stock.save()
                movement = StockMovement.objects.create(
                    product=product, warehouse=warehouse,
                    movement_type=movement_type, quantity=quantity,
                    reference_type=reference_type, reference_id=reference_id
                )

        return movement