from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum
from django.utils import timezone
from datetime import date, timedelta
from inventory.models import (
    Category, Product, ProductBatch, ProductSerial,
    Warehouse, Stock, StockMovement
)
from inventory.forms import ProductForm, StockMovementForm


def manager_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.groups.filter(name='Manager').exists()):
            messages.error(request, 'Manager or Admin access required.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


def admin_or_manager_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_superuser or request.user.groups.filter(name='Manager').exists()):
            messages.error(request, 'Manager or Admin access required.')
            return redirect('dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@login_required
def dashboard(request):
    if request.user.groups.filter(name='Clerk').exists() and not (request.user.is_superuser or request.user.groups.filter(name='Manager').exists()):
        messages.info(request, 'Clerk access: redirected to stock movement entry.')
        return redirect('stock_movement_create')

    today = date.today()
    expiry_threshold = today + timedelta(days=30)

    low_stock_products = []
    for product in Product.objects.filter(status=Product.STATUS_ACTIVE):
        total_available = Stock.objects.filter(product=product).aggregate(
            total=Sum('quantity')
        )['total'] or 0
        if total_available <= product.reorder_level and total_available > 0:
            low_stock_products.append({
                'product': product,
                'total_available': total_available,
                'reorder_level': product.reorder_level,
            })
        elif total_available == 0:
            low_stock_products.append({
                'product': product,
                'total_available': 0,
                'reorder_level': product.reorder_level,
            })

    expiring_batches = ProductBatch.objects.filter(
        expiry_date__lte=expiry_threshold,
        expiry_date__isnull=False
    ).select_related('product')

    context = {
        'low_stock_products': low_stock_products,
        'expiring_batches': expiring_batches,
        'total_products': Product.objects.filter(status=Product.STATUS_ACTIVE).count(),
        'total_warehouses': Warehouse.objects.count(),
    }
    return render(request, 'inventory/dashboard.html', context)


@login_required
def product_list(request):
    query = request.GET.get('q', '')
    category_id = request.GET.get('category', '')

    products = Product.objects.select_related('category', 'unit').filter(status=Product.STATUS_ACTIVE)

    if query:
        products = products.filter(
            Q(sku__icontains=query) | Q(name__icontains=query) | Q(barcode__icontains=query)
        )
    if category_id:
        products = products.filter(category_id=category_id)

    categories = Category.objects.all()

    context = {
        'products': products,
        'query': query,
        'selected_category': category_id,
        'categories': categories,
    }
    return render(request, 'inventory/product_list.html', context)


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related('category', 'unit'), pk=pk)

    stock_records = Stock.objects.filter(product=product).select_related('warehouse', 'batch')
    batches = ProductBatch.objects.filter(product=product).order_by('expiry_date')
    serials = ProductSerial.objects.filter(product=product).select_related('warehouse').order_by('warehouse__name', 'serial_number')

    context = {
        'product': product,
        'stock_records': stock_records,
        'batches': batches,
        'serials': serials,
    }
    return render(request, 'inventory/product_detail.html', context)


@admin_or_manager_required
@login_required
def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product created successfully.')
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'inventory/product_form.html', {'form': form, 'action': 'Create'})


@admin_or_manager_required
@login_required
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated successfully.')
            return redirect('product_detail', pk=product.pk)
    else:
        form = ProductForm(instance=product)
    return render(request, 'inventory/product_form.html', {'form': form, 'action': 'Update', 'product': product})


@login_required
def warehouse_list(request):
    warehouses = Warehouse.objects.all()
    return render(request, 'inventory/warehouse_list.html', {'warehouses': warehouses})


@login_required
def warehouse_detail(request, pk):
    warehouse = get_object_or_404(Warehouse, pk=pk)
    stock_records = Stock.objects.filter(warehouse=warehouse).select_related('product', 'batch')
    return render(request, 'inventory/warehouse_detail.html', {'warehouse': warehouse, 'stock_records': stock_records})


@login_required
def stock_movement_list(request):
    warehouse_id = request.GET.get('warehouse')
    movement_type = request.GET.get('movement_type')

    movements = StockMovement.objects.select_related('product', 'warehouse', 'batch').order_by('-movement_date')

    if warehouse_id:
        movements = movements.filter(warehouse_id=warehouse_id)
    if movement_type:
        movements = movements.filter(movement_type=movement_type)

    warehouses = Warehouse.objects.all()
    movement_types = StockMovement.MOVEMENT_CHOICES

    context = {
        'movements': movements,
        'warehouses': warehouses,
        'movement_types': movement_types,
        'selected_warehouse': warehouse_id,
        'selected_movement_type': movement_type,
    }
    return render(request, 'inventory/stock_movement_list.html', context)


@login_required
def stock_movement_create(request):
    if request.method == 'POST':
        form = StockMovementForm(request.POST)
        if form.is_valid():
            try:
                movement = form.save()
                messages.success(request, f'Stock movement recorded: {movement}')
                return redirect('stock_movement_list')
            except Exception as e:
                form.add_error(None, str(e))
    else:
        form = StockMovementForm()

    return render(request, 'inventory/stock_movement_form.html', {'form': form})


@admin_or_manager_required
@login_required
def stock_report(request):
    today = date.today()
    expiry_threshold = today + timedelta(days=30)

    low_stock = []
    for product in Product.objects.filter(status=Product.STATUS_ACTIVE):
        stock_qs = Stock.objects.filter(product=product)
        total_available = sum(s.available_qty for s in stock_qs)
        if total_available <= product.reorder_level:
            low_stock.append({
                'product': product,
                'total_available': total_available,
                'reorder_level': product.reorder_level,
            })

    expiring_batches = ProductBatch.objects.filter(
        expiry_date__lte=expiry_threshold,
        expiry_date__isnull=False
    ).select_related('product')

    context = {
        'low_stock': low_stock,
        'expiring_batches': expiring_batches,
        'generated_at': timezone.now(),
    }
    return render(request, 'inventory/stock_report.html', context)