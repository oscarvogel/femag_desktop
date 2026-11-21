from peewee import BooleanField, CharField, DateTimeField, ForeignKeyField, TextField

from app.models.base import BaseModel, utc_now


class Supplier(BaseModel):
    """Maestro de proveedores/colonos (#938).

    El legacy `femagfab.proveedo` identifica al productor con un `CODIGO` de
    cuatro caracteres, sin DNI ni CUIT, y **repite nombres**: 23 grupos donde la
    misma persona aparece con dos codigos y su deuda queda partida entre los
    dos (TERESCHUK ALBERTO CESAR 0993 + 1025 = 1.233.645 Gs).

    Por eso el maestro de FEMAG Desktop separa las dos cosas:

    - :class:`Supplier` es **la persona**: un solo registro por productor, con
      su nombre, su localidad, su telefono y, cuando la planta lo brinde, su
      CUIT o DNI.
    - :class:`SupplierLegacyCode` es **la ficha del legacy**: un codigo de
      cuatro caracteres con el nombre tal como venia. Uno o varios codigos
      pueden apuntar a la misma persona.

    La deduplicacion es por nombre normalizado (sin tildes, sin mayusculas, sin
    espacios repetidos) y queda **marcada como no verificada**:
    ``identity_verified`` solo lo pone la planta, cuando conoce al productor.
    """

    name = CharField(max_length=80)
    # Nombre normalizado: es la clave con la que se detectan los duplicados
    # del legacy. Se guarda para poder auditar por que se unificaron dos fichas.
    normalized_name = CharField(max_length=80)
    locality = CharField(max_length=40, null=True)
    phone = CharField(max_length=40, null=True)
    # El legacy no tiene CUIT ni DNI del productor. Es el dato que falta para
    # poder afirmar que dos fichas son la misma persona.
    tax_id = CharField(max_length=20, null=True)
    active = BooleanField(default=True)
    identity_verified = BooleanField(default=False)
    notes = TextField(null=True)
    imported_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "supplier"
        indexes = ((("normalized_name",), False),)

    @property
    def legacy_code_list(self) -> list[str]:
        """Codigos del legacy que corresponden a esta persona."""
        return sorted(ficha.code for ficha in self.legacy_code_rows)


class SupplierLegacyCode(BaseModel):
    """Ficha del legacy (`femagfab.proveedo`) que corresponde a un proveedor.

    El ``source_key`` es unico (`femagfab:proveedo:0993`), asi que reimportar el
    maestro no duplica nada: la ficha se actualiza en el lugar.
    """

    supplier = ForeignKeyField(
        Supplier, backref="legacy_code_rows", on_delete="CASCADE"
    )
    source_instance = CharField(max_length=80, default="femagfab")
    code = CharField(max_length=4)
    source_key = CharField(max_length=180, unique=True)
    # El nombre tal como venia en el legacy: puede diferir del nombre canonico
    # de la persona (espacios de mas, tildes, abreviaturas).
    name = CharField(max_length=80)
    locality = CharField(max_length=40, null=True)
    phone = CharField(max_length=40, null=True)
    imported_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "supplier_legacy_code"
        indexes = ((("code",), False),)
