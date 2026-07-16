from pathlib import Path

from PIL import Image


ASSET_NAMES = (
    "femag-logo-source.png",
    "femag-logo-ui.png",
    "femag-logo-compact.png",
    "femag.ico",
)


def test_branding_assets_exist_and_are_valid_images():
    from app.ui.branding import branding_asset_path

    for name in ASSET_NAMES:
        path = branding_asset_path(name)
        assert path.is_file(), name
        with Image.open(path) as image:
            image.verify()


def test_windows_icon_contains_required_sizes():
    from app.ui.branding import branding_asset_path

    with Image.open(branding_asset_path("femag.ico")) as icon:
        sizes = set(icon.info["sizes"])

    assert {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)} <= sizes


def test_branding_asset_path_uses_pyinstaller_bundle_root(monkeypatch, tmp_path):
    import sys

    from app.ui.branding import branding_asset_path

    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert branding_asset_path("femag.ico") == tmp_path / "app" / "ui" / "assets" / "branding" / "femag.ico"


def test_login_displays_accessible_brand_logo():
    from PyQt5.QtWidgets import QApplication, QLabel

    from app.ui.login_window import LoginWindow

    app = QApplication.instance() or QApplication([])
    window = LoginWindow(demo_mode=True)
    logo = window.findChild(QLabel, "loginBrandLogo")

    assert app is not None
    assert logo is not None
    assert logo.accessibleName() == "Logo FEMAG"
    assert logo.pixmap() is not None and not logo.pixmap().isNull()
    window.close()


def test_login_branding_does_not_overlap_title_or_subtitle():
    from PyQt5.QtWidgets import QApplication, QDialog, QLabel

    from app.ui.login_window import LoginWindow

    app = QApplication.instance() or QApplication([])
    window = LoginWindow(demo_mode=True)
    QDialog.show(window)
    app.processEvents()
    logo = window.findChild(QLabel, "loginBrandLogo")
    title = window.findChild(QLabel, "loginTitle")
    subtitle = window.findChild(QLabel, "loginSubtitle")

    assert logo.geometry().bottom() < title.geometry().top(), (
        logo.geometry().getRect(),
        title.geometry().getRect(),
    )
    assert title.geometry().bottom() < subtitle.geometry().top()
    assert window.height() >= window.minimumSizeHint().height()
    window.close()


def test_workspace_displays_balanced_branding_and_window_icon(db):
    from PyQt5.QtWidgets import QApplication, QLabel

    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    PermissionService().seed_defaults()
    user = AuthService().create_user("branding_admin", "clave", "Administrador")
    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=user, demo_mode=True)

    sidebar_logo = window.findChild(QLabel, "sidebarBrandLogo")
    topbar_logo = window.findChild(QLabel, "topbarBrandLogo")
    assert sidebar_logo is not None
    assert sidebar_logo.pixmap() is not None and not sidebar_logo.pixmap().isNull()
    assert topbar_logo is not None
    assert topbar_logo.pixmap() is not None and not topbar_logo.pixmap().isNull()
    assert not window.windowIcon().isNull()
    assert not app.windowIcon().isNull()
    window.close()
