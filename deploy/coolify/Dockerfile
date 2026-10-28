# FEMAG Web - imagen Linux para Coolify (#803).
#
# Solo webapp: no instala PyQt ni dependencias del escritorio. La base MySQL
# corre como servicio aparte, privado, en el mismo proyecto de Coolify.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    FEMAG_DB_ENGINE=mysql \
    FEMAG_SECURE_CONFIG=0 \
    FEMAG_WEB_HOST=0.0.0.0 \
    FEMAG_WEB_PORT=8000

WORKDIR /app

RUN groupadd --system femag \
    && useradd --system --gid femag --create-home femag

COPY requirements-web.txt requirements-container.txt ./
RUN python -m pip install --no-cache-dir -r requirements-container.txt

COPY app ./app
COPY webapp ./webapp
COPY scripts/init_db.py scripts/seed_webapp_demo.py ./scripts/
COPY deploy/coolify/entrypoint.sh deploy/coolify/gunicorn.conf.py ./deploy/coolify/

RUN chmod +x ./deploy/coolify/entrypoint.sh \
    && chown -R femag:femag /app

USER femag

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/app/deploy/coolify/entrypoint.sh"]
