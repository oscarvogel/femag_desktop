# Evidencia visual issue #651

Inventario inicial contado en bolsas, igual que Conteo fisico y partes de produccion.

## Que cambia

La pantalla pedia kilos escritos a mano mientras Conteo fisico pedia bolsas. El mismo numero significaba 25 veces distinto segun donde se escribiera: `500` en Inventario inicial eran 500 kg, y en Conteo fisico 500 bolsas, que a 25 kg son 12.500 kg.

Ahora las dos pantallas cuentan en bolsas y los kilos se derivan del peso de bolsa del producto.

- `inventario_inicial_bolsas.png`: pantalla sin cargar, con el operador escribiendo. `120 bolsas` a 25 kg por bolsa muestra `3.000,000` en "Equivale a (kg)" mientras se escribe. "Almidon (sin peso de bolsa cargado)" aparece bloqueado, con `falta peso de bolsa` en gris, `-` en las otras columnas, y nombrado en el estado de la pantalla.
- `inventario_inicial_cargado.png`: la misma fecha ya cargada. El campo de bolsas muestra lo que se cargo, no los kilos, y la pantalla avisa que cargar dos veces la misma fecha no reemplaza nada.

Los rotulos de las dos pantallas ahora coinciden: Producto - Bolsas contadas - Equivale a (kg). Hay un test (`test_la_pantalla_tiene_el_mismo_rotulo_que_conteo_fisico`) que lo verifica, para que no vuelvan a separarse.

## El error de 25 veces, en numero

El test `test_los_kilos_salen_del_peso_de_cada_producto` corriendo contra el codigo anterior a este PR falla con:

```
assert StockService.balance_for(fecula).balance_kg == Decimal('2500.000')
E   AssertionError: assert Decimal('100.000') == Decimal('2500.000')
```

100 bolsas de 25 kg se guardaban como 100 kg. Eso era el error, y la cifra lo muestra sin necesidad de explicacion.

## Detalle del seed

`_ensure_demo_product` no cargaba `peso_unitario_kg`, asi que los productos del demo los tenian en `0.000` y quedaban bloqueados en las dos pantallas de conteo: el modo demo no podia ejercitar el camino de bolsas. Ahora el seed carga 25 kg, que es el formato de bolsa de la fabrica, y solo completa el peso si esta vacio, para no pisar un valor que el operador haya cargado.

## Como se generaron

A mano, con `QT_QPA_PLATFORM=offscreen` y una base SQLite descartable en `.tmp/`. Las fuentes se cargan desde Windows antes de renderizar: PyQt5 5.15.11 no trae fuentes y en offscreen el texto no se dibuja, asi que sin eso el PNG sale con la estructura de los widgets y sin contenido. Ver #652.
