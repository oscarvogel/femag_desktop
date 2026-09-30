from datetime import date

from peewee import CharField, DateField, FloatField, ForeignKeyField, IntegerField, TextField

from app.config.money_columns import money_field
from app.models.base import BaseModel
from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.masters import Client, Product


class Budget(BaseModel):
    ORIGIN_LOAD_ORDER = "load_order"
    ORIGIN_MANUAL = "manual"

    STATUS_ACTIVE = "active"
    STATUS_ANNULLED = "annulled"

    budget_number = IntegerField(unique=True)
    client = ForeignKeyField(Client, backref="budgets")
    load_order = ForeignKeyField(LoadOrder, backref="budgets", null=True)
    origin = CharField()
    issue_date = DateField(default=date.today)
    status = CharField(default=STATUS_ACTIVE)
    observations = TextField(null=True)
    # Dinero en DECIMAL(18,2): el importe es parte de la identidad del
    # documento y no puede depender de la precisión simple de FLOAT.
    net_amount = money_field()
    discount_amount = money_field()
    vat_amount = money_field()
    total_amount = money_field()
    created_by = CharField(null=True)

    @property
    def display_number(self) -> str:
        return f"PRES-{self.budget_number:06d}"

    @property
    def load_order_reference(self) -> str | None:
        if self.load_order_id is None:
            return None
        return f"OC-{self.load_order.order_number:06d}"

    class Meta:
        indexes = ((("load_order", "client", "origin"), True),)


class BudgetItem(BaseModel):
    budget = ForeignKeyField(Budget, backref="items", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="budget_items")
    source_order_product = ForeignKeyField(
        LoadOrderProduct,
        backref="budget_items",
        null=True,
        on_delete="SET NULL",
    )
    quantity = FloatField()
    unit = CharField()
    unit_price = money_field()
    discount_percentage = FloatField(default=0.0)
    net_subtotal = money_field()
    discount_amount = money_field()
    net_taxable = money_field()
    vat_percentage = FloatField(default=21.0)
    vat_amount = money_field()
    total = money_field()
    observations = TextField(null=True)
