from load_order_printing_cases import _budget_order, _pdf_text


def test_issue_454_prints_client_observation_on_load_order_and_budget(db, tmp_path):
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.ui.load_order_instructions_extension import install_load_order_instructions_extension

    order, client = _budget_order([("Producto presupuesto", 21.0, 100.0, 10)])
    destination = order.destinations.get()
    destination.observations = "Entregar primero este cliente; separar 2 pallets."
    destination.save()

    install_load_order_instructions_extension()
    service = LoadOrderPrintService(current_user="issue454")

    load_order_pdf = service.export_pdf(order, tmp_path)
    budget_pdf = service.export_budget(order, client, tmp_path)

    load_order_text = _pdf_text(load_order_pdf)
    budget_text = _pdf_text(budget_pdf)

    assert "Entregar primero este cliente" in load_order_text
    assert "separar 2 pallets" in load_order_text
    assert "Entregar primero este cliente" in budget_text
    assert "separar 2 pallets" in budget_text


def test_issue_454_places_observation_next_to_destination_label():
    from app.ui.load_order_instructions_extension import destination_label_with_observation

    label = "CLIENTE PRUEBA - POSADAS - RUTA 12"

    assert destination_label_with_observation(label, None) == label
    assert destination_label_with_observation(label, "   ") == label
    assert destination_label_with_observation(label, "Carga lateral") == (
        "CLIENTE PRUEBA - POSADAS - RUTA 12 | Observación: Carga lateral"
    )
