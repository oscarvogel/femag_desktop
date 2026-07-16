# Domicilio compartido fiscal y entrega

## Objetivo

Representar con un único registro el domicilio que cumple simultáneamente la función fiscal y la de entrega, sin impedir que un cliente tenga posteriormente un domicilio fiscal y uno o más lugares de entrega diferentes.

## Modelo lógico

`ClientAddress.address_type` admite tres valores:

- `fiscal`: sólo domicilio fiscal;
- `entrega`: sólo lugar de entrega;
- `fiscal_entrega`: domicilio compartido que cumple ambas funciones.

No se agrega una migración ni una columna nueva. El valor compartido utiliza el campo existente para mantener el cambio pequeño y compatible con SQLite DEMO.

Para un cliente puede existir como máximo un domicilio con función fiscal. Por lo tanto, `fiscal` y `fiscal_entrega` participan juntos de esa restricción. Puede haber varios domicilios `entrega`.

## Comportamiento de importación

La importación DBF de clientes crea un único domicilio `fiscal_entrega` a partir de `DOMICILIO`, `IMPOSITIVO` y `CODPOS` cuando el cliente todavía no posee una dirección con función fiscal o de entrega.

La reimportación es idempotente y no sobrescribe domicilios editados manualmente. Si ya existe un par `fiscal` y `entrega` cuyos datos coinciden exactamente —dirección, ciudad, provincia, observaciones, estado y condición principal— se consolida en un registro `fiscal_entrega`. Si cualquier dato difiere, ambos registros se conservan.

La consolidación se ejecuta en el flujo controlado de importación y también queda disponible como operación interna idempotente para reparar los pares creados por la versión anterior. No se combinan domicilios por similitud textual aproximada.

## Uso operativo

Todo selector o validación que hoy acepta `entrega` debe aceptar también `fiscal_entrega`. El tipo compartido puede utilizarse como destino de una orden de carga.

Todo control de domicilio fiscal debe considerar tanto `fiscal` como `fiscal_entrega`. No se permite crear otro domicilio con función fiscal mientras exista cualquiera de esos tipos activos para el cliente.

Si el usuario necesita separar las funciones, edita el registro compartido y lo cambia a `fiscal`; luego agrega uno o más domicilios `entrega`. El alcance no incluye automatizar esa separación en una sola acción.

## Interfaz de clientes

La sección se denomina `Domicilios`, no `Lugares de entrega`.

La grilla muestra estas columnas:

1. Tipo
2. Dirección
3. Ciudad
4. Provincia
5. Estado

Los valores visibles son `Fiscal`, `Entrega` y `Fiscal / Entrega`. El diálogo de alta y edición ofrece esas mismas tres opciones.

El mensaje vacío se muestra sólo cuando el cliente seleccionado no tiene domicilios. Al cargar filas se limpia `clientPlacesFeedback`; no se modifica por error el mensaje general del ABM.

## Compatibilidad y datos

No se modifica el esquema de base de datos. Las referencias existentes a `ClientAddress` permanecen válidas porque la consolidación conserva uno de los registros coincidentes. Antes de eliminar el duplicado se debe verificar que no esté referenciado por órdenes u otras entidades; si ambos registros tienen referencias incompatibles, no se consolidan automáticamente y se conserva el par.

La base real no se modifica durante las pruebas. La validación de consolidación se realiza sobre SQLite temporal o sobre una copia de la base DEMO.

## Pruebas y validación

- Pruebas del servicio para unicidad entre `fiscal` y `fiscal_entrega`.
- Pruebas del importador para creación única, reimportación y consolidación segura.
- Pruebas de órdenes para aceptar `fiscal_entrega` como destino.
- Pruebas de UI para columna Tipo, etiquetas, mensaje vacío y diálogo.
- Suite completa, `compileall`, smoke y captura visual.
- Generación de un instalador DEMO con versión posterior a `2026.07.16-demo` y smoke del ejecutable empaquetado.

## Fuera de alcance

- Normalización automática de provincia o localidad legacy.
- Comparación aproximada o geocodificación de domicilios.
- Acción automática para dividir un domicilio compartido.
- Cambios en remitos, F150 o lógica de liquidaciones.
