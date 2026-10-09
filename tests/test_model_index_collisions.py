"""Los indices de Meta.indexes no pueden chocar con los de las claves foraneas.

peewee (y MySQL) nombran el indice automatico de una FK como ``<tabla>_<columna>``,
y la columna de una FK ya trae el sufijo ``_id``. Un indice declarado en
``Meta.indexes`` sobre ese mismo campo genera exactamente el mismo nombre, MySQL
responde ``1061 Duplicate key name`` y ``create_tables()`` aborta: la app no
arranca contra una base donde la tabla todavia no existe.

SQLite acepta el nombre repetido, asi que la colision solo se manifiesta contra
MySQL. Estos tests corren sobre SQLite, asi que son la unica red que la detecta.
"""

import pytest
from peewee import ForeignKeyField

from app.models import ALL_MODELS

# Colisiones preexistentes que todavia no se corrigieron. La tabla `client` ya
# existe en las bases instaladas, con lo que create_table(safe=True) nunca la
# intenta y el choque no se manifiesta en produccion; si en cambio impide crear
# una base MySQL desde cero.
COLISIONES_CONOCIDAS = {
    ("client", "client_salesperson_id"),
}


def _nombre_del_indice_declarado(model, campos, unique):
    """Reproduce el nombre que peewee genera para un indice de Meta.indexes."""
    columnas = [model._meta.fields[nombre].column_name for nombre in campos]
    base = columnas[0] if len(columnas) == 1 else "_".join(columnas)
    if unique:
        base += "_unq"
    return f"{model._meta.table_name}_{base}"


def _colisiones():
    """Devuelve {(tabla, nombre_indice)} para todos los modelos."""
    encontradas = set()
    for model in ALL_MODELS:
        tabla = model._meta.table_name
        indices_de_fk = {
            f"{tabla}_{campo.column_name}"
            for campo in model._meta.fields.values()
            if isinstance(campo, ForeignKeyField)
        }
        for campos, unique in model._meta.indexes:
            nombre = _nombre_del_indice_declarado(model, campos, unique)
            if nombre in indices_de_fk:
                encontradas.add((tabla, nombre))
    return encontradas


def test_no_hay_indice_declarado_que_duplique_el_de_una_clave_foranea():
    """ProductionBag declaraba indices sobre part y product: MySQL los rechazaba."""
    colisiones = _colisiones() - COLISIONES_CONOCIDAS
    assert not colisiones, (
        "estos indices de Meta.indexes repiten el nombre que la clave foranea ya "
        f"genera y rompen create_tables() en MySQL: {sorted(colisiones)}"
    )


def test_production_bag_no_declara_indices_sobre_sus_claves_foraneas():
    """Regresion directa de #580: part y product ya traen su propio indice."""
    from app.models.production import ProductionBag

    assert tuple(ProductionBag._meta.indexes) == ()


@pytest.mark.parametrize("nombre", sorted(nombre for _, nombre in COLISIONES_CONOCIDAS))
def test_colisiones_conocidas_siguen_de_pendientes(nombre):
    """Documenta las colisiones preexistentes: si se corrigen, sacarlas de la lista.

    No es un test que pueda pasar hoy. Sirve para que quede explicito que
    Client arrastra el mismo problema y para que, cuando alguien lo arregle, este
    test lo senale en vez de dejar el arreglo pasar inadvertido.
    """
    pendientes = {nombre for _, nombre in _colisiones()}
    assert nombre in pendientes or not pendientes, (
        f"{nombre} ya no choca: sacalo de COLISIONES_CONOCIDAS."
    )
