from __future__ import annotations

from flask import Flask, flash, redirect, render_template, request, url_for

from app.config.database import database_proxy
from webapp.order_service import (
    InvalidQrPayloadError,
    OrderNotFoundError,
    get_order_by_token,
    normalize_qr_token,
    order_line_context,
    order_lines,
    update_order_line,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "femag-local-webapp"

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
            except (InvalidQrPayloadError, OrderNotFoundError) as exc:
                flash(str(exc), "error")
        return render_template("home.html")

    @app.route("/orden/<token>", methods=["GET", "POST"])
    def order_detail(token: str):
        try:
            order = get_order_by_token(token)
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
