"""Configuracion de gunicorn para el contenedor FEMAG Web (#803)."""

import os

bind = f"0.0.0.0:{os.getenv('FEMAG_WEB_PORT', '8000')}"
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "gthread"
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# Cada worker importa webapp.wsgi y abre su propia conexion. No se precarga la
# app en el master para no compartir sockets de MySQL entre procesos.
preload_app = False
