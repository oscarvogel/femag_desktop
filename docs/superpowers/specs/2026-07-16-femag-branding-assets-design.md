# Diseño — identidad visual FEMAG en aplicación e instaladores

**Fecha:** 2026-07-16
**Issue:** #190
**Decisión aprobada:** enfoque 1, familia de assets fiel al original y composición equilibrada.

## Objetivo

Adoptar la imagen provista por el usuario como fuente oficial de marca de FEMAG Desktop. La identidad debe verse de manera consistente en el inicio de sesión, la pantalla de trabajo, la ventana de la aplicación, el ejecutable, los accesos directos y el instalador DEMO. El mismo contrato debe quedar listo para el futuro instalador productivo.

## Alcance

### Incluido

- Versionar la imagen original sin alteraciones como fuente oficial.
- Generar derivados raster optimizados sin redibujar ni reinterpretar la marca.
- Crear un icono Windows `.ico` multirresolución.
- Mostrar el logo completo y protagonista en el login.
- Mostrar una versión compacta en el sector lateral de la pantalla de trabajo.
- Mostrar una firma discreta en la cabecera de la pantalla de trabajo.
- Aplicar el icono a `QApplication`, ventanas, PyInstaller, Inno Setup y accesos directos del instalador DEMO.
- Centralizar la resolución de rutas para ejecución desde el repositorio y desde un bundle PyInstaller.
- Dejar nombres de asset neutros, reutilizables por el futuro instalador productivo.
- Incorporar tests de contrato y evidencia visual de login y pantalla de trabajo.

### Fuera de alcance

- Redibujar o vectorizar el logo.
- Cambiar colores, tipografía o proporciones de la marca.
- Rediseñar por completo el login, sidebar, topbar o dashboard.
- Crear el instalador productivo futuro.
- Modificar lógica de negocio, modelos, migraciones, datos o integraciones legacy.

## Familia de assets

La fuente oficial se guardará en `app/ui/assets/branding/` con un nombre estable. A partir de ella se producirán:

- `femag-logo-source.png`: copia exacta del original entregado.
- `femag-logo-ui.png`: versión optimizada para login y firma de cabecera, conservando composición y colores.
- `femag-logo-compact.png`: derivado cuadrado optimizado para el espacio lateral, sin deformación.
- `femag.ico`: contenedor multirresolución para Windows, con tamaños de 16, 24, 32, 48, 64, 128 y 256 píxeles cuando la herramienta lo soporte.

Los derivados deben mantener la relación de aspecto. Si el logo completo no resulta legible en los tamaños mínimos del `.ico`, se utilizará la imagen cuadrada original completa como icono, priorizando fidelidad sobre una reconstrucción no autorizada.

## Integración en tiempo de ejecución

Se agregará una utilidad pequeña y aislada para resolver assets de marca. La utilidad tendrá dos responsabilidades:

1. Resolver la ruta desde el checkout normal.
2. Resolver la ruta desde el directorio temporal de PyInstaller (`sys._MEIPASS`) cuando corresponda.

La carga visual será defensiva: un asset ausente no impedirá que la aplicación arranque. En ese caso se conservarán el título y textos actuales, y el test de empaquetado será el encargado de impedir que un instalador se publique sin los archivos requeridos.

## Login

El logo completo aparecerá centrado en la parte superior del formulario, antes del título y del subtítulo. Se conservarán los campos, mensajes, credenciales demo, acciones y comportamiento actual. El tamaño se adaptará al ancho disponible sin estirar la imagen, y tendrá texto alternativo accesible mediante `accessibleName`.

## Pantalla de trabajo

La composición equilibrada tendrá dos apariciones:

- Una marca compacta en la parte superior del lateral, integrada con el ancho existente del sidebar.
- Una firma discreta en la cabecera, sin desplazar la búsqueda global, los controles ni la información del usuario.

No se agregará una marca de agua sobre tablas o contenido operativo. El logo no deberá competir visualmente con títulos, métricas ni acciones de trabajo.

## Icono de aplicación e instaladores

- `QApplication` recibirá `femag.ico` como icono global antes de crear las ventanas.
- Login y ventana principal heredarán el icono global; se podrá establecer explícitamente si los tests de plataforma lo requieren.
- El spec de PyInstaller incluirá los assets de branding y usará `femag.ico` como icono del ejecutable.
- Inno Setup usará el mismo archivo como icono del instalador y de los accesos directos.
- La configuración quedará expresada con rutas y nombres neutrales para que el futuro instalador productivo reutilice el contrato sin duplicar assets.

## Validación

### Automatizada

- Test de existencia y formato de la familia de assets.
- Test de tamaños incluidos en el `.ico`.
- Test de resolución de rutas en modo checkout y modo PyInstaller simulado.
- Tests UI que verifiquen presencia, `objectName`, pixmap válido y accesibilidad del logo en login y pantalla de trabajo.
- Tests de contrato para PyInstaller e Inno Setup.
- Suite completa con `python -m pytest`.
- `python -m compileall app`.
- `python -m app.main --smoke`.
- `git diff --check`.

### Visual

- Captura del login con el logo completo.
- Captura de la pantalla de trabajo con marca lateral y firma de cabecera.
- Revisión a tamaños de pantalla representativos para confirmar que no hay recortes ni solapamientos.
- Inspección del icono en ventana y acceso directo cuando el entorno Windows permita compilar el instalador.

## Riesgos y mitigaciones

- **Pérdida de legibilidad en tamaños pequeños:** generar `.ico` multirresolución y revisar 16, 32 y 48 píxeles.
- **Deformación de marca:** escalar siempre conservando relación de aspecto.
- **Rutas rotas en el ejecutable:** centralizar la resolución y cubrir `_MEIPASS` con tests.
- **Regresión de layout:** limitar los cambios a contenedores existentes y generar evidencia visual.
- **Ausencia del compilador Inno:** validar contratos por tests y declarar explícitamente si no se puede producir un instalador real en esta máquina.

## Criterio de terminado

El trabajo estará terminado cuando la familia de assets esté versionada, login y pantalla de trabajo muestren la composición aprobada, el icono se aplique a aplicación y cadena de empaquetado DEMO, las rutas funcionen dentro y fuera de PyInstaller, las validaciones aplicables pasen y el PR incluya evidencia y pendientes reales. El futuro instalador productivo queda preparado para reutilizar el contrato, pero su creación no forma parte de este issue.
