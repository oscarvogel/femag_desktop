# Driver, Truck and Trailer Legacy Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import legacy drivers with a safely inferred carrier, create or reuse their habitual tractor and trailer, and expose those relationships in FEMAG masters without inventing missing carriers.

**Architecture:** Extend the existing Peewee master models and runtime schema migration, then keep legacy inference inside `LegacyDbfMasterImporter` behind small resolution/upsert helpers. Reuse the existing ABM dialogs and tables for manual correction, adding only the habitual-truck and trailer fields required by issue #188.

**Tech Stack:** Python 3.12, Peewee, dbfread, PyQt5, pytest, SQLite test/runtime schema and MySQL-compatible runtime migration.

---

## File map

- `app/models/masters.py`: nullable carrier on trucks, trailer plate, habitual truck on drivers.
- `app/models/__init__.py`: dependency-safe model order for table creation.
- `app/config/schema.py`: existing generic runtime migration; no new migration framework.
- `app/importers/legacy_dbf.py`: carrier inference, truck creation/reuse, warnings and conflict policy.
- `app/services/master_service.py`: manual master creation with trailer/habitual-truck values.
- `app/ui/master_abm.py`: driver/truck dialogs, options, rows and relationship status.
- `app/ui/desktop_app.py`: import-summary warning count in the existing DBF screen.
- `tests/test_schema.py`: compatibility of existing databases with the new nullable columns.
- `tests/test_legacy_dbf_importer.py`: inference, idempotence, duplicate and conflict behavior.
- `tests/test_masters.py`: service contracts for new fields.
- `tests/test_master_abm_desktop_ui.py`: edit and grid behavior.
- `tests/test_legacy_dbf_import_ui.py`: warnings visible after an import.

### Task 1: Add the schema relationships safely

**Files:**
- Modify: `app/models/masters.py:62-100`
- Modify: `app/models/__init__.py:8-35`
- Test: `tests/test_schema.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing model and runtime-schema tests**

Add tests proving a new database and an existing legacy database both support the fields:

```python
def test_driver_can_reference_habitual_truck_and_trailer(db):
    from app.models.masters import Carrier, Driver, Truck

    carrier = Carrier.create(name="Transporte habitual")
    truck = Truck.create(domain="ABC123", trailer_domain="DEF456", carrier=carrier)
    driver = Driver.create(name="Chofer habitual", carrier=carrier, usual_truck=truck)

    stored = Driver.get_by_id(driver.id)
    assert stored.usual_truck == truck
    assert stored.usual_truck.trailer_domain == "DEF456"


def test_runtime_schema_adds_driver_truck_relationship_columns():
    from app.config.database import bind_database
    from app.config.schema import ensure_runtime_schema
    from peewee import SqliteDatabase

    database = SqliteDatabase(":memory:", pragmas={"foreign_keys": 1})
    bind_database(database)
    database.connect()
    database.execute_sql("CREATE TABLE carrier (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)")
    database.execute_sql("CREATE TABLE truck (id INTEGER PRIMARY KEY, domain TEXT NOT NULL UNIQUE, carrier_id INTEGER NOT NULL)")
    database.execute_sql("CREATE TABLE driver (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, carrier_id INTEGER)")
    ensure_runtime_schema(database)

    driver_columns = {column.name: column for column in database.get_columns("driver")}
    truck_columns = {column.name: column for column in database.get_columns("truck")}
    assert driver_columns["usual_truck_id"].null is True
    assert truck_columns["trailer_domain"].null is True
    assert truck_columns["carrier_id"].null is True
```

- [ ] **Step 2: Run the tests and verify the expected red state**

Run:

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_models.py tests/test_schema.py -q
```

Expected: failures because `trailer_domain` and `usual_truck` do not exist and `Truck.carrier` is not nullable.

- [ ] **Step 3: Implement the minimal model changes**

Declare `Truck` before `Driver`, then use a normal foreign key:

```python
class Truck(BaseModel):
    domain = CharField(unique=True)
    trailer_domain = CharField(null=True)
    carrier = ForeignKeyField(Carrier, backref="trucks", null=True)
    # keep the existing active/import trace fields unchanged


class Driver(BaseModel):
    name = CharField(unique=True)
    carrier = ForeignKeyField(Carrier, backref="drivers", null=True)
    usual_truck = ForeignKeyField(Truck, backref="usual_drivers", null=True)
    # keep the existing cuit/document/phone/status/import fields unchanged
```

Move `Truck` before `Driver` in `ALL_MODELS`. Do not write a one-off SQL migration: `ensure_runtime_schema()` already adds missing columns and relaxes nullable columns for SQLite/MySQL.

- [ ] **Step 4: Run focused tests and verify green**

Run the Task 1 command again.

Expected: all tests pass and `PRAGMA foreign_key_check` remains empty.

- [ ] **Step 5: Commit the schema slice**

```powershell
git add app/models/masters.py app/models/__init__.py tests/test_models.py tests/test_schema.py
git commit -m "feat(models): add habitual truck and trailer fields"
```

### Task 2: Add structured import outcomes and safe carrier inference

**Files:**
- Modify: `app/importers/legacy_dbf.py:1-180`
- Test: `tests/test_legacy_dbf_importer.py`

- [ ] **Step 1: Write failing tests for inference and warnings**

Cover these three distinct cases with explicit rows:

```python
def test_driver_carrier_code_requires_compatible_identity(db):
    importer = LegacyDbfMasterImporter()
    result = importer.import_rows({
        "carriers": [{"CODIGO": "0004", "NOMBRE": "Vogel", "CUIT": "20-23737702-9"}],
        "drivers": [{"CODIGO": "0004", "NOMBRE": "Bosing", "CUIT": "20-30717891-6"}],
    })
    assert Driver.get().carrier is None
    assert result["drivers"]["warnings"][0]["code"] == "carrier_code_collision"


def test_driver_uses_unique_cuit_when_code_is_not_valid(db):
    result = LegacyDbfMasterImporter().import_rows({
        "carriers": [{"CODIGO": "0009", "NOMBRE": "Mendieta", "CUIT": "20-24834384-3"}],
        "drivers": [{"CODIGO": "0012", "NOMBRE": "Mendieta Gabriel", "CUIT": "20-24834384-3"}],
    })
    assert Driver.get().carrier.source_id == "0009"
    assert result["drivers"]["warnings"] == []


def test_driver_without_carrier_is_imported_with_warning(db):
    result = LegacyDbfMasterImporter().import_rows({
        "drivers": [{"CODIGO": "0015", "NOMBRE": "Sin relacion", "CUIT": "20-11111111-1"}],
    })
    assert Driver.get().carrier is None
    assert result["drivers"]["created"] == 1
    assert result["drivers"]["warnings"][0]["code"] == "carrier_not_found"
```

Also test that duplicate carrier CUITs produce `carrier_cuit_ambiguous` and no relationship.

- [ ] **Step 2: Run the new tests and verify red**

Run:

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_legacy_dbf_importer.py -q
```

Expected: failures because summaries have no `warnings` and drivers do not infer carriers.

- [ ] **Step 3: Add an explicit outcome type and summary support**

Use one result contract for all entity handlers:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ImportOutcome:
    action: str
    warnings: tuple[dict[str, str], ...] = ()
    related_actions: tuple[tuple[str, str], ...] = ()
```

Make `_empty_summary()` include `"warnings": []`. In `import_rows()`, accept an `ImportOutcome`, increment `outcome.action`, extend the entity warning list, and increment every `(entity, action)` pair in `related_actions`. Return `ImportOutcome(action)` from handlers without warnings.

- [ ] **Step 4: Implement safe carrier resolution**

Add focused helpers:

```python
def _resolve_driver_carrier(self, row, source_system):
    source_id = self._value(row, "TRANSP", "TRANSPORTISTA", "CARRIER") or self._value(row, "CODIGO")
    driver_cuit = self._clean_cuit(self._value(row, "CUIT", "CUITCHOFER"))
    driver_name = self._clean_identity_name(self._value(row, "NOMBRE", "CHOFER"))
    by_code = self._find_carrier_by_source_id(source_system, source_id)
    if by_code is not None and self._carrier_identity_matches(by_code, driver_cuit, driver_name):
        return by_code, ()
    by_cuit = self._find_unique_carrier_by_cuit(driver_cuit)
    if by_cuit is not None:
        return by_cuit, ()
    warning_code = "carrier_code_collision" if by_code is not None else "carrier_not_found"
    return None, ({"code": warning_code, "source_id": self._value(row, "CODIGO")},)
```

Identity compatibility means equal normalized CUIT when both sides have CUIT; only when CUIT is missing on one side may equal normalized names validate the code. A non-unique CUIT returns `carrier_cuit_ambiguous`.

- [ ] **Step 5: Run importer tests and commit**

Run the focused command; expect all importer tests green.

```powershell
git add app/importers/legacy_dbf.py tests/test_legacy_dbf_importer.py
git commit -m "feat(import): infer driver carriers safely"
```

### Task 3: Create/reuse habitual trucks and preserve conflicts

**Files:**
- Modify: `app/importers/legacy_dbf.py`
- Test: `tests/test_legacy_dbf_importer.py`

- [ ] **Step 1: Write failing truck-import tests**

Add independent tests for:

```python
def test_driver_row_creates_habitual_truck_and_trailer(db):
    importer = LegacyDbfMasterImporter()
    result = importer.import_rows({
        "carriers": [{"CODIGO": "0001", "NOMBRE": "Aguirre", "CUIT": "20-26565521-2"}],
        "drivers": [{
            "CODIGO": "0001", "NOMBRE": "Aguirre", "CUIT": "20-26565521-2",
            "CHASIS": " ab 123 cd ", "ACOPLADO": " de 456 fg ",
        }],
    })
    driver = Driver.get()
    assert driver.usual_truck.domain == "AB123CD"
    assert driver.usual_truck.trailer_domain == "DE456FG"
    assert driver.usual_truck.carrier == driver.carrier
    assert result["trucks"]["created"] == 1


def test_two_drivers_reuse_same_normalized_truck(db):
    importer = LegacyDbfMasterImporter()
    importer.import_rows({"drivers": [
        {"CODIGO": "0011", "NOMBRE": "Chofer Uno", "CHASIS": "LAB956"},
        {"CODIGO": "0014", "NOMBRE": "Chofer Dos", "CHASIS": " lab-956 "},
    ]})
    assert Truck.select().count() == 1
    assert Driver.select().where(Driver.usual_truck == Truck.get()).count() == 2


def test_unmatched_driver_still_creates_unassigned_truck(db):
    importer.import_rows({"drivers": [{"CODIGO": "15", "NOMBRE": "Sin transporte", "CHASIS": "GWA390", "ACOPLADO": "GWA396"}]})
    assert Driver.get().carrier is None
    assert Truck.get().carrier is None
    assert Driver.get().usual_truck == Truck.get()
```

Also add conflict tests proving that an existing non-null carrier or trailer is preserved and a `truck_carrier_conflict` or `truck_trailer_conflict` warning is emitted.

- [ ] **Step 2: Run the importer tests and verify red**

Run the Task 2 focused command.

Expected: failures because driver rows do not create trucks or link `usual_truck`.

- [ ] **Step 3: Implement a driver-owned truck upsert helper**

Keep conflict logic outside generic `_upsert()`:

```python
def _upsert_habitual_truck(self, row, carrier, source_system, batch):
    domain = self._clean_domain(self._value(row, "CHASIS"))
    trailer = self._clean_domain(self._value(row, "ACOPLADO")) or None
    warnings = []
    if not domain:
        return None, None, ({"code": "habitual_truck_missing", "source_id": self._value(row, "CODIGO")},)
    truck = Truck.select().where(Truck.domain == domain).first()
    created = truck is None
    if created:
        truck = Truck.create(domain=domain, trailer_domain=trailer, carrier=carrier)
    # For an existing row, fill only null carrier/trailer values. Preserve an
    # incompatible non-null value and append the corresponding warning.
    return truck, "created" if created else "updated", tuple(warnings)
```

Update `_import_drivers()` to resolve carrier, upsert the habitual truck, save `usual_truck`, and return one outcome containing all warnings. Increment the `trucks` created/updated counters from the driver handler through an explicit `related_actions` field on `ImportOutcome`; do not count a reused unchanged truck as newly created.

- [ ] **Step 4: Prove idempotence**

Add and pass a test that imports the same carrier/driver row twice and asserts one carrier, one driver, one truck, two batches, and second-run `updated` counts without conflict warnings.

- [ ] **Step 5: Run tests and commit**

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_legacy_dbf_importer.py -q
git add app/importers/legacy_dbf.py tests/test_legacy_dbf_importer.py
git commit -m "feat(import): create habitual trucks from driver DBF"
```

### Task 4: Extend master services and ABM correction flows

**Files:**
- Modify: `app/services/master_service.py:52-78`
- Modify: `app/ui/master_abm.py:133-880`
- Test: `tests/test_masters.py`
- Test: `tests/test_master_abm_desktop_ui.py`

- [ ] **Step 1: Write failing service and UI tests**

Test these stable object names and visible columns:

```python
assert dialog.findChild(QComboBox, "driverUsualTruckInput") is not None
assert dialog.findChild(QLineEdit, "truckTrailerDomainInput") is not None
assert headers == ["Chofer", "Transportista", "Tractor", "Acoplado", "Estado de relación"]
```

Create a driver with no carrier/truck and assert its row ends with `Sin transportista`; create a driver with carrier but no truck and assert `Sin tractor`; create a complete relationship and assert `Completa`.

- [ ] **Step 2: Run focused UI/service tests and verify red**

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_masters.py tests/test_master_abm_desktop_ui.py -q
```

- [ ] **Step 3: Extend service signatures without weakening manual creation rules**

```python
def create_driver(self, name, *, carrier, usual_truck=None, document=None, phone=None):
    if carrier is None:
        raise ValueError("El chofer debe estar asociado a un transportista.")
    row = Driver.create(name=name, carrier=carrier, usual_truck=usual_truck, document=document, phone=phone)
    self._record("Driver", row, {"name": name, "carrier_id": carrier.id, "usual_truck_id": usual_truck.id if usual_truck else None})
    return row

def create_truck(self, domain, carrier, *, trailer_domain=None):
    if carrier is None:
        raise ValueError("El camion debe estar asociado a un transportista.")
    row = Truck.create(domain=domain, trailer_domain=trailer_domain, carrier=carrier)
    self._record("Truck", row, {"domain": domain, "trailer_domain": trailer_domain, "carrier_id": carrier.id})
    return row
```

The importer continues to use model upserts directly so legacy unassigned records remain allowed; manual `Nuevo` keeps requiring a carrier.

- [ ] **Step 4: Add truck options and update dialogs**

Add `_truck_master_options(carrier_id)` returning active trucks, filtered by carrier when selected and including the current imported unassigned truck when editing. In `DriverEntryDialog`, add `driverUsualTruckInput`, load `usual_truck_id`, and save it only when compatible with the selected carrier or unassigned.

In `TruckEntryDialog`, add `truckTrailerDomainInput`, safely load a nullable carrier, normalize both plates, and save `trailer_domain`. Opening an imported truck with no carrier must not raise; saving still asks the operator to choose a carrier.

- [ ] **Step 5: Update rows and table configurations**

Use left joins for both nullable relationships. `_driver_rows()` returns name, carrier label, tractor, trailer and relationship state. `_truck_rows()` returns tractor, trailer, carrier and active state. Update `master_abm_configs()` column labels to match returned cells.

- [ ] **Step 6: Run focused tests and commit**

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_masters.py tests/test_master_abm_desktop_ui.py -q
git add app/services/master_service.py app/ui/master_abm.py tests/test_masters.py tests/test_master_abm_desktop_ui.py
git commit -m "feat(ui): manage habitual truck and trailer relationships"
```

### Task 5: Surface import warnings in CLI and desktop import UI

**Files:**
- Modify: `app/ui/desktop_app.py:895-975,1130-1165`
- Test: `tests/test_legacy_dbf_import_ui.py`
- Test: `tests/test_legacy_dbf_importer.py`

- [ ] **Step 1: Write a failing UI warning test**

Return a fake summary containing:

```python
"drivers": {
    "created": 1,
    "updated": 0,
    "skipped": 0,
    "errors": [],
    "warnings": [{"code": "carrier_not_found", "source_id": "0015"}],
}
```

Assert `legacyDbfImportFeedback` says `1 advertencia` and the summary table has an `Advertencias` column with value `1` for Choferes.

- [ ] **Step 2: Run and verify red**

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_legacy_dbf_import_ui.py -q
```

- [ ] **Step 3: Extend the existing summary table**

Add the warning column in `_fill_legacy_import_summary()` and calculate a total warning count for the feedback label. Keep CLI behavior unchanged because `scripts/import_legacy_dbf_masters.py` already prints the complete JSON summary.

- [ ] **Step 4: Run tests and commit**

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_legacy_dbf_import_ui.py tests/test_legacy_dbf_importer.py -q
git add app/ui/desktop_app.py tests/test_legacy_dbf_import_ui.py
git commit -m "feat(import-ui): show legacy relationship warnings"
```

### Task 6: Validate against copied real DBFs and complete the PR loop

**Files:**
- Modify only if evidence requires a scoped fix from Tasks 1-5.
- Do not modify: `C:\femag_importacion\*.dbf`
- Do not stage: `docs/prints/issue_131_load_order_footer_cutoff/load_order_footer_at_min_height.png`

- [ ] **Step 1: Run focused and full automated validation**

```powershell
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest tests/test_schema.py tests/test_legacy_dbf_importer.py tests/test_masters.py tests/test_master_abm_desktop_ui.py tests/test_legacy_dbf_import_ui.py -q
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m pytest -q
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m compileall app scripts
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe -m app.main --smoke
git diff --check
```

Expected: zero failures, compileall exit 0, `FEMAG smoke OK`, and no whitespace errors.

- [ ] **Step 2: Run a controlled import into a temporary SQLite database**

Copy only the source DBFs to a disposable folder and point FEMAG at a disposable SQLite file:

```powershell
$env:FEMAG_DB_ENGINE='sqlite'
$env:FEMAG_SQLITE_PATH="$env:TEMP\femag_issue_188.sqlite3"
D:\notebook\active\femag_desktop\.venv\Scripts\python.exe scripts\import_legacy_dbf_masters.py `
  --carriers C:\femag_importacion\transporte.dbf `
  --drivers C:\femag_importacion\chofer.dbf `
  --source-system legacy_dbf_issue_188
```

Expected evidence: 14 carrier source rows processed, 22 driver source rows processed, normalized tractors created/reused, 9 safe carrier relationships, 13 unassigned drivers, and structured collision/not-found warnings. Verify exact counts from the JSON rather than hard-coding success if source files have changed.

- [ ] **Step 3: Re-run the same import to prove idempotence**

Expected: no duplicate drivers or tractors; existing rows update/reuse and the same relationship warnings remain deterministic.

- [ ] **Step 4: Review repository scope**

```powershell
git status -sb
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

Confirm no remitos, F150, liquidations, production databases, DBF sources or unrelated screenshot files are included.

- [ ] **Step 5: Push, open/update draft PR and comment issue #188**

The draft PR must include issue link, included/out-of-scope sections, exact validation outputs, real-DBF temporary-import counts, warnings, schema risk and screenshots only if the UI changes are manually rendered. Add the operational close comment to issue #188 only after every acceptance criterion is evidenced.
