# Diseño: importación de chofer, transportista, tractor y acoplado habitual

Issue: #188

## Objetivo

Reconstruir durante la importación legacy las relaciones operativas entre
transportistas, choferes y camiones usando los datos disponibles en
`C:\femag_importacion`, sin inventar transportistas ni modificar datos reales.

El resultado debe permitir que FEMAG conozca para cada chofer su transportista,
tractor y acoplado habituales, y debe dejar visibles las relaciones que no se
puedan inferir con seguridad.

## Evidencia de origen

- `transporte.dbf` contiene 14 transportistas con `CODIGO`, `NOMBRE` y `CUIT`.
- `chofer.dbf` contiene 22 choferes.
- `chofer.CODIGO` y `transporte.CODIGO` comparten numeración, pero ocho códigos
  de la muestra pertenecen a personas distintas y no son una relación segura.
- Un código solo es aceptable cuando coincide también el CUIT normalizado o,
  si falta CUIT en uno de los lados, el nombre normalizado.
- El CUIT permite resolver coincidencias adicionales cuando el código no es
  válido.
- `chofer.CHASIS` contiene la patente del tractor habitual.
- `chofer.ACOPLADO` contiene la patente del acoplado habitual.
- Con la regla segura, 9 de 22 choferes encuentran transportista: 5 por código
  validado y 4 por CUIT. Los 13 restantes deben importarse sin transportista.
- Existen patentes repetidas entre choferes; representan un mismo camión y no
  deben generar duplicados.

## Modelo de datos

### Truck

Se mantiene `domain` como patente normalizada del tractor y se agrega:

- `trailer_domain`: patente normalizada del acoplado habitual, nullable.

La relación existente `Truck.carrier` continúa representando el transportista
del camión y debe aceptar vacío para los casos legacy no resueltos.

### Driver

Se agrega:

- `usual_truck`: clave foránea nullable a `Truck`.

La relación existente `Driver.carrier` continúa representando el transportista
del chofer y debe aceptar vacío.

No se crea una tabla independiente de acoplados en este alcance. El dato de
origen describe una combinación habitual tractor-acoplado y no justifica aún un
ABM adicional.

## Orden y reglas de importación

1. Importar transportistas antes de choferes.
2. Para cada chofer, buscar transportista primero por `CODIGO`, pero aceptar la
   coincidencia solamente si también coincide el CUIT normalizado o, cuando
   falte CUIT en alguno de los lados, el nombre normalizado.
3. Si el código no existe o no supera esa validación, buscar por CUIT
   normalizado.
4. Si no existe una coincidencia única, importar el chofer con transportista
   vacío y agregar una advertencia al resumen.
5. Normalizar `CHASIS` eliminando espacios y signos, y convirtiendo a mayúsculas.
6. Si `CHASIS` tiene valor, crear o reutilizar `Truck` por `domain`.
7. Copiar `ACOPLADO`, normalizado con la misma regla, a
   `Truck.trailer_domain`; si está vacío, conservarlo como nulo.
8. Asignar al camión el mismo transportista inferido para el chofer.
9. Asignar el camión a `Driver.usual_truck`.
10. Si `CHASIS` está vacío, importar el chofer sin camión habitual y registrar
    una advertencia.

## Idempotencia y conflictos

- Una nueva ejecución debe actualizar registros importados, no duplicarlos.
- La patente normalizada del tractor es la clave natural para reutilizar
  camiones.
- Dos choferes con la misma patente pueden apuntar al mismo `Truck`.
- Si una patente existente aparece con otro transportista no vacío, no se debe
  sobrescribir silenciosamente. Se conserva la relación existente y se informa
  el conflicto.
- Si una patente existente aparece con otro acoplado no vacío, se conserva el
  primer valor válido y se informa el conflicto.
- Una coincidencia por CUIT solo es válida cuando identifica exactamente un
  transportista.
- La coincidencia numérica de `CODIGO` sin identidad compatible nunca crea una
  relación y debe generar una advertencia de colisión.
- No se crea un transportista ficticio como “Sin identificar”.

## Resumen de importación

Además de creados, actualizados y errores, el resultado debe exponer
advertencias estructuradas para:

- chofer sin transportista;
- chofer sin tractor habitual;
- patente con transportistas incompatibles;
- patente con acoplados incompatibles;
- CUIT que no identifica un transportista único.

Las advertencias no deben impedir la importación de registros válidos.

## Interfaz de usuario

La grilla de choferes debe mostrar:

`Chofer | Transportista | Tractor | Acoplado | Estado de relación`

Estados mínimos:

- `Completa`: transportista y tractor presentes;
- `Sin transportista`: chofer y camión importados sin transportista;
- `Sin tractor`: chofer importado sin `CHASIS`.

El formulario de chofer debe permitir seleccionar el camión habitual y filtrar
primero los camiones del transportista elegido, sin impedir una corrección
manual de datos legacy.

El formulario de camión debe permitir editar transportista, patente del tractor
y patente del acoplado.

## Alcance incluido

- Cambios mínimos de modelo y esquema para `trailer_domain` y `usual_truck`.
- Inferencia por código y CUIT durante importación DBF.
- Creación/reutilización de camiones desde `chofer.dbf`.
- Advertencias y conflictos en el resumen.
- Actualización de ABM/grillas de choferes y camiones.
- Pruebas automatizadas y prueba controlada sobre copias de los DBF indicados.

## Fuera de alcance

- Tabla o ABM independiente de acoplados.
- Historial de asignaciones chofer-camión.
- Asignación temporal por viaje.
- Cambios en remitos, F150, liquidaciones o integraciones fiscales.
- Escritura en bases productivas o modificación de los DBF originales.

## Validación

- Tests de migración/inicialización para columnas nuevas.
- Tests del importador para coincidencia por código, respaldo por CUIT,
  relaciones ausentes, patentes repetidas, conflictos e idempotencia.
- Tests de UI para columnas, estados y edición.
- Suite completa del proyecto.
- `python -m compileall app scripts`.
- `python -m app.main --smoke`.
- Importación en SQLite temporal usando copias de `C:\femag_importacion`, con
  conteos y advertencias documentados.

## Riesgos y mitigaciones

- Inferencia incorrecta por códigos reutilizados: CUIT actúa solo como respaldo
  y los conflictos se reportan.
- Sobrescritura de relaciones manuales: los conflictos no reemplazan valores
  existentes silenciosamente.
- Duplicación de patentes: todas se normalizan antes del upsert.
- Cambio de esquema: debe ser compatible con bases existentes y validarse en
  SQLite temporal antes de cualquier entorno operativo.
