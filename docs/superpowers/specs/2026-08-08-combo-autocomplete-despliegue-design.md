# Diseño: despliegue claro de los combos autocompletables

Fecha: 2026-08-08
Estado: aprobado por el usuario

## Problema

Los combos autocompletables implementados en #218 son campos editables con `QCompleter`.
Hoy no es evidente cómo desplegar la lista: la flecha del dropdown es sutil y hacer clic
sobre el texto solo posiciona el cursor, no abre la lista. El usuario no descubre que puede
ver todas las opciones sin tipear.

## Comportamiento esperado

- Hacer clic en cualquier parte del campo despliega la lista completa de opciones.
- Si ya hay texto, al hacer clic se muestran las opciones filtradas por ese texto.
- Un segundo clic con el popup abierto lo cierra (toggle).
- Al tipear, el filtro parcial case-insensitive sigue funcionando como hoy.
- La flecha de despliegue se percibe como botón: estado `:hover` visible.
- Tooltip en el campo: "Clic para ver la lista, escribí para filtrar".
- Se preservan el `commit_combo_text` al perder foco y el `currentData()`.

## Enfoque elegido

Event filter en `combo.lineEdit()` dentro de `enable_combo_autocomplete`.

Ventajas:
- Cambio centralizado en `app/ui/combo_autocomplete.py`; no se tocan los ~15 call sites.
- La flecha sigue siendo el botón nativo del combo.
- No rompe el filtrado en vivo.

Alternativas descartadas:
- Subclase `SearchableComboBox`: más idiomática pero obliga a reemplazar los `QComboBox()` de
  las 6 pantallas; mismo resultado con más superficie de cambio.
- Combo no editable con autocomplete emulado: pierde el filtrado en vivo; descartada.

## Cambios

### `app/ui/combo_autocomplete.py`

1. Agregar un `ClickToOpenEventFilter(QObject)` (interno al módulo) que:
   - En `eventFilter`, para `MouseButtonPress` sobre el line edit:
     - Si `combo.view().isVisible()` -> `combo.hidePopup()`.
     - Si no -> `combo.showPopup()`.
   - Devolver `False` siempre para no tragar el evento (el clic sigue posicionando el cursor).
2. En `enable_combo_autocomplete`, después de configurar el completer:
   - Instalar el event filter sobre `combo.lineEdit()`.
   - Setear el tooltip del line edit con el texto de pista (parámetro nuevo `hint`).
   - Guardar el filtro como atributo del combo (`combo.setProperty` o referencia) para que
     no sea recolectado por GC mientras el combo viva. Usar `functools.partial`/referencia
     fuerte y el flag `AUTOCOMPLETE_PROPERTY` existente para no instalar dos veces.

3. Firma nueva:
   `enable_combo_autocomplete(combo, *, placeholder="Buscar...", hint="Clic para ver la lista, escribí para filtrar")`.

### `app/ui/desktop_app.py` (STYLES)

- Agregar `QComboBox::drop-down:hover, QDateEdit::drop-down:hover { background: #eef2f7; }`
  para que la flecha se note como botón al pasar el mouse.

### `tests/test_combo_autocomplete.py`

- Test: clic sobre el line edit abre el popup (`combo.showPopup()` llamado).
- Test: con popup visible, un clic más lo cierra.
- Test: el tooltip del line edit queda seteado con la pista por defecto.
- Test: filtro por texto sigue funcionando después de habilitar el clic para abrir.

### `tests/test_ui_smoke.py`

- Extender `test_global_styles_include_polished_combo_controls` (o agregar uno) para
  validar que STYLES contiene el `:hover` del drop-down.

## Riesgos

- No interferir con el clic que posiciona el cursor: el filter devuelve `False`.
- No abrir el popup al hacer clic sobre la flecha (eso lo maneja el propio combo; el filter
  solo se instala en el line edit).
- No recolectar el filter antes que el combo: se guarda referencia fuerte.
- `combo.view()` en un editable combo con completer debe responder a `isVisible()` para el
  toggle; verificar en el smoke manual.

## Validaciones

- `python -m pytest` (con al menos los tests de `test_combo_autocomplete.py` y `test_ui_smoke.py`).
- `python -m compileall app`.
- Smoke manual: abrir una pantalla con combo (ej: Nueva orden de carga), hacer clic en el
  campo cliente y verificar que despliega la lista completa; tipear un substring y verificar
  que filtra; seleccionar y verificar `currentData()`.
- Regenerar captura de ejemplo si aplica.
