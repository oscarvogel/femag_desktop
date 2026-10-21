# Issue #748: la pantalla de Importación DBF se aplastaba en pantallas bajas

Capturas de la pantalla **Importación -> Importación DBF** antes y después del
fix, renderizadas con el plugin de Windows (no `offscreen`, que dibuja los
widgets sin texto: ver issue #652).

| archivo | resolución | qué se ve |
|---|---|---|
| `antes_1366x768.png` | 1366x768 | las 7 filas del formulario de maestros superpuestas; los campos de ruta y los botones "Examinar" se pisan entre sí |
| `antes_1638x969.png` | 1638x969 (la del cliente) | mismo defecto: las etiquetas se apilan y los "Examinar" quedan encimados |
| `despues_1366x768.png` | 1366x768 | cada fila en su línea, con la barra vertical de desplazamiento a la derecha |
| `despues_1638x969.png` | 1638x969 | la pantalla se ve completa y se puede elegir cada DBF |

## Cómo se generaron

Con la app real, una base SQLite en memoria y la ventana forzada a cada
resolución:

```python
window = FemagDesktopWindow(user=user, demo_mode=True)
window._navigate_to_route("legacy_dbf_import")
window.setFixedSize(1366, 768)
app.processEvents()
window.grab().save("captura.png", "PNG")
```

## Qué cambió

La página mide ~1290 px de alto y antes se agregaba **directamente** al
`QStackedWidget` de la ventana. Con una ventana más baja que ese mínimo, Qt
comprimía los layouts y los widgets se superponían. Ahora la página va dentro
de un `QScrollArea` (`#pageScrollArea`): el contenido conserva su alto y el
operador lo recorre con la barra vertical.
