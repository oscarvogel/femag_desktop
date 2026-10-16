"""#717: el arranque ofrece actualizar el esquema en vez de negarse a entrar.

Antes, con la conexion ya guardada, un puesto con la base atrasada moria con
un mensaje que mandaba a ejecutar un script de desarrollo. Este PR agrega el
camino que si llega al puesto: preguntar y aplicar la migracion con la
credencial administrativa, sin guardarla, y tolerar la carrera entre dos
puestos que migran al mismo tiempo.

Los tests de esquema van aparte de los de interfaz a proposito: mezclar un
import de ``app.config.schema`` con la creacion de widgets Qt dentro del mismo
proceso de pytest lo deja colgado en Windows. Separados, cada uno pasa.
"""

import pytest


class _BaseNormal:
    def __init__(self):
        self.sentencias = []

    def execute_sql(self, sql, params=None):
        self.sentencias.append(sql)


class _BaseQueFalla:
    """Doble que simula MySQL diciendo que la sentencia ya se aplico."""

    def __init__(self, codigo):
        self.codigo = codigo
        self.sentencias = []

    def execute_sql(self, sql, params=None):
        self.sentencias.append(sql)
        raise Exception(self.codigo, "Duplicate column name 'address'")


class _BaseConOtroError:
    def execute_sql(self, sql, params=None):
        raise Exception(1142, "SELECT command denied to user")


def test_sentencia_de_esquema_normal_se_aplica():
    from app.config.schema import _execute_schema_statement

    base = _BaseNormal()
    assert _execute_schema_statement(base, "ALTER TABLE `x` ADD COLUMN `y` INT NULL") is True
    assert base.sentencias


@pytest.mark.parametrize("codigo", [1060, 1061, 1062])
def test_carrera_entre_dos_puestos_no_es_error(codigo):
    """1060 columna duplicada, 1061 indice duplicado, 1062 entrada duplicada.

    Dos puestos que abren la actualizacion al mismo tiempo corren la misma
    migracion. El segundo llega y la columna ya esta: no es un fallo.
    """
    from app.config.schema import _execute_schema_statement

    base = _BaseQueFalla(codigo)
    assert _execute_schema_statement(base, "ALTER TABLE `x` ADD COLUMN `y` INT NULL") is False


def test_otro_error_se_propaga():
    """Solo se tolerancia lo que es carrera. Un permiso denegado es un fallo."""
    from app.config.schema import _execute_schema_statement, _mysql_error_code

    with pytest.raises(Exception) as error:
        _execute_schema_statement(_BaseConOtroError(), "ALTER TABLE `x` ADD COLUMN `y` INT NULL")
    assert _mysql_error_code(error.value) == 1142


def test_error_sin_codigo_no_se_traga():
    from app.config.schema import _execute_schema_statement

    class _SinCodigo(Exception):
        pass

    base = _BaseNormal()

    def _explota(sql, params=None):
        raise _SinCodigo("se rompio")

    base.execute_sql = _explota
    with pytest.raises(_SinCodigo):
        _execute_schema_statement(base, "ALTER TABLE `x` ADD COLUMN `y` INT NULL")