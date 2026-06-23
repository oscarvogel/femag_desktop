from __future__ import annotations

from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PIL import Image, ImageDraw, ImageFont
from peewee import SqliteDatabase

from app.config.database import bind_database
from app.models.masters import Client, Driver, Product
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.abm import build_master_abm_specs
from app.ui.dashboard import DashboardService, future_module_message
from app.ui.load_orders import build_load_order_form_spec
from app.ui.main_window import MainWindow
from scripts.seed_demo_data import DEMO_DB_PATH, seed_demo_data


OUTPUT_DIR = Path("docs/screenshots/ux_base_final")
CANVAS = (1440, 960)


def generate_screenshots(output_dir: Path = OUTPUT_DIR, *, db_path: Path = DEMO_DB_PATH) -> list[Path]:
    seed_demo_data(db_path)
    db = SqliteDatabase(db_path)
    bind_database(db)
    db.connect(reuse_if_open=True)
    PermissionService().seed_defaults()
    user = _demo_user()
    shell = MainWindow(user=user, demo_mode=True).shell_spec
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = [
        _draw_login(output_dir / "01_login.png"),
        _draw_dashboard(output_dir / "02_dashboard_datos_demo.png", shell),
        _draw_menu(output_dir / "03_menu_lateral.png", shell),
        _draw_quick_actions(output_dir / "04_dashboard_accesos_rapidos.png"),
        _draw_abm(output_dir / "05_clientes.png", "Clientes", [client.name for client in Client.select().limit(5)]),
        _draw_abm(output_dir / "06_productos.png", "Productos", [product.name for product in Product.select().limit(5)]),
        _draw_abm(output_dir / "07_choferes.png", "Choferes", [driver.name for driver in Driver.select().limit(5)]),
        _draw_load_order(output_dir / "08_nueva_orden_carga.png", occupied=False),
        _draw_load_order(output_dir / "09_orden_varios_renglones.png", occupied=False, rows=True),
        _draw_load_order(output_dir / "10_chofer_ocupado.png", occupied=True, rows=True),
        _draw_print(output_dir / "11_impresion_a4.png"),
        _draw_placeholder(output_dir / "12_placeholder_modulo_futuro.png"),
    ]
    db.close()
    return paths


def _demo_user():
    service = AuthService()
    user = service.authenticate("demo_visual", "demo")
    if user:
        return user
    return service.create_user("demo_visual", "demo", "Administrador")


def _base(title: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", CANVAS, "#f4f7fb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS[0], 72), fill="#ffffff")
    draw.text((32, 22), "FEMAG Desktop", fill="#111827", font=_font(28, bold=True))
    draw.text((276, 28), "Gestión operativa local", fill="#475569", font=_font(18))
    draw.text((1120, 24), "demo_visual · Administrador · Modo demo", fill="#334155", font=_font(15))
    draw.rectangle((0, 72, 255, CANVAS[1] - 34), fill="#f8fafc")
    draw.rectangle((0, CANVAS[1] - 34, CANVAS[0], CANVAS[1]), fill="#111827")
    draw.text((24, CANVAS[1] - 25), "v0.1 · Listo · Último backup OK", fill="#e5e7eb", font=_font(13))
    draw.text((288, 104), title, fill="#0f172a", font=_font(30, bold=True))
    return image, draw


def _draw_login(path: Path) -> Path:
    image = Image.new("RGB", CANVAS, "#eef2f7")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((470, 220, 970, 680), radius=8, fill="#ffffff", outline="#cbd5e1")
    draw.text((540, 285), "FEMAG Desktop", fill="#111827", font=_font(34, bold=True))
    draw.text((540, 330), "Gestión operativa local", fill="#64748b", font=_font(18))
    _field(draw, 540, 390, "Usuario", "demo_visual")
    _field(draw, 540, 478, "Contraseña", "••••••••")
    draw.rounded_rectangle((540, 585, 900, 635), radius=6, fill="#1d4ed8")
    draw.text((650, 599), "Ingresar", fill="#ffffff", font=_font(18, bold=True))
    image.save(path)
    return path


def _draw_dashboard(path: Path, shell) -> Path:
    image, draw = _base("Dashboard operativo")
    _sidebar(draw, shell.sidebar.sections)
    x = 290
    for index, (label, value) in enumerate(shell.dashboard.summary_cards.items()):
        left = x + (index % 3) * 335
        top = 170 + (index // 3) * 130
        _card(draw, left, top, 300, 100, label, str(value))
    draw.text((290, 450), "Pendientes y alertas", fill="#0f172a", font=_font(22, bold=True))
    for i, alert in enumerate(shell.dashboard.alerts):
        draw.text((310, 500 + i * 34), f"• {alert}", fill="#334155", font=_font(17))
    image.save(path)
    return path


def _draw_menu(path: Path, shell) -> Path:
    image, draw = _base("Menú lateral tipo árbol")
    _sidebar(draw, shell.sidebar.sections)
    draw.text((310, 180), "Opción activa destacada: Dashboard", fill="#1d4ed8", font=_font(24, bold=True))
    draw.text((310, 230), "Módulos futuros atenuados con mensaje claro.", fill="#475569", font=_font(18))
    image.save(path)
    return path


def _draw_quick_actions(path: Path) -> Path:
    image, draw = _base("Acciones rápidas")
    actions = DashboardService().view_spec(demo_mode=True).quick_actions
    for index, action in enumerate(actions):
        left = 290 + (index % 3) * 345
        top = 175 + (index // 3) * 115
        fill = "#1d4ed8" if action.enabled else "#e2e8f0"
        text = "#ffffff" if action.enabled else "#64748b"
        draw.rounded_rectangle((left, top, left + 310, top + 74), radius=8, fill=fill)
        draw.text((left + 22, top + 24), action.title, fill=text, font=_font(18, bold=True))
    image.save(path)
    return path


def _draw_abm(path: Path, title: str, rows: list[str]) -> Path:
    image, draw = _base(title)
    spec = next(item for item in build_master_abm_specs() if item.title == title)
    _field(draw, 290, 160, "Buscar", spec.search_placeholder)
    draw.rounded_rectangle((290, 270, 1280, 710), radius=8, fill="#ffffff", outline="#cbd5e1")
    for i, column in enumerate(spec.table_columns[:5]):
        draw.text((320 + i * 175, 292), column, fill="#334155", font=_font(15, bold=True))
    for r, row in enumerate(rows or [spec.empty_message]):
        y = 340 + r * 52
        draw.line((310, y - 12, 1260, y - 12), fill="#e2e8f0")
        draw.text((320, y), row, fill="#111827", font=_font(16))
        draw.text((1020, y), "Activo", fill="#047857", font=_font(16, bold=True))
    image.save(path)
    return path


def _draw_load_order(path: Path, *, occupied: bool, rows: bool = False) -> Path:
    image, draw = _base("Nueva orden de carga")
    spec = build_load_order_form_spec()
    draw.rounded_rectangle((290, 155, 1310, 345), radius=8, fill="#ffffff", outline="#cbd5e1")
    for i, column in enumerate(("Número", "Fecha", "Cliente", "Producto", "Cantidad", "Chofer", "Estado")):
        draw.text((310 + i * 135, 178), column, fill="#334155", font=_font(13, bold=True))
    table_rows = (
        ("9001", "23/06/2026", "CANTERO FLAVIA", "Fécula 25 kg", "320", "GLIENKE", "Borrador"),
        ("9002", "23/06/2026", "GALEANO", "Fécula 10 kg", "140", "PEREZ", "Emitida"),
    )
    for r, row in enumerate(table_rows if rows else table_rows[:1]):
        y = 225 + r * 46
        draw.line((305, y - 12, 1295, y - 12), fill="#e2e8f0")
        for c, value in enumerate(row):
            draw.text((310 + c * 135, y), value, fill="#111827", font=_font(13))

    draw.text((290, 380), spec.sections[0].title, fill="#0f172a", font=_font(20, bold=True))
    _field(draw, 290, 420, "Cliente", "CANTERO FLAVIA")
    _field(draw, 700, 420, "Domicilio entrega", "Ruta nacional 117")
    _field(draw, 1040, 420, "Estado", "Borrador")
    draw.text((290, 540), spec.sections[1].title, fill="#0f172a", font=_font(20, bold=True))
    _field(draw, 290, 580, "Transportista", "GLIENKE EZEQUIEL")
    _field(draw, 700, 580, "Camión / patente", "RIA609 / CIE907")
    status = spec.driver_status_messages["blocked" if occupied else "available"]
    draw.text((290, 690), status, fill="#b91c1c" if occupied else "#047857", font=_font(17, bold=True))
    for i, action in enumerate(("Nueva", "Guardar", "Emitir", "Anular", "Imprimir A4")):
        left = 290 + i * 145
        fill = "#1d4ed8" if action not in {"Anular"} else "#475569"
        draw.rounded_rectangle((left, 745, left + 125, 790), radius=6, fill=fill)
        draw.text((left + 20, 758), action, fill="#ffffff", font=_font(14, bold=True))
    image.save(path)
    return path


def _draw_print(path: Path) -> Path:
    image = Image.new("RGB", (900, 1200), "#dbe4ee")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 55, 800, 1145), fill="#ffffff", outline="#94a3b8")
    draw.text((140, 100), "FEMAG", fill="#111827", font=_font(28, bold=True))
    draw.text((360, 100), "Orden de despacho de fécula de mandioca", fill="#111827", font=_font(22, bold=True))
    draw.text((140, 170), "Cliente cabecera: CANTERO FLAVIA     Vehículo limpio y apto: Sí", fill="#334155", font=_font(15))
    draw.rectangle((140, 250, 760, 680), outline="#94a3b8")
    for y in range(300, 680, 56):
        draw.line((140, y, 760, y), fill="#cbd5e1")
    draw.text((155, 265), "Destinatario / bolsas / pack / pallet / lote / fecha elaboración", fill="#334155", font=_font(14, bold=True))
    draw.text((155, 720), "Totales: 800 unidades declaradas - 18 pallets", fill="#111827", font=_font(16, bold=True))
    draw.line((160, 1020, 380, 1020), fill="#111827")
    draw.line((520, 1020, 740, 1020), fill="#111827")
    image.save(path)
    return path


def _draw_placeholder(path: Path) -> Path:
    image, draw = _base("Registrar remito")
    draw.rounded_rectangle((410, 300, 1160, 570), radius=8, fill="#ffffff", outline="#cbd5e1")
    draw.text((500, 380), future_module_message(), fill="#334155", font=_font(28, bold=True))
    draw.text((500, 440), "Remitos, F150, pagos y cuenta corriente quedan fuera de esta entrega.", fill="#64748b", font=_font(18))
    image.save(path)
    return path


def _sidebar(draw: ImageDraw.ImageDraw, sections) -> None:
    y = 110
    for section in sections:
        draw.text((24, y), section.title, fill="#0f172a", font=_font(15, bold=True))
        y += 30
        for item in section.items:
            active = item.route_key == "dashboard"
            fill = "#dbeafe" if active else "#f8fafc"
            color = "#1d4ed8" if active else ("#94a3b8" if item.placeholder else "#334155")
            draw.rounded_rectangle((18, y - 4, 232, y + 25), radius=6, fill=fill)
            draw.text((34, y), item.title, fill=color, font=_font(13, bold=active))
            y += 30
        y += 10


def _card(draw: ImageDraw.ImageDraw, x: int, y: int, width: int, height: int, title: str, value: str) -> None:
    draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill="#ffffff", outline="#cbd5e1")
    draw.text((x + 20, y + 18), title, fill="#475569", font=_font(15))
    draw.text((x + 20, y + 48), value, fill="#111827", font=_font(28, bold=True))


def _field(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, value: str) -> None:
    draw.text((x, y), label, fill="#334155", font=_font(14, bold=True))
    draw.rounded_rectangle((x, y + 24, x + 360, y + 74), radius=6, fill="#ffffff", outline="#cbd5e1")
    draw.text((x + 14, y + 39), value, fill="#111827", font=_font(16))


def _font(size: int, *, bold: bool = False):
    name = "arialbd.ttf" if bold else "arial.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def main() -> int:
    paths = generate_screenshots()
    print(f"Capturas UX generadas: {len(paths)} en {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
