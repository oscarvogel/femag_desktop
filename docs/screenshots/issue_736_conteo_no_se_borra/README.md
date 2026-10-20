# #736 — El refresco automático no borra lo que el operador escribe

El refresco multi-estación recarga la pantalla visible **cada 10 segundos**, para que un operador vea lo que hacen los demás (un despacho de otra máquina, una compra, un ajuste).

En las pantallas de conteo, esa recarga **reconstruía la tabla y los campos**: el operador perdía lo que estaba escribiendo a los 10 segundos de empezar, sin llegar a grabar nada.

Desde #736, la pantalla actualiza lo que viene de la base (el saldo en el libro, el estado del conteo) y **conserva lo que el operador está escribiendo**. Cambiar la fecha de corte sigue descartando lo escrito: lo que se contó es de una fecha y no aplica a otra.

## Qué muestra cada captura

- `conteo_escrito.png` — el operador cuenta 120 bolsas de almidón de maíz.
- `conteo_tras_el_refresco.png` — llega el refresco automático: las **120 bolsas siguen ahí**, y la columna "Stock en el libro" se actualizó con el dato fresco de la base.

## Cómo se generaron

```bash
python scripts/generate_issue_736_screenshot.py
```

Base SQLite en memoria con datos sintéticos: **ningún dato real entra en la evidencia**. La plataforma es `windows` y no `offscreen` para que el texto se dibuje (#652).

El script además **falla con un error** si el refresco se lleva el conteo: no es solo una captura, es una comprobación.
