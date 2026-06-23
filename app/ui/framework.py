from dataclasses import dataclass
from importlib.util import find_spec


@dataclass(frozen=True)
class UIFramework:
    name: str
    qt_binding: str
    required_components: tuple[str, ...]
    installed: bool
    install_note: str


def get_ui_framework() -> UIFramework:
    return UIFramework(
        name="pyqt5libs",
        qt_binding="PyQt5",
        required_components=("ABM", "tables", "buttons", "forms", "views"),
        installed=find_spec("pyqt5libs") is not None,
        install_note="Instalar pyqt5libs desde el origen privado acordado para FEMAG.",
    )
