# Ajuste de importacion DBF para choferes sin transportista

## Contexto

El PR #168 importa maestros legacy desde DBF. Los archivos reales disponibles para validacion contienen clientes, transportistas y choferes, pero `chofer.dbf` no informa una relacion explicita con `transporte.dbf`. Su campo `CUIT` pertenece al chofer y no al transportista.

El importador actual exige `TRANSP`, `TRANSPORTISTA` o `CARRIER` para cada chofer. Esa exigencia impide importar correctamente el archivo real y no debe resolverse inventando asociaciones.

## Objetivo

Importar choferes legacy aun cuando no tengan transportista asignado, conservar su CUIT como dato propio y mantener bloqueado su uso operativo hasta que un usuario asigne un transportista valido.

## Alcance

- Hacer opcional la relacion `Driver.carrier`.
- Agregar `Driver.cuit` como campo nullable.
- Normalizar el CUIT del chofer conservando solo digitos.
- Aceptar filas de chofer con `CODIGO`, `NOMBRE` y `CUIT`, sin exigir una referencia a transportista.
- Mantener compatibilidad con filas que si incluyan `TRANSP`, `TRANSPORTISTA` o `CARRIER`.
- Actualizar pruebas del importador, modelos, esquema y flujo de ordenes afectado.
- Documentar que los choferes sin transportista deben completarse manualmente antes de usarse.

## Fuera de alcance

- Inferir transportistas por coincidencia de codigo o CUIT.
- Crear un transportista ficticio "Sin asignar".
- Importar automaticamente camiones desde los campos `CHASIS` o `ACOPLADO` de `chofer.dbf`.
- Importar DBF reales a una base productiva.
- Modificar remitos, F150, saldos iniciales o otras areas protegidas.

## Modelo de datos

`Driver.carrier` aceptara `NULL`. `Driver.cuit` sera un campo de texto nullable porque el origen puede no informarlo y porque se debe preservar cualquier cero inicial tras la normalizacion.

No se reutilizara `Driver.document` para guardar el CUIT: documento y CUIT representan datos distintos y deben poder evolucionar independientemente.

## Flujo de importacion

Para cada fila de chofer:

1. Usar `CODIGO`, `ID` o `IDLEGACY` como identificador del origen.
2. Usar `NOMBRE` o `CHOFER` como nombre.
3. Leer `CUIT` o `CUITCHOFER`, normalizarlo a digitos y guardarlo en `Driver.cuit`.
4. Si existe `TRANSP`, `TRANSPORTISTA` o `CARRIER`, resolver el transportista importado y asociarlo.
5. Si no existe referencia, guardar `carrier = NULL` sin producir un error de importacion.
6. Mantener la trazabilidad y el comportamiento idempotente existentes.

No se intentara inferir la asociacion a partir de coincidencias entre archivos porque los datos observados no ofrecen una regla inequivoca.

## Comportamiento operativo

Un chofer sin transportista puede existir y mostrarse como maestro pendiente de completar. No puede completar una orden de carga. El flujo actual de ordenes debe conservar o reforzar el mensaje que indica que el chofer seleccionado no tiene transportista asociado.

## Errores y resumen

La ausencia de transportista deja de ser un error para la importacion de choferes. Siguen siendo errores la ausencia de identificador legacy o nombre, y una referencia explicita a un transportista que no existe.

El resumen del lote mantiene los conteos `created`, `updated`, `skipped` y `errors` por entidad.

## Validacion

El cambio se desarrollara con TDD usando filas sinteticas que reproduzcan los nombres de columnas reales. La validacion incluira:

- chofer sin referencia a transportista importado con `carrier = NULL`;
- CUIT normalizado y conservado en `Driver.cuit`;
- chofer con referencia valida asociado como antes;
- referencia explicita inexistente reportada como error;
- segunda ejecucion idempotente;
- creacion de esquema SQLite con el nuevo campo y la FK nullable;
- flujo de ordenes bloqueado para chofer sin transportista;
- suite focalizada, suite completa, `compileall`, smoke y `git diff --check`.

Como prueba operativa final se usara una base SQLite nueva con copias externas de los DBF. Los DBF reales no se versionaran ni se modificaran. Los conteos esperados para los archivos observados son 395 clientes, 14 transportistas y 22 choferes; cualquier error o diferencia se informara antes de promover el PR.

## Riesgos

- Cambiar la nulabilidad de `Driver.carrier` requiere verificar la creacion y actualizacion del esquema en los entornos soportados.
- Pantallas o consultas pueden asumir que todo chofer tiene transportista; las dependencias deben revisarse y cubrirse con pruebas.
- Los archivos reales son una muestra del sistema anterior y pueden existir variantes con otros aliases; este ajuste solo agrega los aliases comprobados o expresamente definidos.
