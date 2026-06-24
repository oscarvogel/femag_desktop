# FEMAG Desktop

Sistema de gestion operativa local para FEMAG, fabrica de fecula de mandioca en Misiones, Argentina.

El proyecto apunta a ordenar la operatoria administrativa y de despacho con una aplicacion de escritorio usada en red interna, conectada a una base de datos MySQL alojada en el servidor de la fabrica.

## Alcance inicial

La fase 1 cubre:

- Clientes, domicilios fiscales y domicilios de entrega.
- Productos, choferes, transportistas, camiones y pallets.
- Ordenes de carga.
- Remitos manuales.
- Generacion de archivo F150 para Rentas.
- Cuenta corriente basica multimoneda de clientes.
- Registro de pagos y recibos numerados.
- Importacion incremental desde sistemas anteriores MySQL y DBF.
- Usuarios, perfiles y permisos por menu/accion.
- Auditoria basica desde el inicio.
- Backup automatico diario de MySQL.
- Dashboard central y menu lateral simple.

Fuera de esta etapa quedan nube, portal web, pedidos online, stock avanzado, balanza, facturacion electronica, aplicacion movil y automatizaciones externas de WhatsApp/email.

## Stack tecnico

- Python 3.
- PyQt5 como binding Qt.
- `pyqt5libs` como libreria reutilizable de interfaz para ABM, tablas, botones, formularios y vistas.
- MySQL como base de datos central.
- Peewee como ORM.
- Reportes imprimibles en HTML A4 o formato apto para impresion.
- Arquitectura local para 5/6 puestos en red interna.

## Principios de producto

- Uso simple para personal administrativo.
- Menu lateral fijo y dashboard al iniciar.
- Botones grandes para acciones frecuentes.
- Formularios claros, con pocos campos obligatorios.
- Busqueda rapida y reimpresion facil.
- Permisos por usuario, perfil, menu y accion.
- Auditoria de acciones sensibles.
- Servicios reutilizables para permisos, auditoria, numeraciones, importaciones, backups y cuenta corriente.
- Logica de negocio separada de las pantallas.

## Entregas previstas

### Entrega 1 - Dia 15

Base del proyecto, MySQL, Peewee, login, menu lateral, dashboard, usuarios, perfiles, permisos, auditoria, maestros iniciales y backup basico.

### Entrega 2 - Dia 30

Ordenes de carga, detalle de productos y pallets, bloqueo de chofer con carga activa, estados, consulta e impresion de orden y hoja resumen.

### Entrega 3 - Dia 45

Remitos manuales, numeracion existente, consulta, reimpresion, anulacion con clave de administrador, generacion de archivo F150 e historial de lotes.

### Entrega 4 - Dia 60

Cuenta corriente multimoneda, saldos iniciales, pagos, recibos, anulacion de pagos, importacion incremental, instalacion en puestos, capacitacion y ajustes finales.

## Backlog inicial

El backlog inicial se organiza en issues de GitHub y ramas `feature/<nombre-corto>`:

1. `feature/bootstrap-project` - Inicializar estructura base del proyecto.
2. `feature/base-models` - Crear modelos base MySQL/Peewee.
3. `feature/auth-permissions` - Login, usuarios, perfiles y permisos.
4. `feature/main-menu-dashboard` - Menu lateral y dashboard central.
5. `feature/audit-log` - Auditoria basica.
6. `feature/clients-addresses` - Clientes y domicilios.
7. `feature/operational-masters` - Productos, choferes, transportistas, camiones y pallets.
8. `feature/load-orders` - Ordenes de carga.
9. `feature/load-order-printing` - Impresion de orden y hoja resumen.
10. `feature/manual-remittances` - Remitos manuales.
11. `feature/f150-batches` - F150 por lote de remitos.
12. `feature/customer-accounts` - Cuenta corriente multimoneda.
13. `feature/payments-receipts` - Pagos y recibos.
14. `feature/incremental-imports` - Importacion incremental MySQL/DBF.
15. `feature/mysql-backups` - Backups automaticos.
16. `feature/local-installation` - Instalacion en servidor y puestos.
17. `feature/tests-validation` - Tests y validaciones basicas.
18. `feature/user-docs` - Documentacion operativa inicial.

## Configuracion inicial esperada

El proyecto debe incorporar en los primeros issues:

- `.env.example` con variables de conexion MySQL y modo de ejecucion.
- Configuracion separada para desarrollo y produccion.
- Logging de aplicacion.
- Estructura de carpetas para UI, modelos, servicios, reportes, importaciones, backups y tests.
- Script o comando para inicializar la base de datos.

## Estado del proyecto

Entrega 1 completada y Entrega 2 en implementacion: ordenes de carga, bloqueo de chofer, dashboard operativo e impresion HTML A4. La fuente de planificacion general es `plan_implementacion.md`.

## Puesta en marcha tecnica

1. Crear y activar un entorno virtual de Python.
2. Instalar dependencias:

```bash
pip install -r requirements.txt
```

FEMAG Desktop usa PyQt5 para la interfaz grafica. La UI funcional debe apoyarse en `pyqt5libs` para ABM, tablas, botones, formularios y vistas reutilizables.

`pyqt5libs` es una dependencia externa del proyecto FEMAG y se instala desde [oscarvogel/pyqt5libs](https://github.com/oscarvogel/pyqt5libs). No se modifica dentro de este repositorio. Si hace falta mejorar el ABM generico o componentes reutilizables, ese cambio corresponde al repo `oscarvogel/pyqt5libs`, no a `femag_desktop`.

3. Copiar `.env.example` a `.env` y completar los datos de MySQL.
4. Crear tablas iniciales:

```bash
python scripts/init_db.py
```

5. Crear usuario administrador:

```bash
python scripts/create_admin_user.py admin <clave>
```

## Validaciones

Antes de cerrar cambios ejecutar:

```bash
python -m pytest
python -m compileall app
python -m app.main --smoke
```

El smoke test valida que la base UI apunte a `pyqt5libs`, pero no importa componentes graficos pesados ni abre ventanas. Esto permite ejecutar validaciones en entornos headless aunque la libreria privada todavia no este instalada.

## Ejecucion de la UI de escritorio

Para abrir una ventana real de FEMAG Desktop en una sesion de workstation con la configuracion local:

```bash
py -3.12 -m app.main --ui
```

Para revisiones visuales sin depender de MySQL ni crear datos productivos, usar la pantalla demo aprobada:

```bash
py -3.12 -m app.main --demo-ui
```

La ventana usa el titulo `FEMAG Desktop` para que herramientas de validacion visual como Computer Use puedan detectarla. El modo demo abre el dashboard aprobado con usuario `demo_visual`, menu lateral plano, buscador superior y contadores vacios.

El comando headless de smoke sigue siendo:

```bash
py -3.12 -m app.main --smoke
```

## Ordenes de carga

La Entrega 2 agrega modelos y servicios para:

- Cabecera de orden con cliente, domicilio, transportista, chofer, camion, estado y auditoria de usuarios.
- Detalle de productos por orden.
- Detalle de pallets por orden.
- Bloqueo de chofer mientras tenga una orden pendiente o emitida.
- Liberacion de chofer al cerrar o anular la orden.
- Impresion y reimpresion HTML A4 de orden, hoja resumen y salida conjunta.

La logica vive en servicios (`LoadOrderService`, `DriverAvailabilityService`, `LoadOrderPrintService`) y la UI declara su contrato en `app/ui/load_orders.py` sobre la base local `app/ui/abm.py` orientada a `pyqt5libs`.

La guia operativa esta en `docs/guia_usuario_entrega_2.md`.

## Backups

El backup manual se ejecuta con:

```bash
python scripts/run_backup.py --user admin
```

`BACKUP_DIR` define la carpeta principal y `BACKUP_EXTRA_DIR` permite una copia adicional en otra PC o recurso compartido.
