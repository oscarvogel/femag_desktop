# Diseño: codificador F150 compatible con el sistema legacy

## Contexto

El issue #11 requiere generar archivos F150 por lotes de remitos. El formulario
legacy `C:\programacion\sistema\contable\forms\f150.scx` fue inspeccionado en
Visual FoxPro y se toma como referencia funcional del formato vigente.

El formulario anterior genera:

- un registro `C` por cabecera de remito;
- un registro `D` por cada producto;
- campos delimitados por `@`;
- fechas de proceso `ddMMyyyy` en el prefijo y `dd-MM-yyyy` como dato;
- un archivo de texto Windows-1252 con terminadores CRLF.

## Alcance de este corte

- Definir snapshots tipados para origen, destino, transportista, vehículo,
  chofer y detalle.
- Serializar registros `C` y `D` en el mismo orden del formulario legacy.
- Formatear cantidades, precios y totales como el formulario anterior.
- Impedir remitos repetidos dentro del mismo archivo.
- Validar detalle, cantidades y consistencia de totales.
- Evitar sobrescritura accidental de un archivo existente.
- Cubrir el contrato con pruebas unitarias independientes de la base de datos.

## Fuera de alcance de este corte

- Cambios en los modelos o en la estructura MySQL.
- Adaptación automática desde `Remittance`.
- Persistencia e historial de lotes F150.
- Pantalla de filtros y selección múltiple.
- Marcado de remitos ya incluidos.

Esos puntos continúan en el issue #11 y deben implementarse sobre este contrato,
sin duplicar la lógica de codificación.

## Riesgos y datos faltantes

El modelo actual de remitos no conserva todos los datos que utiliza el F150
legacy. Antes de conectar el generador a producción se debe definir de dónde se
obtienen y cómo se congelan, como mínimo:

- códigos de localidad, departamento, provincia y país;
- domicilios de transportista y chofer;
- tipo y patente de tractor y acoplado;
- clasificaciones de producto `rh1` a `rh4` y rubro;
- precio unitario y total del renglón.

No se deben completar estos valores con datos inventados ni consultar maestros
mutables luego de generar el lote. El adaptador MySQL deberá construir un
snapshot auditable al momento de la generación.

## Validación

```powershell
python -m pytest tests/test_f150_encoder.py -q
python -m compileall app
python -m app.main --smoke
git diff --check
```
