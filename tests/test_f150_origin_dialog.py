"""El dialogo de origen DGR no se rompe al filtrar ni preselecciona mal.

Dos regresiones que solo aparecian en la pantalla y rompian el uso:

1. ``filter.textChanged`` se conectaba directo a ``_reload``, que espera la
   localidad configurada. Qt le pasaba el texto escrito, un ``str``, y el
   dialogo caia con ``'str' object has no attribute 'locality_code'`` al
   tipear un solo caracter.
2. La preseleccion recorria el indice del combo buscando en
   ``self._localities``. El combo solo tiene las localidades que pasan el
   filtro, asi que el indice N del combo no es el indice N de la lista: con un
   filtro activo preseleccionaba otra localidad, o una que no estaba en la
   lista.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from app.models.dgr import DgrCountry, DgrLocality  # noqa: E402
from app.services.f150_encoder import F150Location  # noqa: E402


# QApplication en referencia de modulo: si queda en una local, el recolector la
# libera y Qt se usa destruido.
_QT_APP = None


def _localidad(country, code, name, dgr_code, dgr_id):
    return DgrLocality.create(
        code=code,
        name=name,
        dgr_id=dgr_id,
        dgr_code=dgr_code,
        department_code=10,
        province_code=14,
        country=country,
        source_system="test",
        source_id=code,
    )


def _pais(db):
    return DgrCountry.create(legacy_id=200, name="ARGENTINA", abbr="ARG")


def _tres_localidades(db):
    country = _pais(db)
    return [
        _localidad(country, "2426", "CAPIOVI", 15, 26),
        _localidad(country, "2427", "POSADAS", 20, 27),
        _localidad(country, "2428", "CORONEL SUAREZ", 21, 28),
    ]


def _app():
    global _QT_APP
    if _QT_APP is None:
        _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def test_escribir_en_el_filtro_no_revienta(db):
    """La senal textChanged entrega texto, no la localidad configurada."""
    _app()
    from app.ui.f150 import OriginLocalityDialog

    localidades = _tres_localidades(db)
    dialog = OriginLocalityDialog(None, localidades, F150Location())

    dialog.filter.setText("POS")

    assert dialog.list.count() == 1
    assert "POSADAS" in dialog.list.itemText(0)


def test_preselecciona_la_localidad_configurada(db):
    _app()
    from app.ui.f150 import OriginLocalityDialog

    localidades = _tres_localidades(db)
    dialog = OriginLocalityDialog(None, localidades, F150Location(locality_code="0020"))

    assert "POSADAS" in dialog.list.currentText()


def test_preselecciona_respetando_el_filtro(db):
    """Con filtro activo, el indice del combo no es el indice de la lista."""
    _app()
    from app.ui.f150 import OriginLocalityDialog

    localidades = _tres_localidades(db)
    dialog = OriginLocalityDialog(None, localidades, F150Location(locality_code="0020"))

    dialog.filter.setText("POS")

    assert dialog.list.count() == 1
    assert dialog.list.currentIndex() == 0
    assert "POSADAS" in dialog.list.currentText()


def test_aceptar_devuelve_el_id_de_la_localidad_elegida(db):
    _app()
    from app.ui.f150 import OriginLocalityDialog

    localidades = _tres_localidades(db)
    dialog = OriginLocalityDialog(None, localidades, F150Location())

    dialog.filter.setText("CORONEL")
    dialog._accept()

    assert dialog.selected_id() == localidades[2].id