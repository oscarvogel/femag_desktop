from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    ForeignKeyField,
    TextField,
)

from app.models.base import BaseModel, utc_now


class Supplier(BaseModel):
    """Maestro de proveedores/colonos (#938).

    El legacy `femagfab.proveedo` identifica al productor con un `CODIGO` de
    cuatro caracteres, sin DNI ni CUIT, y **repite nombres**: 23 grupos donde la
    misma persona aparece con dos codigos y su deuda queda partida entre los
    dos (TERESCHUK ALBERTO CESAR 0993 + 1025 = 1.233.645 ARS).

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


class SupplierDocument(BaseModel):
    """Documento que genera deuda con un proveedor (#939).

    Son los dos documentos del legacy: el **ticket de materia prima**
    (`femagfab.movi`) y el **pagare** (`femagfab.documentos`). Cada uno se
    importa con su importe original y con el saldo que el legacy tiene
    pendiente.

    El legacy no tiene libro de movimientos: descuenta el `SALDO` del documento
    cuando alguien paga, sin dejar rastro. Por eso este modelo guarda el saldo
    **como estaba al importar**, y a partir de ahi la imputacion de pagos es
    cosa de FEMAG Desktop (#940).

    Las marcas de la fila cuentan que se le hizo al dato de origen:

    - ``balance_corrected``: el legacy guardaba el precio por tonelada en vez
      del total. El saldo importado es el recalculado con la misma formula del
      legacy (``kilos x precio / 1000``).
    - ``date_inferred``: la fecha del legacy no era confiable (bloque con
      ``FECHA = 2002-01-01``) y se dedujo de los tickets vecinos por numero de
      ``COMP``.
    """

    KIND_TICKET = "raw_material_ticket"
    KIND_PROMISSORY_NOTE = "promissory_note"
    KINDS = (KIND_TICKET, KIND_PROMISSORY_NOTE)

    supplier = ForeignKeyField(
        Supplier, backref="documents", on_delete="CASCADE"
    )
    kind = CharField(max_length=32)
    source_key = CharField(max_length=180, unique=True)
    source_instance = CharField(max_length=80, default="femagfab")
    # `COMP` del ticket o codigo del pagare, tal como en el legacy.
    source_code = CharField(max_length=12)
    issued_at = DateField(null=True)
    date_inferred = BooleanField(default=False)
    # Ventana dentro de la cual se puede afirmar la fecha, cuando se dedujo.
    date_bracket_from = DateField(null=True)
    date_bracket_to = DateField(null=True)
    product_code = CharField(max_length=2, null=True)
    quantity_kg = DecimalField(max_digits=14, decimal_places=2, null=True)
    price_per_ton = DecimalField(max_digits=12, decimal_places=2, null=True)
    # Importe original: lo que se le debia cuando se emitio el documento.
    amount = DecimalField(max_digits=14, decimal_places=2)
    # Saldo pendiente al momento de la importacion.
    balance = DecimalField(max_digits=14, decimal_places=2)
    # El legacy no tiene columna de moneda: es una sola moneda, la de la
    # empresa (pesos argentinos). Se deja explicito para que el documento no
    # dependa de esa suposicion, igual que en la cuenta corriente de clientes.
    currency = CharField(max_length=8, default="ARS")
    balance_corrected = BooleanField(default=False)
    description = CharField(max_length=120, null=True)
    source_hash = CharField(max_length=64)
    imported_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "supplier_document"
        indexes = (
            (("supplier", "issued_at"), False),
            (("kind",), False),
        )

    @property
    def kind_label(self) -> str:
        if self.kind == self.KIND_TICKET:
            return "Ticket de materia prima"
        return "Pagare"


class SupplierDocumentExclusion(BaseModel):
    """Documento del legacy que **no** se importo, con el motivo (#939).

    Excluir es esconder: cada exclusion es deuda que la pantalla no va a
    mostrar. Por eso queda guardada, con su monto y su motivo, para poder
    publicarla y revisarla.
    """

    REASON_NO_QUANTITY = "sin_kilos_o_precio"
    REASON_BALANCE_OUT_OF_RANGE = "saldo_fuera_de_rango"
    REASON_WITHOUT_SUPPLIER = "sin_proveedor"
    REASON_ALREADY_IMPORTED = "ya_importado"

    kind = CharField(max_length=32)
    source_key = CharField(max_length=180, unique=True)
    source_code = CharField(max_length=12)
    supplier_code = CharField(max_length=4, null=True)
    amount = DecimalField(max_digits=14, decimal_places=2)
    reason = CharField(max_length=64)
    detail = TextField(null=True)
    detected_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "supplier_document_exclusion"
        indexes = ((("reason",), False),)
