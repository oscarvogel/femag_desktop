from datetime import date
from decimal import Decimal

from app.importers.dgr_reference import DgrReferenceImporter
from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.remittance_service import RemittanceService


DGR_ROWS = {
    "paises": [{"IDPAIS": 200, "NOMBRE": "ARGENTINA", "ABR": "ARG"}],
    "provincias": [{"CODIGO": 14, "DESCRIPCIO": "MISIONES"}],
    "locdgr": [
        {"IDLOCALIDA": 61, "CODIGODGR": 61, "PROVINCIA": 14, "DPTO": 10,
         "DESCRIPCIO": "PUERTO RICO"}
    ],
    "localidades": [
        {"CODIGO": "2457", "LOCALIDAD": "PUERTO RICO", "CODIGODGR": 61,
         "PAISDGR": 200, "PROVDGR": 14, "DEPA": 10, "PROVINCIA": "MISIONES"}
    ],
}


def test_master_import_captures_f150_codes(db):
    DgrReferenceImporter().import_rows(DGR_ROWS)
    LegacyDbfMasterImporter().import_rows(
        {
            "carriers": [
                {"CODIGO": "0004", "NOMBRE": "Transporte 404", "CUIT": "20-23737702-9",
                 "TIPO": "DIR", "LOCALIDAD": "2457"}
            ],
            "drivers": [
                {"CODIGO": "0007", "NOMBRE": "Chofer 404", "CUIT": "20-30717891-6",
                 "LOCALIDAD": "2457", "TRANSP": "0004", "CHASIS": "GET683",
                 "ACOPLADO": "KKV479", "TIPOPATE": "1", "TIPOPATEAC": "1"}
            ],
            "products": [
                {"CODIGO": "0001", "NOMBRE": "Almidon 404", "UNIDADDGR": "U",
                 "RH1": "2", "RH2": "2", "RH3": "19", "RH4": "0"}
            ],
            "clients": [
                {"CODIGO": "0404", "NOMBRE": "Cliente 404", "CUIT": "30-63634545-4",
                 "DOMICILIO": "Ruta 12", "LOCALIDAD": "2457"}
            ],
        },
        source_system="legacy_dbf",
    )

    carrier = Carrier.get(Carrier.name == "Transporte 404")
    assert carrier.codigo == "0004"
    assert carrier.tipo == "DIR"
    assert carrier.locality.code == "2457"

    driver = Driver.get(Driver.name == "Chofer 404")
    assert driver.locality.code == "2457"
    assert driver.usual_truck.domain == "GET683"
    assert driver.usual_truck.trailer_domain == "KKV479"
    assert driver.usual_truck.chassis_type == "1"
    assert driver.usual_truck.trailer_type == "1"

    product = Product.get(Product.name == "Almidon 404")
    assert (product.rh1, product.rh2, product.rh3, product.rh4) == ("2", "2", "19", "0")
    assert product.unidad_dgr == "U"

    client = Client.get(Client.name == "Cliente 404")
    address = ClientAddress.select().where(ClientAddress.client == client).first()
    assert address is not None
    assert address.locality.code == "2457"


def _coded_setup():
    DgrReferenceImporter().import_rows(DGR_ROWS)
    AppParameter.create(key="f150.origin", value='{"locality_code": "2426"}')
    locality = DgrLocality.get(DgrLocality.code == "2457")
    client = Client.create(name="Cliente 404b", cuit="30-63634545-4", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8", locality=locality,
    )
    carrier = Carrier.create(
        name="Transporte 404b", cuit="20-23737702-9", codigo="0004",
        tipo="DIR", locality=locality,
    )
    truck = Truck.create(
        domain="GET683", trailer_domain="KKV479", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="Chofer 404b", carrier=carrier, usual_truck=truck,
        cuit="20-30717891-6", document="30717891", locality=locality,
    )
    product = Product.create(
        codigo="G-300", name="Almidon 404b", unit="bolsa", precio_neto_base=18600.0,
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="U",
    )
    return client, address, carrier, truck, driver, product


def test_generate_maps_master_codes_to_legacy_positions(db, tmp_path):
    client, address, carrier, truck, driver, product = _coded_setup()
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="4040",
        remittance_date=date(2026, 9, 7),
        items=[{"product": product, "quantity": Decimal("500")}],
    )
    issued = service.issue(remittance)
    output = tmp_path / "f150-404b.TXT"
    F150BatchService("admin").generate([issued], output)
    lines = output.read_bytes().decode("cp1252").splitlines()

    header = lines[0]
    assert len(header.split("@")) == 50
    assert not header.endswith("@")
    for field in ("@DIR@", "@0004@", "@0061@", "@PUERTO RICO@", "@14@", "@ARG@",
                  "@20-30717891-6@DNI@30717891@", "@30-63634545-4@"):
        assert field in header, field

    detail = lines[1]
    assert len(detail.split("@")) == 16
    assert detail.endswith("@")
    assert "@2@2@19@0@G-300@U@500@" in detail
