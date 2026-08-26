import sys
from pathlib import Path

from peewee import SqliteDatabase


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.services.remittance_print_service import RemittancePrintService
from app.services.remittance_service import RemittanceService


DEFAULT_OUTPUT = Path("output") / "pdf" / "issue_351_remittance_preview.pdf"


def generate(output: Path = DEFAULT_OUTPUT) -> Path:
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    try:
        client = Client.create(
            name="Cliente FEMAG",
            cuit="30-71234567-8",
            iva_condition="Responsable inscripto",
        )
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            address="Ruta 12 km 1540",
            city="Eldorado",
            province="Misiones",
            is_primary=True,
        )
        carrier = Carrier.create(name="Transporte Norte", cuit="30-77777777-0")
        truck = Truck.create(
            domain="AB123CD",
            trailer_domain="AC456EF",
            carrier=carrier,
        )
        driver = Driver.create(
            name="Juan Perez",
            document="30111222",
            carrier=carrier,
            usual_truck=truck,
        )
        product = Product.create(name="Fecula de mandioca", unit="kg")
        remittance = RemittanceService(current_user="issue351").create_manual(
            client=client,
            delivery_address=address,
            carrier=carrier,
            truck=truck,
            driver=driver,
            document_reference="OC 000351",
            items=[
                {
                    "product": product,
                    "quantity": 760,
                    "printed_description": "BOL FECULA 2 CALIDAD",
                }
            ],
        )
        return RemittancePrintService(current_user="issue351").export_preview(
            remittance,
            output,
        )
    finally:
        database.close()


if __name__ == "__main__":
    print(generate().resolve())
