# Issue 65 Load Order Multi Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reformular Ordenes de carga para representar una carga logistica de camion/viaje con varios clientes, destinos y productos.

**Architecture:** La cabecera `LoadOrder` conserva fecha, transporte, chofer, camion, estado y observaciones. Los clientes y lugares de entrega se modelan en `LoadOrderDestination`, y cada producto se asocia al destino correspondiente mediante `LoadOrderProduct.destination`.

**Tech Stack:** Python, Peewee, PyQt5, pytest, HTML imprimible A4.

---

### Task 1: Modelo y Servicio Multi Cliente

**Files:**
- Modify: `app/models/load_orders.py`
- Modify: `app/models/__init__.py`
- Modify: `app/services/load_order_service.py`
- Test: `tests/test_load_orders.py`

- [x] **Step 1: Write failing tests**

Add tests that call `LoadOrderService.create_order(destinations=[...])` with one client and multiple products, several clients, several delivery places, invalid quantity, a destination without products, an invalid driver/carrier relation, and blocked driver reuse.

- [x] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_load_orders.py -q`
Expected: FAIL because `LoadOrderDestination` and `destinations` do not exist yet.

- [x] **Step 3: Implement minimal model/service**

Add `LoadOrderDestination`, allow nullable cabecera client/address, validate the logistic header separately, normalize destinations and their products, and preserve legacy calls by converting old `client + delivery_address + products` into one destination.

- [x] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_load_orders.py -q`
Expected: PASS for load-order service behaviors.

### Task 2: UI Contract and Screen Adapter

**Files:**
- Modify: `app/ui/load_orders.py`
- Modify: `app/ui/desktop_app.py`
- Test: `tests/test_load_order_multi_client_ui.py`

- [x] **Step 1: Write failing tests**

Add tests for a logistic header without required cliente/domicilio/producto fields, client/product action buttons, multi-client screen creation, table summaries, and validation message surfacing.

- [x] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_load_order_multi_client_ui.py -q`
Expected: FAIL because the UI spec still exposes monoclient detail actions or missing screen helpers.

- [x] **Step 3: Implement minimal UI contract**

Expose `build_load_order_screen_state()` and `create_load_order_from_screen()` for destination blocks, update workspace/form labels, and make the desktop list/detail read client/destination/product summaries from the new detail structure.

- [x] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_load_order_multi_client_ui.py -q`
Expected: PASS for UI contract and screen adapter behaviors.

### Task 3: Printing and Documentation

**Files:**
- Modify: `app/services/load_order_print_service.py`
- Modify: `docs/guia_usuario_entrega_2.md`
- Test: `tests/test_load_order_printing.py`

- [x] **Step 1: Write failing tests**

Add a print test that creates a multi-client order and asserts that the generated HTML includes cabecera logistica and grouped client/destination product detail.

- [x] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_load_order_printing.py -q`
Expected: FAIL because the previous HTML prints a single client/domicilio from the header.

- [x] **Step 3: Implement grouped HTML**

Render cabecera logistica separately from `Detalle por cliente / destino`, and keep A4 HTML generation plus audit logging.

- [x] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_load_order_printing.py -q`
Expected: PASS for print exports.

### Task 4: Final Validation and PR

**Files:**
- Modify: PR description only after code validation.

- [ ] **Step 1: Run required validation**

Run:
`git diff --check`
`git diff --cached --check`
`py -3 -m pytest`
`py -3 -m compileall app`
`py -3 -m app.main --smoke`
`py -3 -m app.main --demo-ui`

- [ ] **Step 2: Document unsupported commands**

If `python ...` fails because the Windows Store alias shadows Python, record that and use `py -3 ...` as the actual interpreter. If `--demo-ui` opens an interactive window or cannot be captured non-interactively, record the exact result.

- [ ] **Step 3: Commit and open draft PR**

Commit only issue #65 files, push `codex/issue-65-load-order-multi-client`, and open a draft PR against `main` with `Closes #65` and no reference closing `#56`.
