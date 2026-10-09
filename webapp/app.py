from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_file, url_for

from app.config.database import database_proxy
from webapp.order_service import (
    InvalidQrPayloadError,
    OrderNotFoundError,
    OrderUnavailableError,
    get_order_by_token,
    normalize_qr_token,
    order_line_context,
    order_lines,
    update_order_line,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "femag-local-webapp"

    @app.get("/manifest.webmanifest")
    def manifest():
        response = jsonify(
            {
                "name": "FEMAG · Despachos",
                "short_name": "FEMAG",
                "description": "Lectura de órdenes QR y registro operativo de despacho FEMAG.",
                "start_url": "/",
                "scope": "/",
                "display": "standalone",
                "background_color": "#f3f5f7",
                "theme_color": "#17324d",
                "icons": [
                    {
                        "src": "/pwa/icon-192.png",
                        "sizes": "192x192",
                        "type": "image/png",
                        "purpose": "any",
                    },
                    {
                        "src": "/pwa/icon-512.png",
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "any maskable",
                    },
                ],
            }
        )
        response.mimetype = "application/manifest+json"
        response.headers["Cache-Control"] = "no-cache"
        return response

    def _pwa_icon_response(size: int):
        icon_path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "ui"
            / "assets"
            / "branding"
            / "femag-logo-compact.png"
        )
        with Image.open(icon_path) as source:
            icon = source.convert("RGBA")
            icon.thumbnail((size, size), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (size, size), (255, 255, 255, 255))
            x = (size - icon.width) // 2
            y = (size - icon.height) // 2
            canvas.alpha_composite(icon, (x, y))
            output = BytesIO()
            canvas.convert("RGB").save(output, format="PNG", optimize=True)
            output.seek(0)
        return send_file(
            output,
            mimetype="image/png",
            max_age=86400,
            download_name=f"femag-{size}.png",
        )

    @app.get("/pwa/icon-192.png")
    def pwa_icon_192():
        return _pwa_icon_response(192)

    @app.get("/pwa/icon-512.png")
    def pwa_icon_512():
        return _pwa_icon_response(512)

    @app.get("/service-worker.js")
    def service_worker():
        # La PWA es deliberadamente online-first: no se cachean órdenes ni
        # respuestas operativas para evitar trabajar con información obsoleta.
        script = """
self.addEventListener("install", event => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => {
  event.respondWith(fetch(event.request));
});
""".strip()
        response = Response(script, mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.get("/health")
    def health():
        db = database_proxy.obj
        database_ok = False
        if db is not None:
            try:
                db.execute_sql("SELECT 1")
                database_ok = True
            except Exception:
                database_ok = False
        status = 200 if database_ok else 503
        return {"status": "ok" if database_ok else "degraded", "database": database_ok}, status

    @app.route("/", methods=["GET", "POST"])
    def home():
        if request.method == "POST":
            try:
                token = normalize_qr_token(request.form.get("qr", ""))
                get_order_by_token(token)
                return redirect(url_for("order_detail", token=token))
            except (InvalidQrPayloadError, OrderNotFoundError, OrderUnavailableError) as exc:
                flash(str(exc), "error")
        return render_template("home.html")

    @app.route("/orden/<token>", methods=["GET", "POST"])
    def order_detail(token: str):
        try:
            order = get_order_by_token(token)
        except OrderUnavailableError as exc:
            return render_template("error.html", message=str(exc)), 409
        except (InvalidQrPayloadError, OrderNotFoundError) as exc:
            return render_template("error.html", message=str(exc)), 404

        lines = order_lines(order)
        if request.method == "POST":
            try:
                with database_proxy.atomic():
                    for line in lines:
                        update_order_line(
                            order,
                            line.id,
                            lote=request.form.get(f"lote_{line.id}"),
                            fecha_elaboracion=request.form.get(f"fecha_{line.id}"),
                        )
                flash("Lote y fecha de elaboración guardados.", "success")
                return redirect(url_for("order_detail", token=order.ensure_qr_token()))
            except (ValueError, OrderNotFoundError) as exc:
                flash(str(exc), "error")
                lines = order_lines(order)

        return render_template(
            "order.html",
            order=order,
            lines=lines,
            line_context=order_line_context(order, lines),
        )

    return app
