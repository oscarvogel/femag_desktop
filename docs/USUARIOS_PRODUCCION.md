# Gestión de usuarios en producción

## Primer inicio

1. Ejecutar `python scripts/init_db.py` en la base de FEMAG.
2. Crear el primer administrador con:

   ```bash
   python scripts/create_admin_user.py admin <clave>
   ```

   También se puede utilizar **Crear administrador inicial** desde la pantalla de login
   cuando la base todavía no tiene usuarios.
3. Ingresar con el administrador y abrir **Sistema → Usuarios**.
4. Crear los usuarios operativos, asignarles un perfil y dejarlos habilitados únicamente
   cuando estén listos para ingresar.

## Operación diaria

- **Editar** modifica el nombre visible, el usuario, el perfil y el estado.
- **Habilitar / deshabilitar** realiza una baja lógica. Los usuarios con operaciones
  históricas no se eliminan físicamente.
- **Restablecer contraseña** permite a un administrador generar una nueva contraseña para
  otro usuario. La contraseña no se muestra ni se guarda en texto plano.
- Cada usuario puede utilizar **Cambiar clave** en la barra superior para cambiar su propia
  contraseña.
- **Cerrar sesión** termina la sesión actual y vuelve a mostrar el login.

## Perfiles y permisos

La pestaña **Perfiles y permisos** muestra la matriz por módulo, pantalla y acción. Solo un
administrador habilitado puede guardar cambios. Las modificaciones quedan auditadas con
usuario, fecha/hora, perfil, pantalla, acción y valor anterior/nuevo.

Los perfiles integrados son exactamente **Administrador**, **Secretaría**,
**Administración** y **Solo consulta**. Al iniciar el sistema, los nombres históricos sin
tilde (`Secretaria` y `Administracion`) se normalizan y sus usuarios y permisos se
consolidan en el perfil oficial correspondiente.

La ausencia de un permiso explícito se interpreta como denegación. Ocultar un botón no es la
única protección: las operaciones sensibles también deben rechazar la acción desde el servicio
que las ejecuta.

## Regla del último administrador

El sistema impide deshabilitar al último administrador habilitado o quitarle el perfil de
Administrador. Crear otro administrador antes de realizar ese cambio.
