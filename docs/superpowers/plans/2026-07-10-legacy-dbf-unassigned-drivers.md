# Legacy DBF Unassigned Drivers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Importar `chofer.dbf` real conservando el CUIT del chofer y permitiendo que quede sin transportista hasta su asignacion manual.

**Architecture:** El modelo `Driver` representara explicitamente un CUIT propio y una relacion opcional con `Carrier`. El importador solo resolvera un transportista cuando el DBF aporte una referencia explicita; las pantallas de maestros mostraran el estado pendiente y las ordenes seguiran rechazando choferes sin transportista.

**Tech Stack:** Python 3.13, Peewee, PyQt5, dbfread, pytest, SQLite.

---

### Task 1: Contrato de modelo para choferes sin transportista

**Files:**
- Modify: `tests/test_schema.py`
- Modify: `tests/test_masters.py`
- Modify: `app/models/masters.py`

- [ ] **Step 1: Escribir pruebas fallidas del esquema y modelo**

Agregar aserciones que creen `Driver(name="Chofer pendiente", carrier=None, cuit="27123456789")`, comprueben que persiste, y verifiquen mediante `db.get_columns("driver")` que `carrier_id.null` es verdadero y existe `cuit` nullable.

- [ ] **Step 2: Ejecutar las pruebas y verificar RED**

Run: `python -m pytest tests/test_schema.py tests/test_masters.py -q`

Expected: FAIL porque `Driver.cuit` no existe y `carrier_id` todavia es obligatorio.

- [ ] **Step 3: Implementar el cambio minimo de modelo**

En `Driver`, cambiar:

```python
carrier = ForeignKeyField(Carrier, backref="drivers", null=True)
cuit = CharField(null=True)
```

Mantener `document` separado y sin migraciones ni cambios en otros maestros.

- [ ] **Step 4: Ejecutar las pruebas y verificar GREEN**

Run: `python -m pytest tests/test_schema.py tests/test_masters.py -q`

Expected: PASS.

- [ ] **Step 5: Crear commit focalizado**

```powershell
git add app/models/masters.py tests/test_schema.py tests/test_masters.py
git commit -m "feat: allow drivers without carriers"
```

### Task 2: Importar CUIT y transportista opcional con TDD

**Files:**
- Modify: `tests/test_legacy_dbf_importer.py`
- Modify: `app/importers/legacy_dbf.py`

- [ ] **Step 1: Escribir prueba fallida para la estructura real de `chofer.dbf`**

Agregar una prueba con esta fila sintetica:

```python
{"CODIGO": "0001", "NOMBRE": "Chofer Legacy", "CUIT": "20-12345678-3", "CHASIS": "ABC123", "ACOPLADO": "DEF456"}
```

Debe producir un chofer creado, `driver.carrier is None`, `driver.cuit == "20123456783"` y no crear camiones.

- [ ] **Step 2: Ejecutar la prueba y verificar RED**

Run: `python -m pytest tests/test_legacy_dbf_importer.py::test_legacy_dbf_imports_driver_without_carrier_and_preserves_cuit -q`

Expected: FAIL con el error actual que exige transportista o porque `cuit` no se guarda.

- [ ] **Step 3: Implementar la relacion opcional**

En `_import_drivers`, obtener la referencia con `_value(row, "TRANSP", "TRANSPORTISTA", "CARRIER")`; resolverla con `_get_carrier` solo si existe. Guardar:

```python
values = {
    "name": name,
    "carrier": carrier,
    "cuit": self._clean_cuit(self._value(row, "CUIT", "CUITCHOFER")) or None,
    "document": self._value(row, "DNI", "DOCUMENTO", "DOC"),
    "phone": self._value(row, "TELEFONO", "TEL", "PHONE"),
}
```

- [ ] **Step 4: Ejecutar la prueba y verificar GREEN**

Run: `python -m pytest tests/test_legacy_dbf_importer.py::test_legacy_dbf_imports_driver_without_carrier_and_preserves_cuit -q`

Expected: PASS.

- [ ] **Step 5: Escribir y verificar pruebas de compatibilidad**

Agregar pruebas separadas para: referencia valida conserva la asociacion; referencia explicita inexistente queda en `errors`; segunda importacion actualiza el mismo chofer sin duplicarlo.

Run: `python -m pytest tests/test_legacy_dbf_importer.py -q`

Expected: PASS con todos los casos del importador.

- [ ] **Step 6: Crear commit focalizado**

```powershell
git add app/importers/legacy_dbf.py tests/test_legacy_dbf_importer.py
git commit -m "fix: import legacy drivers without carriers"
```

### Task 3: Mostrar y bloquear correctamente choferes pendientes

**Files:**
- Modify: `tests/test_master_abm_desktop_ui.py`
- Modify: `tests/test_load_order_desktop_ui.py`
- Modify: `app/ui/master_abm.py`
- Modify: `docs/guia_importacion_dbf.md`

- [ ] **Step 1: Escribir prueba fallida de listado de maestros**

Crear un chofer con `carrier=None`, abrir el ABM de choferes y verificar que aparece con transportista `Sin asignar`, sin excepcion ni exclusion por `JOIN` interno.

- [ ] **Step 2: Ejecutar la prueba y verificar RED**

Run: `python -m pytest tests/test_master_abm_desktop_ui.py -k unassigned -q`

Expected: FAIL porque el listado actual usa `join(Carrier)` y `driver.carrier.name`.

- [ ] **Step 3: Ajustar el ABM de choferes**

Cambiar el listado a `join(Carrier, JOIN.LEFT_OUTER)` o consulta equivalente y renderizar `driver.carrier.name if driver.carrier_id is not None else "Sin asignar"`. Al editar un chofer sin transportista, seleccionar ningun transportista sin acceder a `.id` sobre `None`; mantener la regla actual que exige asignarlo al guardar manualmente.

- [ ] **Step 4: Verificar GREEN del ABM**

Run: `python -m pytest tests/test_master_abm_desktop_ui.py -k "driver or unassigned" -q`

Expected: PASS.

- [ ] **Step 5: Escribir prueba del bloqueo en ordenes**

Crear un chofer activo con `carrier=None`, seleccionarlo en `LoadOrderEntryDialog` y comprobar el texto `El chofer seleccionado no tiene transportista asociado.` y que no se habilita un guardado valido.

- [ ] **Step 6: Ejecutar la prueba de ordenes**

Run: `python -m pytest tests/test_load_order_desktop_ui.py -k no_carrier -q`

Expected: PASS con el comportamiento defensivo existente; si falla por una excepcion, aplicar el ajuste minimo en `app/ui/desktop_app.py` y repetir hasta PASS.

- [ ] **Step 7: Actualizar la guia operativa**

Documentar que `CUIT` en `chofer.dbf` pertenece al chofer, que la ausencia de transportista no bloquea el lote y que debe asignarse manualmente antes de crear una orden.

- [ ] **Step 8: Crear commit focalizado**

```powershell
git add app/ui/master_abm.py app/ui/desktop_app.py tests/test_master_abm_desktop_ui.py tests/test_load_order_desktop_ui.py docs/guia_importacion_dbf.md
git commit -m "fix: show unassigned legacy drivers safely"
```

### Task 4: Prueba operativa segura con los DBF externos

**Files:**
- No versionar archivos DBF ni la base temporal.

- [ ] **Step 1: Crear un directorio temporal fuera del repositorio**

Usar `$env:TEMP\femag-pr168-validation` y copiar alli `clientes.dbf`, `transporte.dbf` y `chofer.dbf` desde `C:\femag_importacion`, conservando intactos los originales.

- [ ] **Step 2: Crear una SQLite nueva y ejecutar el importador**

Configurar `FEMAG_DB_ENGINE=sqlite` y `FEMAG_SQLITE_PATH` apuntando a una base nueva dentro del directorio temporal. Crear el esquema con los mecanismos del proyecto y ejecutar:

```powershell
python scripts/import_legacy_dbf_masters.py --clients "$temp\clientes.dbf" --carriers "$temp\transporte.dbf" --drivers "$temp\chofer.dbf" --encoding cp1252 --source-system validation_legacy_dbf
```

- [ ] **Step 3: Verificar conteos y errores sin exponer datos**

Comprobar 395 clientes leidos, 14 transportistas leidos y 22 choferes leidos. Informar creados, actualizados, omitidos y errores; no imprimir nombres, CUIT ni domicilios. Si hay errores de campos reales, detener la promocion del PR y agregar primero una prueba sintetica que reproduzca cada incompatibilidad.

- [ ] **Step 4: Repetir la importacion para probar idempotencia**

La segunda corrida debe crear cero registros nuevos para las tres entidades y actualizar los registros ya trazados sin duplicarlos.

### Task 5: Validacion completa y actualizacion del PR #168

**Files:**
- Review: todos los archivos modificados en la rama.

- [ ] **Step 1: Ejecutar validaciones focalizadas**

```powershell
python -m pytest tests/test_legacy_dbf_importer.py tests/test_schema.py tests/test_masters.py tests/test_master_abm_desktop_ui.py tests/test_load_order_desktop_ui.py -q
```

Expected: PASS, cero fallos.

- [ ] **Step 2: Ejecutar validaciones generales**

```powershell
git diff --check origin/main...HEAD
python -m compileall app scripts
python -m app.main --smoke
python -m pytest -q
```

Expected: todos los comandos con exit code 0. Cualquier fallo externo se documenta con su prueba y PR relacionado; no se declara listo mientras afecte el alcance de #168.

- [ ] **Step 3: Auditar el diff y archivos no trackeados**

Run: `git status -sb` y `git diff --stat origin/main...HEAD`.

Confirmar que `.codegraph`, `.cursor`, DBF y SQLite permanecen ignorados o fuera del repositorio y que no hay cambios ajenos al issue.

- [ ] **Step 4: Subir la rama y actualizar GitHub**

Push de `codex/issue-14-dbf-master-import`, actualizar el cuerpo de PR #168 con el soporte de chofer sin transportista, comandos/resultados y riesgos, y comentar el cierre operativo en #165 sin marcar el PR listo hasta completar la validacion visual/manual requerida.
