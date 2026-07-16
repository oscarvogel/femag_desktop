# Product Classification and Weight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clasificar artículos legacy, inferir su peso comercial, excluir conceptos no cargables de órdenes y publicar un nuevo DEMO.

**Architecture:** Crear un analizador puro y testeable en `app/services/product_classification_service.py`; persistir resultado y procedencia en `Product`; hacer que importación, backfill, ABM y órdenes consuman una única semántica. Las correcciones manuales se identifican por campos de procedencia y nunca se pisan.

**Tech Stack:** Python 3.12, Peewee, PyQt5, pytest, PyInstaller e Inno Setup 6.

---

### Task 1: Analizador puro de descripción

**Files:**
- Create: `app/services/product_classification_service.py`
- Create: `tests/test_product_classification_service.py`

- [ ] Escribir pruebas parametrizadas para las cinco clasificaciones y pesos `10 x 1 kg`, `25 kg`, `900 gr`, `500 gr`, `x kg` y sin presentación.
- [ ] Ejecutar `python -m pytest tests/test_product_classification_service.py -q` y verificar que falla porque el módulo no existe.
- [ ] Implementar `analyze_legacy_product(name) -> ProductInference` con normalización de acentos, reglas ordenadas y `Decimal` a tres decimales.
- [ ] Ejecutar el archivo de pruebas y comprobar que pasa.

### Task 2: Persistencia, backfill e importación

**Files:**
- Modify: `app/models/masters.py`
- Modify: `app/config/schema.py`
- Modify: `app/importers/legacy_dbf.py`
- Test: `tests/test_schema.py`
- Test: `tests/test_legacy_dbf_importer.py`

- [ ] Escribir pruebas que exijan columnas de clasificación/procedencia/revisión, backfill idempotente e inferencia durante importación.
- [ ] Agregar campos nullable a `Product` y helpers de etiqueta/cargabilidad.
- [ ] Implementar backfill de productos sin fuente y preservar todo peso positivo preexistente como manual.
- [ ] Adaptar `_import_products()` para inferir sólo campos cuya fuente no sea `manual` y usar `UNIDADDGR` para la unidad cuando corresponda.
- [ ] Ejecutar `python -m pytest tests/test_schema.py tests/test_legacy_dbf_importer.py -q`.

### Task 3: Edición manual y ABM

**Files:**
- Modify: `app/services/master_service.py`
- Modify: `app/ui/master_abm.py`
- Test: `tests/test_masters.py`
- Test: `tests/test_master_abm_desktop_ui.py`

- [ ] Escribir pruebas de alta/edición manual que fijen ambas fuentes en `manual`, validen peso no negativo y comprueben las nuevas columnas.
- [ ] Extender `MasterService.create_product()` y agregar `update_product()` para centralizar auditoría y procedencia.
- [ ] Incorporar combo Clasificación, peso y estado de revisión al diálogo; ampliar la grilla con Clasificación, Órdenes y Revisión.
- [ ] Ejecutar las pruebas focalizadas de maestros y UI.

### Task 4: Exclusión real de órdenes de carga

**Files:**
- Modify: `app/ui/desktop_app.py`
- Modify: `app/ui/load_orders.py`
- Modify: `app/services/load_order_service.py`
- Test: `tests/test_load_order_desktop_ui.py`
- Test: `tests/test_load_orders.py`

- [ ] Escribir pruebas que muestren sólo `producto` en ambos proveedores de opciones y rechacen un servicio enviado directamente al servicio.
- [ ] Filtrar `_product_options()` en ambas UI por `active` y `product_kind == producto`.
- [ ] Validar en creación y actualización que cada producto tenga función cargable, con error en español.
- [ ] Ejecutar los tests focalizados de órdenes.

### Task 5: Evidencia real y regresión

**Files:**
- Create: `scripts/generate_issue_200_screenshot.py`
- Create: `docs/screenshots/issue_200_product_classification/products.png`

- [ ] Ejecutar el DBF real sobre SQLite temporal y registrar conteo por clasificación, pesos inferidos y pendientes.
- [ ] Probar backfill sobre una copia de la base DEMO instalada y verificar integridad sin modificar el original.
- [ ] Generar y revisar una captura de la grilla con varias clasificaciones.
- [ ] Ejecutar `python -m pytest -q`, `python -m compileall -q app`, `python -m app.main --smoke` y `git diff --check`.

### Task 6: GitHub e instalador DEMO

**Files:**
- Modify: `installer/FEMAG_Desktop_Demo.iss`
- Modify: `tests/test_inno_demo_installer.py`

- [ ] Versionar el instalador como `2026.07.16-demo.3` mediante prueba roja y cambio mínimo.
- [ ] Confirmar cambios, subir rama, abrir PR vinculado a #200 y fusionar tras validación.
- [ ] Compilar el árbol fusionado con PyInstaller e Inno Setup.
- [ ] Ejecutar smoke empaquetado, verificar versión, tamaño y SHA-256.
- [ ] Copiar el instalador a `D:\notebook\active\femag_desktop\installer\output\FEMAG_Desktop_DEMO_Standalone_Setup.exe` y comentar evidencia final en #200.
