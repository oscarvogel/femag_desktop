# Print Pallet Assignments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Print compact kilogram values and the real pallet sequence numbers assigned to every PDF detail row.

**Architecture:** Keep PDF rendering in `LoadOrderPrintService`, but derive pallet labels from persisted allocations instead of proportional pallet counts. Use focused helpers for kilogram formatting, row pallet sequences, and used-pallet totals.

**Tech Stack:** Python 3.12, Peewee, ReportLab, pypdf, pytest.

---

### Task 1: Reproduce both PDF defects

**Files:**
- Modify: `tests/test_load_order_printing.py`

- [ ] Add a kilogram-format test for `300.000`, `300.500`, and `1250.750`.
- [ ] Add a PDF test with one destination whose products occupy pallets 1 and 3, including repeated allocations on pallet 3.
- [ ] Assert extracted text contains `300 kg`, `1, 3`, and `2 pallets`.
- [ ] Run both tests and verify they fail for the current fixed-three-decimal and proportional-count behavior.

### Task 2: Implement minimal formatting and assignment lookup

**Files:**
- Modify: `app/services/load_order_print_service.py`

- [ ] Trim insignificant decimal zeros in `_kg_text` while preserving Argentine separators.
- [ ] Replace `_pallet_share_for_products` with a helper that filters persisted allocations by the destination/product identities represented by the row.
- [ ] Return ordered, unique sequence labels.
- [ ] Change the totals cell to the count of distinct pallets with allocations.
- [ ] Run the new tests and the complete `tests/test_load_order_printing.py` file.
- [ ] Commit the implementation and tests.

### Task 3: Validate and publish

**Files:**
- Create: `docs/prints/issue_181_print_pallet_assignments/README.md`
- Create: `docs/prints/issue_181_print_pallet_assignments/orden_carga_*.pdf`

- [ ] Generate a real PDF from the regression fixture and inspect extracted text.
- [ ] Run `git diff --check`, full pytest, compileall and smoke.
- [ ] Document exact results and any pre-existing validation failure.
- [ ] Review the diff, push the branch, open a draft PR linked to #181 and comment operational status on the issue.
