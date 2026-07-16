# Shared Client Address Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Incorporar un domicilio único `fiscal_entrega`, mostrar su tipo en el ABM, usarlo como destino y publicar un nuevo instalador DEMO.

**Architecture:** Centralizar la semántica de tipos en `app/models/masters.py`, aplicar las reglas de unicidad y consolidación en `ClientService`, y hacer que importador y UI consuman esas reglas. Mantener el esquema existente y consolidar únicamente pares exactamente iguales que no requieran reasignar referencias incompatibles.

**Tech Stack:** Python 3.12, Peewee, PyQt5, pytest, PyInstaller e Inno Setup 6.

---

### Task 1: Semántica y reglas del tipo compartido

**Files:**
- Modify: `app/models/masters.py`
- Modify: `app/services/client_service.py`
- Test: `tests/test_clients.py`

- [ ] Escribir pruebas que exijan etiquetas para `fiscal`, `entrega` y `fiscal_entrega`, que `fiscal_entrega` tenga ambas funciones y que la unicidad fiscal considere `fiscal` y `fiscal_entrega`.
- [ ] Ejecutar `python -m pytest tests/test_clients.py -q` y comprobar que falla por ausencia de la semántica compartida.
- [ ] Agregar constantes y funciones pequeñas de tipo en `masters.py`; actualizar `ClientService.add_address()` para validar valores y la función fiscal compartida.
- [ ] Ejecutar `python -m pytest tests/test_clients.py -q` y comprobar que pasa.

### Task 2: Importación única y consolidación segura

**Files:**
- Modify: `app/importers/legacy_dbf.py`
- Modify: `app/services/client_service.py`
- Test: `tests/test_legacy_dbf_importer.py`

- [ ] Reemplazar en pruebas la expectativa de dos filas por una fila `fiscal_entrega` y agregar casos de reimportación, consolidación exacta y conservación de pares diferentes.
- [ ] Ejecutar los casos nuevos y verificar fallos por el comportamiento de dos filas actual.
- [ ] Implementar `ensure_imported_shared_address()` y `consolidate_identical_fiscal_delivery()`; elegir como registro conservado el que tenga referencias y no eliminar cuando ambos registros estén referenciados de forma incompatible.
- [ ] Hacer que `_ensure_client_addresses()` delegue al servicio y nunca sobrescriba domicilios manuales.
- [ ] Ejecutar `python -m pytest tests/test_legacy_dbf_importer.py tests/test_clients.py -q`.

### Task 3: Compatibilidad con órdenes y datos DEMO

**Files:**
- Modify: `app/ui/desktop_app.py`
- Modify: `app/services/load_order_service.py` sólo si existe una validación estricta del tipo
- Test: `tests/test_load_order_desktop_ui.py`
- Test: `tests/test_load_orders.py`

- [ ] Crear un domicilio `fiscal_entrega` en pruebas y exigir que aparezca en el selector y sea aceptado como destino.
- [ ] Ejecutar los casos nuevos y verificar el fallo de filtrado o validación actual.
- [ ] Actualizar las consultas para considerar tipos `entrega` y `fiscal_entrega`, manteniendo fuera los domicilios exclusivamente fiscales.
- [ ] Ejecutar los tests focalizados de órdenes y UI.

### Task 4: Grilla y diálogo de domicilios

**Files:**
- Modify: `app/ui/master_abm.py`
- Test: `tests/test_master_abm_desktop_ui.py`

- [ ] Crear pruebas que exijan el título `Domicilios`, cinco columnas con `Tipo` primero, etiqueta `Fiscal / Entrega`, opción compartida en el diálogo y limpieza de `clientPlacesFeedback` cuando hay filas.
- [ ] Ejecutar los casos nuevos y comprobar que fallan por la grilla de cuatro columnas y el mensaje persistente.
- [ ] Actualizar `_client_address_rows()`, `build_client_abm_page()` y `ClientAddressEntryDialog` usando las etiquetas centralizadas.
- [ ] Corregir `refresh_places()` para limpiar `places_feedback` en la rama con resultados.
- [ ] Ejecutar `python -m pytest tests/test_master_abm_desktop_ui.py -q`.

### Task 5: Validación visual y regresión completa

**Files:**
- Modify: `scripts/generate_ux_screenshots.py` o agregar un generador focalizado sólo si el flujo existente no cubre Clientes
- Create: `docs/screenshots/issue_198_shared_address/client_addresses.png`

- [ ] Ejecutar tests focalizados de clientes, importador, órdenes y ABM.
- [ ] Ejecutar `python -m pytest -q`, `python -m compileall -q app`, `python -m app.main --smoke` y `git diff --check`.
- [ ] Generar una captura con filas Fiscal, Entrega y Fiscal / Entrega; revisar que no haya texto superpuesto ni mensaje vacío incorrecto.
- [ ] Probar `clientes.dbf` contra SQLite temporal y verificar un domicilio compartido por cliente válido e integridad `ok`.

### Task 6: PR, datos instalados y nuevo instalador DEMO

**Files:**
- Modify: `installer/FEMAG_Desktop_Demo.iss`
- Modify: `tests/test_inno_demo_installer.py`

- [ ] Versionar el instalador como `2026.07.16-demo.2` mediante una prueba que falle primero.
- [ ] Confirmar el cambio, subir la rama, abrir PR vinculado a #198 y fusionarlo tras las validaciones.
- [ ] Compilar desde el commit integrado con PyInstaller e Inno Setup.
- [ ] Ejecutar el `.exe` empaquetado con `--smoke`, verificar salida `FEMAG smoke OK`, tamaño, versión y SHA-256.
- [ ] Copiar el instalador verificado a `D:\notebook\active\femag_desktop\installer\output\FEMAG_Desktop_DEMO_Standalone_Setup.exe`.
- [ ] Sobre una copia de la base DEMO instalada, ejecutar la consolidación y verificar que los pares idénticos se convierten en `fiscal_entrega` sin afectar referencias ni integridad.
