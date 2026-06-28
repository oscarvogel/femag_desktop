# Manual de pruebas — FEMAG Desktop

Auditoría funcional integral del estado real del proyecto.
Issue: [#111](https://github.com/oscarvogel/femag_desktop/issues/111)

---

## 1. Arquitectura y entry points

### 1.1 Instalación de dependencias

```bash
pip install -r requirements.txt
```

Requiere Python 3.12 y PyQt5. Ver `guia_instalacion.md` para instalación completa.

### 1.2 Entry points

| Concepto | Detalle |
|---|---|
| Entry point | `app/main.py` |
| Flags | `--smoke` (test automático), `--ui` (login + UI producción), `--demo-ui` (demo directo sin login) |
| DB engine | SQLite (`femag_demo.sqlite3`) en modo demo; MySQL en producción (config `.env`) |
| ORM | Peewee |
| UI framework | PyQt5 |
| Tests | pytest vía `py -3.12 -m pytest` |

### Flujo de inicio (demo-ui)

1. `main.py --demo-ui` → `run_desktop_app(demo_mode=True)` (desktop_app.py:53)
2. `_prepare_database(True)` → SQLite, `ensure_runtime_schema()`
3. `_demo_user()` → crea usuario `demo_visual` / `demo` si no existe
4. Abre `FemagDesktopWindow` sin login — la `LoginWindow` es un stub

### Flujo de inicio (producción-ui)

1. `main.py --ui` → intenta MySQL, si falla abre igual sin DB
2. No se muestra login real (LoginWindow.show() → return None)
3. Ventana sin usuario → sidebar vacío, sin datos

---

## 2. Autenticación

| Aspecto | Estado |
|---|---|
| Login real | **NO** — `app/ui/login_window.py` es stub |
| Demo auto-login | Sí — `_demo_user()` crea "demo_visual" con password "demo" |
| Creación manual | `scripts/create_admin_user.py <user> <pass>` |
| Hash | bcrypt via `AuthService.authenticate()` |
| Sesión | No hay sesión real — el user se pasa como string `current_user` a servicios |

**⚠️ Limitación:** No existe pantalla de login funcional. En demo se saltea; en producción entra directamente sin auth.

---

## 3. ABMs y páginas disponibles

### 3.1 Pantallas con UI real (registradas en QStackedWidget)

| Ruta | Título | ¿Funciona? | Archivo |
|---|---|---|---|
| `dashboard` | Dashboard operativo | Sí (cards + quick actions) | desktop_app.py:246 |
| `clients` | Clientes | Sí (CRUD) | desktop_app.py + master_abm.py:182 |
| `addresses` | Domicilios | Sí (CRUD, con combo activo/inactivo) | desktop_app.py + master_abm.py:254 |
| `products` | Productos | Sí (CRUD) | desktop_app.py + master_abm.py:536 |
| `drivers` | Choferes | Sí (CRUD, ligado a transportista) | desktop_app.py + master_abm.py:405 |
| `carriers` | Transportistas | Sí (CRUD) | desktop_app.py + master_abm.py:343 |
| `trucks` | Camiones | Sí (CRUD, ligado a transportista + estado activo) | desktop_app.py + master_abm.py:475 |
| `load_orders` | Órdenes de carga | Sí (ver sección 4) | desktop_app.py:280 |
| `placeholder` | Módulo futuro | Sí (pantalla genérica) | desktop_app.py:117 |

### 3.2 Sidebar — items del menú

| Item | Ruta | Estado |
|---|---|---|
| Dashboard | `dashboard` | Real |
| Órdenes de carga | `load_orders` | Real |
| Remitos | `placeholder` | **Placeholder** — sin UI |
| F150 | `placeholder` | **Placeholder** — sin UI |
| Clientes | `clients` | Real |
| Transporte > Transportistas | `carriers` | Real |
| Transporte > Choferes | `drivers` | Real |
| Transporte > Camiones | `trucks` | Real |
| Productos | `products` | Real |
| Cuenta corriente | `placeholder` | **Placeholder** — aunque hay `account_ledger_service` |
| Reportes | `placeholder` | **Placeholder** |
| Configuración | `placeholder` | **Placeholder** |

### 3.3 Botones y acciones del Dashboard

| Acción | Ruta | Estado |
|---|---|---|
| Nueva orden de carga | `load_orders.new` | Real |
| Buscar orden | `load_orders.search` | Real |
| Nuevo cliente | `clients.new` | Real |
| Registrar remito | `(ninguna)` | **Placeholder** — botón deshabilitado |
| F150 | `(ninguna)` | **Placeholder** — botón deshabilitado |
| Registrar pago | `(ninguna)` | **Placeholder** — botón deshabilitado |
| Cuenta corriente | `(ninguna)` | **Placeholder** — botón deshabilitado |

---

## 4. Órdenes de carga — ciclo de vida completo

### 4.1 Estados

| Constante | Etiqueta | Descripción |
|---|---|---|
| `STATUS_PENDING` | `Pendiente` | Creada, no emitida |
| `STATUS_ISSUED` | `Emitida` | Emitida operativamente |
| `STATUS_CLOSED` | `Cerrada` | Finalizada |
| `STATUS_ANNULLED` | `Anulada` | Anulada |

Estados activos: `Pendiente`, `Emitida`
Estados finales: `Cerrada`, `Anulada`

### 4.2 Transiciones

```
Pendiente ──emitir──▶ Emitida ──cerrar──▶ Cerrada
    │                    │
    └──anular──────────▶ Anulada ◀──anular──┘
```

- `Pendiente → Emitida`: issue() — bloquea chofer, genera cuenta corriente
- `Emitida → Cerrada`: close() — libera chofer
- `Emitida → Anulada`: annul() — reverso contable
- `Pendiente → Anulada`: annul() — sin efecto contable
- `Pendiente → (edit)`: modifica destinos y productos
- `Anulada` → no permite emitir, imprimir ni reimprimir

### 4.3 Acciones operativas (UI + Service)

| Acción | Botón UI | Service | ¿Funciona? |
|---|---|---|---|
| Crear orden | `Nuevo` → `LoadOrderEntryDialog` | `LoadOrderService.create_order()` | Sí |
| Editar pendiente | `Editar` | `LoadOrderService.update_order()` | Sí |
| Emitir | `Emitir` | `LoadOrderOperationService.issue()` | Sí |
| Imprimir | `Imprimir` | `LoadOrderOperationService.print_order()` | Sí |
| Reimprimir | `Imprimir` (en emitida) | `LoadOrderOperationService.reprint_order()` | Sí |
| Cerrar | `Cerrar` | `LoadOrderOperationService.close()` | Sí |
| Anular | `Anular` | `LoadOrderOperationService.annul()` | Sí |
| Buscar | `Buscar` + input | Filtro en memoria por texto | Sí |

### 4.4 Validaciones en ordenes

| Validación | ¿Implementada? |
|---|---|
| Transportista obligatorio | Sí |
| Chofer obligatorio | Sí |
| Camión obligatorio | Sí |
| Chofer debe pertenecer al transportista | Sí |
| Camión debe pertenecer al transportista | Sí |
| Cliente obligatorio | Sí |
| Dirección de entrega obligatoria | Sí |
| Producto con cantidad > 0 | Sí |
| No emitir orden anulada | Sí |
| No imprimir orden anulada | Sí |
| No emitir sin permiso | Sí (vía PermissionService) |
| Chofer bloqueado si tiene orden activa | Sí (DriverAvailabilityService) |
| Dirección de entrega activa requerida | Sí (Loop #108) |
| Dirección de entrega filtrada por cliente | Sí (Loop #109) |

### 4.5 Creación desde el UI (entry dialog)

La UI tiene `LoadOrderEntryDialog` con flujo:
1. Seleccionar chofer → autocompleta transportista y filtra camiones
2. Seleccionar transportista (solo lectura, autocompletado)
3. Seleccionar camión (filtrado por transportista del chofer)
4. Agregar cliente → filtra direcciones de entrega activas de ese cliente
5. Seleccionar dirección de entrega (auto-select si hay una sola activa)
6. Agregar producto con cantidad
7. Validar y guardar

**Dialog específicos:**
- `LoadOrderEntryDialog` — entrada principal (desktop_app.py ~line 450)
- `LoadOrderProductDialog` — cantidad por producto (desktop_app.py ~line 390)

---

## 5. Impresión (HTML — sin PDF real)

| Aspecto | Estado |
|---|---|
| Formato | HTML generado con templates inline |
| Orden A4 | `order_<id>.html` |
| Hoja/sobre resumen | `summary_<id>.html` |
| Combinado | `order_and_summary_<id>.html` |
| Reimpresión | Marcada "Reimpresion — Copia operativa" |
| Directorio | `docs/prints/` |
| Impresión física | **NO** — solo HTML para visualización/guardado |
| Servicio | `LoadOrderPrintService` + `LoadOrderOperationService` |

---

## 6. Cuenta corriente clientes (documental)

| Aspecto | Estado |
|---|---|
| Modelo | `ClientAccountMovement` (no fiscal) |
| Creación | Al emitir orden → 1 movimiento por destino |
| Reverso | Al anular orden → movimientos espejo con `is_reversal=True` |
| Protección duplicados | Sí (idempotencia) |
| UI | **Placeholder** — el sidebar redirige a pantalla placeholder |
| Servicio | `AccountLedgerService` |

---

## 7. Base de datos

### 7.1 Modelos

| Módulo | Modelos |
|---|---|
| `masters` | `Client`, `ClientAddress`, `Carrier`, `Driver`, `Truck`, `Product`, `PalletType`, `Service` |
| `load_orders` | `LoadOrder`, `LoadOrderDestination`, `LoadOrderProduct`, `LoadOrderPallet` |
| `accounting` | `ClientAccountMovement` |
| `audit` | `AuditLog` |
| `security` | `User`, `Profile`, `MenuItem`, `Permission` |
| `system` | `BackupLog`, `SchemaVersion` |

### 7.2 Migraciones

| Aspecto | Estado |
|---|---|
| Schema inicial | `ensure_runtime_schema()` crea tablas si no existen |
| Columnas faltantes | Se agregan con ALTER TABLE si no existen |
| Migraciones manuales | `scripts/migrate_schema.py` |
| Versionado | Modelo `SchemaVersion` con hash de schema |

---

## 8. Demo y scripts

### 8.1 Scripts disponibles

| Script | Función |
|---|---|
| `scripts/instalar_femag_demo.ps1` | Instalador automático PowerShell |
| `scripts/create_admin_user.py` | Crea usuario admin en DB |
| `scripts/seed_issue_65_load_order_demo.py` | Seed básico de maestros + orden demo |
| `scripts/issue_73_integral_demo.py` | Demo integral: crear → emitir → imprimir → reimprimir → anular → verificar cuenta corriente |
| `scripts/migrate_schema.py` | Migración manual de schema |

### 8.2 Test de humo

```bash
py -3.12 -m app.main --smoke
```

Ejecuta comprobaciones básicas:
- Carga de settings
- Inicialización de DB SQLite
- Creación de schema
- Operaciones básicas de maestro y orden

### 8.3 Demo integral (`issue_73_integral_demo.py`)

Flujo completo que:
1. Crea maestros sintéticos (transportista, chofer, camión, 2 clientes, 3 direcciones, 3 productos)
2. Crea orden multi-cliente/multi-destino (3 destinos, 4 productos)
3. Emite la orden
4. Genera HTML de orden y resumen
5. Reimprime como copia operativa
6. Genera cuenta corriente documental
7. Anula la orden y verifica reversos

---

## 9. Tests automatizados

### 9.1 Ejecución

```bash
py -3.12 -m pytest -q
```

Total: **114 passed** (al 28-Jun-2026)

### 9.2 Cobertura por archivo

| Archivo | Tests | Cubre |
|---|---|---|
| `test_masters.py` | 3 | Creación de maestros, filtrado chofer/camión, validación transportista requerido |
| `test_load_orders.py` | 15+ | CRUD órdenes, multi-cliente, productos, pallets, validaciones, auditoría |
| `test_load_order_desktop_ui.py` | 19 | UI dialogo (entry dialog), UI página (workspace), filtros, permisos, edición, emisión, cierre |
| `test_load_order_multi_client_ui.py` | 3 | Form spec, creación multi-cliente, validaciones |
| `test_load_order_operations.py` | 4 | emitir → imprimir → reimprimir → anular, permisos, rechazar anulada |
| `test_load_order_printing.py` | 1 | Exportación HTML |
| `test_load_order_account_ledger.py` | 6 | Movimientos contables, multi-cliente, idempotencia, reversos |
| `test_clients.py` | 2 | Creación cliente + dirección, reglas de validación |
| `test_audit.py` | 1 | Auditoría estructurada |
| `test_backup.py` | 1 | Backup manual + auditoría |
| `test_config.py` | 4 | Settings, inicialización SQLite/MySQL |
| `test_schema.py` | 1 | Schema versionado |
| `test_permissions.py` | 2 | Permisos por perfil |
| `test_models.py` | 1 | Modelos básicos |
| `test_ui_pyqt5libs.py` | 1 | Detección de pyqt5libs |
| `test_ui_smoke.py` | 1 | Smoke test UI básico |
| `test_demo_client_windows_docs.py` | 1 | Documentación del instalador |
| `test_issue_73_integral_demo.py` | 2 | Demo integral + CLI |

### 9.3 Lo que NO cubren los tests

- ❌ Impresión física PDF
- ❌ Login real (no existe)
- ❌ Remitos / F150 / pagos / cuenta corriente UI (placeholder)
- ❌ Integración MySQL real (tests usan SQLite)
- ❌ Rendición de transportistas
- ❌ Importación DBF/MySQL

---

## 10. Procedimientos de validación manual

### 10.1 Smoke test básico

```bash
py -3.12 -m app.main --smoke
```

Esperado: salida limpia sin errores, exit code 0.

### 10.2 Tests automatizados

```bash
py -3.12 -m pytest -q
```

Esperado: 114 passed, 0 failed (con advertencias conocidas de .pytest_cache).

### 10.3 Compilación

```bash
py -3.12 -m compileall app
```

Esperado: OK, sin errores de sintaxis.

### 10.4 Demo integral

```bash
py -3.12 scripts/issue_73_integral_demo.py
```

Esperado: genera HTML en `docs/prints/issue_73_integral_demo/`, muestra resumen con
orden OC-00000X, estado Anulada, 3 destinos, 4 productos, cuenta corriente
con movimientos originales y reversos.

### 10.5 Demo UI (requiere display)

```bash
py -3.12 -m app.main --demo-ui
```

Esperado: ventana PyQt5 con sidebar, dashboard, ABMs funcionales.
**Requiere servidor X/display.** No corre en terminal sin GUI.

### 10.6 Verificación manual desde UI

1. **Dashboard**: ver tarjetas de resumen, acciones rápidas, alertas
2. **Clientes**: crear, editar, ver listado con estado Activo/Inactivo
3. **Domicilios**: crear dirección para cliente, verificar filtro por cliente
4. **Transportistas**: crear, editar
5. **Choferes**: crear ligado a transportista, verificar listado
6. **Camiones**: crear ligado a transportista con patente
7. **Productos**: crear con nombre y unidad
8. **Órdenes de carga**:
   - Crear orden con transportista, chofer, camión, cliente, dirección, producto
   - Verificar que la orden aparece en el listado
   - Emitir orden → ver estado "Emitida", chofer bloqueado
   - Imprimir → ver HTML generado
   - Cerrar orden → ver estado "Cerrada", chofer liberado
   - Crear otra orden, emitir, anular → ver estado "Anulada"
   - Verificar que orden anulada no permite emitir ni imprimir

---

## 11. Limitaciones conocidas

| Área | Limitación | Impacto |
|---|---|---|
| **Login** | No hay pantalla de login real | Producción sin auth real |
| **Remitos** | Placeholder | No se puede emitir remitos |
| **F150** | Placeholder | No se puede generar F150 |
| **Cuenta corriente UI** | Placeholder | No se puede consultar desde UI |
| **Reportes** | Placeholder | No hay reportes |
| **Configuración** | Placeholder | No hay pantalla de configuración |
| **Pagos** | Placeholder | No hay registro de pagos |
| **Impresión** | Solo HTML, sin PDF | No imprime en papel |
| **Fiscal** | Sin integración AFIP/ARCA | No tiene validez fiscal |
| **Importación** | Sin migración desde sistema anterior | No hay importación DBF/MySQL |
| **Rendición** | Sin rendición de transportistas | No hay liquidación de viajes |
| **pyqt5libs** | No instalado | ABMs usan dialogs propios en vez de AutoABM |
| **Búsqueda global** | Top bar search visual sin comportamiento | No filtra nada |
| **Notificaciones** | Botón "Avisos" sin comportamiento | No muestra alertas |
| **Ayuda** | Botón "Ayuda" sin comportamiento | No abre ayuda |
| **Config (top bar)** | Botón "Config" sin comportamiento | No abre configuración |

---

## 12. Áreas protegidas (no tocar sin issue explícito)

- Remitos reales
- F150 real
- Importación DBF/MySQL
- Lógica pesada de liquidaciones
- Integración con sistemas legacy
- Datos demo usados para validación
- Modelos, migraciones o estructura de base de datos
- Pantallas existentes fuera del flujo pedido

---

## 13. Resumen ejecutivo

| Aspecto | Cantidad |
|---|---|
| Loops completados | 4 (0, 1, 2, 3) |
| Pantallas funcionales | 8 (dashboard, 6 ABMs, carga) |
| Pantallas placeholder | 5 (remitos, F150, cta cte, reportes, config) |
| Tests | 114 |
| Servicios | 13 |
| Modelos | 18 |
| Scripts demo | 5 |
| PR mergeados | 20+ |
| Issue tracking abierto | #95 (plan loops) |
| PR draft abierto | #110 (loop 3 hardening) |
