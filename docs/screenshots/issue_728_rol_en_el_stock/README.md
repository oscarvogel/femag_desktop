# Evidencia visual issue #728

El ABM de productos que corre en la app no tenia el campo "Rol en el stock": era imposible marcar una materia prima, y por lo tanto la pantalla de Ingreso de materia prima (#656) quedaba vacia y el libro de stock no tenia ninguna entrada.

## Que cambia

`app/ui/product_code_extension.py` reemplaza el dialogo de Producto del ABM base por uno propio, para agregar el campo "Codigo" (#319). Como reconstruye el formulario entero, se llevó puesto el campo "Rol en el stock" que #656 habia agregado al ABM base: no lo creaba, no lo cargaba y no lo guardaba. El campo existia en el modelo, en el servicio y en el listado del ABM base, pero era **inalcanzable desde la app**.

Ahora el dialogo real tiene el campo, carga el rol del producto que se esta editando y lo guarda; el listado vuelve a mostrar la columna "Rol en el stock".

- `producto_rol_en_el_stock.png`: el dialogo de Producto con "Rol en el stock" en "Materia prima" y la aclaracion de que el "Peso unitario" es el peso de un big bag, no el de una bolsa de venta.
- `listado_productos_con_rol.png`: el listado de Productos con la columna "Rol en el stock" entre "Clasificacion" y "Ordenes".

## Por que el "Tipo de producto" no era el campo

"Clasificacion" (`product_kind`: producto, servicio, financiero, interno, revisar) clasifica **para facturar**: define que se puede cargar en una orden de carga y como se factura. "Rol en el stock" (`stock_role`: terminado, materia prima) responde otra pregunta: si el producto se compra y se consume para fabricar, o se vende tal cual. Un big bag de almidon es "producto" comercialmente (se factura) y al mismo tiempo es materia prima (se consume al fraccionar). Por eso son dos campos y no uno.

## Como se generaron

Con `python scripts/generate_issue_728_screenshot.py`. Base SQLite en memoria con productos sinteticos: ningun dato real entra en la evidencia. La plataforma es `windows` en vez de `offscreen` para que el texto se dibuje (#652).
