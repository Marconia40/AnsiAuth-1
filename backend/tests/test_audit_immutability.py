import pytest
from sqlalchemy import event

from app.composition import audit_repository
from app.db.audit_guard import AuditImmutabilityError
from app.db.models import AuditLogModel
from app.db.session import get_engine, get_session
from app.models.audit import AuditRecord


def _clear_audit_log() -> None:
    with get_session() as session:
        session.query(AuditLogModel).delete(synchronize_session=False)


def _log(user: str, action: str, resource: str, details: dict, *, status: str = "success", device=None) -> AuditRecord:
    return audit_repository.append(AuditRecord(
        user=user, action=action, resource=resource, details=details,
        status=status, device=device,
    ))


def _append_followup(parent: AuditRecord, status: str, extra_details: dict) -> AuditRecord:
    return audit_repository.append(AuditRecord(
        parent_audit_id=parent.id,
        user=parent.user, action=parent.action, resource=parent.resource,
        resource_id=parent.resource_id, device=parent.device,
        details={**parent.details, **extra_details},
        status=status,
    ))


@pytest.fixture(autouse=True)
def clear_audit():
    _clear_audit_log()
    yield
    _clear_audit_log()


@pytest.fixture
def update_interceptor():
    engine = get_engine()
    captured = {"updates": []}

    def _intercept(conn, clauseelement, multiparams, params, execution_options, *args, **kwargs):
        stmt = str(clauseelement)
        if "UPDATE" in stmt.upper() and "audit_logs" in stmt.lower():
            captured["updates"].append(stmt)
            raise AssertionError(f"Illegal UPDATE on audit_logs: {stmt[:200]}")

    event.listen(engine, "before_execute", _intercept)
    yield captured
    event.remove(engine, "before_execute", _intercept)


def test_log_action_issues_no_update(update_interceptor):
    _log("system", "test_event", "resource", {"key": "value"})
    assert update_interceptor["updates"] == []


def test_append_audit_event_issues_no_update(update_interceptor):
    record = _log("system", "create_vlan", "vlan", {"vlan_id": 99})
    _append_followup(record, "completed", {"duration": 0.1})
    assert update_interceptor["updates"] == []


def test_vlan_lifecycle_produces_no_updates(update_interceptor):
    initial = _log(
        "operator", "create_vlan", "vlan",
        {"vlan_id": 200, "name": "IMMUTE_TEST"},
        status="pending",
    )
    _append_followup(initial, "completed", {"duration_seconds": 0.5})
    assert update_interceptor["updates"] == []


def test_failed_vlan_lifecycle_produces_no_updates(update_interceptor):
    initial = _log(
        "operator", "create_vlan", "vlan",
        {"vlan_id": 201, "name": "FAIL_TEST"},
        status="pending",
    )
    _append_followup(initial, "failed", {"error": "device unreachable"})
    assert update_interceptor["updates"] == []


def test_status_transition_inserts_new_row():
    record = _log("system", "test_action", "resource", {}, status="pending")

    with get_session() as session:
        count_before = session.query(AuditLogModel).count()

    _append_followup(record, "completed", {})

    with get_session() as session:
        count_after = session.query(AuditLogModel).count()

    assert count_after == count_before + 1


def test_original_row_status_unchanged_after_append():
    initial = _log("system", "test_op", "resource", {}, status="pending")
    _append_followup(initial, "completed", {})

    with get_session() as session:
        original = session.query(AuditLogModel).filter_by(id=int(initial.id)).first()
        assert original.status == "pending"


def test_initial_row_has_no_parent():
    record = _log("operator", "create_vlan", "vlan", {})

    with get_session() as session:
        row = session.query(AuditLogModel).filter_by(id=int(record.id)).first()
        parent_id = row.parent_audit_id

    assert parent_id is None


def test_follow_up_row_parent_audit_id_links_to_initial():
    initial = _log("operator", "create_vlan", "vlan", {"vlan_id": 300})
    follow_up = _append_followup(initial, "completed", {})

    assert follow_up is not None
    assert follow_up.parent_audit_id == initial.id


def test_multi_step_chain_links_correctly():
    step1 = _log("operator", "create_vlan", "vlan", {"vlan_id": 301}, status="pending")
    step2 = _append_followup(step1, "running", {})
    step3 = _append_followup(step2, "completed", {})

    assert step2.parent_audit_id == step1.id
    assert step3.parent_audit_id == step2.id


def test_all_statuses_present_in_chain():
    step1 = _log("operator", "create_vlan", "vlan", {"vlan_id": 302}, status="pending")
    step2 = _append_followup(step1, "running", {})
    _append_followup(step2, "completed", {})

    with get_session() as session:
        rows = session.query(AuditLogModel).filter(
            AuditLogModel.action == "create_vlan",
            AuditLogModel.resource == "vlan",
        ).all()
        statuses = {r.status for r in rows}

    assert {"pending", "running", "completed"}.issubset(statuses)


def test_direct_mutation_caught_by_guard():
    record = _log("admin", "immutability_test", "audit_log", {})

    with pytest.raises(AuditImmutabilityError, match=r"audit_logs row id=\d+ is immutable"):
        with get_session() as session:
            row = session.query(AuditLogModel).filter_by(id=int(record.id)).first()
            row.status = "tampered"
