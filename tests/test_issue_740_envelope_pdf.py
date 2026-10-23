"""Tests del issue #740: PDF de sobres automatico por cliente.

Cubren lo que el issue pide explicito:

* la pagina del PDF es el sobre real de 235 x 120 mm;
* el cliente, el domicilio de destino, el telefono, el contacto y la cantidad de
  pallets salen de las fuentes reales, y los pallets se cuentan como pallets
  distintos (no como renglones ni como identificadores);
* la mercaderia sale de los renglones de la orden de carga;
* el layout es el del sobre escrito a mano: destinatario arriba a la izquierda,
  mercaderia y pallets abajo a la derecha, presupuesto abajo a la izquierda;
* el logo oficial de FEMAG va en el sobre solo si el puesto lo pide (por
  omision no va: el 21/10/2026 se pidio que el sobre no llevara logo);
* la rotacion 90/270 y los desplazamientos en mm se aplican al contenido, y
  ningun texto queda fuera de la pagina;
* en la misma operacion de exportacion salen N presupuestos y N sobres, con
  las fallas informadas cliente por cliente;
* el presupuesto, el stock y la cuenta corriente no se tocan.
"""

from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.config.envelope_settings import (
    EnvelopeSettings,
    load_envelope_settings,
    save_envelope_settings,
)
from app.models.budgets import Budget
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.services.envelope_print_service import (
    EnvelopeDataError,
    EnvelopePrintService,
)
from app.services.load_order_operation_service import LoadOrderOperationService

MM_PER_PT = 25.4 / 72.0


def _pdf_text(path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _page_size_mm(path) -> tuple[float, float]:
    reader = PdfReader(str(path))
    box = reader.pages[0].mediabox
    return (float(box.width) * MM_PER_PT, float(box.height) * MM_PER_PT)


def _content_stream(path) -> str:
    reader = PdfReader(str(path))
    page = reader.pages[0]
    data = page.get_contents()
    if data is None:
        return ""
    return data.get_data().decode("latin-1")


def _has_image(path) -> bool:
    reader = PdfReader(str(path))
    resources = reader.pages[0].get("/Resources")
    if resources is None:
        return False
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return False
    for reference in xobjects.values():
        obj = reference.get_object()
        if obj.get("/Subtype") == "/Image":
            return True
    return False


def _master_data():
    carrier = Carrier.create(name="Transportista sobres")
    driver = Driver.create(name="Chofer sobres", carrier=carrier)
    truck = Truck.create(domain="SOB01", carrier=carrier)
    return {"carrier": carrier, "driver": driver, "truck": truck}


def _client(name: str, cuit: str, address: str = "Ruta 12", city: str = "Posadas"):
    client = Client.create(name=name, cuit=cuit, iva_condition="RI", phone="0371-4000001")
    client_address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city=city,
        address=address,
        is_primary=True,
    )
    return client, client_address


def _order_with_pallets(pallets_per_client: int = 1):
    """Orden con dos clientes y pallets reales asignados por destino."""
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    client_a, address_a = _client("ALMACEN SUR S.A.", "30711111111", "Ruta 12 km 4", "Posadas")
    client_b, address_b = _client("COOPERATIVA NORTE", "30722222222", "Ruta 14 km 9", "Obera")
    product_a = Product.create(name="Fecula A", unit="kg", peso_unitario_kg=25)
    product_b = Product.create(name="Fecula B", unit="kg", peso_unitario_kg=25)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": client_a,
                "delivery_address": address_a,
                "products": [{"product": product_a, "quantity": 100 * pallets_per_client}],
            },
            {
                "client": client_b,
                "delivery_address": address_b,
                "products": [{"product": product_b, "quantity": 100 * pallets_per_client}],
            },
        ],
        pallets=[
            {
                "sequence": index,
                "allocations": [
                    {
                        "client": client_a,
                        "delivery_address": address_a,
                        "product": product_a,
                        "quantity": Decimal("100"),
                    }
                ],
            }
            for index in range(1, pallets_per_client + 1)
        ],
    )
    # Los presupuestos se emiten aca para que los tests partan del presupuesto
    # guardado, que es el punto de partida del sobre.
    from app.services.budget_service import BudgetService

    BudgetService(current_user="admin").ensure_for_load_order(order)
    return order, client_a, client_b, product_a, product_b


def _settings(**kwargs) -> EnvelopeSettings:
    return EnvelopeSettings(**kwargs)


def test_envelope_page_is_the_real_envelope_size_235x120_mm(db, tmp_path):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings()
    ).export_envelope(budget, tmp_path)

    width_mm, height_mm = _page_size_mm(path)
    assert width_mm == pytest.approx(235, abs=0.5)
    assert height_mm == pytest.approx(120, abs=0.5)


def test_envelope_carries_client_address_phone_budget_and_pallets(db, tmp_path):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings()
    ).export_envelope(budget, tmp_path)
    text = _pdf_text(path)

    assert "ALMACEN SUR S.A." in text
    assert "Ruta 12 km 4" in text
    assert "Posadas" in text
    assert "Misiones" in text
    assert "0371-4000001" in text
    assert budget.display_number in text
    # La cantidad de pallets se escribe como la escribe Secretaría a mano.
    assert "(1 pallet)" in text


def test_envelope_prints_the_merchandise_of_the_load_order(db, tmp_path):
    """La mercadería sale de los renglones de la orden: cantidad, unidad y producto."""
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings()
    ).export_envelope(budget, tmp_path)
    text = _pdf_text(path)

    assert "100 kg Fecula A" in text
    # La mercadería del otro cliente no se imprime en este sobre.
    assert "Fecula B" not in text


def test_envelope_prints_the_contact_name_next_to_the_phone(db, tmp_path):
    """El contacto del cliente va junto al teléfono, como en el sobre a mano."""
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    client_a.contact = "PERSONA DE CONTACTO"
    client_a.save()

    budget = Budget.get(Budget.client == client_a)
    path = EnvelopePrintService(
        current_user="admin", settings=_settings()
    ).export_envelope(budget, tmp_path)
    text = _pdf_text(path)

    assert "Tel: 0371-4000001 - PERSONA DE CONTACTO" in text


def test_merchandise_lines_do_not_pile_up_on_the_pallet_summary(db, tmp_path):
    """La mercadería sube desde el resumen: no se pisan ni salen del margen.

    Este es el control del defecto que se encontró al revisar el layout: las
    líneas de mercadería bajaban desde el resumen, la última caía en la misma
    baseline y se pisaba con él.
    """
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets(
        pallets_per_client=2
    )
    budget = Budget.get(Budget.client == client_a)
    service = EnvelopePrintService(current_user="admin", settings=_settings())

    texts = _device_texts(service.export_envelope(budget, tmp_path))

    summary = [row for row in texts if row[0].startswith("(2 pallets")]
    merchandise = [row for row in texts if "Fecula" in row[0]]
    assert summary, "El sobre no lleva el resumen de pallets"
    assert merchandise, "El sobre no lleva la mercadería"

    summary_y = summary[0][2]
    for text, _x, y in merchandise:
        assert abs(y - summary_y) > 1, (
            f"La mercadería se pisa con el resumen de pallets: {text!r}"
        )

    # El bloque de la derecha (mercadería y resumen) respeta el margen inferior.
    margin_pt = 12 * 72 / 25.4
    for text, x, y in texts:
        if x > 300:
            assert y >= margin_pt, (
                f"El bloque de la derecha quedó bajo el margen: {text!r} en {y}"
            )


def test_envelope_has_no_logo_by_default(db, tmp_path):
    """En el uso real de FEMAG (21/10/2026) se pidió que el sobre no lleve logo."""
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings()
    ).export_envelope(budget, tmp_path)

    assert _has_image(path) is False


def test_envelope_prints_the_official_femag_logo_when_the_post_wants_it(db, tmp_path):
    """El logo sigue disponible para los puestos que lo pidan."""
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings(show_logo=True)
    ).export_envelope(budget, tmp_path)

    assert _has_image(path) is True


def test_envelope_counts_distinct_pallets_and_not_detail_rows(db, tmp_path):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets(
        pallets_per_client=3
    )
    budget = Budget.get(Budget.client == client_a)
    service = EnvelopePrintService(current_user="admin", settings=_settings())

    data = service.data_for_budget(budget)
    assert data.pallet_count == 3

    text = _pdf_text(service.export_envelope(budget, tmp_path))
    assert "(3 pallets)" in text


def _manual_budget(client, product, quantity: float = 10.0, unit_price: float = 100.0):
    """Presupuesto manual escrito directo: no toca stock ni cuenta corriente."""
    from datetime import date

    number = Budget.select().count() + 1
    budget = Budget.create(
        budget_number=number,
        client=client,
        load_order=None,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=date.today(),
        net_amount=quantity * unit_price,
        discount_amount=0.0,
        vat_amount=quantity * unit_price * 0.21,
        total_amount=quantity * unit_price * 1.21,
    )
    return budget


def test_envelope_without_pallet_association_does_not_invent_a_number(db, tmp_path):
    """Sin orden de carga no hay fuente de pallets: se avisa, no se inventa."""
    client, _address = _client("CLIENTE SIN PALLETS", "30733333333")
    product = Product.create(name="Producto suelto", unit="kg")
    budget = _manual_budget(client, product)
    service = EnvelopePrintService(current_user="admin", settings=_settings())

    data = service.data_for_budget(budget)
    assert data.pallet_count is None
    assert any("manual" in warning for warning in data.warnings)

    text = _pdf_text(service.export_envelope(budget, tmp_path))
    # Sin dato de pallets no se imprime ningun numero de pallets.
    assert "pallet)" not in text
    assert "Pallets:" not in text


def test_envelope_without_destination_address_fails_instead_of_printing_blank(db, tmp_path):
    """Sin domicilio no se genera un sobre: se informa el motivo."""
    client, _address = _client("CLIENTE SIN DOMICILIO", "30744444444")
    product = Product.create(name="Producto sin destino", unit="kg")
    budget = _manual_budget(client, product)
    # El presupuesto manual ya no tiene a donde enviar el sobre.
    for address in client.addresses:
        address.is_primary = False
        address.active = False
        address.save()

    service = EnvelopePrintService(current_user="admin", settings=_settings())
    with pytest.raises(EnvelopeDataError):
        service.export_envelope(budget, tmp_path)


def test_envelope_rotation_90_swaps_the_page_and_rotates_the_content(db, tmp_path):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings(rotation_deg=90)
    ).export_envelope(budget, tmp_path)

    width_mm, height_mm = _page_size_mm(path)
    assert width_mm == pytest.approx(120, abs=0.5)
    assert height_mm == pytest.approx(235, abs=0.5)
    # Matriz de rotacion de 90 grados en el flujo de contenido.
    assert "0 1 -1 0" in _content_stream(path)


def test_envelope_rotation_270_also_swaps_the_page(db, tmp_path):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin", settings=_settings(rotation_deg=270)
    ).export_envelope(budget, tmp_path)

    width_mm, height_mm = _page_size_mm(path)
    assert width_mm == pytest.approx(120, abs=0.5)
    assert height_mm == pytest.approx(235, abs=0.5)
    assert "0 -1 1 0" in _content_stream(path)


def _device_positions(path) -> list[tuple[float, float]]:
    """Posicion en la pagina (en puntos) de cada texto dibujado."""
    reader = PdfReader(str(path))
    positions: list[tuple[float, float]] = []

    def visitor(text, cm, tm, _font, _size):
        if not text.strip():
            return
        x, y = _device_point(cm, tm)
        positions.append((x, y))

    for page in reader.pages:
        page.extract_text(visitor_text=visitor)
    return positions


def _device_point(cm, tm) -> tuple[float, float]:
    """Compone la matriz de texto con la de la pagina.

    La composicion es ``x' = tm[4]*cm[0] + tm[5]*cm[2] + cm[4]`` y
    ``y' = tm[4]*cm[1] + tm[5]*cm[3] + cm[5]``. Con ``cm[1]`` y ``cm[3]``
    cambiados el control de "texto fuera de la pagina" daba falsos positivos
    en las rotaciones, porque tomaba la coordenada X como si fuera la Y.
    """
    x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
    return x, y


def _device_texts(path) -> list[tuple[str, float, float]]:
    """Cada texto dibujado con su posicion en la pagina (en puntos)."""
    reader = PdfReader(str(path))
    rows: list[tuple[str, float, float]] = []

    def visitor(text, cm, tm, _font, _size):
        if not text.strip():
            return
        x, y = _device_point(cm, tm)
        rows.append((text.strip(), x, y))

    for page in reader.pages:
        page.extract_text(visitor_text=visitor)
    return rows


def _translations(stream: str) -> list[tuple[float, float]]:
    """Traslaciones ``1 0 0 1 x y cm`` que aparecen en el flujo de contenido."""
    import re

    return [
        (float(match.group(1)), float(match.group(2)))
        for match in re.finditer(r"1 0 0 1 (-?[\d.]+) (-?[\d.]+) cm", stream)
    ]


def test_envelope_content_stays_inside_the_page_for_every_rotation(db, tmp_path):
    """Nada puede quedar fuera de la pagina: un sobre recortado no se puede rotular.

    Este es el control que evita el fallo silencioso de la rotacion: con la
    matriz mal compuesta el PDF sale vacio y el error no aparece en ningun otro
    lado.
    """
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    for rotation in (0, 90, 180, 270):
        path = EnvelopePrintService(
            current_user="admin", settings=_settings(rotation_deg=rotation)
        ).export_envelope(budget, tmp_path)

        reader = PdfReader(str(path))
        box = reader.pages[0].mediabox
        width, height = float(box.width), float(box.height)
        positions = _device_positions(path)
        assert positions, f"La rotacion {rotation} dejo el sobre sin texto"
        for x, y in positions:
            assert -1 <= x <= width + 1, f"Texto fuera de la pagina en {rotation}°: {x}"
            assert -1 <= y <= height + 1, f"Texto fuera de la pagina en {rotation}°: {y}"


def test_envelope_offsets_are_applied_in_millimeters(db, tmp_path):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)

    path = EnvelopePrintService(
        current_user="admin",
        settings=_settings(offset_x_mm=5, offset_y_mm=-3),
    ).export_envelope(budget, tmp_path)

    # Los desplazamientos van como traslacion propia, en puntos (1 mm = 72/25.4).
    expected = (5 * 72 / 25.4, -3 * 72 / 25.4)
    translations = _translations(_content_stream(path))
    assert any(
        abs(x - expected[0]) < 0.01 and abs(y - expected[1]) < 0.01
        for x, y in translations
    ), f"No se aplico el desplazamiento en mm: {translations}"


def test_batch_export_generates_one_budget_pdf_and_one_envelope_pdf_per_client(
    db, tmp_path
):
    order, client_a, client_b, _product_a, _product_b = _order_with_pallets()
    service = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)

    # Es lo que hace la pantalla al apretar "Presupuesto": los presupuestos y
    # los sobres salen en la misma operacion.
    budget_paths = service.export_budgets(order)
    envelopes = service.export_envelopes(order)

    assert len(budget_paths) == 2
    assert len(envelopes.paths) == 2
    assert envelopes.failures == []

    budget_names = sorted(path.name for path in budget_paths)
    assert budget_names == ["presupuesto_000001.pdf", "presupuesto_000002.pdf"]

    envelope_names = sorted(path.name for path in envelopes.paths)
    budget_numbers = sorted(budget.budget_number for budget in Budget.select())
    assert envelope_names == [
        f"sobre_{client_a.id}_{budget_numbers[0]:06d}.pdf",
        f"sobre_{client_b.id}_{budget_numbers[1]:06d}.pdf",
    ]
    for path in envelopes.paths:
        assert path.exists() and path.stat().st_size > 0


def test_batch_export_keeps_the_budget_pdf_unchanged(db, tmp_path):
    """El PDF de presupuesto tiene que salir igual que antes del issue."""
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    service = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)

    before = service.export_budgets(order)
    after = service.export_budgets(order)

    assert [path.name for path in before] == [path.name for path in after]
    for path_before, path_after in zip(before, after):
        assert _pdf_text(path_before) == _pdf_text(path_after)


def test_batch_export_informs_the_client_of_each_failed_envelope(db, tmp_path):
    """Un sobre que falla no corta el lote ni se presenta como exitoso."""
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    client_ok, address_ok = _client("CLIENTE OK", "30755555555")
    # Un cliente sin nombre no tiene sobre: es el caso real que el issue pide
    # informar, con el cliente y el motivo.
    client_bad, address_bad = _client("", "30766666666")
    product = Product.create(name="Fecula sobres", unit="kg", peso_unitario_kg=25)
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": client_ok,
                "delivery_address": address_ok,
                "products": [{"product": product, "quantity": 50}],
            },
            {
                "client": client_bad,
                "delivery_address": address_bad,
                "products": [{"product": product, "quantity": 50}],
            },
        ],
        pallets=[],
    )

    service = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)
    budget_paths = service.export_budgets(order)
    envelopes = service.export_envelopes(order)

    assert len(budget_paths) == 2
    assert len(envelopes.paths) == 1
    assert envelopes.failed_count == 1
    failure = envelopes.failures[0]
    assert failure.reason
    assert "sin nombre" in failure.client_name or failure.client_name == ""


def test_envelope_export_does_not_change_the_budget_or_the_ledger(db, tmp_path):
    from app.models.accounting import ClientAccountMovement

    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)
    total_before = budget.total_amount
    movements_before = ClientAccountMovement.select().count()

    EnvelopePrintService(
        current_user="admin", settings=_settings()
    ).export_envelope(budget, tmp_path)

    budget_after = Budget.get_by_id(budget.id)
    assert budget_after.total_amount == total_before
    assert budget_after.status == budget.status
    assert ClientAccountMovement.select().count() == movements_before


def test_reexport_overwrites_its_own_file_and_leaves_foreign_files_alone(
    db, tmp_path
):
    order, client_a, _client_b, _product_a, _product_b = _order_with_pallets()
    budget = Budget.get(Budget.client == client_a)
    service = EnvelopePrintService(current_user="admin", settings=_settings())

    first = service.export_envelope(budget, tmp_path)
    second = service.export_envelope(budget, tmp_path)
    assert first == second
    assert len(list(tmp_path.glob("sobre_*.pdf"))) == 1

    # Un archivo ajeno con el mismo nombre no se pisa.
    foreign = tmp_path / first.name
    foreign.write_bytes(b"no soy un pdf de femag")
    third = service.export_envelope(budget, tmp_path)
    assert third != first
    assert foreign.read_bytes() == b"no soy un pdf de femag"


def test_envelope_settings_are_persistent_and_survive_invalid_values(tmp_path):
    settings = EnvelopeSettings(
        envelope_width_mm=235,
        envelope_height_mm=120,
        rotation_deg=90,
        offset_x_mm=2.5,
        offset_y_mm=-1.5,
        printer_name="EPSON L3250",
        copies=2,
    )
    save_envelope_settings(settings, config_dir=tmp_path)

    loaded = load_envelope_settings(config_dir=tmp_path)
    assert loaded.rotation_deg == 90
    assert loaded.offset_x_mm == 2.5
    assert loaded.offset_y_mm == -1.5
    assert loaded.printer_name == "EPSON L3250"
    assert loaded.copies == 2
    assert loaded.page_size_mm == (120, 235)

    # Un archivo a medias no puede dejar la impresion sin configurar.
    (tmp_path / "envelope.json").write_text("{ roto", encoding="utf-8")
    assert load_envelope_settings(config_dir=tmp_path).rotation_deg == 0


def test_calibration_sheet_is_generated_with_the_current_geometry(db, tmp_path):
    service = EnvelopePrintService(current_user="admin", settings=_settings())

    path = service.export_calibration_sheet(tmp_path)

    assert path.exists() and path.stat().st_size > 0
    width_mm, height_mm = _page_size_mm(path)
    assert width_mm == pytest.approx(235, abs=0.5)
    assert height_mm == pytest.approx(120, abs=0.5)
    assert "CLIENTE DE EJEMPLO" in _pdf_text(path)
