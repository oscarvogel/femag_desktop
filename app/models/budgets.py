from datetime import date

from peewee import CharField, DateField, FloatField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel
from app.models.load_orders import (
    BILLING_TIMING_DEFERRED,
    BILLING_TIMING_IMMEDIATE,
    LoadOrder,
    LoadOrderProduct,
)
from app.models.masters import Client, Product


class Budget(BaseModel):
    ORIGIN_LOAD_ORDER = "load_order"
    ORIGIN_MANUAL = "manual"

    TIMING_IMMEDIATE = BILLING_TIMING_IMMEDIATE
    TIMING_DEFERRED = BILLING_TIMING_DEFERRED

    STATUS_ACTIVE = "active"
    STATUS_ANNULLED = "annulled"

    budget_number = IntegerField(unique=True)
    client = ForeignKeyField(Client, backref="budgets")
    load_order = ForeignKeyField(LoadOrder, backref="budgets", null=True)
    origin = CharField()
    # Momento de facturación. Una orden puede emitir un presupuesto por
    # cliente para cada parte, y el índice único de abajo los distingue.
    timing = CharField(default=TIMING_IMMEDIATE)
    issue_date = DateField(default=date.today)
    status = CharField(default=STATUS_ACTIVE)
    observations = TextField(null=True)
    net_amount = FloatField(default=0.0)
    discount_amount = FloatField(default=0.0)
    vat_amount = FloatField(default=0.0)
    total_amount = FloatField(default=0.0)
    created_by = CharField(null=True)

    @property
    def display_number(self) -> str:
        return f"PRES-{self.budget_number:06d}"

    @property
    def load_order_reference(self) -> str | None:
        if self.load_order_id is None:
            return None
        return f"OC-{self.load_order.order_number:06d}"

    @property
    def timing_label(self) -> str:
        return "Facturado ahora" if self.timing == self.TIMING_IMMEDIATE else "A facturar después"

    class Meta:
        indexes = ((("load_order", "client", "origin", "timing"), True),)


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
    unit_price = FloatField(default=0.0)
    discount_percentage = FloatField(default=0.0)
    net_subtotal = FloatField(default=0.0)
    discount_amount = FloatField(default=0.0)
    net_taxable = FloatField(default=0.0)
    vat_percentage = FloatField(default=21.0)
    vat_amount = FloatField(default=0.0)
    total = FloatField(default=0.0)
    observations = TextField(null=True)
