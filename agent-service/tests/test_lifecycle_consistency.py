from datetime import date, datetime, timezone

from app.domain.lifecycle import analyze_audit, analyze_compliance_gaps
from app.domain.schemas import (
    AuditStatus, ChecklistProgress, ChecklistResult, NCStatus,
    OrientationStatus,
)
from app.providers.mock_qms import MockQMSProvider
from app.tools.qms_tools import ReadOnlyQMSTools


def sample_snapshot():
    return ReadOnlyQMSTools(MockQMSProvider()).get_audit_snapshot("audit-1003")


def warning_map(analysis):
    return {fact.id: fact for fact in analysis.facts if fact.kind == "warning"}


def test_closed_audit_future_dates_are_inferred_warning_with_fixed_review_date():
    snapshot = sample_snapshot()
    audit = snapshot.audit.model_copy(update={
        "status": AuditStatus.CLOSED,
        "planned_start_date": date(2027, 2, 10),
        "planned_end_date": date(2027, 2, 12),
    })

    result = analyze_audit(snapshot.model_copy(update={"audit": audit}), as_of=date(2027, 2, 1))

    warning = warning_map(result)["closed-audit-future-planned-date"]
    assert "CLOSED" in warning.detail
    assert {ref.field for ref in warning.source_refs} >= {"status", "planned_start_date", "planned_end_date", "as_of_date"}
    assert all(fact.source_refs for fact in result.facts)
    assert next(fact for fact in result.facts if fact.id == "audit-status").kind == "fact"


def test_accepted_nc_requires_corrective_action_and_verification_evidence():
    snapshot = sample_snapshot()
    ncs = [nc.model_copy(update={
        "status": NCStatus.ACCEPTED,
        "corrective_action_submitted": True,
        "verified_by_id": None,
        "verified_at": None,
    }) for nc in snapshot.non_conformities]
    accepted_snapshot = snapshot.model_copy(update={"non_conformities": ncs})

    result = analyze_audit(accepted_snapshot, as_of=date(2026, 11, 1))

    warnings = warning_map(result)
    assert {f"accepted-nc-completion-unconfirmed-{nc.id}" for nc in ncs} <= warnings.keys()
    assert all(warnings[f"accepted-nc-completion-unconfirmed-{nc.id}"].source_refs for nc in ncs)
    assert "closure-checks-met" not in {rec.id for rec in result.recommendations}

    verified_ncs = [nc.model_copy(update={
        "verified_by_id": "auditor-7",
        "verified_at": datetime(2026, 10, 30, tzinfo=timezone.utc),
    }) for nc in ncs]
    verified_snapshot = accepted_snapshot.model_copy(update={"non_conformities": verified_ncs})
    warnings_after_verification = warning_map(analyze_audit(verified_snapshot, as_of=date(2026, 11, 1)))
    assert not any(key.startswith("accepted-nc-completion-unconfirmed-") for key in warnings_after_verification)


def test_nc_field_level_gaps_are_sourced_and_preventive_action_is_not_required():
    snapshot = sample_snapshot()
    nc = snapshot.non_conformities[0].model_copy(update={
        "status": NCStatus.ACCEPTED,
        "finding": "",
        "risk_action": "",
        "correction": "",
        "corrective_action": "",
        "preventive_action": "",
        "verified_by_id": None,
        "verified_by_name": "",
        "verified_at": None,
        "verification_remarks": "",
        "returned_fields": {
            "finding", "risk_action", "correction", "corrective_action",
            "preventive_action", "verified_by", "verified_by_name",
            "verified_at", "verification_remarks",
        },
    })
    result = analyze_audit(snapshot.model_copy(update={"non_conformities": [nc]}), as_of=date(2026, 11, 1))
    warnings = warning_map(result)
    facts = {fact.id: fact for fact in result.facts}
    recs = {recommendation.id: recommendation for recommendation in result.recommendations}

    assert f"nc-field-empty-correction-{nc.id}" in warnings
    assert f"nc-field-empty-corrective_action-{nc.id}" in warnings
    assert f"nc-field-empty-finding-{nc.id}" in warnings
    assert f"nc-verification-field-empty-verified_by-{nc.id}" in warnings
    assert f"nc-verification-field-empty-verified_at-{nc.id}" in warnings
    assert f"nc-verification-field-empty-verification_remarks-{nc.id}" in warnings
    assert f"nc-field-empty-risk_action-{nc.id}" in facts
    assert "separate from correction and corrective action" in facts[f"nc-field-empty-risk_action-{nc.id}"].detail
    preventive = facts[f"nc-field-empty-preventive_action-{nc.id}"]
    assert preventive.kind == "fact"
    assert "mandatory has not been established" in preventive.detail
    assert all(ref.field == "preventive_action" for ref in preventive.source_refs)
    assert f"accepted-nc-completion-unconfirmed-{nc.id}" in warnings
    assert f"recheck-nc-evidence-{nc.id}" in recs
    assert all(fact.source_refs for fact in result.facts)


def test_audit_facts_include_nc_finding_with_source_reference():
    snapshot = sample_snapshot()
    nc = snapshot.non_conformities[0]
    result = analyze_audit(snapshot, as_of=date(2026, 11, 1))
    finding = next(fact for fact in result.facts if fact.id == f"nc-finding-{nc.id}")

    assert finding.detail == nc.finding
    assert any(ref.field == "finding" and ref.value == nc.finding for ref in finding.source_refs)


def test_omitted_nc_fields_are_not_misreported_as_explicitly_empty():
    snapshot = sample_snapshot()
    nc = snapshot.non_conformities[0].model_copy(update={
        "status": NCStatus.ACCEPTED,
        "finding": "",
        "correction": "",
        "corrective_action": None,
        "verified_by_id": None,
        "verified_at": None,
        "returned_fields": {"finding", "correction", "status", "verified_by", "verified_at"},
    })
    result = analyze_audit(snapshot.model_copy(update={"non_conformities": [nc]}), as_of=date(2026, 11, 1))
    warnings = warning_map(result)
    facts = {fact.id: fact for fact in result.facts}

    empty = facts[f"nc-field-empty-correction-{nc.id}"]
    assert any(ref.field == "correction" and ref.value == "empty" for ref in empty.source_refs)
    unavailable = warnings[f"nc-fields-unavailable-{nc.id}"]
    assert any(ref.field == "corrective_action" and ref.value == "not returned" for ref in unavailable.source_refs)
    assert f"nc-field-empty-corrective_action-{nc.id}" not in facts
    assert any(ref.field == "finding" and ref.value == "empty" for ref in facts[f"nc-finding-{nc.id}"].source_refs)


def test_rework_recommendation_uses_verification_remarks():
    snapshot = sample_snapshot()
    nc = snapshot.non_conformities[0].model_copy(update={
        "status": NCStatus.REWORK_REQUIRED,
        "verification_remarks": "Attach proof that obsolete copies were removed.",
        "returned_fields": {"status", "verification_remarks"},
    })
    result = analyze_audit(snapshot.model_copy(update={"non_conformities": [nc]}), as_of=date(2026, 11, 1))
    recommendation = next(rec for rec in result.recommendations if rec.id == f"nc-rework-{nc.id}")
    warning = warning_map(result)[f"nc-rework-required-{nc.id}"]

    assert "Attach proof that obsolete copies were removed." in recommendation.text
    assert "Attach proof that obsolete copies were removed." in warning.detail
    assert {ref.field for ref in recommendation.source_refs} >= {"status", "verification_remarks"}


def test_missing_and_inconsistent_lifecycle_records_are_warnings_not_actions():
    snapshot = sample_snapshot()
    audit = snapshot.audit.model_copy(update={
        "status": AuditStatus.IN_PROGRESS,
        "planned_start_date": date(2026, 11, 12),
        "planned_end_date": date(2026, 11, 11),
    })
    broken = snapshot.model_copy(update={"audit": audit, "assignments": [], "schedule": None})

    result = analyze_audit(broken, as_of=date(2026, 11, 1))
    warnings = warning_map(result)

    assert {"audit-planned-date-order", "missing-audit-assignments", "missing-progressed-audit-schedule"} <= warnings.keys()
    assert all(warning.source_refs for warning in warnings.values())
    assert not any(rec.id in {"assign-auditors", "schedule-audit"} for rec in result.recommendations)


def test_partial_assignments_and_inconsistent_aggregate_counts_are_reported():
    snapshot = sample_snapshot()
    partial_assignments = snapshot.assignments[:1]
    progress = ChecklistProgress(item_count=5, compliant=2, non_compliant=1, pending=1)
    partial = snapshot.model_copy(update={
        "assignments": partial_assignments,
        "checklist_progress": progress,
        "checklist_items": [],
    })

    warnings = warning_map(analyze_audit(partial, as_of=date(2026, 11, 1)))

    assert "lifecycle-assignment-roles-incomplete" in warnings
    assert "checklist-progress-counts-inconsistent" in warnings
    assert all(warnings[key].source_refs for key in (
        "lifecycle-assignment-roles-incomplete",
        "checklist-progress-counts-inconsistent",
    ))


def test_aggregate_only_checklist_and_unknown_orientation_are_incomplete_not_pending():
    snapshot = sample_snapshot()
    assignments = [assignment.model_copy(update={"orientation_status": None}) for assignment in snapshot.assignments]
    progress = ChecklistProgress(item_count=4, compliant=2, non_compliant=1, pending=1)
    limited = snapshot.model_copy(update={
        "checklist_items": [],
        "checklist_progress": progress,
        "checklist_item_details_available": False,
        "assignments": assignments,
    })

    result = analyze_audit(limited, as_of=date(2026, 11, 1))
    warnings = warning_map(result)

    assert "checklist-item-evidence-incomplete" in warnings
    assert all(f"orientation-status-unavailable-{assignment.id}" in warnings for assignment in assignments)
    assert "complete-orientations" not in {rec.id for rec in result.recommendations}
    assert all(fact.source_refs for fact in result.facts)
    assert "4 item(s)" in next(fact.detail for fact in result.facts if fact.id == "checklist-results")


def test_policy_note_only_requires_resolution_before_write_operations():
    result = analyze_audit(sample_snapshot(), as_of=date(2026, 11, 1))

    assert len(result.unresolved_policies) == 1
    assert "before enabling write operations" in result.unresolved_policies[0]
    assert "do not block read-only authenticated integration" in result.unresolved_policies[0]


def test_missing_checklist_evidence_does_not_claim_no_compliance_gaps():
    snapshot = sample_snapshot().model_copy(update={
        "checklist_items": [],
        "checklist_progress": None,
        "checklist_item_details_available": False,
        "non_conformities": [],
    })

    findings = analyze_compliance_gaps(snapshot)

    assert [finding.kind for finding in findings] == ["warning"]
    assert findings[0].id == "compliance-evidence-incomplete"
    assert findings[0].source_refs

