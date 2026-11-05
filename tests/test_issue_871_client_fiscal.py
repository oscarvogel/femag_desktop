"""Datos fiscales y certificados de exclusion de clientes (#871)."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditLog
from app.models.masters import Client, ClientFiscalCertificate
from app.services.client_fiscal_service import (
    ClientFiscalError,
    ClientFiscalService,
    STATUS_POR_VENCER,
    STATUS_PROGRAMADA,
    STATUS_SIN_CERTIFICADO,
    STATUS_VENCIDA,
    STATUS_VIGENTE,
)


def _client(name="Cliente fiscal", cuit="30700871001"):
    return Client.create(name=name, cuit=cuit, iva_condition="RI")


def _pdf(tmp_path, name="certificado.pdf"):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4\n% FEMAG test\n")
    return path


def _service(tmp_path, user="secretaria"):
    return ClientFiscalService(user, docs_dir=tmp_path / "fiscales")


def test_upload_rentas_and_iva_keeps_files_and_metadata(db, tmp_path):
    client = _client()
    service = _service(tmp_path)

    rentas = service.upload_certificate(
        client=client,
        kind=ClientFiscalCertificate.RENTAS,
        source_path=_pdf(tmp_path, "rentas.pdf"),
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
    )
    iva = service.upload_certificate(
        client=client,
        kind=ClientFiscalCertificate.IVA,
        source_path=_pdf(tmp_path, "iva.pdf"),
        valid_from=date(2026, 2, 1),
        valid_until=date(2027, 1, 31),
    )

    assert rentas.client_id == client.id
    assert rentas.kind == ClientFiscalCertificate.RENTAS
    assert rentas.mime == "application/pdf"
    assert rentas.size_bytes > 0
    assert service.absolute_path(rentas).exists()
    assert service.absolute_path(iva).exists()
    assert service.current_certificate(client, "rentas").id == rentas.id
    assert service.current_certificate(client, "iva").id == iva.id

    audits = list(
        AuditLog.select().where(AuditLog.action == "cargar certificado fiscal")
    )
    assert len(audits) == 2
    assert audits[0].user == "secretaria"


def test_history_keeps_previous_certificate_and_current_uses_newest(db, tmp_path):
    client = _client()
    service = _service(tmp_path)

    first = service.upload_certificate(
        client=client,
        kind=ClientFiscalCertificate.RENTAS,
        source_path=_pdf(tmp_path, "uno.pdf"),
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 6, 30),
    )
    second = service.upload_certificate(
        client=client,
        kind=ClientFiscalCertificate.RENTAS,
        source_path=_pdf(tmp_path, "dos.pdf"),
        valid_from=date(2026, 7, 1),
        valid_until=date(2026, 12, 31),
    )

    assert service.current_certificate(client, "rentas").id == second.id
    history = service.certificates(client, "rentas")
    assert [row.id for row in history] == [second.id, first.id]
    assert service.absolute_path(first).exists()


def test_clients_are_isolated(db, tmp_path):
    first = _client("Cliente fiscal A", "30700871002")
    second = _client("Cliente fiscal B", "30700871003")
    service = _service(tmp_path)

    service.upload_certificate(
        client=first,
        kind=ClientFiscalCertificate.RENTAS,
        source_path=_pdf(tmp_path),
        valid_from=date(2026, 1, 1),
        valid_until=date(2026, 12, 31),
    )

    assert service.current_certificate(first, "rentas") is not None
    assert service.current_certificate(second, "rentas") is None
    assert (
        service.certificate_state(
            second, "rentas", today=date(2026, 11, 5)
        )["status"]
        == STATUS_SIN_CERTIFICADO
    )


def test_certificate_status_vigente_por_vencer_vencida_y_programada(db, tmp_path):
    client = _client()
    service = _service(tmp_path)
    today = date(2026, 11, 5)

    def upload(valid_from, valid_until, name):
        return service.upload_certificate(
            client=client,
            kind=ClientFiscalCertificate.IVA,
            source_path=_pdf(tmp_path, name),
            valid_from=valid_from,
            valid_until=valid_until,
        )

    upload(date(2026, 1, 1), date(2027, 12, 31), "vigente.pdf")
    assert service.certificate_state(client, "iva", today=today)["status"] == STATUS_VIGENTE

    upload(date(2026, 1, 1), date(2026, 11, 20), "por-vencer.pdf")
    assert (
        service.certificate_state(client, "iva", today=today)["status"]
        == STATUS_POR_VENCER
    )

    upload(date(2026, 1, 1), date(2026, 10, 1), "vencida.pdf")
    assert service.certificate_state(client, "iva", today=today)["status"] == STATUS_VENCIDA

    upload(date(2026, 12, 1), date(2027, 12, 31), "programada.pdf")
    assert (
        service.certificate_state(client, "iva", today=today)["status"]
        == STATUS_PROGRAMADA
    )


def test_update_fiscal_data_and_validation(db, tmp_path):
    client = _client()
    service = _service(tmp_path)

    updated = service.update_fiscal_data(
        client,
        rentas_alicuota="2,50",
        fiscal_observations="Exclusion parcial",
    )

    assert updated.rentas_alicuota == Decimal("2.50")
    assert updated.fiscal_observations == "Exclusion parcial"
    audit = AuditLog.get(AuditLog.action == "modificar datos fiscales")
    assert audit.new_value["rentas_alicuota"] == "2.50"

    with pytest.raises(ClientFiscalError, match="alicuota"):
        service.update_fiscal_data(client, rentas_alicuota=101)
    with pytest.raises(ClientFiscalError, match="alicuota"):
        service.update_fiscal_data(client, rentas_alicuota="abc")


def test_upload_rejects_non_pdf_empty_and_invalid_dates(db, tmp_path):
    client = _client()
    service = _service(tmp_path)

    text = tmp_path / "archivo.txt"
    text.write_text("no es pdf", encoding="utf-8")
    with pytest.raises(ClientFiscalError, match="PDF"):
        service.upload_certificate(
            client=client,
            kind="rentas",
            source_path=text,
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
        )

    fake = tmp_path / "falso.pdf"
    fake.write_bytes(b"no es un pdf")
    with pytest.raises(ClientFiscalError, match="PDF"):
        service.upload_certificate(
            client=client,
            kind="rentas",
            source_path=fake,
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 12, 31),
        )

    with pytest.raises(ClientFiscalError, match="vigencia"):
        service.upload_certificate(
            client=client,
            kind="rentas",
            source_path=_pdf(tmp_path),
            valid_from=date(2026, 12, 31),
            valid_until=date(2026, 1, 1),
        )


def test_order_notices_show_vigente_and_expired(db, tmp_path):
    vigente_client = _client("Cliente vigente", "30700871004")
    expired_client = _client("Cliente vencido", "30700871005")
    service = _service(tmp_path)
    today = date(2026, 11, 5)

    service.upload_certificate(
        client=vigente_client,
        kind=ClientFiscalCertificate.RENTAS,
        source_path=_pdf(tmp_path, "vigente.pdf"),
        valid_from=date(2026, 1, 1),
        valid_until=date(2027, 12, 31),
    )
    service.upload_certificate(
        client=expired_client,
        kind=ClientFiscalCertificate.IVA,
        source_path=_pdf(tmp_path, "vencido.pdf"),
        valid_from=date(2025, 1, 1),
        valid_until=date(2026, 10, 1),
    )

    notices = service.fiscal_notices_for_clients(
        [vigente_client, expired_client], today=today
    )

    assert len(notices) == 2
    vigente = next(row for row in notices if row["client_id"] == vigente_client.id)
    expired = next(row for row in notices if row["client_id"] == expired_client.id)
    assert vigente["has_expired"] is False
    assert "vigente hasta" in vigente["messages"][0]
    assert expired["has_expired"] is True
    assert "VENCIDA" in expired["messages"][0]

    expired_rows = service.clients_with_expired_certificates(today=today)
    assert [row["client_id"] for row in expired_rows] == [expired_client.id]


def test_schema_has_client_fiscal_fields_and_table(db):
    from app.config.schema import ensure_runtime_schema

    ensure_runtime_schema(db)
    columns = {column.name for column in db.get_columns("client")}
    assert {"rentas_alicuota", "fiscal_observations"} <= columns
    assert db.table_exists("clientfiscalcertificate")
