# Evidencia visual issue #730

El parte de produccion registraba **solo** las bolsas embolsadas. La materia prima que el turno fracciono nunca salia del stock, asi que el mismo kilo quedaba en el stock de la materia prima y en el del producto terminado, y el stock de almidon solo crecia.

Desde #730 el parte declara tambien los kilos de materia prima consumidos. Al confirmar, las bolsas entran al stock y el almidon sale, en la misma transaccion.

## Que muestra la captura

`parte_con_materia_prima_consumida.png`: la pantalla de Partes de produccion con los dos bloques.

- **Productos embolsados**: 80 bolsas de BOLSAS ALMIDON DE MAIZ X 25 KG = 2.000,00 kg embolsados.
- **Materia prima consumida**: ALMIDON DE MAIZ BIG BAG, 2.000,00 kg consumidos, con la columna "Disponible en stock" mostrando los 3.000,000 kg que quedaron de la compra.
- El hint de arriba del bloque junta las dos cosas que el operador necesita antes de confirmar: cuanto hay disponible de la materia prima que esta seleccionada y cuanto lleva cargado de este turno.
- La tabla de abajo suma la columna **"Kg consumidos"** al parte.

## El bloqueo

Si la materia prima no alcanza, la confirmacion se bloquea y el libro no se toca:

```
No hay materia prima suficiente para confirmar: de «ALMIDON DE MAIZ BIG BAG» hay
1,000.000 kg en stock y el parte consume 9,999.000 kg. Registrá la compra del big
bag (Producción > Ingreso de materia prima) o el inventario inicial antes de confirmar.
```

Por eso el disponible se muestra **antes** de elegir la materia prima: el operador ve el numero y no se lleva la sorpresa al confirmar.

## Como se genero

Con `python scripts/generate_issue_730_screenshot.py`. Base SQLite en memoria con datos sinteticos: ningun dato real entra en la evidencia. La plataforma es `windows` en vez de `offscreen` para que el texto se dibuje (#652).
