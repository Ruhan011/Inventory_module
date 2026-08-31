# Manual Test Checklist — Inventory Management Demo

## Setup

1. Activate virtual environment:
   ```bash
   source venv/bin/activate
   ```

2. Start development server:
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```

3. Open browser to `http://localhost:8000/`

4. Three seeded accounts:
   - **Admin**: `admin` / `admin123`
   - **Manager**: `manager` / `manager123`
   - **Clerk**: `clerk` / `clerk123`

---

## Role-Based Checklist

### As Clerk (clerk / clerk123)

- [ ] **Login** — Can log in successfully
- [ ] **Dashboard redirect** — After login, redirected to "Stock In/Out" page (movement create), not dashboard
- [ ] **Dashboard link hidden** — Navbar shows no "Dashboard" or "Reports" links
- [ ] **"Add Product" hidden** — Navbar shows no "Add Product" button on product list
- [ ] **Stock Movement Create** — Can access `/movements/add/`
- [ ] **Field toggle — Greek Yogurt (BATCH)**:
  - Select product "Greek Yogurt 200g"
  - Select movement type "Purchase In"
  - Batch fields (batch_number, manufacture_date, expiry_date) appear
  - Serial numbers field stays hidden
- [ ] **Field toggle — iPhone 15 Pro (SERIAL)**:
  - Select product "iPhone 15 Pro"
  - Select movement type "Purchase In"
  - Serial numbers textarea appears
  - Batch fields stay hidden
- [ ] **Field toggle — A4 Paper Box (NONE)**:
  - Select product "A4 Paper Box"
  - Select movement type "Purchase In"
  - Neither batch nor serial fields appear
- [ ] **Field toggle — Non-PURCHASE_IN types**:
  - Select any product
  - Select movement type "Sales Out" / "Damage/Loss" / "Transfer"
  - Both batch and serial fields stay hidden
- [ ] **Stock-out validation** — Submit SALES_OUT with quantity > available_qty:
  - Form shows validation error: "Only X available in this warehouse. Cannot move Y."
  - No server crash / 500 error
- [ ] **Cannot reach /products/add/** — Accessing `/products/add/` redirects with message
- [ ] **Cannot reach /reports/** — Accessing `/reports/` redirects with message

### As Manager (manager / manager123)

- [ ] **Login** — Can log in successfully
- [ ] **Dashboard visible** — Navbar shows "Dashboard" and "Reports" links
- [ ] **Dashboard content**:
  - Low-stock table shows any products at/below reorder_level
  - Expiring batches table shows "Greek Yogurt" batch (expiry within 30 days, seeded at today+20)
- [ ] **"Add Product" visible** — Product list page shows "Add Product" button
- [ ] **Product create** — Can create a new product via `/products/add/`
- [ ] **Product edit** — Can edit an existing product via `/products/<pk>/edit/`
- [ ] **Stock Report** — Can access `/reports/`
- [ ] **Print preview** — Browser print preview of `/reports/`:
  - Navbar hidden
  - Footer hidden
  - Tables render cleanly
  - Low-stock rows highlighted (light yellow)
  - Expiring-soon rows highlighted (light orange)

### As Admin (admin / admin123)

- [ ] **Login** — Can log in successfully
- [ ] **Full Django admin** — Can access `/admin/`
- [ ] **StockMovement admin read-only**:
  - Navigate to `/admin/inventory/stockmovement/`
  - No "Add Stock Movement" button
  - Clicking a row shows detail view only — no "Save", "Delete", "Change" buttons
  - List display shows: product, warehouse, movement_type, quantity, movement_date
- [ ] **All other models editable in admin** — Category, Unit, Product, ProductBatch, ProductSerial, Warehouse, Stock all have normal add/change/delete

---

## Known Simplifications (Intentional Scope Decisions)

| Feature | Behavior | Rationale |
|---------|----------|-----------|
| **TRANSFER movement** | Only decrements source warehouse `Stock.quantity`. No destination warehouse increment, no serial relocation, no batch split. | Out of scope for this demo. Documented here so it reads as an intentional design decision, not a bug. |
| **SALES_OUT / DAMAGE_LOSS on batch-tracked** | Decrements from earliest-expiring batches first (FEFO). Clerk does not select specific batch. | Simplification for demo; real system would require batch selection UI. |
| **ProductSerial.warehouse** | Set on PURCHASE_IN; cleared (set to NULL) on TRANSFER. No destination warehouse tracking. | Aligns with TRANSFER simplification above. |
| **reference_type / reference_id** | Free-text fields, default `MANUAL` / blank. No foreign key linkage to PurchaseOrder/SalesOrder (those models don't exist). | Out of scope — stubbed for future integration. |
| **Clerk permissions** | Can only add/view StockMovement. Cannot change/delete anything, including their own movements. | Append-only ledger enforced at form + admin level. |
| **No async / Celery / signals** | All stock updates happen synchronously in `StockMovementForm.save()`. | Demo simplicity. |

---

## If Something Looks Wrong

Re-run the four verification commands to confirm data/form integrity:

```bash
# 1. Warehouse queryset branching
grep -n -B2 -A2 "stock_records__product_id" inventory/forms.py

# 2. total_available check location (should only appear in SALES_OUT/DAMAGE_LOSS/TRANSFER branch)
grep -n "total_available" inventory/forms.py

# 3. No Sum() on available_qty
grep -n "Sum(" inventory/forms.py

# 4. iPhone 15 Pro stock quantities (should be 3 at Central, 2 at Retail)
python manage.py shell -c "
from inventory.models import Stock, Product
p = Product.objects.get(name='iPhone 15 Pro')
for s in Stock.objects.filter(product=p):
    print(s.warehouse.name, 'quantity=', s.quantity)
"
```

If any check fails, apply the corresponding fix (A/B/C/D) as documented in the build notes.

---

## Final System Check

```bash
python manage.py check
# Should output: "System check identified no issues (0 silenced)."
```