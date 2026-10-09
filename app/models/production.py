from peewee import (
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    ForeignKeyField,
    IntegerField,
    TextField,
)

from app.models.base import BaseModel, utc_now
from app.models.masters import Product


class RawMaterialReceipt(BaseModel):
    """Snapshot inmutable/auditable de un ticket finalizado en femagfab.movi."""

    source_key = CharField(max_length=180, unique=True)
    source_instance = CharField(max_length=80, default="femagfab")
    source_comp = CharField(max_length=12)
    source_hash = CharField(max_length=64)

    received_at = DateTimeField()
    supplier_code = CharField(max_length=4)
    supplier_name = CharField(max_length=80, null=True)
    product_code = CharField(max_length=2)
    product_name = CharField(max_length=80, null=True)

    gross_kg = DecimalField(max_digits=12, decimal_places=2)
    tare_kg = DecimalField(max_digits=12, decimal_places=2)
    net_kg = DecimalField(max_digits=12, decimal_places=2)
    payable_kg = DecimalField(max_digits=12, decimal_places=2)
    earth_discount_pct = DecimalField(max_digits=7, decimal_places=2, default=0)
    cepa_discount_pct = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_1 = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_2 = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_3 = DecimalField(max_digits=7, decimal_places=2, default=0)
    yield_average = DecimalField(max_digits=7, decimal_places=2)
    legacy_starch_kg = DecimalField(max_digits=12, decimal_places=2, default=0)
    theoretical_starch_kg = DecimalField(max_digits=12, decimal_places=2)
    source_payload = TextField()
    imported_at = DateTimeField(default=utc_now)

    class Meta:
        table_name = "raw_material_receipt"
        indexes = ((("received_at",), False), (("source_comp",), False))


class ProductionPart(BaseModel):
    """Parte de embolsado por fecha y turno.

    A partir de #580 el parte ya no pide kg de mandioca procesada ni de fécula
    producida: en planta esos datos no se pueden medir. Lo que se registra es
    cuántas bolsas de cada producto se embolsaron, en :class:`ProductionBag`.

    El parte tiene estados. Mientras ``confirmed_at`` está vacío es un
    borrador: se puede editar y borrar libremente, y **no toca el stock**. Al
    confirmarlo, el operador lo convierte en producción real y en ese momento
    se escriben los movimientos ``PRODUCCION`` en el libro de stock (#572). Un
    parte confirmado ya no se edita ni se borra: se anula generando los
    movimientos contrarios, y queda el rastro de quien lo hizo y por qué.
    """

    production_date = DateField()
    shift = CharField(max_length=40)
    observations = TextField(null=True)

    confirmed_at = DateTimeField(null=True)
    confirmed_by = CharField(max_length=80, null=True)

    voided_at = DateTimeField(null=True)
    voided_by = CharField(max_length=80, null=True)
    void_reason = TextField(null=True)

    class Meta:
        table_name = "production_part"
        indexes = ((("production_date", "shift"), False),)

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    @property
    def status_label(self) -> str:
        if self.is_voided:
            return "Anulado"
        return "Confirmado" if self.is_confirmed else "Borrador"


class ProductionBag(BaseModel):
    """Bolsas embolsadas de un producto terminado dentro de un turno.

    ``unit_weight_kg`` es una copia del peso del producto al momento del
    registro: si despues se corrige el maestro, la produccion ya registrada
    no debe cambiar. ``kg`` queda congelado por el mismo motivo.
    """

    part = ForeignKeyField(ProductionPart, backref="bags", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="production_bags", on_delete="RESTRICT")
    bags = IntegerField()
    unit_weight_kg = DecimalField(max_digits=12, decimal_places=3)
    kg = DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        table_name = "production_bag"
        # Sin indices declarados a proposito: `part` y `product` son claves
        # foraneas y ya generan su propio indice. Declarar aqui un indice sobre
        # esos mismos campos produce el MISMO nombre que el indice automatico de
        # la FK (peewee deriva el nombre de la columna, que ya trae el sufijo
        # _id) y MySQL responde 1061 Duplicate key name, con lo que
        # create_tables() aborta y la app no arranca. SQLite tolera el nombre
        # duplicado, por eso el choque solo aparece contra MySQL.
        pass


class RawMaterialIntake(BaseModel):
    """Ingreso de materia prima comprada en big bags (#656).

    Es la primera mitad del circuito del fraccionado y hoy no existia de ninguna
    forma: el legacy `femagfab` recibe raiz de mandioca, no big bags de almidon
    (sus 6 productos son todos mandioca), y FEMAG Desktop no tenia ningun modulo
    de compras. `StockMovement.TYPE_PURCHASE` estaba declarado desde #572 sin
    que ningun servicio lo escribiera.

    A diferencia de :class:`RawMaterialReceipt`, que es un snapshot de solo
    lectura de un ticket ajeno, este ingreso es un documento propio de FEMAG y
    **si mueve el stock**: al confirmarse escribe los movimientos de compra.

    Los estados son los de :class:`ProductionPart`. Mientras ``confirmed_at``
    esta vacio es un borrador: se edita y se borra libremente y no toca el
    stock. Al confirmar, la materia prima entra al libro. Un ingreso confirmado
    ya no se edita: se anula generando los movimientos contrarios.
    """

    received_at = DateField()
    observations = TextField(null=True)

    confirmed_at = DateTimeField(null=True)
    confirmed_by = CharField(max_length=80, null=True)

    voided_at = DateTimeField(null=True)
    voided_by = CharField(max_length=80, null=True)
    void_reason = TextField(null=True)

    class Meta:
        table_name = "raw_material_intake"
        indexes = ((("received_at",), False),)

    @property
    def is_confirmed(self) -> bool:
        return self.confirmed_at is not None

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    @property
    def status_label(self) -> str:
        if self.is_voided:
            return "Anulado"
        return "Confirmado" if self.is_confirmed else "Borrador"


class RawMaterialIntakeLine(BaseModel):
    """Big bags de una materia prima que entran en un ingreso.

    ``bags`` es la unidad que el operador cuenta: en planta **no se pesa**
    almidon suelto, se cuentan big bags. El libro de stock sigue trabajando en
    kg, asi que la linea guarda el peso del big bag **congelado** en
    ``unit_weight_kg`` y deriva los kg, exactamente igual que hace
    :class:`ProductionBag` con el peso de la bolsa.

    Que el peso quede congelado no es un detalle: si despues se corrige el
    maestro, el ingreso ya registrado no debe cambiar, porque el movimiento de
    stock que lo respalda tampoco.
    """

    intake = ForeignKeyField(RawMaterialIntake, backref="lines", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="intake_lines", on_delete="RESTRICT")
    bags = IntegerField()
    unit_weight_kg = DecimalField(max_digits=12, decimal_places=3)
    kg = DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        table_name = "raw_material_intake_line"
        # Sin indices declarados a proposito, por la misma razon que en
        # ``ProductionBag``: las dos claves foraneas ya generan su indice y
        # duplicar el nombre hace fallar create_tables() contra MySQL.
        pass
