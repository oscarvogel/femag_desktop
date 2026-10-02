# Issue #452 — Reimprimir presupuesto desde el resumen de cuenta corriente

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/452
- **Issue padre / tracking:** #450 — [TRACKING] Presupuesto manual con deuda, trazabilidad y gestión desde cuenta corriente
- **Estado:** implementado en este PR, pendiente de revisión
- **Base auditada:** `origin/main` @ `7f6d1dc`
- **Rama:** `feat/issue-452-reimprimir-presupuesto`
- **Registrado:** 2026-10-01

## Hilo al que continúa

- #450 (abierto) — tracking de presupuesto manual con deuda, trazabilidad y gestión.
- #451 (cerrado) — creación del presupuesto manual e impacto de deuda en cuenta corriente.
- #452 (este) — **reimpresión** del presupuesto desde la cuenta corriente.
- #453 (cerrado) — envío por WhatsApp del mismo documento desde la cuenta corriente.

## Contexto

El usuario tenía en la pantalla de **Cuenta corriente** tres acciones sobre documentos: **“Enviar presupuesto por WhatsApp”** y **“Imprimir recibo”**, pero **ninguna para imprimir el presupuesto**. El presupuesto se podía mandar por WhatsApp, pero no recuperar en papel/PDF.

Es el punto 5 del tracking #450 (“Permitir reimprimir el presupuesto desde cuenta corriente”) y el hueco exacto que dejó #453 resuelto solo para el canal de WhatsApp.

## Auditoría del estado real del repo (base `origin/main` @ `7f6d1dc`)

Rama de trabajo base `origin/main` (`7f6d1dc`); el trabajo en curso de #580 quedó en `feat/issue-580-bolsas-embolsadas` y **no** se mezcló.

**Lo que ya existía y se reutilizó (sin tocar):**

- `app/ui/customer_ledger.py:296-299` — menú **Acciones** con `whatsapp_budget_action` y `print_receipt_action`, dentro de la sección “Movimiento seleccionado”.
- `app/ui/customer_ledger.py:750-758` — `can_resolve_budget`: condición ya resuelta que detecta presupuesto por `movement.budget_id`, `movement.load_order_id` o `source_ref` con prefijo `Budget:`.
- `app/ui/desktop_app.py:863-891` — `_budget_for_movement()`: resuelve el presupuesto **incluido el caso legacy** de OC sin presupuesto persistido.
- `app/services/budget_print_service.py:112-134` — `export_pdf(budget, output_dir)`: arma el PDF desde los datos persistidos y **solo registra auditoría** (`action="imprimir"`); no crea movimientos.
- `app/ui/desktop_app.py:1108-1118` — `_print_payment_receipt()`: patrón de referencia para imprimir un documento y abrirlo.

**Lo que faltaba:** ninguna acción de menú ni callback para imprimir el presupuesto.

## Comportamiento actual

Con un movimiento de presupuesto seleccionado (por ejemplo `Presupuesto PRES-000008 / OC-000004`), el menú Acciones ofrece enviar por WhatsApp e imprimir recibo, pero **no hay forma de obtener el PDF del presupuesto**. Para imprimirlo había que ir a otra pantalla.

## Comportamiento implementado

Nueva acción **“Reimprimir presupuesto”** en el menú **Acciones**, dentro de la sección “Movimiento seleccionado”, ubicada entre “Enviar presupuesto por WhatsApp” e “Imprimir recibo”.

1. Se habilita solo cuando el movimiento seleccionado **resuelve un presupuesto** (misma regla ya usada por el envío por WhatsApp) y hay callback disponible.
2. Reutiliza `_budget_for_movement()`: funciona igual para **presupuesto manual** y para **OC con presupuesto ya persistido o generado al vuelo** (caso legacy).
3. Reutiliza `BudgetPrintService.export_pdf()`: el PDF se arma desde la cabecera y el detalle **persistidos**, conservando cliente, productos, cantidades, precios, total y **número interno originales**.
4. Abre el PDF generado con `_open_print_output()`.
5. Si el movimiento no tiene presupuesto, la acción queda **deshabilitada** (mismo criterio que el envío por WhatsApp).

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Nombre de la acción | **Reimprimir presupuesto** (texto del issue #452; el documento ya existe y persistido) |
| Ubicación | Menú Acciones, junto a las demás acciones de presupuesto; sin romper el layout compacto |
| Reimpresión | **Reutiliza** el presupuesto persistido; no crea presupuesto nuevo |
| Permisos | Sin permiso nuevo, siguiendo el precedente de **#453** (misma condición que el envío por WhatsApp); la impresión queda auditada por el servicio |
| Movimiento de reverso | No habilitada: un reverso no es un presupuesto imprimible |
| Deuda | Reimprimir **no** vuelve a impactar la cuenta corriente (garantizado por `export_pdf`, que no crea movimientos) |

## Alcance incluido

- `app/ui/customer_ledger.py`: kwarg `print_budget_callback`, atributo, acción `print_budget_action`, connect, handler `_on_print_budget()` y habilitación en `_sync_more_actions()`.
- `app/ui/desktop_app.py`: método `_print_budget_for_movement()` y cableado del callback en `_customer_ledger_page()`.
- `tests/test_issue_452_reprint_budget.py`: **nuevo**, 6 tests.

## Fuera de alcance

- No se toca el cálculo de saldos, la grilla ni el layout de la pantalla.
- No se crean permisos nuevos ni se modifica `permission_service.py`.
- No se toca Orden de Carga, Remitos ni F150.
- No se cambia el flujo de **ver detalle** ni el de envío por WhatsApp (#453).
- No se agrega reimpresión en lote ni desde otras pantallas (fuera del flujo pedido).

## Criterios de aceptación

- [x] La cuenta corriente permite identificar movimientos generados por presupuesto manual.
- [x] Se visualiza el número interno del presupuesto (columna Descripción, ya existente: `Presupuesto PRES-000008 / OC-000004`).
- [x] Existe acción **Reimprimir presupuesto** en el menú Acciones.
- [x] La reimpresión conserva **el mismo número interno** (`presupuesto_<número>.pdf`, mismo archivo).
- [x] El PDF muestra el **detalle original** de mercadería (se arma desde el detalle persistido).
- [x] Reimprimir **no crea ningún débito nuevo ni altera el saldo** (test dedicado).
- [x] Funciona con clientes que tengan múltiples presupuestos históricos.
- [x] Si el movimiento no tiene presupuesto, la acción no está disponible.
- [x] Funciona también con movimientos de OC **sin presupuesto persistido** (resolución al vuelo).

## Archivos modificados

- `app/ui/customer_ledger.py`
- `app/ui/desktop_app.py`
- `tests/test_issue_452_reprint_budget.py` (nuevo)
- `scripts/generate_issue_452_screenshot.py` (nuevo) — evidencia visual, sigue la convención `generate_issue_<N>_screenshot.py` del repo.
- `docs/screenshots/issue_452_reimprimir_presupuesto/` (nuevo) — capturas.

## Validaciones ejecutadas

```bash
git diff --check                                   # OK
python -m compileall app                            # OK
python -m app.main --smoke                          # FEMAG smoke OK (exit 0)
python -m pytest tests/test_issue_452_reprint_budget.py tests/test_issue_453_budget_whatsapp.py -q
                                                     # 10 passed
python -m pytest tests/test_customer_ledger_ui.py tests/test_budget_service.py \
  tests/test_load_order_account_ledger.py tests/test_budget_monetary_integrity.py \
  tests/test_issue_472_financial_audit.py -q        # 63 passed
python -m pytest -q                                 # 1000 passed (266s)
python scripts/generate_issue_452_screenshot.py      # 2 capturas generadas
```

Cobertura de los 6 tests nuevos:

1. Se puede reimprimir el presupuesto del movimiento seleccionado (acción habilitada y callback invocado).
2. Sin presupuesto asociado la acción queda deshabilitada.
3. Sin callback (permiso no concedido) la acción queda deshabilitada.
4. En un movimiento de anulación/reverso la acción queda deshabilitada.
5. Funciona con movimiento de OC legacy sin presupuesto persistido.
6. Reimprimir dos veces conserva número y archivo, no crea presupuestos ni movimientos y no altera la deuda.

## Riesgos y dependencias

1. **Bajo.** Reutiliza servicios ya probados; no toca modelo de datos, migraciones ni permisos.
2. El PDF se **sobreescribe** en `presupuesto_<número>.pdf` al reimprimir: es el comportamiento buscado (mismo documento), pero significa que no se conserva una copia histórica de cada reimpresión. La trazabilidad queda en el registro de auditoría del servicio.
3. La carpeta de salida es la misma que usa el resto de las impresiones (`self._print_output_dir`).
4. No se validó en pantalla con un usuario real: la evidencia es automatizada (suite + smoke) más las capturas generadas.

## Evidencia visual

Generada con `python scripts/generate_issue_452_screenshot.py`:

- `docs/screenshots/issue_452_reimprimir_presupuesto/customer_ledger_presupuesto_seleccionado.png` — Cuenta Corriente con el movimiento `Presupuesto manual PRES-000001` seleccionado y el número interno visible.
- `docs/screenshots/issue_452_reimprimir_presupuesto/customer_ledger_acciones_reimprimir_presupuesto.png` — menú **Acciones** abierto: la acción **“Reimprimir presupuesto”** aparece entre “Enviar presupuesto por WhatsApp” e “Imprimir recibo”.

El script además falla si la acción no quedara habilitada con el movimiento de presupuesto seleccionado, así que la captura no es solo cosmetics: es una aserción de estado.

## Prioridad

**Alta**, tal como define el tracking #450.

## Bitácora

| Fecha | Qué se hizo |
|---|---|
| 2026-10-01 | Auditoría de estado real del repo y de la pantalla de Cuenta Corriente. |
| 2026-10-01 | Detectado que el pedido ya estaba cubierto por el issue abierto #452 (hijo de #450); se continúa ese hilo sin abrir issue nuevo (Regla 1). |
| 2026-10-01 | Implementada la acción “Reimprimir presupuesto” reutilizando `_budget_for_movement()` y `BudgetPrintService.export_pdf()`. |
| 2026-10-01 | Agregados 6 tests; validaciones ejecutadas en verde. |

## Pendientes

- [ ] Validación visual en pantalla con la nueva acción en el menú Acciones (captura).
- [ ] Decidir si la reimpresión debe quedar en el historial visible del presupuesto (`FinancialHistoryDialog`) con una etiqueta propia; hoy queda solo en la auditoría del servicio.
- [ ] Evaluar reimpresión en lote desde Órdenes de Carga como issue aparte si se solicita.
