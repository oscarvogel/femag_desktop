# Proyecto FEMAG — Sistema de Gestión Operativa Local

## Objetivo del pedido para Codex

Necesito iniciar un nuevo proyecto de escritorio para FEMAG, una fábrica de fécula de mandioca ubicada en Misiones, Argentina.

El objetivo es crear los **issues iniciales de GitHub**, proponer una **estructura de ramas**, definir el **plan técnico de implementación** y dejar organizado el backlog inicial para comenzar el desarrollo.

El sistema será una aplicación de escritorio local, conectada a una base de datos MySQL alojada en un servidor interno de la fábrica.

---

# 1. Contexto general del sistema

FEMAG necesita un sistema para ordenar su operatoria administrativa y de despacho.

La primera etapa del sistema debe cubrir:

* Clientes.
* Domicilios fiscales y domicilios de entrega.
* Productos.
* Choferes.
* Transportistas.
* Camiones.
* Tipos/detalles de pallets.
* Órdenes de carga.
* Remitos.
* Generación de archivo F150 para Rentas.
* Cuenta corriente básica multimoneda de clientes.
* Registro de pagos.
* Recibos con numeración propia.
* Importación incremental desde sistemas anteriores MySQL y DBF.
* Usuarios, perfiles y permisos por menú/acción.
* Auditoría básica desde el inicio.
* Backup automático diario en servidor.
* Dashboard central.
* Menú lateral simple.

---

# 2. Stack técnico decidido

El sistema debe desarrollarse como aplicación de escritorio.

Tecnologías:

* Python 3.
* PyQt o PySide para interfaz gráfica.
* MySQL como base de datos central.
* Peewee como ORM.
* Reportes/imprimibles en PDF o formato apto para impresión.
* Arquitectura local en red interna.
* Uso desde 5/6 PCs.
* Varias secretarias trabajando simultáneamente.
* Base MySQL en servidor interno de FEMAG.

No se desarrollará nube en esta etapa.

---

# 3. Principios de diseño

El sistema debe ser muy simple de usar para personal administrativo.

Prioridades de UX:

* Menú lateral fijo.
* Dashboard central al iniciar.
* Botones grandes para acciones frecuentes.
* Formularios simples.
* Pocos campos obligatorios.
* Búsqueda rápida.
* Accesos directos.
* Permisos por usuario y por menú.
* Mensajes claros.
* Reimpresión fácil.
* Estados visibles.
* Auditoría de acciones sensibles.
* Manejo rápido con teclado cuando sea posible.

Accesos rápidos sugeridos:

* Nueva orden de carga.
* Nuevo remito.
* Registrar pago.
* Buscar cliente.
* Buscar remito.
* Generar F150.
* Cuenta corriente.

---

# 4. Perfiles de usuario iniciales

Crear soporte para estos perfiles:

## Administrador

* Acceso total.
* Puede crear usuarios.
* Puede asignar permisos.
* Puede modificar datos sensibles.
* Puede anular remitos.
* Puede modificar/anular pagos.
* Puede cambiar saldo inicial.
* Puede ver auditoría.
* Puede ejecutar importaciones.
* Puede configurar backups.

## Secretaría

* Puede cargar datos operativos.
* Puede consultar información.
* Puede crear órdenes de carga.
* Puede registrar remitos.
* Puede imprimir y reimprimir documentación.
* No puede borrar.
* No puede modificar datos cargados por otras personas.
* No puede anular remitos sin clave de administrador.
* No puede cambiar saldos iniciales.

## Administración

* Puede consultar y administrar clientes.
* Puede registrar pagos.
* Puede emitir recibos.
* Puede consultar cuenta corriente.
* Puede imprimir reportes.
* No puede anular pagos sin clave de administrador.
* No puede modificar saldo inicial sin clave de administrador.

## Solo consulta

* Solo puede visualizar información.
* No puede crear, modificar, anular ni borrar.

---

# 5. Permisos requeridos

El sistema debe implementar permisos por:

* Usuario.
* Perfil.
* Menú.
* Acción.

Acciones mínimas:

* Ver.
* Crear.
* Modificar.
* Anular.
* Eliminar, solo administrador.
* Imprimir.
* Reimprimir.
* Importar.
* Exportar.
* Configurar.

Acciones que requieren clave de administrador:

* Anular remito.
* Modificar pago.
* Anular pago.
* Cambiar saldo inicial.

Acción que NO requiere clave de administrador:

* Reimprimir documentación.

---

# 6. Auditoría básica obligatoria

Desde el inicio debe existir auditoría básica.

Registrar como mínimo:

* Usuario.
* Fecha.
* Hora.
* Módulo.
* Acción.
* Registro afectado.
* Valor anterior cuando corresponda.
* Valor nuevo cuando corresponda.
* Observación opcional.
* IP/equipo si está disponible.

Auditar especialmente:

* Altas.
* Modificaciones.
* Anulaciones.
* Eliminaciones.
* Cambio de saldo inicial.
* Modificación/anulación de pagos.
* Anulación de remitos.
* Generación de F150.
* Importaciones.
* Cambios de permisos.
* Cambios de numeración.
* Backups manuales.

---

# 7. Menú lateral propuesto

Crear un menú lateral con esta estructura inicial:

## Inicio

* Dashboard.
* Pendientes.
* Accesos rápidos.

## Operaciones

* Órdenes de carga.
* Remitos.
* Generar F150.
* Hoja resumen / sobre de carga.

## Cuenta corriente

* Clientes con saldo.
* Movimientos.
* Registrar pago.
* Recibos.
* Anulación de pagos.

## Maestros

* Clientes.
* Domicilios.
* Productos.
* Pallets / tipos de pallet.
* Choferes.
* Transportistas.
* Camiones.

## Importación

* Importar clientes.
* Importar productos.
* Importar choferes.
* Importar transportistas.
* Importar remitos.
* Importar saldos.
* Control de diferencias.

## Sistema

* Usuarios.
* Perfiles.
* Permisos por menú.
* Parámetros.
* Numeraciones.
* Backups.
* Auditoría.

---

# 8. Dashboard central

El dashboard inicial debe mostrar:

* Órdenes del día.
* Remitos del día.
* Pagos del día.
* Clientes con saldo.
* Pendientes.
* Accesos rápidos.

Botones grandes:

* Nueva orden de carga.
* Nuevo remito.
* Registrar pago.
* Buscar cliente.
* Buscar remito.
* Generar F150.
* Cuenta corriente.

Pendientes sugeridos:

* Órdenes abiertas.
* Choferes bloqueados por carga activa.
* Remitos no incluidos en F150.
* Pagos anulados.
* Clientes con saldo.
* Importaciones con errores.

---

# 9. Reglas funcionales principales

## 9.1 Clientes

Cada cliente debe tener:

* Razón social / nombre.
* CUIT.
* Condición IVA.
* Teléfono.
* Email.
* Contacto.
* Domicilio fiscal.
* Domicilios de entrega múltiples.
* Un domicilio de entrega principal.
* Estado activo/inactivo.

El email del cliente se usará desde esta etapa.

---

## 9.2 Domicilios

El cliente puede tener:

* Un domicilio fiscal.
* Varios domicilios de entrega.
* Un domicilio de entrega marcado como principal.

Campos mínimos de domicilio:

* Provincia.
* Localidad.
* Dirección.
* Tipo: fiscal / entrega.
* Es principal: sí/no.
* Observaciones.

---

## 9.3 Productos

Productos iniciales:

* Fécula de mandioca.
* Fécula de maíz.
* Otros.

No se maneja stock en esta etapa.

---

## 9.4 Choferes, transportistas y camiones

El sistema debe permitir administrar:

* Choferes.
* Transportistas.
* Camiones.

Los choferes pueden bloquearse cuando tienen una carga activa.

Regla:

* Un chofer no puede asignarse a otra orden mientras tenga una carga activa.

---

## 9.5 Pallets

Los pallets no son solo una cantidad.

Deben tener detalle:

* Tipo.
* Medida.
* Peso.
* Cantidad.

Deben poder cargarse dentro de la orden de carga.

---

## 9.6 Órdenes de carga

Una orden de carga corresponde a:

* Un camión.
* Un chofer.
* Un transporte.
* Uno o más renglones de despacho para distintos clientes/destinatarios y productos.

Una orden NO se divide en más de un camión.

La orden puede tener varios renglones de despacho. Cada renglón puede corresponder a un destinatario distinto y contener cantidades por presentación, lote y fecha de elaboración.

Campos de cabecera:

* Número.
* Fecha.
* Cliente de cabecera opcional o texto de cabecera.
* Destino general.
* Transportista.
* Chofer.
* Camión.
* Vehículo limpio y apto.
* Estado.
* Observaciones.

Detalle de renglones:

* Cliente asociado opcional.
* Destinatario / cliente texto.
* Localidad / destino texto.
* Producto asociado opcional.
* Detalle del producto o presentación.
* Bolsas x 25 kg.
* Bolsas x 10 kg.
* Pack.
* Pallet.
* Número de lote.
* Fecha de elaboración.
* Observaciones.

Detalle de pallets:

* Tipo.
* Medida.
* Peso.
* Cantidad.

Estados sugeridos:

* Pendiente.
* Emitida.
* Cerrada.
* Anulada.

Al imprimir la orden de carga, también debe imprimirse la hoja resumen/sobre.

---

## 9.7 Remitos

Los remitos son independientes de las órdenes de carga.

Reglas:

* El remito se puede registrar manualmente.
* El remito debe respetar numeración existente.
* Los remitos son individuales.
* Un remito no impacta automáticamente en cuenta corriente.
* Un remito puede o no estar vinculado a una orden de carga.
* Debe poder consultarse y reimprimirse.

Campos mínimos:

* Número de remito.
* Fecha.
* Cliente.
* Productos.
* Cantidades.
* Transportista opcional.
* Chofer opcional.
* Camión opcional.
* Orden de carga vinculada opcional.
* Estado.
* Observaciones.

Acción sensible:

* Anular remito requiere clave de administrador.
* Debe quedar auditado.

---

## 9.8 F150

El F150 se genera por lote de remitos seleccionados.

Reglas:

* El usuario debe poder buscar y seleccionar remitos.
* Los remitos seleccionados pueden no coincidir con órdenes de carga.
* El sistema genera un archivo para subir a Rentas.
* La impresión final del F150 se realiza desde Rentas.
* El sistema debe marcar qué remitos ya fueron incluidos en un lote F150.
* Debe existir historial de lotes F150 generados.
* Debe evitarse incluir accidentalmente el mismo remito en más de un lote, salvo acción autorizada.

Filtros de pantalla F150:

* Fecha desde / hasta.
* Cliente.
* Número de remito.
* Estado.
* Incluido/no incluido en F150.

Acciones:

* Seleccionar remitos.
* Validar selección.
* Generar archivo.
* Registrar lote.
* Consultar lotes anteriores.
* Reexportar archivo si corresponde.

---

## 9.9 Cuenta corriente básica multimoneda

La cuenta corriente es de clientes.

Debe ser multimoneda.

Los pagos se aplican al saldo general del cliente, no a remitos específicos.

Campos mínimos de movimiento:

* Cliente.
* Fecha.
* Moneda.
* Tipo: débito / crédito.
* Concepto.
* Importe.
* Referencia.
* Observaciones.
* Usuario.
* Estado.

Saldos:

* Deben poder consultarse por cliente y moneda.
* La carga o cambio de saldo inicial requiere clave de administrador.
* Debe quedar auditado.

---

## 9.10 Pagos y recibos

Pagos manuales.

Medios de pago:

* Efectivo.
* Transferencia.
* Cheque.
* Otros.

Los pagos bajan el saldo general del cliente.

El recibo debe tener numeración propia.

Campos mínimos del pago:

* Cliente.
* Fecha.
* Moneda.
* Importe.
* Medio de pago.
* Número de recibo.
* Observaciones.
* Estado: activo / anulado.
* Usuario que cargó.

Reglas:

* Se pueden anular pagos.
* Anular pago requiere clave de administrador.
* La anulación debe quedar auditada.
* Debe existir consulta de pagos anulados.
* Debe quedar visible para el administrador en dashboard o pendientes.

No incluir en esta etapa envío externo automático por email/WhatsApp al jefe. Puede quedar como mejora futura.

---

## 9.11 Importación incremental desde sistema anterior

Existen datos en:

* MySQL.
* DBF.

Hay acceso directo a esas bases.

La importación debe poder ejecutarse varias veces durante la convivencia con el sistema anterior.

Reglas:

* Se debe poder importar varias veces.
* Se deben agregar registros nuevos.
* Se deben actualizar registros existentes.
* Se debe mantener identificador del sistema origen.
* Si hay diferencia entre sistema anterior y sistema nuevo, manda el sistema anterior.
* Debe existir reporte básico de importación.
* Debe haber control básico de duplicados.
* Deben quedar auditadas las importaciones.

Datos a importar:

* Clientes.
* Choferes.
* Transportistas.
* Productos.
* Remitos.
* Saldos.

Campos técnicos sugeridos para entidades importadas:

* source_system.
* source_id.
* imported_at.
* updated_from_source_at.
* last_import_batch_id.

---

## 9.12 Backup automático

Implementar backup automático diario de MySQL en lo posible.

Primera etapa:

* Backup diario local en servidor.
* Copia adicional configurable en otra PC.
* Registro de fecha/hora de último backup.
* Opción de ejecutar backup manual desde administrador.

Nube queda para etapa futura.

---

# 10. Alcance fuera de esta etapa

No incluir en esta primera etapa:

* Portal web para clientes.
* Carga de pedidos desde internet.
* Aprobación de pedidos.
* Sincronización con nube.
* Manejo avanzado de stock.
* Integración automática con balanza.
* Facturación electrónica.
* Liquidación completa de compra de mandioca.
* Cuenta corriente avanzada de transportistas.
* Liquidación de viajes.
* Rendición avanzada de choferes o transportistas.
* Tableros gerenciales avanzados.
* Automatización bancaria.
* Aplicación móvil.
* Envío automático externo de alertas por WhatsApp/email.
* Importación histórica completa con depuración avanzada.

---

# 11. Plan de entregas

## Entrega 1 — Día 15

Objetivo: permitir comenzar con la carga de datos reales.

Debe incluir:

* Estructura base del proyecto.
* Configuración MySQL.
* Peewee models base.
* Login.
* Menú lateral.
* Dashboard inicial.
* Usuarios.
* Perfiles.
* Permisos básicos por menú.
* Auditoría básica.
* Clientes.
* Domicilios.
* Productos.
* Choferes.
* Transportistas.
* Camiones.
* Tipos/detalles base de pallets.
* Backup básico.

Resultado esperado:

FEMAG puede empezar a cargar clientes, domicilios, productos, choferes, transportistas, camiones y datos base.

---

## Entrega 2 — Día 30

Objetivo: comenzar con operaciones de despacho.

Debe incluir:

* Órdenes de carga.
* Detalle de productos por orden.
* Detalle de pallets por orden.
* Bloqueo de chofer con carga activa.
* Estados de orden.
* Consulta de órdenes.
* Impresión de orden.
* Hoja resumen/sobre impresa junto con la orden.
* Auditoría de cambios.

Resultado esperado:

FEMAG puede registrar y emitir órdenes de carga.

---

## Entrega 3 — Día 45

Objetivo: documentar remitos y generar F150.

Debe incluir:

* Registro manual de remitos.
* Numeración existente.
* Consulta de remitos.
* Reimpresión.
* Anulación con clave de administrador.
* Selección de remitos para F150.
* Generación de archivo F150.
* Historial de lotes F150.
* Control de remitos ya incluidos en F150.

Resultado esperado:

FEMAG puede registrar remitos, consultarlos, imprimirlos y generar archivo F150 por lote.

---

## Entrega 4 — Día 60

Objetivo: administración, cuenta corriente e importación.

Debe incluir:

* Cuenta corriente básica multimoneda.
* Saldos iniciales.
* Cambio de saldo inicial con clave de administrador.
* Pagos contra saldo general.
* Recibos numerados.
* Anulación de pagos con clave de administrador.
* Consulta de pagos anulados.
* Importación incremental básica desde MySQL y DBF.
* Reporte básico de importación.
* Instalación final en hasta 6 puestos.
* Capacitación.
* Ajustes finales.

Resultado esperado:

Sistema operativo completo para la Fase 1.

---

# 12. Issues de GitHub a crear

Crear los siguientes issues iniciales.

---

## Issue 1 — Inicializar proyecto desktop FEMAG

Título:

`Inicializar estructura base del proyecto FEMAG Desktop`

Descripción:

Crear la estructura inicial del proyecto Python de escritorio para FEMAG.

Alcance:

* Crear estructura de carpetas.
* Configurar entorno Python.
* Definir dependencias base.
* Preparar configuración para MySQL.
* Preparar integración con Peewee.
* Agregar README inicial.
* Agregar archivo `.env.example`.
* Agregar configuración de logging.
* Agregar estructura para tests.

Criterios de aceptación:

* El proyecto instala dependencias correctamente.
* Existe README con instrucciones iniciales.
* Existe configuración separada para desarrollo/producción.
* Existe conexión base a MySQL configurable por entorno.
* Existe estructura inicial para módulos UI, modelos, servicios y reportes.

Rama sugerida:

`feature/bootstrap-project`

---

## Issue 2 — Crear modelos base MySQL/Peewee

Título:

`Crear modelos base de datos con Peewee`

Descripción:

Definir modelos iniciales de base de datos.

Modelos mínimos:

* User.
* Role/Profile.
* Permission.
* MenuItem.
* AuditLog.
* Client.
* ClientAddress.
* Product.
* Driver.
* Carrier.
* Truck.
* PalletType.
* AppParameter.
* NumberSequence.
* ImportBatch.
* BackupLog.

Criterios de aceptación:

* Los modelos se crean con Peewee.
* Las tablas pueden crearse en MySQL.
* Existen índices básicos.
* Existen campos de auditoría técnica cuando corresponda.
* Existe comando/script para inicializar la base.

Rama sugerida:

`feature/base-models`

---

## Issue 3 — Login, usuarios, perfiles y permisos

Título:

`Implementar login, perfiles y permisos por menú/acción`

Descripción:

Implementar autenticación local y control de permisos.

Perfiles iniciales:

* Administrador.
* Secretaría.
* Administración.
* Solo consulta.

Funcionalidad:

* Login.
* Gestión básica de usuarios.
* Gestión de perfiles.
* Permisos por menú.
* Permisos por acción: ver, crear, modificar, anular, eliminar, imprimir, reimprimir, importar, configurar.
* Validación de clave de administrador para acciones sensibles.

Acciones sensibles:

* Anular remito.
* Modificar pago.
* Anular pago.
* Cambiar saldo inicial.

Criterios de aceptación:

* Un usuario solo ve las opciones permitidas.
* Las acciones sensibles solicitan clave de administrador.
* La reimpresión no solicita clave.
* Los cambios de permisos quedan auditados.

Rama sugerida:

`feature/auth-permissions`

---

## Issue 4 — Menú lateral y dashboard inicial

Título:

`Implementar menú lateral y dashboard central`

Descripción:

Crear la estructura principal de navegación del sistema.

Menú lateral:

* Inicio.
* Operaciones.
* Cuenta corriente.
* Maestros.
* Importación.
* Sistema.

Dashboard:

* Órdenes del día.
* Remitos del día.
* Pagos del día.
* Clientes con saldo.
* Pendientes.
* Accesos rápidos.

Botones grandes:

* Nueva orden de carga.
* Nuevo remito.
* Registrar pago.
* Buscar cliente.
* Buscar remito.
* Generar F150.
* Cuenta corriente.

Criterios de aceptación:

* El menú lateral se muestra según permisos.
* El dashboard carga sin errores.
* Los accesos rápidos abren las pantallas correspondientes.
* El diseño es simple y apto para uso administrativo.

Rama sugerida:

`feature/main-menu-dashboard`

---

## Issue 5 — Auditoría básica

Título:

`Implementar auditoría básica de operaciones`

Descripción:

Crear un servicio centralizado de auditoría para registrar operaciones relevantes.

Registrar:

* Usuario.
* Fecha/hora.
* Módulo.
* Acción.
* Registro afectado.
* Valor anterior.
* Valor nuevo.
* Observación.
* Equipo/IP si está disponible.

Auditar:

* Altas.
* Modificaciones.
* Anulaciones.
* Eliminaciones.
* Cambio de saldo inicial.
* Modificación/anulación de pagos.
* Anulación de remitos.
* Generación de F150.
* Importaciones.
* Cambios de permisos.
* Cambios de numeración.
* Backups manuales.

Criterios de aceptación:

* Existe tabla de auditoría.
* Existe servicio reutilizable para registrar auditoría.
* Las acciones principales pueden llamar al servicio.
* Existe pantalla básica de consulta para administrador.

Rama sugerida:

`feature/audit-log`

---

## Issue 6 — Maestros: clientes y domicilios

Título:

`Implementar ABM de clientes y domicilios`

Descripción:

Crear pantallas de clientes y domicilios.

Cliente:

* Razón social / nombre.
* CUIT.
* Condición IVA.
* Teléfono.
* Email.
* Contacto.
* Estado.

Domicilios:

* Domicilio fiscal.
* Domicilios de entrega múltiples.
* Provincia.
* Localidad.
* Dirección.
* Principal sí/no.
* Observaciones.

Reglas:

* Un cliente puede tener varios domicilios de entrega.
* Un cliente puede tener un domicilio fiscal.
* Un cliente puede tener un domicilio de entrega principal.

Criterios de aceptación:

* Se puede crear, consultar y editar clientes según permisos.
* Se pueden administrar domicilios.
* Se puede marcar un domicilio de entrega principal.
* Las modificaciones quedan auditadas.

Rama sugerida:

`feature/clients-addresses`

---

## Issue 7 — Maestros: productos, choferes, transportistas, camiones y pallets

Título:

`Implementar maestros operativos`

Descripción:

Crear ABMs para:

* Productos.
* Choferes.
* Transportistas.
* Camiones.
* Tipos de pallets.

Producto:

* Nombre.
* Unidad.
* Estado.

Chofer:

* Nombre.
* Documento si corresponde.
* Teléfono.
* Estado.
* Estado de disponibilidad.

Transportista:

* Nombre/razón social.
* CUIT si corresponde.
* Teléfono.
* Estado.

Camión:

* Dominio/patente.
* Transportista asociado opcional.
* Estado.

Pallet:

* Tipo.
* Medida.
* Peso.
* Estado.

Criterios de aceptación:

* Todos los maestros pueden cargarse y consultarse.
* Se respetan permisos.
* Las modificaciones quedan auditadas.
* Los datos quedan disponibles para órdenes y remitos.

Rama sugerida:

`feature/operational-masters`

---

## Issue 8 — Órdenes de carga

Título:

`Implementar módulo de órdenes de carga`

Descripción:

Crear módulo para registrar órdenes de carga.

Reglas:

* Una orden corresponde a un camión y un chofer.
* Una orden puede tener más de un producto.
* Una orden puede tener detalle de pallets.
* Una orden no se divide en más de un camión.
* El chofer se bloquea mientras tenga carga activa.

Cabecera:

* Número.
* Fecha.
* Cliente.
* Domicilio de entrega.
* Transportista.
* Chofer.
* Camión.
* Estado.
* Observaciones.

Detalle productos:

* Producto.
* Cantidad.
* Unidad.
* Observaciones.

Detalle pallets:

* Tipo.
* Medida.
* Peso.
* Cantidad.

Criterios de aceptación:

* Se puede crear orden de carga.
* Se puede cargar destino general.
* Se pueden agregar varios renglones de despacho.
* Cada renglón puede tener destinatario/localidad diferente, cantidades por presentación, lote y fecha de elaboración.
* No se permite asignar chofer bloqueado.
* Al crear carga activa, el chofer queda bloqueado.
* Se puede cerrar/anular según permisos.
* Las operaciones quedan auditadas.

Rama sugerida:

`feature/load-orders`

---

## Issue 9 — Impresión de orden y hoja resumen

Título:

`Implementar impresión de orden de carga y hoja resumen`

Descripción:

Crear reportes/imprimibles en hoja A4.

Requisitos:

* Orden de carga en A4.
* Hoja resumen/sobre en A4.
* La hoja resumen debe imprimirse junto con la orden.
* Debe permitir reimpresión sin clave de administrador.

Criterios de aceptación:

* Se genera documento imprimible de orden.
* Se genera hoja resumen.
* Desde la orden se puede imprimir ambas.
* La reimpresión no solicita clave.
* Queda registro de impresión/reimpresión si corresponde.

Rama sugerida:

`feature/load-order-printing`

---

## Issue 10 — Remitos manuales

Título:

`Implementar registro manual de remitos`

Descripción:

Crear módulo de remitos.

Reglas:

* Los remitos se cargan manualmente.
* Deben respetar numeración existente.
* Son independientes de la orden de carga.
* Pueden vincularse opcionalmente a una orden.
* No impactan automáticamente en cuenta corriente.

Campos mínimos:

* Número de remito.
* Fecha.
* Cliente.
* Detalle de productos.
* Transportista opcional.
* Chofer opcional.
* Camión opcional.
* Orden vinculada opcional.
* Estado.
* Observaciones.

Criterios de aceptación:

* Se puede registrar remito manual.
* Se puede consultar remito.
* Se puede reimprimir.
* Se puede anular con clave de administrador.
* La anulación queda auditada.
* No genera automáticamente movimiento de cuenta corriente.

Rama sugerida:

`feature/manual-remittances`

---

## Issue 11 — F150 por lote de remitos

Título:

`Implementar generación de archivo F150 por lote de remitos`

Descripción:

Crear módulo para generar archivo F150 seleccionando remitos.

Requisitos:

* Filtro de remitos.
* Selección múltiple.
* Validación de remitos seleccionados.
* Generación de archivo.
* Registro de lote F150.
* Historial de lotes.
* Marcar remitos incluidos en F150.
* Evitar duplicados accidentales.

Filtros:

* Fecha desde/hasta.
* Cliente.
* Número de remito.
* Estado.
* Incluido/no incluido en F150.

Criterios de aceptación:

* Se pueden seleccionar remitos.
* Se genera archivo F150.
* Se registra lote generado.
* Se marcan remitos como incluidos.
* Se puede consultar historial.
* La generación queda auditada.

Rama sugerida:

`feature/f150-batches`

---

## Issue 12 — Cuenta corriente multimoneda

Título:

`Implementar cuenta corriente básica multimoneda de clientes`

Descripción:

Crear módulo de cuenta corriente para clientes.

Reglas:

* Cuenta corriente por cliente.
* Multimoneda.
* Pagos contra saldo general.
* No aplica pagos a remitos específicos.
* Saldos por cliente y moneda.
* Saldo inicial editable solo con clave de administrador.

Movimientos:

* Cliente.
* Fecha.
* Moneda.
* Tipo: débito/crédito.
* Concepto.
* Importe.
* Referencia.
* Estado.
* Observaciones.

Criterios de aceptación:

* Se puede consultar cuenta corriente por cliente.
* Se puede consultar saldo por moneda.
* Se puede cargar saldo inicial con permiso.
* Cambiar saldo inicial pide clave de administrador.
* Los movimientos quedan auditados.

Rama sugerida:

`feature/customer-accounts`

---

## Issue 13 — Pagos y recibos

Título:

`Implementar pagos manuales y recibos numerados`

Descripción:

Crear módulo de pagos y recibos.

Medios de pago:

* Efectivo.
* Transferencia.
* Cheque.
* Otros.

Reglas:

* El pago baja saldo general del cliente.
* El recibo tiene numeración propia.
* Se puede anular pago con clave de administrador.
* Toda anulación queda auditada.
* Los pagos anulados deben verse en consulta del administrador o pendientes.

Campos:

* Cliente.
* Fecha.
* Moneda.
* Importe.
* Medio de pago.
* Número de recibo.
* Observaciones.
* Estado.
* Usuario.

Criterios de aceptación:

* Se puede registrar pago.
* Se genera número de recibo.
* Se puede imprimir recibo.
* Se puede anular con clave de administrador.
* La anulación ajusta la cuenta corriente.
* La anulación queda visible para administrador.

Rama sugerida:

`feature/payments-receipts`

---

## Issue 14 — Importación incremental MySQL/DBF

Título:

`Implementar importación incremental desde sistema anterior MySQL y DBF`

Descripción:

Crear sistema de importación incremental.

Fuentes:

* MySQL anterior.
* DBF.

Datos:

* Clientes.
* Choferes.
* Transportistas.
* Productos.
* Remitos.
* Saldos.

Reglas:

* La importación puede ejecutarse varias veces.
* Agrega registros nuevos.
* Actualiza registros existentes.
* Si hay diferencia, manda sistema anterior.
* Control básico de duplicados.
* Reporte de importación.
* Auditoría de importación.

Campos técnicos:

* source_system.
* source_id.
* imported_at.
* updated_from_source_at.
* last_import_batch_id.

Criterios de aceptación:

* Se puede ejecutar importación por entidad.
* Se genera reporte básico.
* Se registran altas/actualizaciones.
* Se puede identificar origen de cada registro.
* Las importaciones quedan auditadas.

Rama sugerida:

`feature/incremental-imports`

---

## Issue 15 — Backups automáticos

Título:

`Implementar backup automático diario de MySQL`

Descripción:

Crear mecanismo básico de backup.

Requisitos:

* Backup diario en servidor.
* Carpeta adicional configurable para copia en otra PC.
* Registro de último backup.
* Backup manual desde administrador.
* Registro en auditoría para backup manual.

Criterios de aceptación:

* Existe script o servicio de backup.
* Se puede configurar carpeta destino.
* Se registra fecha/hora de backup.
* El administrador puede ejecutar backup manual.
* El estado del último backup se ve en sistema.

Rama sugerida:

`feature/mysql-backups`

---

## Issue 16 — Instalación y empaquetado en puestos

Título:

`Preparar instalación en servidor y puestos de trabajo`

Descripción:

Preparar instalación local.

Requisitos:

* Configuración para servidor MySQL.
* Configuración para cliente escritorio.
* Documentar instalación en hasta 6 puestos.
* Documentar variables de entorno.
* Documentar backups.
* Documentar actualización del sistema.

Criterios de aceptación:

* Existe guía de instalación.
* Existe configuración por puesto.
* La app puede conectarse al servidor MySQL.
* El sistema puede correr en red local.
* La documentación es clara.

Rama sugerida:

`feature/local-installation`

---

## Issue 17 — Tests y validaciones básicas

Título:

`Agregar tests y validaciones funcionales básicas`

Descripción:

Agregar pruebas básicas para modelos y servicios críticos.

Cubrir:

* Permisos.
* Auditoría.
* Bloqueo de chofer.
* Cuenta corriente.
* Anulación de pagos.
* Remitos incluidos en F150.
* Importación incremental.
* Numeraciones.

Criterios de aceptación:

* Hay tests automáticos para servicios principales.
* Los tests pueden ejecutarse localmente.
* README indica cómo correrlos.
* Las reglas críticas tienen cobertura mínima.

Rama sugerida:

`feature/tests-validation`

---

## Issue 18 — Documentación operativa inicial

Título:

`Crear documentación operativa para usuarios`

Descripción:

Crear documentación simple para uso interno.

Documentar:

* Cómo ingresar al sistema.
* Cómo cargar cliente.
* Cómo cargar domicilio.
* Cómo crear orden de carga.
* Cómo imprimir orden/hoja resumen.
* Cómo cargar remito.
* Cómo generar F150.
* Cómo registrar pago.
* Cómo imprimir recibo.
* Cómo consultar cuenta corriente.
* Cómo ejecutar importación.
* Cómo revisar auditoría.
* Cómo revisar backups.

Criterios de aceptación:

* Existe documentación en Markdown.
* Está orientada a usuarios administrativos.
* Usa pasos simples.
* Incluye advertencias sobre acciones sensibles.

Rama sugerida:

`feature/user-docs`

---

# 13. Orden sugerido de trabajo

Prioridad recomendada:

1. Issue 1 — Inicializar proyecto.
2. Issue 2 — Modelos base.
3. Issue 3 — Login/permisos.
4. Issue 5 — Auditoría.
5. Issue 4 — Menú/dashboard.
6. Issue 6 — Clientes/domicilios.
7. Issue 7 — Maestros operativos.
8. Issue 8 — Órdenes de carga.
9. Issue 9 — Impresión orden/hoja resumen.
10. Issue 10 — Remitos.
11. Issue 11 — F150.
12. Issue 12 — Cuenta corriente.
13. Issue 13 — Pagos/recibos.
14. Issue 14 — Importación incremental.
15. Issue 15 — Backups.
16. Issue 16 — Instalación.
17. Issue 17 — Tests.
18. Issue 18 — Documentación.

---

# 14. Rama principal y ramas de trabajo

Usar rama principal:

`main`

Crear ramas por issue con formato:

`feature/<nombre-corto>`

Ejemplos:

* `feature/bootstrap-project`
* `feature/base-models`
* `feature/auth-permissions`
* `feature/audit-log`
* `feature/main-menu-dashboard`
* `feature/clients-addresses`
* `feature/operational-masters`
* `feature/load-orders`
* `feature/load-order-printing`
* `feature/manual-remittances`
* `feature/f150-batches`
* `feature/customer-accounts`
* `feature/payments-receipts`
* `feature/incremental-imports`
* `feature/mysql-backups`
* `feature/local-installation`
* `feature/tests-validation`
* `feature/user-docs`

---

# 15. Criterios generales de aceptación del proyecto

La Fase 1 se considera completa cuando:

* El sistema corre localmente contra MySQL.
* Hay login de usuarios.
* Hay menú lateral.
* Hay dashboard central.
* Los permisos funcionan por perfil/menú/acción.
* Hay auditoría básica.
* Se pueden cargar clientes y domicilios.
* Se pueden cargar productos, choferes, transportistas, camiones y pallets.
* Se pueden registrar órdenes de carga con varios productos y pallets.
* Se bloquea chofer con carga activa.
* Se imprime orden de carga junto con hoja resumen.
* Se pueden registrar remitos manuales.
* Se puede generar F150 por lote de remitos.
* Se puede manejar cuenta corriente básica multimoneda.
* Se pueden registrar pagos y emitir recibos.
* Se pueden anular pagos/remitos con clave de administrador.
* Se puede importar incrementalmente desde MySQL/DBF.
* Hay backup diario básico.
* Hay documentación de instalación y uso.
* El sistema queda listo para instalarse en servidor y hasta 6 puestos.

---

# 16. Notas importantes para Codex

* Mantener el alcance acotado a sistema local.
* No implementar nube.
* No implementar stock avanzado.
* No implementar balanza.
* No implementar facturación electrónica.
* No implementar pedidos web.
* No implementar liquidación completa de transportistas.
* Priorizar simplicidad de uso.
* Priorizar código mantenible.
* Separar UI, modelos, servicios y reportes.
* Evitar lógica de negocio dentro de pantallas si es posible.
* Crear servicios reutilizables para permisos, auditoría, numeraciones, importaciones y cuenta corriente.
* Pensar en operación real con varias secretarias usando el sistema.
* Documentar supuestos técnicos en cada issue si falta información.
