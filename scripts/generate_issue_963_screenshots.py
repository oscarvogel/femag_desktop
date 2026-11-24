"""Capturas del ABM "Maestros > Productores" (#963), con datos ficticios.

Uso: python scripts/generate_issue_963_screenshots.py [--output-dir DIR]
"""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from peewee import SqliteDatabase  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from app.config.database import bind_database  # noqa: E402
from app.models import ALL_MODELS, SYNC_MODELS  # noqa: E402
from app.models.security import User, UserProfile  # noqa: E402
from app.models.suppliers import Supplier, SupplierLegacyCode  # noqa: E402
from app.services.permission_service import PermissionService  # noqa: E402
from app.services.supplier_master_service import SupplierMasterService  # noqa: E402
from generate_ux_screenshots import _capture  # noqa: E402

DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_963"

DEMO = [
    ("COOPERATIVA YERBATERA DEMO", ("0101", "0102"), "Oberá", "3755-000001", "30-71234567-1", True),
    ("ACOPIO LOS PINOS DEMO", ("0201",), "Leandro N. Alem", "", "", False),
    ("PRODUCTOR EJEMPLO UNO", ("0301",), "Campo Viera", "3755-000003", "20-12345678-6", False),
    ("PRODUCTOR EJEMPLO DOS", ("0302", "0303"), "", "", "", False),
    ("COLONO DE PRUEBA", (), "Oberá", "3755-000005", "12345678", True),
]


def _seed() -> User:
    PermissionService().seed_defaults()
    service = SupplierMasterService("captura963")
    for name, codes, locality, phone, tax_id, verified in DEMO:
        supplier = service.create(
            name=name, locality=locality, phone=phone, tax_id=tax_id or None,
            identity_verified=verified,
        )
        for code in codes:
            SupplierLegacyCode.create(
                supplier=supplier, code=code, source_key=f"demo:proveedo:{code}", name=name
            )
    service.set_active(Supplier.get(Supplier.name == "PRODUCTOR EJEMPLO DOS"), False)
    profile = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username="captura963", password_hash="x", profile=profile)


def generate(output_dir: Path) -> list[Path]:
    from app.ui.supplier_master import (
        SupplierDetailDialog,
        SupplierEntryDialog,
        build_supplier_master_page,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables([*ALL_MODELS, *SYNC_MODELS])
    app = QApplication.instance() or QApplication([])
    user = _seed()

    page = build_supplier_master_page(user=user, current_user=user.username)
    page.show()
    targets = []
    for width, height in ((1638, 969), (1366, 768)):
        page.resize(width, height)
        app.processEvents()
        target = output_dir / f"01_productores_{width}x{height}.png"
        _capture(page, target)
        targets.append(target)

    cooperativa = Supplier.get(Supplier.name == DEMO[0][0])
    dialog = SupplierEntryDialog(current_user=user.username, record_id=cooperativa.id)
    dialog.show()
    app.processEvents()
    target = output_dir / "02_editar_productor.png"
    _capture(dialog, target)
    targets.append(target)
    dialog.close()

    ejemplo = Supplier.get(Supplier.name == "PRODUCTOR EJEMPLO DOS")
    detail = SupplierDetailDialog(supplier_id=ejemplo.id)
    detail.show()
    app.processEvents()
    target = output_dir / "03_ficha_productor.png"
    _capture(detail, target)
    targets.append(target)
    detail.close()
    page.close()
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    for target in generate(args.output_dir):
        print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
