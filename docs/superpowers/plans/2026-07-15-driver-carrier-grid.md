# Driver Carrier Grid Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer que la grilla del ABM de choferes muestre el transportista realmente asignado sin perder compatibilidad con choferes legacy sin asignación.

**Architecture:** Mantener el flujo actual del ABM y corregir únicamente la consulta de lectura. La selección incluirá explícitamente `Driver` y `Carrier` en el `LEFT OUTER JOIN`, para que Peewee hidrate la relación y conserve las filas cuyo transportista sea nulo.

**Tech Stack:** Python 3.12, Peewee, PyQt5, pytest.

---

### Task 1: Corregir la consulta de la grilla de choferes

**Files:**
- Modify: `app/ui/master_abm.py:839-849`
- Test: `tests/test_master_abm_desktop_ui.py:226-238`
- Test: `tests/test_master_abm_desktop_ui.py:531-551`

- [ ] **Step 1: Ejecutar la regresión existente y verificar RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_abm_desktop_ui.py::test_drivers_abm_page_creates_edits_with_carrier_combo -q
```

Expected: FAIL porque la grilla devuelve `Sin asignar` en lugar de `Transportista Chofer UI`.

- [ ] **Step 2: Confirmar que el caso legacy ya está cubierto**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_abm_desktop_ui.py::test_driver_abm_lists_and_opens_unassigned_driver -q
```

Expected: PASS mostrando `Sin asignar` para un chofer con `carrier_id` nulo.

- [ ] **Step 3: Implementar el cambio mínimo**

En `app/ui/master_abm.py`, conservar la construcción de filas y cambiar únicamente la selección:

```python
def _driver_rows() -> list[list[object]]:
    try:
        return [
            [
                driver.id,
                driver.name,
                driver.carrier.name if driver.carrier_id is not None else "Sin asignar",
                "Disponible" if driver.available and driver.active else "No disponible",
            ]
            for driver in Driver.select(Driver, Carrier)
            .join(Carrier, JOIN.LEFT_OUTER)
            .order_by(Driver.name)
            .limit(50)
        ]
    except (InterfaceError, OperationalError):
        return []
```

- [ ] **Step 4: Verificar GREEN en ambos comportamientos**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_master_abm_desktop_ui.py::test_drivers_abm_page_creates_edits_with_carrier_combo tests/test_master_abm_desktop_ui.py::test_driver_abm_lists_and_opens_unassigned_driver -q
```

Expected: `2 passed`.

- [ ] **Step 5: Confirmar el cambio funcional**

```powershell
git diff --check
git diff -- app/ui/master_abm.py
git add app/ui/master_abm.py
git commit -m "fix(ui): show assigned carrier in driver grid"
```

Expected: un único cambio productivo en `_driver_rows()` y commit exitoso.

### Task 2: Validar y publicar la reparación

**Files:**
- Verify: `app/ui/master_abm.py`
- Verify: `tests/test_master_abm_desktop_ui.py`

- [ ] **Step 1: Ejecutar la suite completa**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: toda la suite PASS; la advertencia existente por `pytest.mark.smoke` puede permanecer.

- [ ] **Step 2: Ejecutar validaciones de aplicación**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app
.\.venv\Scripts\python.exe -m app.main --smoke
git diff --check
```

Expected: código compilado, `FEMAG smoke OK` y `git diff --check` sin salida.

- [ ] **Step 3: Revisar el alcance final**

Run:

```powershell
git status -sb
git diff main...HEAD --stat
```

Expected: solamente el diseño, el plan y el cambio localizado en `app/ui/master_abm.py`; `.superpowers/` permanece local y sin versionar.

- [ ] **Step 4: Publicar PR del issue #184**

```powershell
git push -u origin codex/issue-184-driver-carrier-grid
$prBody = @'
Closes #184

## Resumen
- hidrata el transportista en la consulta de la grilla de choferes
- conserva `Sin asignar` para registros legacy

## Validaciones
- `python -m pytest -q`
- `python -m compileall -q app`
- `python -m app.main --smoke`
- `git diff --check`
'@
gh pr create --base main --head codex/issue-184-driver-carrier-grid --title "fix(ui): mostrar transportista asignado en grilla de choferes" --body $prBody
```

Expected: PR abierto y vinculado a `#184`, con validaciones reales documentadas.

- [ ] **Step 5: Reanudar integración a main**

Marcar los PR #182, #183 y el PR de #184 como listos, fusionarlos respetando el orden de dependencias que informe GitHub, actualizar `main` con `git pull --ff-only` y repetir la suite completa sobre el resultado final antes de limpiar las ramas.
