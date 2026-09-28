from datetime import date
from decimal import Decimal

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.masters import Carrier, Client, Driver, Product, Truck
from app.reports.product_profitability import ProductProfitabilityService


def test_summary_groups_same_product_and_preserves_cost_coverage(db):
    client=Client.create(name="Cliente resumen",cuit="30756301001",iva_condition="RI")
    carrier=Carrier.create(name="Transporte resumen",cuit="30756301002")
    driver=Driver.create(name="Chofer resumen",carrier=carrier,document="563-summary")
    truck=Truck.create(domain="SUM563",carrier=carrier)
    product=Product.create(name="Fecula resumen",unit="kg")
    order=LoadOrder.create(order_number=563100,date=date.today(),client=client,carrier=carrier,driver=driver,truck=truck,status=LoadOrder.STATUS_ISSUED)
    LoadOrderProduct.create(order=order,product=product,quantity=10,unit="kg",precio_neto_unitario=100,neto_gravado=1000,total=1210,costo_unitario_aplicado=Decimal("60"))
    LoadOrderProduct.create(order=order,product=product,quantity=5,unit="kg",precio_neto_unitario=100,neto_gravado=500,total=605,costo_unitario_aplicado=None)

    snap=ProductProfitabilityService().snapshot(date.today(),date.today())
    row=snap.products[0]
    assert row.product=="Fecula resumen"
    assert row.quantity==15
    assert row.sales==1500
    assert row.cost==600
    assert row.gross_profit==400
    assert row.margin_percent==40
    assert row.cost_coverage_percent==66.67
