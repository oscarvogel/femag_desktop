"""Hoja de calibracion del sobre (#740).

Genera un PDF con el contorno del sobre real (235 x 120 mm), los margenes, una
regla en milimetros y un bloque de direccion de ejemplo. Sirve para calibrar
la Epson L3250: se imprime a escala 100 %, se mide el desvio del texto y se
ajustan los desplazamientos (offset X/Y) y la rotacion en la configuracion del
puesto (``%LOCALAPPDATA%\\FEMAG Desktop\\envelope.json``).

No usa datos reales: el bloque es de ejemplo. La correccion final depende de
la prueba fisica con la impresora y el sobre de verdad.

Uso:
    python scripts/generate_envelope_calibration_sheet.py [carpeta_destino]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.envelope_settings import load_envelope_settings
from app.services.envelope_print_service import EnvelopePrintService

DEFAULT_OUTPUT_DIR = Path("outputs") / "envelopes"


def main(argv: list[str]) -> int:
    output_dir = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT_DIR
    settings = load_envelope_settings()
    target = EnvelopePrintService(current_user="admin", settings=settings).export_calibration_sheet(
        output_dir
    )
    width_mm, height_mm = settings.page_size_mm
    print(f"Hoja de calibracion: {target.resolve()}")
    print(f"Pagina: {width_mm:g} x {height_mm:g} mm")
    print(
        "Sobre: {w:g} x {h:g} mm | Rotacion {rot} deg | Offset X {ox:g} mm | "
        "Offset Y {oy:g} mm | Margen {m:g} mm".format(
            w=settings.envelope_width_mm,
            h=settings.envelope_height_mm,
            rot=settings.rotation_deg,
            ox=settings.offset_x_mm,
            oy=settings.offset_y_mm,
            m=settings.margin_mm,
        )
    )
    print("Imprimir a escala 100 % (sin 'ajustar a pagina').")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
