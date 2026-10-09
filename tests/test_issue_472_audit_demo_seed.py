from peewee import SqliteDatabase

from app.models.load_orders import LoadOrder
from scripts.seed_issue_472_audit_demo import seed_controlled_audit_demo


def test_issue_472_controlled_seed_builds_expected_audit_scenarios(tmp_path):
    database = SqliteDatabase(tmp_path / "audit_demo.sqlite3", pragmas={"foreign_keys": 1})
    try:
        result = seed_controlled_audit_demo(
            database,
            output_dir=tmp_path / "evidence",
        )

        pending = result["pending"]
        emitted = result["emitted"]
        ready = result["ready_to_annul"]

        assert pending.status == LoadOrder.STATUS_PENDING
        assert emitted.status == LoadOrder.STATUS_ISSUED
        assert ready.status == LoadOrder.STATUS_ISSUED
        assert len({pending.driver_id, emitted.driver_id, ready.driver_id}) == 3
        assert len({pending.truck_id, emitted.truck_id, ready.truck_id}) == 3

        pending_actions = [event.action for event in result["pending_events"]]
        assert pending_actions.count("Orden creada") == 1
        assert pending_actions.count("Orden modificada") == 1

        emitted_actions = [event.action for event in result["emitted_events"]]
        assert emitted_actions.count("Orden creada") == 1
        assert emitted_actions.count("Orden emitida") == 1
        assert emitted_actions.count("Orden impresa") == 1
        assert any("excel" in action.lower() for action in emitted_actions)

        ready_actions = [event.action for event in result["ready_events"]]
        assert ready_actions.count("Orden creada") == 1
        assert ready_actions.count("Orden emitida") == 1
        assert "Orden anulada" not in ready_actions

        assert result["pdf_path"].exists()
        assert result["xlsx_path"].exists()
    finally:
        if not database.is_closed():
            database.close()
