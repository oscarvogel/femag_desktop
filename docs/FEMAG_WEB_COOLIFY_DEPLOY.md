# FEMAG Web en Coolify — despliegue aislado (#803)

Runbook del issue **#803**. Los artefactos están en el repositorio, pero **el
despliegue en el VPS todavía no se ejecutó**: falta acceso a Coolify, dominio y
credenciales. La arquitectura de referencia está en
[`FEMAG_WEB_ARCHITECTURE.md`](FEMAG_WEB_ARCHITECTURE.md).

## 1. Qué se agrega

| Archivo | Uso |
| --- | --- |
| `deploy/coolify/Dockerfile` | Imagen Linux de la webapp, sin PyQt ni dependencias del escritorio |
| `requirements-container.txt` | `requirements-web.txt` + gunicorn |
| `deploy/coolify/gunicorn.conf.py` | Workers, timeout y logs |
| `deploy/coolify/entrypoint.sh` | Init/seed opcional y arranque de gunicorn |
| `webapp/wsgi.py` | Conexión + validación de esquema antes de atender tráfico |
| `deploy/coolify/docker-compose.demo.yml` | Prueba local con MySQL privado y datos sintéticos |
| `deploy/coolify/demo.env.example` | Variables del entorno demo |
| `scripts/seed_webapp_demo.py` | Admin, maestros y orden demo idempotentes |
| `.dockerignore` | Evita copiar `.env`, tests, `.venv`, builds y documentación |

La imagen **no** contiene credenciales, `.env`, dumps ni datos de fábrica.

## 2. Diferencias con el servidor Windows

| Tema | Windows Server 2019 (fábrica) | Contenedor Coolify |
| --- | --- | --- |
| Servidor WSGI | Waitress | gunicorn (`gthread`) |
| Dependencias | `requirements-web.txt` | `requirements-container.txt` |
| MySQL | Local, misma máquina | Servicio privado del proyecto Coolify |
| URL | `http://192.168.0.111:8000` | HTTPS público |
| Datos | Reales de fábrica | Demo/sintéticos en la primera fase |
| Migraciones | Administrador desde Desktop | Tarea controlada (`scripts/init_db.py`) |

## 3. Prerrequisitos

- VPS con Coolify funcionando y proxy HTTPS.
- Dominio o subdominio apuntando al VPS.
- Acceso a `oscarvogel/femag_desktop` desde Coolify.
- Secretos generados fuera del repositorio.
- Espacio y backup para el volumen de MySQL.
- Ninguna conexión entrante hacia la fábrica.

## 4. Prueba local del contenedor

Requiere Docker y Docker Compose. **Este entorno de desarrollo no tiene Docker
instalado**, así que esta validación queda pendiente de ejecutar en una máquina
con Docker o en CI.

```bash
cd deploy/coolify
cp demo.env.example demo.env
# editar demo.env con claves propias
docker compose --env-file demo.env -f docker-compose.demo.yml up --build
```

Verificar:

```bash
curl -fsS http://localhost:8080/health
curl -fsS http://localhost:8080/login > /dev/null
curl -fsS http://localhost:8080/orden/demo-web-order-2026 > /dev/null
```

Credenciales demo: usuario `demo`, clave `FEMAG_WEB_DEMO_ADMIN_PASSWORD`.
La orden demo se imprime con token `demo-web-order-2026` y dos renglones.

Bajar y borrar el volumen:

```bash
docker compose --env-file demo.env -f docker-compose.demo.yml down -v
```

## 5. Despliegue en Coolify

### 5.1 Proyecto y MySQL

1. Crear un proyecto/entorno **FEMAG Web** aislado de las demás aplicaciones.
2. Crear un servicio MySQL 8.0 dentro del mismo proyecto.
3. Definir base, usuario y clave fuertes. **No publicar el puerto 3306** ni
   crear un proxy TCP para MySQL.
4. Anotar el hostname interno del servicio (Coolify lo asigna en la red del
   proyecto).
5. Configurar backup del volumen de MySQL antes de cargar datos.

### 5.2 Aplicación

1. Nueva aplicación desde el repositorio `oscarvogel/femag_desktop`.
2. Build pack: **Dockerfile**.
3. Dockerfile: `deploy/coolify/Dockerfile`.
4. Base directory: `/`.
5. Puerto expuesto: `8000`.
6. Healthcheck: `GET /health`.
7. Dominio: el que se haya verificado (ver sección 6).
8. TLS: activado por el proxy de Coolify.

Variables mínimas:

| Variable | Obligatoria | Ejemplo / nota |
| --- | --- | --- |
| `FEMAG_DB_ENGINE` | Sí | `mysql` |
| `DB_HOST` | Sí | Hostname interno del servicio MySQL |
| `DB_PORT` | Sí | `3306` |
| `DB_NAME` | Sí | `femag_web` |
| `DB_USER` | Sí | Usuario de la app |
| `DB_PASSWORD` | Sí | Secreto de Coolify |
| `FEMAG_SECURE_CONFIG` | Sí | `0` en Linux |
| `FEMAG_WEB_SECRET_KEY` | Sí | Secreto largo y aleatorio |
| `FEMAG_WEB_PUBLIC_URL` | Sí | `https://dominio` sin slash final |
| `FEMAG_SYNC_API_TOKEN` | No | Token de máquina para `/api/sync/v1`; vacío deshabilita la API |
| `APP_ENV` | Sí | `production` |
| `FEMAG_WEB_AUTO_INIT_SCHEMA` | Demo | `1` solo en demo; producción `0` |
| `FEMAG_WEB_SEED_DEMO` | Demo | `1` solo en demo; producción `0` |
| `FEMAG_DEMO` | Demo | `1` solo en demo; producción `0` |
| `FEMAG_WEB_DEMO_ADMIN_PASSWORD` | Demo | Solo si se carga el seed |
| `GUNICORN_WORKERS` | No | Default `2` |
| `GUNICORN_THREADS` | No | Default `4` |

No commitear valores: cargarlos en la UI de Coolify o en su gestor de secretos.

### 5.3 Esquema y datos

- **Demo:** `FEMAG_WEB_AUTO_INIT_SCHEMA=1` y `FEMAG_WEB_SEED_DEMO=1`. El
  entrypoint crea el esquema y carga el seed sintético.
- **Producción:** `FEMAG_WEB_AUTO_INIT_SCHEMA=0` y `FEMAG_WEB_SEED_DEMO=0`.
  Aplicar el esquema como tarea controlada:

```bash
python scripts/init_db.py
```

Nunca ejecutar el seed demo contra la MySQL de fábrica ni contra datos reales.

### 5.4 Primer smoke

1. `GET /health` debe devolver `{"database": true, "status": "ok"}`.
2. `GET /login` debe renderizar.
3. Si es demo, entrar con el usuario/clave del seed.
4. Abrir `/orden/demo-web-order-2026` y verificar los dos renglones.
5. Confirmar en los logs que no hay excepciones ni secretos impresos.
6. Revisar que MySQL no tenga puerto público.

## 6. Dominio y TLS

- URL provisoria propuesta: `https://femag.186.5.245.12.sslip.io`. **No está
  verificada** y no debe usarse para QR masivos.
- Dominio definitivo recomendado: `portal.femag.com.ar`.
- Antes de operar con datos reales:
  - DNS resuelve al VPS;
  - certificado válido y renovación automática;
  - redirección HTTP→HTTPS;
  - `/health` responde por HTTPS desde fuera de la red del VPS.
- Al migrar de dominio, mantener el anterior como alias y redirigir
  preservando `/orden/<token>` (ver arquitectura, sección 11).

## 7. Backup y restore

Backup lógico propuesto:

```bash
mysqldump --single-transaction --routines --triggers \
  -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" > femag_web_$(date +%Y%m%d_%H%M).sql
```

- Programar backup diario y verificar el archivo.
- Guardar al menos 30 días (propuesta de la arquitectura).
- Probar el restore en un entorno demo antes de confiar en el backup.
- No subir dumps al repositorio (`*.sql` está ignorado por git).

Restore de prueba:

```bash
mysql -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" < backup.sql
```

## 8. Rollback

| Falla | Acción |
| --- | --- |
| Imagen nueva rota | Redeploy de la imagen anterior desde Coolify |
| Esquema incompatible | Restaurar backup y volver a la versión anterior |
| MySQL no responde | Restaurar servicio/volumen; la fábrica sigue operando |
| Dominio/TLS roto | Volver al dominio anterior mientras se corrige |
| Datos demo contaminados | Bajar la app, borrar volumen demo y recrear |

Regla: ningún rollback de la nube debe requerir tocar la MySQL de fábrica.

## 9. Seguridad operativa

- [ ] MySQL sin puerto público.
- [ ] `FEMAG_WEB_SECRET_KEY` fuera de git y rotable.
- [ ] Credenciales de DB en Coolify, no en la imagen.
- [ ] `FEMAG_WEB_ALLOW_DEMO_SEED` ausente y `FEMAG_WEB_SEED_DEMO=0` en producción.
- [ ] HTTPS obligatorio y HTTP redirigido.
- [ ] Logs sin tokens, claves ni datos personales innecesarios.
- [ ] Backup probado.
- [ ] Endpoints de diagnóstico restringidos.
- [ ] Acceso a Coolify con MFA.

## 10. Pendientes reales de #803

- [ ] Ejecutar el build del contenedor en una máquina con Docker o en CI.
- [ ] Crear proyecto y MySQL privada en Coolify.
- [ ] Cargar secretos y variables.
- [ ] Registrar el dominio realmente y validar TLS.
- [ ] Verificar que MySQL no sea alcanzable desde Internet.
- [ ] Probar `/health`, login y QR demo desde un celular externo.
- [ ] Probar backup y restore.
- [ ] Documentar el `source_sha` y la versión desplegada.
- [ ] Recién después avanzar a #804/#805 con sync y datos reales.
