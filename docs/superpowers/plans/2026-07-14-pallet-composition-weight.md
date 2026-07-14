# Pallet Composition and Weight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit weight to articles, distribute each order line across individually numbered pallets, calculate kg per pallet and order, and expose a large live total in the load-order editor.

**Architecture:** Keep `LoadOrderProduct` as the source of truth for requested quantities and add normalized `LoadOrderPalletAllocation` rows as the distribution layer. Isolate quantity/weight reconciliation in a small domain service, snapshot article weight into each allocation, and make the existing load-order service persist nested pallet drafts transactionally. Add a focused pallet-composition widget to the existing dialog rather than growing all UI logic inline.

**Tech Stack:** Python 3, Peewee, SQLite/MySQL runtime schema evolution, PyQt5, pytest.

---

## File map

- Modify `app/models/masters.py`: article unit weight.
- Modify `app/models/load_orders.py`: individual pallet sequence, allocation model, weight properties.
- Modify `app/models/__init__.py`: register the allocation model in dependency-safe order.
- Modify `app/config/schema.py`: decimal SQL support, indexes and legacy pallet expansion.
- Modify `app/services/master_service.py`: validate and persist article weight.
- Create `app/services/pallet_composition_service.py`: pure reconciliation, status and issue-gate rules.
- Modify `app/services/load_order_service.py`: validate and replace pallet/allocation drafts.
- Modify `app/services/load_order_operation_service.py`: block issue when composition is not ready.
- Modify `app/ui/master_abm.py`: article weight field and list column.
- Create `app/ui/pallet_composition.py`: cards, side editor, totals and draft serialization.
- Modify `app/ui/desktop_app.py`: add the Pallets step and connect the focused widget.
- Modify `scripts/generate_ux_screenshots.py`: capture the approved load-order composition screen.
- Add/modify focused tests under `tests/` as listed per task.

## Task 1: Persist article weight and normalized pallet composition

**Files:**
- Modify: `app/models/masters.py`
- Modify: `app/models/load_orders.py`
- Modify: `app/models/__init__.py`
- Modify: `app/config/schema.py`
- Test: `tests/test_models.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write failing model tests**

Add tests that pin defaults, relationships and decimal calculations:

```python
from decimal import Decimal

from app.models.load_orders import LoadOrderPallet, LoadOrderPalletAllocation
from app.models.masters import Product


def test_product_weight_defaults_to_zero(db):
    product = Product.create(name="Sin peso", unit="unidad")
    assert product.peso_unitario_kg == Decimal("0.000")


def test_pallet_allocation_snapshots_weight_and_calculates_kg(order_factory, product_factory):
    order = order_factory()
    destination = order.destinations.get()
    product = product_factory(peso_unitario_kg=Decimal("25.500"))
    pallet = LoadOrderPallet.create(order=order, sequence=1, quantity=1, measure="", weight=0)
    allocation = LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=product,
        quantity=Decimal("12.000"),
        peso_unitario_kg=product.peso_unitario_kg,
    )
    assert allocation.kilos == Decimal("306.000")
    assert pallet.kilos == Decimal("306.000")
```

- [ ] **Step 2: Run model tests and verify RED**

Run:

```powershell
python -m pytest tests/test_models.py -k "weight or pallet_allocation" -v
```

Expected: collection or assertion failure because `peso_unitario_kg` and `LoadOrderPalletAllocation` do not exist.

- [ ] **Step 3: Add the fields and allocation model**

Use `DecimalField` rather than floats for quantity-derived weight:

```python
# app/models/masters.py
from peewee import DecimalField

class Product(BaseModel):
    # existing fields remain unchanged
    peso_unitario_kg = DecimalField(max_digits=12, decimal_places=3, default=Decimal("0.000"))
```

```python
# app/models/load_orders.py
from decimal import Decimal
from peewee import DecimalField

class LoadOrderPallet(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="pallets", on_delete="CASCADE")
    pallet_type = ForeignKeyField(PalletType, backref="load_order_details", null=True)
    sequence = IntegerField(default=1)
    measure = CharField(default="")
    weight = FloatField(default=0.0)  # legacy compatibility; not part of kg calculations
    quantity = IntegerField(default=1)  # legacy compatibility; normalized rows always use 1
    observations = TextField(null=True)

    @property
    def kilos(self) -> Decimal:
        return sum((row.kilos for row in self.allocations), Decimal("0.000"))


class LoadOrderPalletAllocation(BaseModel):
    pallet = ForeignKeyField(LoadOrderPallet, backref="allocations", on_delete="CASCADE")
    destination = ForeignKeyField(LoadOrderDestination, backref="pallet_allocations", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="pallet_allocations")
    quantity = DecimalField(max_digits=14, decimal_places=3)
    peso_unitario_kg = DecimalField(max_digits=12, decimal_places=3)

    @property
    def kilos(self) -> Decimal:
        return (self.quantity * self.peso_unitario_kg).quantize(Decimal("0.001"))

    class Meta:
        indexes = ((('pallet', 'destination', 'product'), True),)
```

Register `LoadOrderPalletAllocation` immediately after `LoadOrderPallet` in `ALL_MODELS`, with the import added in `app/models/__init__.py`.

- [ ] **Step 4: Add failing runtime-schema tests**

Extend `tests/test_schema.py` to verify:

```python
def test_runtime_schema_adds_weight_and_allocation_table(existing_sqlite_db):
    ensure_runtime_schema(existing_sqlite_db)
    product_columns = {column.name for column in existing_sqlite_db.get_columns("product")}
    assert "peso_unitario_kg" in product_columns
    assert existing_sqlite_db.table_exists("loadorderpalletallocation")


def test_runtime_schema_expands_legacy_aggregated_pallet_rows(existing_sqlite_db):
    legacy_id = insert_legacy_pallet(existing_sqlite_db, quantity=3)
    ensure_runtime_schema(existing_sqlite_db)
    rows = list(existing_sqlite_db.execute_sql(
        "SELECT sequence, quantity FROM loadorderpallet ORDER BY sequence"
    ))
    assert rows == [(1, 1), (2, 1), (3, 1)]
```

- [ ] **Step 5: Run schema tests and verify RED**

Run:

```powershell
python -m pytest tests/test_schema.py -k "weight or allocation or legacy_aggregated" -v
```

Expected: FAIL because decimal SQL mapping and legacy expansion are absent.

- [ ] **Step 6: Evolve the runtime schema safely**

Add `DecimalField` support in `_field_sql`:

```python
if isinstance(field, DecimalField):
    return f"DECIMAL({field.max_digits},{field.decimal_places})"
```

After `_ensure_model_columns` completes, call a focused migration helper:

```python
def _normalize_legacy_pallet_rows(database) -> None:
    rows = database.execute_sql(
        "SELECT id, order_id, pallet_type_id, measure, weight, quantity, observations "
        "FROM loadorderpallet WHERE quantity > 1 ORDER BY order_id, id"
    ).fetchall()
    for row_id, order_id, pallet_type_id, measure, weight, quantity, observations in rows:
        current_max = database.execute_sql(
            "SELECT COALESCE(MAX(sequence), 0) FROM loadorderpallet WHERE order_id = ?", (order_id,)
        ).fetchone()[0]
        database.execute_sql(
            "UPDATE loadorderpallet SET sequence = ?, quantity = 1 WHERE id = ?",
            (current_max + 1, row_id),
        )
        for offset in range(1, quantity):
            database.execute_sql(
                "INSERT INTO loadorderpallet "
                "(order_id, pallet_type_id, sequence, measure, weight, quantity, observations, created_at, updated_at) "
                "SELECT order_id, pallet_type_id, ?, measure, weight, 1, observations, created_at, updated_at "
                "FROM loadorderpallet WHERE id = ?",
                (current_max + 1 + offset, row_id),
            )
```

Run it transactionally and idempotently after the new `sequence` column exists. Add a unique `(order, sequence)` model index only after the normalization helper has assigned sequences to all existing rows.

- [ ] **Step 7: Run focused model/schema tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_models.py tests/test_schema.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit the persistence slice**

```powershell
git add app/models/masters.py app/models/load_orders.py app/models/__init__.py app/config/schema.py tests/test_models.py tests/test_schema.py
git commit -m "feat(models): persist article weight and pallet composition"
```

## Task 2: Add article-weight behavior to service and ABM

**Files:**
- Modify: `app/services/master_service.py`
- Modify: `app/ui/master_abm.py`
- Test: `tests/test_masters.py`
- Test: `tests/test_master_abm_desktop_ui.py`

- [ ] **Step 1: Write failing service tests**

```python
from decimal import Decimal
import pytest


def test_create_product_accepts_unit_weight(master_service):
    product = master_service.create_product("Cemento", "bolsa", peso_unitario_kg=Decimal("25.000"))
    assert product.peso_unitario_kg == Decimal("25.000")


def test_create_product_rejects_negative_weight(master_service):
    with pytest.raises(ValueError, match="peso.*no puede ser negativo"):
        master_service.create_product("Invalido", "unidad", peso_unitario_kg=Decimal("-0.001"))
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_masters.py -k "product and weight" -v
```

Expected: FAIL because `create_product` has no weight parameter or validation.

- [ ] **Step 3: Implement service validation**

Add `peso_unitario_kg: Decimal = Decimal("0.000")`, normalize with `Decimal(str(value))`, reject negatives, persist it, and include its string form in the audit payload.

- [ ] **Step 4: Run service tests and verify GREEN**

```powershell
python -m pytest tests/test_masters.py -k "product" -v
```

Expected: PASS.

- [ ] **Step 5: Write failing ABM tests**

```python
def test_product_dialog_creates_and_edits_unit_weight(qtbot, db):
    dialog = ProductEntryDialog(current_user="ui_weight")
    qtbot.addWidget(dialog)
    dialog.name_input.setText("Cal")
    dialog.unit_input.setText("bolsa")
    dialog.weight_input.setValue(20.500)
    dialog._save()
    product = Product.get(Product.name == "Cal")
    assert product.peso_unitario_kg == Decimal("20.500")

    edit = ProductEntryDialog(current_user="ui_weight", record_id=product.id)
    qtbot.addWidget(edit)
    assert edit.weight_input.value() == 20.500
```

Also assert `_product_rows()` includes a `"20.500 kg"` cell and displays `"Peso pendiente"` for zero.

- [ ] **Step 6: Run ABM tests and verify RED**

```powershell
python -m pytest tests/test_master_abm_desktop_ui.py -k "weight or unit_weight" -v
```

Expected: FAIL because `weight_input` and the list column do not exist.

- [ ] **Step 7: Implement ABM controls**

Use a `QDoubleSpinBox` named `productWeightKgInput`, range `0..999999999`, three decimals, suffix ` kg`. Load and save it through `MasterService`; update the article page headers and `_product_rows()` so zero is shown as `Peso pendiente`.

- [ ] **Step 8: Run ABM tests and commit**

```powershell
python -m pytest tests/test_masters.py tests/test_master_abm_desktop_ui.py -v
git add app/services/master_service.py app/ui/master_abm.py tests/test_masters.py tests/test_master_abm_desktop_ui.py
git commit -m "feat(products): manage unit weight in article ABM"
```

Expected: PASS before commit.

## Task 3: Build the pallet reconciliation domain service

**Files:**
- Create: `app/services/pallet_composition_service.py`
- Create: `tests/test_pallet_composition_service.py`

- [ ] **Step 1: Write failing reconciliation tests**

Cover one line split across pallets, mixed clients in one pallet, incomplete drafts, excess, zero weight and exact totals:

```python
def test_reconcile_mixed_pallets_and_split_lines(composition_fixture):
    result = PalletCompositionService().reconcile(
        requested=[
            RequestedLine(destination_id=1, product_id=10, quantity=Decimal("40")),
            RequestedLine(destination_id=2, product_id=20, quantity=Decimal("5")),
        ],
        pallets=[
            PalletDraft(1, [AllocationDraft(1, 10, Decimal("25"), Decimal("2.5"))]),
            PalletDraft(2, [
                AllocationDraft(1, 10, Decimal("15"), Decimal("2.5")),
                AllocationDraft(2, 20, Decimal("5"), Decimal("10")),
            ]),
        ],
    )
    assert result.total_kg == Decimal("150.000")
    assert result.pallets[0].total_kg == Decimal("62.500")
    assert result.pallets[1].total_kg == Decimal("87.500")
    assert result.is_complete is True
    assert result.issues == ()
```

```python
def test_reconcile_reports_pending_excess_and_zero_weight():
    result = PalletCompositionService().reconcile(
        requested=[
            RequestedLine(destination_id=1, product_id=10, quantity=Decimal("10")),
            RequestedLine(destination_id=2, product_id=20, quantity=Decimal("5")),
            RequestedLine(destination_id=3, product_id=30, quantity=Decimal("1")),
        ],
        pallets=[
            PalletDraft(1, [
                AllocationDraft(1, 10, Decimal("5"), Decimal("2.5")),
                AllocationDraft(2, 20, Decimal("6"), Decimal("3")),
                AllocationDraft(3, 30, Decimal("1"), Decimal("0")),
            ]),
        ],
    )
    assert [issue.code for issue in result.issues] == ["pending", "excess", "zero_weight"]
    assert result.can_issue is False
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_pallet_composition_service.py -v
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement typed immutable inputs/results**

Create frozen dataclasses `RequestedLine`, `AllocationDraft`, `PalletDraft`, `CompositionIssue`, `PalletResult`, and `CompositionResult`. Normalize every numeric input through:

```python
def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"))
```

Implement `reconcile()` by grouping requested and assigned quantities by `(destination_id, product_id)`, calculate pallet totals, and produce deterministic issues ordered by destination/product and code. `can_issue` is true only when at least one pallet exists, all requested quantities are exactly assigned, no excess exists, and every used weight is positive.

- [ ] **Step 4: Run and verify GREEN**

```powershell
python -m pytest tests/test_pallet_composition_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the domain slice**

```powershell
git add app/services/pallet_composition_service.py tests/test_pallet_composition_service.py
git commit -m "feat(load-orders): reconcile pallet composition and kilos"
```

## Task 4: Persist nested pallet assignments through LoadOrderService

**Files:**
- Modify: `app/services/load_order_service.py`
- Modify: `tests/test_load_orders.py`

- [ ] **Step 1: Write failing create/update tests**

Create an order payload where one pallet mixes two destinations and a product line is split across two pallets. Assert individual sequences, allocation rows, weight snapshots and order total. Add an update case that replaces assignments transactionally and preserves valid order products.

```python
assert [p.sequence for p in order.pallets.order_by(LoadOrderPallet.sequence)] == [1, 2]
assert order.pallets[0].allocations.count() == 2
assert order.pallets[1].allocations.get().peso_unitario_kg == Decimal("25.000")
assert service.composition(order).total_kg == Decimal("1250.000")
```

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_load_orders.py -k "pallet and (allocation or composition or kilograms)" -v
```

Expected: FAIL because nested allocations are ignored.

- [ ] **Step 3: Extend pallet validation and replacement**

Normalize payloads shaped as:

```python
{
    "sequence": 1,
    "observations": None,
    "allocations": [
        {"destination_id": 4, "product_id": 9, "quantity": Decimal("12.000")}
    ],
}
```

Resolve destination/product instances from the current order draft, snapshot `product.peso_unitario_kg`, reject nonpositive quantities and duplicate destination/product rows within the same pallet, and call the reconciliation service before persistence. Drafts may contain pending quantities but may not contain excess quantities or references outside the order.

In `_replace_pallets`, delete allocations before pallets and recreate pallets with `quantity=1`, followed by allocation rows. Keep the entire order/destination/product/pallet replacement inside the existing database transaction.

Add `composition(order)` to translate persisted rows into domain inputs and return `CompositionResult`.

- [ ] **Step 4: Run focused tests and verify GREEN**

```powershell
python -m pytest tests/test_load_orders.py -k "pallet or destination" -v
```

Expected: PASS.

- [ ] **Step 5: Commit service persistence**

```powershell
git add app/services/load_order_service.py tests/test_load_orders.py
git commit -m "feat(load-orders): persist pallet merchandise assignments"
```

## Task 5: Block issue until composition is complete

**Files:**
- Modify: `app/services/load_order_operation_service.py`
- Modify: `tests/test_load_order_operations.py`
- Modify: `tests/test_load_order_account_ledger.py`

- [ ] **Step 1: Write failing issue-gate tests**

Add cases for no pallets, pending quantities, excess protection and weight zero. Assert the order remains pending and no account movement is created.

```python
with pytest.raises(ValueError, match="No se puede emitir.*faltan asignar"):
    operations.issue(order)
assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_PENDING
assert ClientAccountMovement.select().where(ClientAccountMovement.load_order == order).count() == 0
```

Add a complete mixed-client order case that issues successfully.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_load_order_operations.py tests/test_load_order_account_ledger.py -k "composition or pallet or issue" -v
```

Expected: FAIL because `issue()` changes status without checking composition.

- [ ] **Step 3: Add the gate before any side effect**

In `LoadOrderOperationService.issue`, call `self.load_orders.composition(order)` before `change_status`. If `can_issue` is false, raise one message headed `No se puede emitir la orden:` followed by each concrete issue. Only then change status and generate account movements.

- [ ] **Step 4: Run and verify GREEN**

```powershell
python -m pytest tests/test_load_order_operations.py tests/test_load_order_account_ledger.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit the issue gate**

```powershell
git add app/services/load_order_operation_service.py tests/test_load_order_operations.py tests/test_load_order_account_ledger.py
git commit -m "feat(load-orders): require complete pallets before issue"
```

## Task 6: Build the approved pallet-card and side-panel UI

**Files:**
- Create: `app/ui/pallet_composition.py`
- Modify: `app/ui/desktop_app.py`
- Create: `tests/test_pallet_composition_ui.py`
- Modify: `tests/test_load_order_desktop_ui.py`

- [ ] **Step 1: Write failing focused widget tests**

Instantiate `PalletCompositionWidget` with destination/product drafts and assert:

```python
assert widget.objectName() == "palletCompositionWidget"
assert widget.total_kg_label.objectName() == "loadOrderTotalKg"
assert widget.total_kg_label.text() == "2.100,000 kg"
assert widget.card_for_sequence(1).property("compositionState") == "complete"
assert widget.card_for_sequence(2).property("compositionState") == "incomplete"
```

Simulate clicking Pallet 2, adding a mixed-client allocation, deleting it, and reading `widget.pallet_drafts()`.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_pallet_composition_ui.py -v
```

Expected: collection failure because the widget module does not exist.

- [ ] **Step 3: Implement the focused widget**

Create:

- `PalletCard(QFrame)`: sequence, kg, article/client counts and `compositionState` property.
- `PalletEditorPanel(QFrame)`: destination combo, article combo, quantity spin box, allocation table and add/remove actions.
- `PalletCompositionWidget(QWidget)`: scrollable card grid, add-card button, editor panel, large persistent total, summary label, issues list and `pallet_drafts()` serialization.

Keep all calculations delegated to `PalletCompositionService`; UI code converts drafts to typed inputs and renders results. Use object names from the assertions so screenshots and tests have stable anchors. Apply green/yellow/red through dynamic Qt properties and repolish changed cards.

- [ ] **Step 4: Run widget tests and verify GREEN**

```powershell
python -m pytest tests/test_pallet_composition_ui.py -v
```

Expected: PASS.

- [ ] **Step 5: Write failing dialog integration tests**

Assert `LoadOrderEntryDialog` has five steps `Transporte`, `Destinos`, `Productos`, `Pallets`, `Revisar`; that changing destinations/products refreshes available allocation options; that `_save()` includes `pallets=widget.pallet_drafts()`; and that reopening an order reconstructs the cards and large total.

- [ ] **Step 6: Run integration tests and verify RED**

```powershell
python -m pytest tests/test_load_order_desktop_ui.py -k "pallet or total_kg" -v
```

Expected: FAIL because the dialog has no Pallets step.

- [ ] **Step 7: Integrate the widget into the dialog**

Add the Pallets step between Productos and Revisar. Pass a normalized view of `self.destinations` into the widget whenever a destination or product changes. On load, serialize persisted pallets/allocations into widget drafts. On save, pass the widget payload to `create_order` or `update_order`. Keep the large total within the pallet widget visible for the entire Pallets step and repeat the kg total in Revisar.

- [ ] **Step 8: Run UI tests and commit**

```powershell
python -m pytest tests/test_pallet_composition_ui.py tests/test_load_order_desktop_ui.py tests/test_load_order_multi_client_ui.py -v
git add app/ui/pallet_composition.py app/ui/desktop_app.py tests/test_pallet_composition_ui.py tests/test_load_order_desktop_ui.py
git commit -m "feat(ui): compose pallets with live order kilograms"
```

Expected: PASS before commit.

## Task 7: Preserve importer compatibility and operational summaries

**Files:**
- Modify: `app/importers/legacy_dbf.py`
- Modify: `tests/test_legacy_dbf_importer.py`
- Modify: `app/services/load_order_print_service.py`
- Modify: `tests/test_load_order_printing.py`

- [ ] **Step 1: Write failing compatibility tests**

Assert imported products without a source weight receive `Decimal("0.000")` and existing update paths do not overwrite a manually entered positive weight. Add print-context assertions for pallet sequence, pallet kg and total order kg.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest tests/test_legacy_dbf_importer.py tests/test_load_order_printing.py -k "weight or kilogram or pallet" -v
```

Expected: at least the print-context assertions fail because weight totals are absent.

- [ ] **Step 3: Implement compatibility and summaries**

Leave `peso_unitario_kg` out of legacy update payloads unless the source explicitly contains a valid nonnegative weight column. Extend print context with `pallets`, each containing sequence/composition/total kg, and `total_kg`; do not change fiscal or price calculations.

- [ ] **Step 4: Run and verify GREEN**

```powershell
python -m pytest tests/test_legacy_dbf_importer.py tests/test_load_order_printing.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit compatibility and output context**

```powershell
git add app/importers/legacy_dbf.py app/services/load_order_print_service.py tests/test_legacy_dbf_importer.py tests/test_load_order_printing.py
git commit -m "feat(load-orders): expose pallet kilograms in operational output"
```

## Task 8: Visual smoke, full regression and operational closeout

**Files:**
- Modify: `scripts/generate_ux_screenshots.py`
- Create: `docs/screenshots/issue_178_pallet_composition/README.md`
- Create: generated PNG files under `docs/screenshots/issue_178_pallet_composition/`

- [ ] **Step 1: Extend the screenshot script**

Create a deterministic demo order with two clients, three articles, two pallets, one incomplete pallet and known total kg. Capture:

- new order Pallets step with card grid and large total;
- selected pallet with open side panel;
- edit-order reconstruction;
- red excess/invalid state.

- [ ] **Step 2: Run screenshot generation**

```powershell
python scripts/generate_ux_screenshots.py
```

Expected: exit 0 and four fresh PNG files under `docs/screenshots/issue_178_pallet_composition/`.

- [ ] **Step 3: Inspect each screenshot visually**

Verify the cards are square and readable, side panel does not hide the grid, total kg is the dominant metric, footer remains visible at 1100×660, and green/yellow/red states are distinguishable. Record filenames, resolution and observations in the README.

- [ ] **Step 4: Run the complete validation matrix**

```powershell
git diff --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Expected: every command exits 0; pytest reports zero failures.

- [ ] **Step 5: Review scope and working tree**

```powershell
git status -sb
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

Expected: only issue #178 files are present; `.superpowers/` visual-companion artifacts remain untracked and excluded from commits.

- [ ] **Step 6: Commit visual evidence**

```powershell
git add scripts/generate_ux_screenshots.py docs/screenshots/issue_178_pallet_composition
git commit -m "test(ui): capture pallet composition workflow"
```

- [ ] **Step 7: Push and open a draft PR**

Push `codex/issue-178-pallet-composition-weight` and open a draft PR against `main` referencing `#178`. Include included/out-of-scope sections, exact validation results, screenshot links, migration risk and the explicit statement that pallet tare is not included.

- [ ] **Step 8: Comment operational state on issue #178**

Post what changed, exact commands/results, screenshot evidence, known risks, and the next recommended manual verification. Do not close the issue or mark the PR ready until the visible smoke has been reviewed.
