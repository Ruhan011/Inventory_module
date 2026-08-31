from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from inventory.models import (
    Category, Unit, Product, ProductBatch, ProductSerial,
    Warehouse, Stock, StockMovement
)


class Command(BaseCommand):
    help = 'Seed demo data for inventory module (idempotent)'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Seeding demo data...'))

        self._create_groups_and_permissions()
        self._create_users()
        categories = self._create_categories()
        units = self._create_units()
        warehouses = self._create_warehouses()
        products = self._create_products(categories, units)
        self._create_stock_and_movements(products, warehouses)

        self.stdout.write(self.style.SUCCESS('Demo data seeded successfully.'))

    def _create_groups_and_permissions(self):
        manager_group, _ = Group.objects.get_or_create(name='Manager')
        clerk_group, _ = Group.objects.get_or_create(name='Clerk')

        models = [
            Category, Unit, Product, ProductBatch,
            ProductSerial, Warehouse, Stock, StockMovement
        ]

        for model in models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct)
            manager_group.permissions.add(*perms)

        clerk_models = [Product, ProductBatch, ProductSerial, Stock, Warehouse, StockMovement]
        for model in clerk_models:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct, codename__startswith='view_')
            clerk_group.permissions.add(*perms)

        for model in [StockMovement]:
            ct = ContentType.objects.get_for_model(model)
            perms = Permission.objects.filter(content_type=ct, codename__startswith='add_')
            clerk_group.permissions.add(*perms)

        manager_group.save()
        clerk_group.save()
        self.stdout.write('  Groups & permissions: Manager (full), Clerk (view + add StockMovement)')

    def _create_users(self):
        admin_user, created = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True})
        admin_user.set_password('admin123')
        admin_user.is_superuser = True
        admin_user.is_staff = True
        admin_user.save()

        manager_user, _ = User.objects.get_or_create(username='manager', defaults={'is_staff': True})
        manager_user.set_password('manager123')
        manager_user.is_staff = True
        manager_user.groups.set([Group.objects.get(name='Manager')])
        manager_user.save()

        clerk_user, _ = User.objects.get_or_create(username='clerk', defaults={'is_staff': True})
        clerk_user.set_password('clerk123')
        clerk_user.is_staff = True
        clerk_user.groups.set([Group.objects.get(name='Clerk')])
        clerk_user.save()

        self.stdout.write('  Users: admin/admin123 (super), manager/manager123 (Manager), clerk/clerk123 (Clerk)')

    def _create_categories(self):
        cats = {}
        for name in ['Electronics', 'Food/Groceries', 'Office Supplies']:
            cat, _ = Category.objects.get_or_create(name=name)
            cats[name] = cat
        self.stdout.write('  Categories: Electronics, Food/Groceries, Office Supplies')
        return cats

    def _create_units(self):
        units = {}
        for name, symbol in [('pcs', 'pcs'), ('kg', 'kg'), ('box', 'box')]:
            unit, _ = Unit.objects.get_or_create(name=name, symbol=symbol)
            units[name] = unit
        self.stdout.write('  Units: pcs, kg, box')
        return units

    def _create_warehouses(self):
        wh_data = [
            {'branch_id': 1, 'name': 'Central Warehouse', 'location': 'Dhaka Main Hub'},
            {'branch_id': 2, 'name': 'Retail Store A', 'location': 'Dhanmondi Branch'},
        ]
        warehouses = {}
        for data in wh_data:
            wh, _ = Warehouse.objects.get_or_create(name=data['name'], defaults=data)
            warehouses[data['name']] = wh
        self.stdout.write('  Warehouses: Central Warehouse (branch_id=1), Retail Store A (branch_id=2)')
        return warehouses

    def _create_products(self, categories, units):
        products_data = [
            {
                'sku': 'IPHONE15PRO',
                'barcode': '885909998910',
                'name': 'iPhone 15 Pro',
                'description': 'Apple iPhone 15 Pro 128GB',
                'category': categories['Electronics'],
                'unit': units['pcs'],
                'cost_price': '85000.00',
                'selling_price': '105000.00',
                'reorder_level': 5,
                'tracking_mode': Product.TRACKING_SERIAL,
                'status': Product.STATUS_ACTIVE,
            },
            {
                'sku': 'GREEKYOGURT',
                'barcode': '0000000001234',
                'name': 'Greek Yogurt 200g',
                'description': 'Plain Greek Yogurt 200g cup',
                'category': categories['Food/Groceries'],
                'unit': units['pcs'],
                'cost_price': '40.00',
                'selling_price': '65.00',
                'reorder_level': 20,
                'tracking_mode': Product.TRACKING_BATCH,
                'status': Product.STATUS_ACTIVE,
            },
            {
                'sku': 'A4PAPERBOX',
                'barcode': '0000000005678',
                'name': 'A4 Paper Box',
                'description': '5 reams per box, 80gsm',
                'category': categories['Office Supplies'],
                'unit': units['box'],
                'cost_price': '350.00',
                'selling_price': '520.00',
                'reorder_level': 15,
                'tracking_mode': Product.TRACKING_NONE,
                'status': Product.STATUS_ACTIVE,
            },
        ]
        products = {}
        for data in products_data:
            prod, _ = Product.objects.get_or_create(sku=data['sku'], defaults=data)
            products[data['sku']] = prod
        self.stdout.write('  Products: iPhone 15 Pro (SERIAL), Greek Yogurt (BATCH), A4 Paper Box (NONE)')
        return products

    def _create_stock_and_movements(self, products, warehouses):
        central = warehouses['Central Warehouse']
        retail = warehouses['Retail Store A']
        today = date.today()
        ref_type = 'SEED'
        ref_id = '0'

        iphone = products['IPHONE15PRO']
        yogurt = products['GREEKYOGURT']
        paper = products['A4PAPERBOX']

        # SERIAL product: one Stock row per warehouse (batch=None), serials created separately
        serials_created = 0
        central_serials = 0
        retail_serials = 0

        for wh in [central, retail]:
            Stock.objects.get_or_create(
                product=iphone,
                warehouse=wh,
                defaults={'quantity': 0, 'reserved_qty': 0}
            )

        for i in range(1, 4):
            wh = central
            serial, created = ProductSerial.objects.get_or_create(
                serial_number=f'IPHONE15PRO-SN{i:04d}',
                defaults={
                    'product': iphone,
                    'warehouse': wh,
                    'status': ProductSerial.STATUS_IN_STOCK,
                }
            )
            if created:
                serials_created += 1
                central_serials += 1
                StockMovement.objects.create(
                    product=iphone,
                    warehouse=wh,
                    movement_type=StockMovement.MOVEMENT_PURCHASE_IN,
                    quantity=1,
                    reference_type=ref_type,
                    reference_id=ref_id,
                )
        for i in range(4, 6):
            wh = retail
            serial, created = ProductSerial.objects.get_or_create(
                serial_number=f'IPHONE15PRO-SN{i:04d}',
                defaults={
                    'product': iphone,
                    'warehouse': wh,
                    'status': ProductSerial.STATUS_IN_STOCK,
                }
            )
            if created:
                serials_created += 1
                retail_serials += 1
                StockMovement.objects.create(
                    product=iphone,
                    warehouse=wh,
                    movement_type=StockMovement.MOVEMENT_PURCHASE_IN,
                    quantity=1,
                    reference_type=ref_type,
                    reference_id=ref_id,
                )

        # Update Stock.quantity to match serials created per warehouse
        if central_serials > 0:
            stock = Stock.objects.get(product=iphone, warehouse=central, batch=None)
            stock.quantity += central_serials
            stock.save()
        if retail_serials > 0:
            stock = Stock.objects.get(product=iphone, warehouse=retail, batch=None)
            stock.quantity += retail_serials
            stock.save()

        self.stdout.write(f'  iPhone 15 Pro: {serials_created} serials created (3 Central, 2 Retail)')

        # BATCH product
        batch, batch_created = ProductBatch.objects.get_or_create(
            product=yogurt,
            batch_number='BATCH-2026-001',
            defaults={
                'manufacture_date': today,
                'expiry_date': today + timedelta(days=20),
            }
        )
        if batch_created:
            self.stdout.write(f'  Greek Yogurt: batch {batch.batch_number} created (expiry {batch.expiry_date})')

        yogurt_movement, _ = StockMovement.objects.get_or_create(
            product=yogurt,
            warehouse=central,
            batch=batch,
            movement_type=StockMovement.MOVEMENT_PURCHASE_IN,
            quantity=40,
            reference_type=ref_type,
            reference_id=ref_id,
        )
        Stock.objects.get_or_create(
            product=yogurt,
            warehouse=central,
            batch=batch,
            defaults={'quantity': 40, 'reserved_qty': 0}
        )
        self.stdout.write('  Greek Yogurt: 40 units at Central Warehouse (batch tracked)')

        # NONE product
        paper_central_move, _ = StockMovement.objects.get_or_create(
            product=paper,
            warehouse=central,
            movement_type=StockMovement.MOVEMENT_PURCHASE_IN,
            quantity=100,
            reference_type=ref_type,
            reference_id=ref_id,
        )
        Stock.objects.get_or_create(
            product=paper,
            warehouse=central,
            defaults={'quantity': 100, 'reserved_qty': 0}
        )

        paper_retail_move, _ = StockMovement.objects.get_or_create(
            product=paper,
            warehouse=retail,
            movement_type=StockMovement.MOVEMENT_PURCHASE_IN,
            quantity=30,
            reference_type=ref_type,
            reference_id=ref_id,
        )
        Stock.objects.get_or_create(
            product=paper,
            warehouse=retail,
            defaults={'quantity': 30, 'reserved_qty': 0}
        )
        self.stdout.write('  A4 Paper Box: 100 units Central, 30 units Retail (no batch/serial)')

        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('Summary:'))
        self.stdout.write(f'  Categories: {Category.objects.count()}')
        self.stdout.write(f'  Units: {Unit.objects.count()}')
        self.stdout.write(f'  Warehouses: {Warehouse.objects.count()}')
        self.stdout.write(f'  Products: {Product.objects.count()}')
        self.stdout.write(f'  ProductBatches: {ProductBatch.objects.count()}')
        self.stdout.write(f'  ProductSerials: {ProductSerial.objects.count()}')
        self.stdout.write(f'  Stock records: {Stock.objects.count()}')
        self.stdout.write(f'  StockMovements: {StockMovement.objects.count()}')
        self.stdout.write(f'  Users: {User.objects.count()}')
        self.stdout.write(f'  Groups: {Group.objects.count()}')