"""Genera las capturas de la pantalla "Envío de lista de precios" (#705 Fase B, etapa 3).

Salida: ``docs/screenshots/issue_763_envio_lista_precios/`` con la pantalla a las dos
resoluciones de la PC del cliente (1638x969 y 1366x768).

    python scripts/generate_price_list_send_screenshots.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication

# Con "offscreen" no hay fuentes y las capturas salen sin texto: en Windows se usa la
# plataforma real, como hace scripts/generate_ux_screenshots.py.
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT = ROOT / "docs" / "screenshots" / "issue_763_envio_lista_precios"
RESOLUCIONES = ((1638, 969), (1366, 768))


def _datos():
    from app.models.masters import Client

    clientes = [
        ("RINALDI & VERGES S.H.", "20296461521", 1, "011-1553088679"),
        ("VILLARES S.A.C.", "20296461522", 1, "011-15 5913 3141"),
        ("CAMPOS ANDRES AVELINO", "20296461523", 1, "011-1559888301"),
        ("ALIMENTOS BADALONI S.A.", "30718532066", 1, "0221-154947551"),
        ("ALINAT S.R.L.", "30718532067", 1, "0341156910349"),
        ("GIMENEZ ROMINA JAQUELINE", "27385135918", 2, "+5491164426278"),
    ]
    for nombre, cuit, lista, telefono in clientes:
        Client.create(
            name=nombre,
            cuit=cuit,
            iva_condition="RI",
            phone=telefono,
            lista_precios=lista,
        )


def main(argv=None) -> int:
    from app.config.database import bind_database
    from app.models import ALL_MODELS
    from app.ui.price_list_send_page import PriceListSendPage

    output_dir = DEFAULT_OUTPUT
    if argv:
        output_dir = Path(argv[0])
    output_dir.mkdir(parents=True, exist_ok=True)

    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    _datos()

    app = QApplication.instance() or QApplication([])
    app.processEvents()

    generado = []
    for ancho, alto in RESOLUCIONES:
        pagina = PriceListSendPage(user=None, current_user="captura763")
        pagina.resize(ancho, alto)
        pagina._calcular_destinatarios()
        pagina.pdf_input.setText("C:/listas/lista1.pdf")
        pagina.mensaje_input.setPlainText(
            "Hola {cliente}, adjuntamos la lista de precios {lista} de {empresa}. Quedamos a disposición."
        )
        app.processEvents()
        pagina.grab().save(str(output_dir / f"envio_lista_precios_{ancho}x{alto}.png"))
        generado.append(output_dir / f"envio_lista_precios_{ancho}x{alto}.png")
        pagina.close()

    database.close()
    for ruta in generado:
        print(ruta)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
