from __future__ import annotations

import sys
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap


BRANDING_DIR = Path("app") / "ui" / "assets" / "branding"


def branding_asset_path(name: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / BRANDING_DIR / name
    return Path(__file__).resolve().parent / "assets" / "branding" / name


def load_brand_pixmap(name: str, *, width: int, height: int) -> QPixmap:
    pixmap = QPixmap(str(branding_asset_path(name)))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def femag_icon() -> QIcon:
    return QIcon(str(branding_asset_path("femag.ico")))
