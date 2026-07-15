# Load Order Pallet Action Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep every pallet action compact inside its order row and allow completed pallet compositions to be opened safely in read-only mode.

**Architecture:** Rebuild the `QTableWidget` from a clean structural state on every refresh so old spans and cell widgets cannot leak into new rows. Extend `LoadOrderPalletDialog` with an explicit `read_only` mode and route final orders with persisted pallets to that mode, while pending orders retain the existing editable flow.

**Tech Stack:** Python 3.12, PyQt5, Peewee, pytest, SQLite test fixtures.

---

### Task 1: Prevent stale table spans

**Files:**
- Modify: `tests/test_load_order_desktop_ui.py`
- Modify: `app/ui/desktop_app.py:634-680`

- [ ] **Step 1: Write the failing regression test**

Add a test that creates two orders, opens `FemagDesktopWindow`, changes selection from the first order to the second, processes Qt events, and asserts:

```python
assert table.columnSpan(first_order_row, 0) == 1
assert table.columnSpan(second_order_row, 0) == 1
assert table.columnSpan(detail_row, 0) == table.columnCount()
assert table.cellWidget(first_order_row, action_column).width() < table.viewport().width()
assert table.cellWidget(second_order_row, action_column).width() < table.viewport().width()
```

The helper that finds an order row must identify rows whose column-zero item contains `Qt.UserRole` and whose column-zero cell has no detail widget.

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_load_order_desktop_ui.py::test_load_order_refresh_clears_stale_detail_spans -q
```

Expected: FAIL because the former detail row keeps a full-width column span after selection changes.

- [ ] **Step 3: Implement the minimal structural reset**

At the start of `refresh()` table reconstruction, before adding rows:

```python
table.clearSpans()
table.setRowCount(0)
table.setRowCount(len(rows) + len(selected_ids))
```

This removes prior spans and cell widgets before constructing the new order/detail row arrangement.

- [ ] **Step 4: Verify GREEN**

Run the focused regression test again and expect PASS.

- [ ] **Step 5: Commit the regression fix**

```powershell
git add app/ui/desktop_app.py tests/test_load_order_desktop_ui.py
git commit -m "fix(ui): keep pallet actions inside order rows"
```

### Task 2: Add read-only pallet consultation

**Files:**
- Modify: `tests/test_load_order_desktop_ui.py`
- Modify: `app/ui/desktop_app.py:666-785`
- Modify: `app/ui/desktop_app.py:1322-1367`

- [ ] **Step 1: Write failing dialog tests**

Add tests that create an order with persisted pallet allocations and verify the desired API:

```python
dialog = LoadOrderPalletDialog(service, order, read_only=True)
assert dialog.windowTitle() == "Detalle de pallets"
assert dialog.findChild(QPushButton, "saveLoadOrderPalletsButton") is None
assert dialog.findChild(QPushButton, "closeLoadOrderPalletsButton").text() == "Cerrar"
assert dialog.pallet_widget.isEnabled() is False
```

Also retain a focused assertion that the default editable dialog still contains `Guardar pallets` and has its composition widget enabled.

- [ ] **Step 2: Run the dialog tests and verify RED**

Run the new test and expect a `TypeError` because `read_only` does not exist yet.

- [ ] **Step 3: Implement the minimal read-only dialog mode**

Change the constructor to:

```python
def __init__(self, service: LoadOrderService, order: LoadOrder, parent=None, *, read_only: bool = False):
```

Store `self.read_only`, use `Detalle de pallets` and consultation copy when true, disable `self.pallet_widget`, create only `closeLoadOrderPalletsButton`, and do not create or connect `self.save_button`. Preserve the current editable footer unchanged when false.

- [ ] **Step 4: Verify dialog GREEN**

Run the new dialog tests and expect PASS.

- [ ] **Step 5: Write failing routing test**

Create a final-status order with pallets, build the load-order page, and assert its row action says `Ver pallets`, remains enabled, and opens `LoadOrderPalletDialog(..., read_only=True)`. Also assert a final order without pallets has no enabled pallet action.

- [ ] **Step 6: Run routing test and verify RED**

Expected: FAIL because current code enables pallet actions only when `order.is_unissued` and rejects every final order in `open_pallets_dialog()`.

- [ ] **Step 7: Implement routing semantics**

Enable the row action when the order is pending or has persisted pallets. In `open_pallets_dialog()`, reject only non-pending orders without pallets; otherwise call:

```python
read_only = not order.is_unissued
dialog = LoadOrderPalletDialog(service, order, self, read_only=read_only)
```

Only refresh and show a saved message after `Accepted` editable dialogs; read-only dialogs simply close.

- [ ] **Step 8: Verify routing GREEN and focused UI suite**

Run the new routing test, then:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_load_order_desktop_ui.py tests/test_pallet_composition_ui.py -q
```

- [ ] **Step 9: Commit read-only consultation**

```powershell
git add app/ui/desktop_app.py tests/test_load_order_desktop_ui.py
git commit -m "feat(ui): view final pallet compositions read-only"
```

### Task 3: Full validation and evidence

**Files:**
- Modify: `docs/screenshots/issue_180_pallet_action_layout/README.md`
- Create: `docs/screenshots/issue_180_pallet_action_layout/01_accion_compacta.png`

- [ ] **Step 1: Run automated validation**

```powershell
git diff --check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -m app.main --smoke
```

Expected: zero exit status, all tests pass, compileall reports no syntax errors, smoke prints `FEMAG smoke OK`.

- [ ] **Step 2: Run the demo UI and capture the repaired state**

Open the demo, select both orders in sequence, and capture the table showing that each pallet action stays within the `Acción` column. Open a final order's `Ver pallets` dialog and verify visually that it is read-only.

- [ ] **Step 3: Document evidence**

Write the screenshot README with the tested selection sequence, the final order state, and the read-only result. State any visual or accessibility limitation explicitly.

- [ ] **Step 4: Commit evidence**

```powershell
git add docs/screenshots/issue_180_pallet_action_layout
git commit -m "docs: add pallet action regression evidence"
```

### Task 4: Review and publish

**Files:**
- Review all branch changes against issue #180 and the approved design.

- [ ] **Step 1: Review diff and repository state**

```powershell
git status -sb
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
```

- [ ] **Step 2: Request code review and address all critical or important findings**

Use `origin/main` as the base SHA and the branch HEAD as the review target.

- [ ] **Step 3: Push and open a draft PR**

Push `codex/issue-180-pallet-action-layout` and create a draft PR linked to issue #180 with summary, included/out-of-scope sections, validation commands, evidence, and risks.

- [ ] **Step 4: Comment operational closure on issue #180**

Post what changed, commands executed, results, screenshot evidence, real pending work, and the recommended next step.
