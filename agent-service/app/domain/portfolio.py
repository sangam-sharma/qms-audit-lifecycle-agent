from datetime import date

from app.domain.lifecycle import analyze_audit, analyze_compliance_gaps
from app.domain.schemas import (
    AuditSnapshot,
    Fact,
    NCStatus,
    PortfolioPriorityFactor,
    RankedAuditInsight,
    Recommendation,
    SourceRef,
)


PRIORITY_METHOD = (
    "Deterministic score: overdue planned audit end +80 plus up to 30 overdue days; "
    "overdue scheduled end +25; each missing auditor role +25; missing schedule +20; "
    "each missing schedule confirmation +8; pending orientation +5 each; each pending "
    "checklist item +10 (cap 30); each non-compliant checklist item +15 (cap 45); "
    "each unresolved NC +20; accepted NC evidence gap +15 each. Higher scores rank first. "
    "Ties put non-closed audits first, then earlier planned end date, then audit ID."
)


def rank_portfolio(snapshots: list[AuditSnapshot], *, as_of: date | None = None) -> list[RankedAuditInsight]:
    """Analyze known snapshots and rank them by explicit, source-backed rules."""
    review_date = as_of or date.today()
    ranked = [
        _audit_insight(snapshot, review_date)
        for snapshot in snapshots
    ]
    ranked.sort(key=lambda row: (
        -row.priority_score,
        row.status.value == "CLOSED",
        next(snapshot.audit.planned_end_date for snapshot in snapshots if snapshot.audit.id == row.audit_id),
        row.audit_id,
    ))
    return [row.model_copy(update={"rank": index}) for index, row in enumerate(ranked, start=1)]


def _audit_insight(snapshot: AuditSnapshot, as_of: date) -> RankedAuditInsight:
    audit = snapshot.audit
    analysis = analyze_audit(snapshot, as_of=as_of)
    gap_facts = analyze_compliance_gaps(snapshot)
    facts = [*analysis.facts, *gap_facts]
    recommendations = list(analysis.recommendations)
    factors: list[PortfolioPriorityFactor] = []

    def add_factor(code: str, points: int, reason: str, refs: list[SourceRef]) -> None:
        if points > 0 and refs:
            factors.append(PortfolioPriorityFactor(code=code, points=points, reason=reason, source_refs=refs))

    if audit.status.value != "CLOSED" and audit.planned_end_date < as_of:
        overdue_days = (as_of - audit.planned_end_date).days
        refs = [
            _ref("audit", audit.id, "planned_end_date", audit.planned_end_date.isoformat()),
            _ref("audit", audit.id, "status", audit.status.value),
        ]
        add_factor(
            "overdue_audit", 80 + min(overdue_days, 30),
            f"Planned audit end date passed {overdue_days} day(s) ago while status is {audit.status.value}.", refs,
        )
        recommendations.append(Recommendation(
            id=f"portfolio-overdue-audit-{audit.id}",
            text=f"Review the overdue audit and record its current lifecycle status in the QMS.",
            source_refs=refs,
        ))

    if snapshot.schedule and audit.status.value != "CLOSED" and snapshot.schedule.scheduled_end.date() < as_of:
        refs = [
            _ref("schedule", snapshot.schedule.id, "scheduled_end", snapshot.schedule.scheduled_end.isoformat()),
            _ref("audit", audit.id, "status", audit.status.value),
        ]
        add_factor("overdue_scheduled_activity", 25, "The scheduled end date has passed and the audit is not recorded as closed.", refs)

    assigned_roles = {assignment.assignment_type.value for assignment in snapshot.assignments}
    missing_roles = sorted({"PRIMARY", "SECONDARY"} - assigned_roles)
    if missing_roles:
        refs = [
            _ref("audit", audit.id, "status", audit.status.value),
            _ref("audit", audit.id, "missing_assignment_roles", ",".join(missing_roles)),
        ]
        refs.extend(_ref("assignment", assignment.id, "assignment_type", assignment.assignment_type.value)
                    for assignment in snapshot.assignments)
        add_factor("missing_assignments", 25 * len(missing_roles), f"Missing auditor role(s): {', '.join(missing_roles)}.", refs)
        recommendations.append(Recommendation(
            id=f"portfolio-assignments-{audit.id}",
            text=f"Assign the missing auditor role(s): {', '.join(missing_roles)}.",
            source_refs=refs,
        ))

    pending_orientations = [a for a in snapshot.assignments if a.orientation_status and a.orientation_status.value == "PENDING"]
    if pending_orientations:
        refs = [_ref("assignment", a.id, "orientation_status", "PENDING") for a in pending_orientations]
        add_factor("pending_orientations", 5 * len(pending_orientations),
                   f"{len(pending_orientations)} auditor orientation(s) are pending.", refs)

    if audit.status.value in {"ASSIGNED", "IN_PROGRESS", "PENDING_CLOSURE"} and snapshot.schedule is None:
        refs = [_ref("audit", audit.id, "schedule", "none returned by provider"), _ref("audit", audit.id, "status", audit.status.value)]
        add_factor("missing_schedule", 20, "No schedule record is available for this audit stage.", refs)
        recommendations.append(Recommendation(
            id=f"portfolio-schedule-{audit.id}", text="Record the audit schedule in the QMS.", source_refs=refs,
        ))
    elif snapshot.schedule:
        missing_confirmations = sorted({"COMBINED", "INDIVIDUAL"} - set(snapshot.schedule.confirmations))
        if missing_confirmations:
            refs = [
                _ref("schedule", snapshot.schedule.id, "status", snapshot.schedule.status.value),
                _ref("schedule", snapshot.schedule.id, "confirmations", ",".join(snapshot.schedule.confirmations) or "none"),
                _ref("schedule", snapshot.schedule.id, "missing_confirmations", ",".join(missing_confirmations)),
            ]
            add_factor("missing_confirmations", 8 * len(missing_confirmations),
                       f"Missing schedule confirmation(s): {', '.join(missing_confirmations)}.", refs)

    progress = snapshot.checklist_progress
    if snapshot.checklist_items:
        pending_count = sum(item.result.value == "PENDING" for item in snapshot.checklist_items)
        noncompliant_count = sum(item.result.value == "NON_COMPLIANT" for item in snapshot.checklist_items)
        pending_refs = [_ref("checklist_item", item.id, "result", item.result.value)
                        for item in snapshot.checklist_items if item.result.value == "PENDING"]
        noncompliant_refs = [_ref("checklist_item", item.id, "result", item.result.value)
                             for item in snapshot.checklist_items if item.result.value == "NON_COMPLIANT"]
    elif progress:
        pending_count = progress.pending
        noncompliant_count = progress.non_compliant
        pending_refs = [_ref("audit_progress", audit.id, "checklist.pending", progress.pending)]
        noncompliant_refs = [_ref("audit_progress", audit.id, "checklist.non_compliant", progress.non_compliant)]
    else:
        pending_count = noncompliant_count = 0
        pending_refs = noncompliant_refs = []

    if pending_count:
        add_factor("pending_checklist", min(30, 10 * pending_count),
                   f"{pending_count} checklist item(s) are pending.", pending_refs)
    if noncompliant_count:
        add_factor("non_compliant_checklist", min(45, 15 * noncompliant_count),
                   f"{noncompliant_count} checklist item(s) are recorded as non-compliant.", noncompliant_refs)
    elif not snapshot.checklist_items and progress is None and audit.status.value in {"IN_PROGRESS", "PENDING_CLOSURE"}:
        checklist_fact = next((fact for fact in analysis.facts if fact.id == "checklist-results"), None)
        refs = checklist_fact.source_refs if checklist_fact else [_ref("audit", audit.id, "checklist_items", "none returned by provider")]
        add_factor("missing_checklist", 20, "No checklist items or aggregate progress are available for this active audit.", refs)
        recommendations.append(Recommendation(
            id=f"portfolio-checklist-{audit.id}",
            text="Review checklist availability and record checklist progress through the QMS process.",
            source_refs=refs,
        ))

    unresolved_ncs = [nc for nc in snapshot.non_conformities if nc.status in {NCStatus.OPEN, NCStatus.SUBMITTED, NCStatus.REWORK_REQUIRED}]
    if unresolved_ncs:
        refs = [_ref("non_conformity", nc.id, "status", nc.status.value) for nc in unresolved_ncs]
        add_factor("unresolved_non_conformities", 20 * len(unresolved_ncs),
                   f"{len(unresolved_ncs)} non-conformity record(s) are not accepted.", refs)
    evidence_gaps = [rec for rec in recommendations if rec.id.startswith("recheck-nc-evidence-")]
    if evidence_gaps:
        refs = [ref for rec in evidence_gaps for ref in rec.source_refs]
        add_factor("nc_evidence_gaps", 15 * len(evidence_gaps),
                   f"{len(evidence_gaps)} accepted NC record(s) lack completion evidence.", refs)

    factor_refs = [ref for factor in factors for ref in factor.source_refs]
    refs = list({(ref.entity, ref.record_id, ref.field, ref.value): ref
                 for ref in [*(ref for fact in facts for ref in fact.source_refs),
                             *(ref for rec in recommendations for ref in rec.source_refs), *factor_refs]}.values())
    return RankedAuditInsight(
        rank=1,
        audit_id=audit.id,
        audit_code=audit.code,
        project_name=audit.project_name,
        status=audit.status,
        priority_score=sum(factor.points for factor in factors),
        priority_factors=factors,
        facts=facts,
        recommendations=_unique_recommendations(recommendations),
        source_refs=refs,
        unresolved_policies=analysis.unresolved_policies,
    )


def _unique_recommendations(recommendations: list[Recommendation]) -> list[Recommendation]:
    return list({(rec.id, rec.text): rec for rec in recommendations}.values())


def _ref(entity: str, record_id: str, field: str, value: object) -> SourceRef:
    return SourceRef(entity=entity, record_id=record_id, field=field, value=str(value))
