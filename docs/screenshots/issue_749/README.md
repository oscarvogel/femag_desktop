# Issue #749: Ingreso de materia prima y Partes de producción se aplastaban

Capturas de las dos pantallas de **Producción** antes y después del fix,
renderizadas con el plugin de Windows (no `offscreen`, que dibuja los widgets
sin texto: ver issue #652).

| archivo | resolución | qué se ve |
|---|---|---|
| `antes_ingreso_materia_prima_1366x768.png` | 1366x768 | las filas del formulario comprimidas |
| `antes_ingreso_materia_prima_1638x969.png` | 1638x969 (la del cliente) | las filas del formulario comprimidas |
| `antes_partes_produccion_1366x768.png` | 1366x768 | "Fecha", "Turno" y "Observación" superpuestos |
| `antes_partes_produccion_1638x969.png` | 1638x969 | "Fecha", "Turno" y "Observación" superpuestos |
| `despues_ingreso_materia_prima_1366x768.png` | 1366x768 | cada fila en su línea, con barra vertical |
| `despues_ingreso_materia_prima_1638x969.png` | 1638x969 | la pantalla se ve completa |
| `despues_partes_produccion_1366x768.png` | 1366x768 | cada fila en su línea, con barra vertical |
| `despues_partes_produccion_1638x969.png` | 1638x969 | la pantalla se ve completa |

## Cómo se generaron

Con la app real, una base SQLite en memoria y la ventana forzada a cada
resolución:

```python
window = FemagDesktopWindow(user=user, demo_mode=True)
window.stack.setCurrentIndex(window._route_indexes["production_parts"])
window.setFixedSize(1366, 768)
app.processEvents()
window.grab().save("captura.png", "PNG")
```

## Qué cambió

Dos cosas, y las dos hacen falta:

1. Las dos páginas van dentro de un `QScrollArea`, así el contenido conserva su
   alto y el operador lo recorre con la barra vertical en vez de quedar
   comprimido.
2. Los textos largos de estas pantallas ahora hacen **word wrap**. Sin eso, el
   `QLabel` del subtítulo imponía un ancho mínimo de 1571 px: dentro del área
   desplazable la página quedaba más ancha que la ventana y lo de la derecha
   se perdía, sin barra horizontal con la que llegar.
