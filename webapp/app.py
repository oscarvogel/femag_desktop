from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config.database import database_proxy
from app.services.audit_query_service import AuditQueryService
from app.utils.datetime_utils import utc_datetime_to_local
from webapp import audit, production_service
from webapp.auth import (
    SESSION_LIFETIME,
    csrf_token,
    csrf_token_is_valid,
    current_username,
    is_administrator,
    login_is_rate_limited,
    login_required,
    login_user,
    logout_user,
    redirect_after_login,
    resolve_secret_key,
)
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
from webapp.projected_order_service import (
    get_projected_order_by_token,
    projected_line_context,
    projected_order_lines,
    update_projected_content,
    update_projected_line,
)
from webapp.qr_sheet import build_turno_sheet
from webapp.sync_api import sync_api


def _production_target(value: str) -> str | None:
    """Destino de un QR que apunta a la pantalla de produccion.

    El QR de turno lleva la URL completa del servidor (o un caminho relativo).
    Se devuelve el camino interno para que el escaner desde el celular no
    dependa de que el proxy reenvie el host.
    """
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("/produccion"):
        return value
    parsed = urlparse(value)
    if parsed.path.startswith("/produccion"):
        return parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return None


def create_app(*, secret_key: str | None = None) -> Flask:
    app = Flask(__name__)
    # El secreto de la sesion no puede ser un valor fijo del repositorio: con
    # una clave conocida, cualquiera podria firmar una cookie de sesion
    # inventada y entrar como otro usuario. Ver ``webapp.auth.resolve_secret_key``.
    app.config["SECRET_KEY"] = secret_key or resolve_secret_key()
    # URL publica del servidor, cuando hay un proxy (Caddy) delante. Sin esto
    # el QR de turno se imprimiria con la direccion interna del servidor.
    app.config["PUBLIC_URL"] = os.getenv("FEMAG_WEB_PUBLIC_URL", "").strip()
    public_url = app.config["PUBLIC_URL"]
    uses_https = public_url.lower().startswith("https://")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=uses_https,
        PERMANENT_SESSION_LIFETIME=SESSION_LIFETIME,
        PREFERRED_URL_SCHEME="https" if uses_https else "http",
    )
    if uses_https:
        # Traefik termina el TLS y reenvia a gunicorn por HTTP interno.
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,
            x_proto=1,
            x_host=1,
        )
    # Los numeros se muestran como se leen aca: punto de miles y coma decimal.
    app.jinja_env.filters["kg"] = production_service.kg_text
    app.register_blueprint(sync_api)

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), microphone=(), geolocation=()",
        )
        if uses_https or request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    @app.context_processor
    def _inject_auth():
        """La barra de arriba muestra quien esta conectado."""
        return {
            "current_username": current_username,
            "is_administrator": is_administrator,
            "csrf_token": csrf_token,
        }

    def _load_order(token: str):
        try:
            return get_order_by_token(token), False
        except OrderNotFoundError:
            projected = get_projected_order_by_token(token)
            if projected is None:
                raise
            return projected, True

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
self.addEventListener("install", event => event.skipWaiting());
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

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if login_is_rate_limited(username, station=audit.client_station()):
                flash(
                    "Demasiados intentos fallidos. Esperá unos minutos e intentá de nuevo.",
                    "error",
                )
                return render_template("login.html"), 429
            if login_user(username, password):
                flash("Sesión iniciada.", "success")
                return redirect(redirect_after_login("production"))
            flash("Usuario o contraseña incorrectos.", "error")
        return render_template("login.html")

    @app.get("/logout")
    def logout():
        logout_user()
        flash("Sesión cerrada.", "success")
        return redirect(url_for("home"))

    @app.route("/", methods=["GET", "POST"])
    def home():
        if request.method == "POST":
            raw = (request.form.get("qr") or "").strip()
            # Un QR de turno de produccion no es un token de orden: se abre
            # la pantalla de produccion con el turno ya puesto.
            production_target = _production_target(raw)
            if production_target:
                return redirect(production_target)
            try:
                token = normalize_qr_token(raw)
                _load_order(token)
                return redirect(url_for("order_detail", token=token))
            except (InvalidQrPayloadError, OrderNotFoundError, OrderUnavailableError) as exc:
                flash(str(exc), "error")
        return render_template("home.html")

    @app.route("/orden/<token>", methods=["GET", "POST"])
    def order_detail(token: str):
        try:
            order, is_projected = _load_order(token)
        except OrderUnavailableError as exc:
            return render_template("error.html", message=str(exc)), 409
        except (InvalidQrPayloadError, OrderNotFoundError) as exc:
            return render_template("error.html", message=str(exc)), 404

        if is_projected:
            lines = projected_order_lines(order)
            if request.method == "POST":
                username = current_username()
                if not username:
                    flash(
                        "Iniciá sesión para modificar el lote y la fecha de la orden.",
                        "error",
                    )
                    return redirect(
                        url_for(
                            "login",
                            next=url_for(
                                "order_detail", token=order.ensure_qr_token()
                            ),
                        )
                    )
                if not csrf_token_is_valid():
                    return (
                        render_template(
                            "error.html",
                            message=(
                                "La sesión expiró o el formulario no es válido. "
                                "Volvé a abrir la orden e intentá de nuevo."
                            ),
                        ),
                        400,
                    )
                try:
                    changed = False
                    if order.has_contents:
                        contents = [
                            content
                            for pallet in order.pallets
                            for content in pallet.contents
                        ] + list(order.loose_contents)
                        for content in contents:
                            lote_key = f"lote_{content.id}"
                            fecha_key = f"fecha_{content.id}"
                            if lote_key not in request.form and fecha_key not in request.form:
                                continue
                            if update_projected_content(
                                order,
                                content.id,
                                content_type=content.kind,
                                lote=request.form.get(lote_key),
                                fecha_elaboracion=request.form.get(fecha_key),
                            ):
                                changed = True
                        audit_value = {
                            "orden": order.order_number,
                            "contenidos": [
                                {
                                    "contenido": content.id,
                                    "tipo": content.kind,
                                    "producto": content.product.name,
                                    "lote": request.form.get(
                                        f"lote_{content.id}"
                                    ),
                                    "fecha_elaboracion": request.form.get(
                                        f"fecha_{content.id}"
                                    ),
                                }
                                for content in contents
                            ],
                        }
                    else:
                        for line in lines:
                            if update_projected_line(
                                order,
                                line.id,
                                lote=request.form.get(f"lote_{line.id}"),
                                fecha_elaboracion=request.form.get(
                                    f"fecha_{line.id}"
                                ),
                            ):
                                changed = True
                        audit_value = {
                            "orden": order.order_number,
                            "renglones": [
                                {
                                    "renglon": line.id,
                                    "producto": line.product.name,
                                    "lote": request.form.get(f"lote_{line.id}"),
                                    "fecha_elaboracion": request.form.get(
                                        f"fecha_{line.id}"
                                    ),
                                }
                                for line in lines
                            ],
                        }
                    if changed:
                        audit.record(
                            user=username,
                            module=audit.MODULE_DESPACHOS,
                            action=audit.ACTION_LOTE,
                            record_ref=f"SyncOrder:{order.order_uid}",
                            new_value=audit_value,
                        )
                        flash(
                            "Lote y fecha guardados. Pendiente de sincronización "
                            "con fábrica.",
                            "success",
                        )
                    else:
                        flash("No había cambios para guardar.", "success")
                    return redirect(
                        url_for("order_saved", token=order.ensure_qr_token())
                    )
                except (ValueError, OrderUnavailableError) as exc:
                    flash(str(exc), "error")
                    lines = projected_order_lines(order)

            return render_template(
                "order.html",
                order=order,
                lines=lines,
                line_context=projected_line_context(order, lines),
                is_projected=True,
            )

        lines = order_lines(order)
        if request.method == "POST":
            username = current_username()
            if not username:
                flash("Iniciá sesión para modificar el lote y la fecha de la orden.", "error")
                return redirect(
                    url_for(
                        "login",
                        next=url_for("order_detail", token=order.ensure_qr_token()),
                    )
                )
            if not csrf_token_is_valid():
                return (
                    render_template(
                        "error.html",
                        message=(
                            "La sesión expiró o el formulario no es válido. "
                            "Volvé a abrir la orden e intentá de nuevo."
                        ),
                    ),
                    400,
                )
            try:
                before = {
                    line.id: (line.lote, line.fecha_elaboracion) for line in lines
                }
                with database_proxy.atomic():
                    for line in lines:
                        update_order_line(
                            order,
                            line.id,
                            lote=request.form.get(f"lote_{line.id}"),
                            fecha_elaboracion=request.form.get(f"fecha_{line.id}"),
                        )
                lines = order_lines(order)
                changed = any(
                    (line.lote, line.fecha_elaboracion) != before.get(line.id)
                    for line in lines
                )
                if changed:
                    audit.record(
                        user=username,
                        module=audit.MODULE_DESPACHOS,
                        action=audit.ACTION_LOTE,
                        record_ref=f"LoadOrder:{order.id}",
                        new_value={
                            "orden": order.order_number,
                            "renglones": [
                                {
                                    "renglon": line.id,
                                    "producto": line.product.name,
                                    "lote": line.lote,
                                    "fecha_elaboracion": (
                                        line.fecha_elaboracion.isoformat()
                                        if line.fecha_elaboracion
                                        else None
                                    ),
                                }
                                for line in lines
                            ],
                        },
                    )
                    flash("Lote y fecha de elaboración guardados.", "success")
                else:
                    flash("No había cambios para guardar.", "success")
                return redirect(
                    url_for("order_saved", token=order.ensure_qr_token())
                )
            except (ValueError, OrderNotFoundError) as exc:
                flash(str(exc), "error")
                lines = order_lines(order)

        return render_template(
            "order.html",
            order=order,
            lines=lines,
            line_context=order_line_context(order, lines),
            is_projected=False,
        )

    @app.get("/orden/<token>/guardado")
    def order_saved(token: str):
        try:
            order, is_projected = _load_order(token)
        except OrderUnavailableError as exc:
            return render_template("error.html", message=str(exc)), 409
        except (InvalidQrPayloadError, OrderNotFoundError) as exc:
            return render_template("error.html", message=str(exc)), 404

        lines = (
            projected_order_lines(order)
            if is_projected
            else order_lines(order)
        )
        return render_template(
            "order_saved.html",
            order=order,
            lines=lines,
            is_projected=is_projected,
        )

    def _blank_submitted():
        """Formulario vacio con el mismo largo que el que se procesa."""
        return {
            "product": [""] * production_service.BAG_ROWS,
            "bags": [""] * production_service.BAG_ROWS,
            "materia": [""] * production_service.CONSUMPTION_ROWS,
            "kg": [""] * production_service.CONSUMPTION_ROWS,
            "observaciones": "",
        }

    def _part_audit_payload(part, user):
        """Lo que queda registrado de un parte en la auditoria (#778).

        Con esto se sabe que parte cargo cada persona, cuando y cuanto salio,
        sin tener que buscarlo parte por parte.
        """
        bags = production_service.lines_of(part)
        consumptions = production_service.consumptions_of(part)
        return {
            "parte": part.id,
            "fecha": part.production_date.isoformat(),
            "turno": part.shift,
            "bolsas": sum(int(bag.bags or 0) for bag in bags),
            "kg": float(
                sum((Decimal(str(bag.kg or 0)) for bag in bags), Decimal("0"))
            ),
            "materia_prima_kg": float(
                sum((Decimal(str(item.kg or 0)) for item in consumptions), Decimal("0"))
            ),
            "usuario": user,
        }

    def _production_context(day, shift, submitted=None):
        parts = production_service.parts_for_day(day)
        part_rows = []
        for part in parts:
            bags = production_service.lines_of(part)
            consumptions = production_service.consumptions_of(part)
            part_rows.append(
                {
                    "part": part,
                    "bags": bags,
                    "consumptions": consumptions,
                    "bags_count": sum(int(bag.bags or 0) for bag in bags),
                    "kg_total": sum(
                        (Decimal(str(bag.kg or 0)) for bag in bags), Decimal("0")
                    ),
                }
            )
        productos = production_service.products_for_bags()
        materias = production_service.raw_materials()
        productos_opciones = production_service.combo_options(productos)
        materias_opciones = production_service.combo_options(
            materias,
            sufijo=lambda producto: (
                f"hay {production_service.kg_text(production_service.available_kg(producto), 3)} kg"
            ),
        )
        return {
            "day": day,
            "shift": shift,
            "shifts": production_service.SHIFTS,
            "products": productos,
            "raw_materials": materias,
            "productos_opciones": productos_opciones,
            "materias_opciones": materias_opciones,
            "etiquetas_producto": production_service.combo_labels(productos_opciones),
            "etiquetas_materia": production_service.combo_labels(materias_opciones),
            "available_kg": production_service.available_kg,
            "part_rows": part_rows,
            "totals": production_service.totals(parts),
            "bag_rows": production_service.BAG_ROWS,
            "consumption_rows": production_service.CONSUMPTION_ROWS,
            "submitted": submitted if submitted is not None else _blank_submitted(),
        }

    @app.route("/produccion", methods=["GET", "POST"])
    @login_required
    def production():
        username = current_username()
        if request.method == "POST":
            day = production_service.parse_date(request.form.get("fecha"))
            shift = (request.form.get("turno") or "").strip()
            products = {
                product.id: product
                for product in production_service.products_for_bags()
            }
            raw_materials = {
                product.id: product
                for product in production_service.raw_materials()
            }
            lines = production_service.parse_bag_lines(request.form, products)
            consumptions = production_service.parse_consumptions(
                request.form, raw_materials
            )
            observations = (request.form.get("observaciones") or "").strip()
            submitted = {
                "product": [form_value(request.form, f"product_{i}") for i in range(production_service.BAG_ROWS)],
                "bags": [form_value(request.form, f"bags_{i}") for i in range(production_service.BAG_ROWS)],
                "materia": [form_value(request.form, f"materia_{i}") for i in range(production_service.CONSUMPTION_ROWS)],
                "kg": [form_value(request.form, f"kg_{i}") for i in range(production_service.CONSUMPTION_ROWS)],
                "observaciones": observations,
            }
            try:
                part = production_service.create_part(
                    production_date=day,
                    shift=shift,
                    lines=lines,
                    consumptions=consumptions,
                    observations=observations,
                    recorded_by=username,
                )
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template(
                    "production.html", **_production_context(day, shift, submitted)
                )
            audit.record(
                user=username,
                module=audit.MODULE_PRODUCCION,
                action=audit.ACTION_CARGA,
                record_ref=f"ProductionPart:{part.id}",
                new_value=_part_audit_payload(part, username),
            )
            flash("Parte guardado. Revisalo y confirmalo cuando esté todo bien.", "success")
            return redirect(
                url_for("production", fecha=day.isoformat(), turno=shift)
            )

        day = production_service.parse_date(request.args.get("fecha"))
        shift = (request.args.get("turno") or production_service.SHIFTS[0]).strip()
        return render_template("production.html", **_production_context(day, shift))

    @app.post("/produccion/<int:part_id>/confirmar")
    @login_required
    def production_confirm(part_id: int):
        part = production_service.part_by_id(part_id)
        if part is None:
            flash("El parte no existe.", "error")
            return redirect(url_for("production"))
        try:
            production_service.confirm_part(part, current_user=current_username())
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            audit.record(
                user=current_username(),
                module=audit.MODULE_PRODUCCION,
                action=audit.ACTION_CONFIRMACION,
                record_ref=f"ProductionPart:{part.id}",
                new_value=_part_audit_payload(part, current_username()),
            )
            flash("Parte confirmado: las bolsas entraron al stock y la materia prima salió.", "success")
        return redirect(
            url_for(
                "production",
                fecha=part.production_date.isoformat(),
                turno=part.shift,
            )
        )

    @app.post("/produccion/<int:part_id>/anular")
    @login_required
    def production_annul(part_id: int):
        part = production_service.part_by_id(part_id)
        if part is None:
            flash("El parte no existe.", "error")
            return redirect(url_for("production"))
        username = current_username()
        if part.recorded_by != username and not is_administrator():
            flash("Solo podés anular un parte que cargaste vos.", "error")
            return redirect(
                url_for(
                    "production",
                    fecha=part.production_date.isoformat(),
                    turno=part.shift,
                )
            )
        reason = (request.form.get("motivo") or "").strip()
        try:
            production_service.annul_part(
                part, current_user=username, reason=reason
            )
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            audit.record(
                user=username,
                module=audit.MODULE_PRODUCCION,
                action=audit.ACTION_ANULACION,
                record_ref=f"ProductionPart:{part.id}",
                new_value=_part_audit_payload(part, username),
                observation=reason or None,
            )
            flash("Parte anulado.", "success")
        return redirect(
            url_for(
                "production",
                fecha=part.production_date.isoformat(),
                turno=part.shift,
            )
        )

    @app.get("/produccion/turnos.pdf")
    @login_required
    def production_turnos_pdf():
        if not is_administrator():
            flash("Sólo un administrador puede imprimir la hoja de QR.", "error")
            return redirect(url_for("production"))
        base = (app.config.get("PUBLIC_URL") or "").strip().rstrip("/")

        def url_for_turno(turno: str) -> str:
            path = url_for("production", turno=turno)
            if base:
                return f"{base}{path}"
            return request.url_root.rstrip("/") + path

        data = build_turno_sheet(production_service.SHIFTS, url_for_turno)
        return send_file(
            BytesIO(data),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="femag-qr-turnos.pdf",
        )

    @app.get("/accesos")
    @login_required
    def accesos():
        """Informe de accesos y de carga de partes (#779).

        Solo para administradores: muestra quien entro, desde que equipo y
        que parte cargo cada persona, sin tocar el servidor de MySQL a mano.
        """
        if not is_administrator():
            flash("Sólo un administrador puede ver los accesos.", "error")
            return redirect(url_for("production"))

        service = AuditQueryService()
        filtros = {
            "desde": (request.args.get("desde") or "").strip(),
            "hasta": (request.args.get("hasta") or "").strip(),
            "usuario": (request.args.get("usuario") or "").strip(),
            "modulo": (request.args.get("modulo") or "").strip(),
            "accion": (request.args.get("accion") or "").strip(),
            "referencia": (request.args.get("referencia") or "").strip(),
        }
        pagina = max(_entero(request.args.get("pagina"), 0), 0)
        resultado = service.search_page(
            module=filtros["modulo"] or None,
            user=filtros["usuario"] or None,
            action=filtros["accion"] or None,
            reference=filtros["referencia"] or None,
            date_from=_fecha(filtros["desde"]),
            date_to=_fecha(filtros["hasta"]),
            page=pagina,
            page_size=50,
        )

        filas = []
        for row in resultado.rows:
            momento = utc_datetime_to_local(row.occurred_at)
            filas.append(
                {
                    "fecha": momento.strftime("%d/%m/%Y %H:%M") if momento else "—",
                    "usuario": row.user or "—",
                    "modulo": row.module,
                    "accion": row.action,
                    "referencia": service.display_reference(row) or "—",
                    "detalle": (
                        service.reason_or_summary(row)
                        or service.transition(row)
                        or "—"
                    ),
                    "puesto": row.workstation or "—",
                }
            )

        return render_template(
            "accesos.html",
            filas=filas,
            opciones=service.filter_options(),
            filtros=filtros,
            pagina=pagina,
            pagina_anterior=pagina - 1 if resultado.has_previous else None,
            pagina_siguiente=pagina + 1 if resultado.has_next else None,
        )

    return app


def form_value(form, key: str) -> str:
    return (form.get(key) or "").strip()


def _entero(valor, defecto: int = 0) -> int:
    """Un entero de la query string, o el valor por defecto si no lo es."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return defecto


def _fecha(valor) -> date | None:
    """'AAAA-MM-DD' a fecha; si no se puede leer, no se filtra por fecha."""
    texto = (valor or "").strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None
