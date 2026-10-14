from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter


HEADERS = (
    "Nombre / Razón social",
    "CUIT",
    "Cond. IVA",
    "Celular / Teléfono",
    "Email",
    "Contacto",
    "Vendedor",
    "Lista",
    "Estado",
)


def resolve_client_email(client) -> str:
    """Email principal del cliente: ClientEmail activo y primario, si no el de Client."""
    try:
        from app.models.masters import ClientEmail

        primary = (
            ClientEmail.select()
            .where(
                (ClientEmail.client == client.id)
                & (ClientEmail.active == True)  # noqa: E712
            )
            .order_by(ClientEmail.is_primary.desc(), ClientEmail.id)
            .first()
        )
        if primary is not None and (primary.email or "").strip():
            return primary.email.strip()
    except Exception:
        pass
    return (getattr(client, "email", None) or "").strip()


def build_client_export_rows(clients) -> list[tuple]:
    rows = []
    for client in clients:
        salesperson_name = "Sin asignar"
        try:
            if getattr(client, "salesperson_id", None) is not None and client.salesperson is not None:
                salesperson_name = client.salesperson.name or "Sin asignar"
        except Exception:
            salesperson_name = "Sin asignar"
        rows.append(
            (
                client.name or "",
                client.cuit or "",
                client.iva_condition or "",
                client.phone or "",
                resolve_client_email(client),
                getattr(client, "contact", None) or "",
                salesperson_name,
                int(client.lista_precios or 1),
                "Activo" if getattr(client, "active", True) else "Inactivo",
            )
        )
    return rows


def fetch_ordered_clients(client_ids: list[int]):
    """Devuelve los Client en el mismo orden que client_ids (orden visible de la grilla)."""
    from app.models.masters import Client

    if not client_ids:
        return []
    clients = list(Client.select().where(Client.id.in_(client_ids)))
    by_id = {client.id: client for client in clients}
    return [by_id[client_id] for client_id in client_ids if client_id in by_id]


def export_clients_xlsx(clients, destination: str | Path) -> Path:
    path = Path(destination)
    if not str(path).lower().endswith(".xlsx"):
        path = path.with_suffix(".xlsx")
    path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in build_client_export_rows(clients):
        ws.append(row)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(HEADERS))}{max(1, ws.max_row)}"
    ws.freeze_panes = "A2"
    widths = (38, 16, 12, 20, 32, 22, 24, 10, 12)
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    wb.save(path)
    return path
