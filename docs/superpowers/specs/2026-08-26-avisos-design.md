# Avisos — Design Spec (Enfoque 3 Híbrido)

Fecha: 2026-08-26
Issue tracking: #116 (Botones barra superior). Epic tracking: avisos-epic
Autores: Loop Engineering
Estado: Draft para revisión

## 1. Resumen
Centro de Avisos por perfil con dropdown en topbar (badge) + página Centro de Avisos. Cálculo híbrido: causas computadas en vivo, persistencia mínima solo para “leído/oculto” por usuario. Accionable (click navega a entidad). Ciclo híbrido: auto-expira si la causa se resuelve, permite marcar leído para ocultar temporalmente.

## 2. Contexto y alcance
- Topbar actual (`app/ui/desktop_app.py:_topbar`) tiene botones `Avisos` y `Ayuda` sin handler (bug observado).
- Perfil-dependiente: Administrador, Gerencia, Secretaría, Administración, Solo consulta.
- Reusa servicios existentes: `LoadOrder`, `LoadOrderClosureService`, `ManagerialAccountRisk`/`ClientCreditService`, `Product`.
- Fuera de alcance entrega 1: push/email, backups, importación, auditoría de avisos full.

## 3. Arquitectura
- Fuente computada: `AvisoService.get_for_user(user) -> list[AvisoView]` ejecuta queries por tipo; sin tabla `Aviso`.
- Filtro por perfil via `PermissionService.has_permission` y `MENU`.
- Capa lectura: tabla `aviso_lectura(user_id, tipo, referencia_id, leido_at, oculto_hasta)` para ocultar avisos leídos.
- Cache badge: `count_unread(user)` cache 60s en memoria, invalida tras `close_order`/`payment`.

## 4. Componentes
- `app/models/notifications.py`: `AvisoLectura` (id, user, tipo, referencia_id, leido_at, oculto_hasta). Alternativa fallback: `UserPreference` JSON si se quiere evitar migración.
- `app/services/aviso_service.py`: 
  - `AvisoView(titulo, descripcion, tipo, prioridad, route_key, referencia_id, created_at)`
  - `get_for_user(user)`, `count_unread(user)`, `mark_read(user, tipo, ref)`, `mark_all_read(user)`
- `app/ui/aviso_dropdown.py`: `AvisoDropdown` (QFrame flotante, lista, badge, “Marcar todo leído”, “Ver todos”)
- `app/ui/aviso_center.py`: `AvisoCenterPage` (QTable filtrable por tipo/prioridad, búsqueda, marcar leído, navegación)
- Integración `app/ui/desktop_app.py`: conectar `notifications.clicked` → toggle dropdown, actualizar badge periódico y al refrescar ruta.
- Ruta `avisos` en sidebar (grupo Principal o Sistema según permiso).

## 5. Flujo de datos y UI
- Badge: al iniciar y cada 60s o tras eventos, `count_unread(user)` → `notifications.setText("Avisos (n)")`.
- Dropdown: renderiza `get_for_user` filtrado por no leídos; item muestra prioridad, título, hace X min, clickable → `_navigate_to_route(route_key)` + `mark_read`. Footer “Ver todos →” → `aviso_center`.
- Centro: tabla `Prioridad | Tipo | Mensaje | Fecha | Acción`; filtros por tipo/prioridad + búsqueda por cliente/producto; acción Marcar leído inserta `AvisoLectura`.
- Accionable: cada `AvisoView.route_key` ∈ {`load_orders`, `customer_ledger`, `products`} con `referencia_id`.

## 6. Tipos iniciales (Entrega 1)
- **Aviso 1 — Orden emitida sin cierre** (Alta si >2 días). Fuente `LoadOrder status=emitida`. Perfiles: Secretaría, Administración, Administrador.
- **Aviso 2 — Cliente con deuda vencida / saldo a favor** (Media). Fuente `ManagerialAccountRisk`. Perfiles: Secretaría, Gerencia, Administración.
- **Aviso 3 — Producto en revisión / peso pendiente** (Baja). Fuente `Product review_required or peso=0`. Perfiles: Administración, Administrador.
- No incluye en entrega 1: backups, import errores, push.

## 7. Manejo de errores
- Si query de un tipo falla (`InterfaceError/OperationalError`), se omite ese tipo, se loguea y se muestra “Avisos no disponibles” sin romper dropdown. `count_unread` no bloquea UI (timeout 500ms).

## 8. Testing
- `tests/test_aviso_service.py`: filtra por perfil, saldo a favor genera aviso, producto revisión.
- `tests/test_aviso_dropdown.py`: badge, marcar leído, navegación accionable.
- `tests/test_aviso_center.py`: filtros, persistencia lectura, ciclo híbrido (reaparece si causa persiste tras expiración, desaparece si causa resuelta).
- Validaciones: `python -m compileall app`, `pytest`.

## 9. Rollout — Issues y ramas
- Epic tracking branch: `codex/avisos-epic` (origen común).
- Issue A — Infra Avisos: `codex/avisos-infra` (servicio + lectura + badge + dropdown base).
- Issue B — Tipos operativos/comerciales: `codex/avisos-tipos` (3 tipos + filtro por perfil).
- Issue C — Centro de Avisos accionable: `codex/avisos-center` (página completa, filtros, navegación).
- Cada rama PR chico contra `main`; epic se cierra al mergear las tres. #116 queda como epic/tracking.

## 10. Riesgos y decisiones
- Decisión Enfoque 3 evita tabla masiva de avisos; si se necesita auditoría histórica, migrar a Enfoque 2 (tabla `Aviso`).
- Cache badge simple en memoria; si escala a multi-proceso, mover a DB o expiración por evento.
- `AvisoLectura` requiere migración peewee; alternativa `UserPreference` evita migración pero es menos explícita.

## 11. Criterios de aceptación
- Click en `Avisos` abre dropdown (no hace nada ya no sucede).
- Badge refleja no leídos por perfil, se actualiza tras cerrar orden/pagar deuda.
- Marcar leído oculta aviso; si causa se resuelve, aviso desaparece automáticamente.
- Click en aviso navega a entidad correcta (OC, cuenta, producto).
- Tests 3 tipos pasan por perfil.

## 12. Referencias
- `app/ui/desktop_app.py:379` topbar botones sin handler
- `app/ui/dashboard.py:12` `future_module_message`
- `app/services/load_order_closure_service.py:21` `LoadOrderClosure`
- `app/services/permission_service.py:MENU`
