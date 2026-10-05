# Evidencia visual issue #650

Conteo fisico: un producto sin `peso_unitario_kg` cargado no se puede contar en bolsas.

- `conteo_fisico_producto_sin_peso.png`: grilla con dos productos. "Fecula de maiz (sin peso de bolsa cargado)" aparece con **falta peso de bolsa** en gris, sin campo editable, y con `-` en Equivale a y Diferencia. "Fecula de mandioca" conserva su campo de bolsas. El estado de la pantalla nombra el producto y dice que no es contable. El boton "Cerrar conteo y ajustar" esta deshabilitado porque no hay lineas cargadas.
- `conteo_fisico_con_linea_cargada.png`: mismo estado con un conteo abierto y 480 bolsas de mandioca cargadas (12.000,000 kg, diferencia -500,000 kg). El producto sin peso sigue bloqueado: cargar su conteo no es posible, y el operador ve el motivo.

## Que faltaba antes

`add_line` derivaba los kilos multiplicando bolsas por el peso, sin validar que el peso fuera mayor a cero. Con peso `0.000`, 50 bolsas contadas daban `counted_kg = 0.000`, la diferencia contra el libro era `-saldo` y al cerrar el conteo se generaba un `adjustment_negative` por el saldo completo: **el producto quedaba en cero**, sin error y sin aviso en pantalla.

## Como se generaron

A mano, con `QT_QPA_PLATFORM=offscreen` y una base SQLite descartable en `.tmp/`.

**Las fuentes se cargan a mano desde Windows antes de renderizar.** Sin eso el PNG sale con la estructura de los widgets pero sin un solo caracter: PyQt5 5.15.11 no incluye fuentes y en offscreen Qt no encuentra ninguna. Eso es lo que paso en la primera corrida, que produjo PNG de 5,6 KB. Con `QFontDatabase.addApplicationFont` sobre `C:\Windows\Fonts\segoeui.ttf` y otras tres, los PNG(suben a ~48 KB y se leen.

Ese defecto no es de este PR: afecta a todos los generadores de capturas del proyecto. Ver #652.
