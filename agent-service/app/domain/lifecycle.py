from collections import Counter
from datetime import date

from app.domain.schemas import (
    AuditAnalysis,
    AuditSnapshot,
    ChecklistResult,
    Fact,
    NCStatus,
    OrientationStatus,
    Recommendation,
    SourceRef,
)


UNRESOLVED_POLICIES = [
    "QMS descriptions disagree about non-conformity verification and audit closure policy. Confirm these policies before enabling write operations; they do not block read-only authenticated integration.",
]


def _ref(entity: str, record_id: str, field: str, value: object) -> SourceRef:
    return SourceRef(entity=entity, record_id=record_id, field=field, value=str(value))


def _warning(warning_id: str, title: str, detail: str, refs: list[SourceRef]) -> Fact:
    return Fact(id=warning_id, title=title, detail=detail, source_refs=refs, kind="warning")


_NC_TEXT_FIELDS = (
    "finding", "risk_action", "correction", "corrective_action",
    "preventive_action", "verification_remarks", "verified_by_name",
)
_NC_VERIFICATION_FIELDS = ("verified_by", "verified_at", "verification_remarks")


def _nc_value(nc, field_name: str):
    return {
        "verified_by": nc.verified_by_id,
        "verified_by_name": nc.verified_by_name,
        "verified_at": nc.verified_at,
    }.get(field_name, getattr(nc, field_name, None))


def _nc_field_state(nc, field_name: str) -> str:
    """Return present, empty, or unavailable without conflating blank and omitted."""
    if not nc.field_was_returned(field_name):
        return "unavailable"
    value = _nc_value(nc, field_name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return "empty"
    return "present"


def _nc_action_presence(nc) -> bool | None:
    """Whether correction or corrective action text is known to be recorded."""
    correction_state = _nc_field_state(nc, "correction")
    action_state = _nc_field_state(nc, "corrective_action")
    if "present" in {correction_state, action_state}:
        return True
    if correction_state == action_state == "empty":
        return False
    if nc.returned_fields is None:
        # Compatibility with mock fixture records that predate raw text fields.
        if nc.correction_submitted or nc.corrective_action_submitted:
            return True
        if "correction_submitted" in nc.model_fields_set and "corrective_action_submitted" in nc.model_fields_set:
            return False
    return None


def _consistency_warnings(snapshot: AuditSnapshot, as_of: date) -> list[Fact]:
    """Flag explicit record inconsistencies and missing evidence without inferring actions."""
    audit = snapshot.audit
    warnings: list[Fact] = []

    if audit.planned_end_date <= audit.planned_start_date:
        warnings.append(_warning(
            "audit-planned-date-order",
            "Audit planned dates are inconsistent",
            "The planned end date is not later than the planned start date.",
            [
                _ref("audit", audit.id, "planned_start_date", audit.planned_start_date),
                _ref("audit", audit.id, "planned_end_date", audit.planned_end_date),
            ],
        ))

    if audit.status.value == "CLOSED":
        future_dates = [
            ("planned_start_date", audit.planned_start_date),
            ("planned_end_date", audit.planned_end_date),
        ]
        future_dates = [(field, value) for field, value in future_dates if value > as_of]
        if future_dates:
            warnings.append(_warning(
                "closed-audit-future-planned-date",
                "Closed audit has a future planned date",
                "The audit is recorded as CLOSED, but one or more planned dates are after the review date. This is a record consistency warning; the audit status remains the QMS fact.",
                [
                    _ref("audit", audit.id, "status", audit.status.value),
                    *[_ref("audit", audit.id, field, value) for field, value in future_dates],
                    _ref("analysis_context", audit.id, "as_of_date", as_of),
                ],
            ))

    progressed_statuses = {"IN_PROGRESS", "PENDING_CLOSURE", "CLOSED"}
    if audit.status.value in progressed_statuses and not snapshot.assignments:
        warnings.append(_warning(
            "missing-audit-assignments",
            "Lifecycle assignment evidence is missing",
            f"The audit is recorded as {audit.status.value}, but no auditor assignments were returned.",
            [
                _ref("audit", audit.id, "status", audit.status.value),
                _ref("audit", audit.id, "assignments", "none returned by provider"),
            ],
        ))
    elif audit.status.value in progressed_statuses:
        present_roles = {assignment.assignment_type.value for assignment in snapshot.assignments}
        missing_roles = {"PRIMARY", "SECONDARY"} - present_roles
        if missing_roles:
            warnings.append(_warning(
                "lifecycle-assignment-roles-incomplete",
                "Lifecycle assignment information is incomplete",
                f"The audit is recorded as {audit.status.value}, but assignment records are missing the {', '.join(sorted(missing_roles))} role(s).",
                [
                    _ref("audit", audit.id, "status", audit.status.value),
                    *[
                        _ref("assignment", assignment.id, "assignment_type", assignment.assignment_type.value)
                        for assignment in snapshot.assignments
                    ],
                    _ref("audit", audit.id, "missing_assignment_roles", ",".join(sorted(missing_roles))),
                ],
            ))

    if audit.status.value == "PENDING_ASSIGNMENT":
        assigned_types = {assignment.assignment_type.value for assignment in snapshot.assignments}
        if {"PRIMARY", "SECONDARY"}.issubset(assigned_types):
            warnings.append(_warning(
                "assignment-status-inconsistent",
                "Audit status may not reflect its assignments",
                "The audit is recorded as PENDING_ASSIGNMENT, while both primary and secondary assignments are present.",
                [
                    _ref("audit", audit.id, "status", audit.status.value),
                    *[
                        _ref("assignment", assignment.id, "assignment_type", assignment.assignment_type.value)
                        for assignment in snapshot.assignments
                        if assignment.assignment_type.value in {"PRIMARY", "SECONDARY"}
                    ],
                ],
            ))

    if snapshot.schedule:
        schedule = snapshot.schedule
        if schedule.scheduled_end <= schedule.scheduled_start:
            warnings.append(_warning(
                "schedule-date-order",
                "Schedule dates are inconsistent",
                "The scheduled end is not later than the scheduled start.",
                [
                    _ref("schedule", schedule.id, "scheduled_start", schedule.scheduled_start),
                    _ref("schedule", schedule.id, "scheduled_end", schedule.scheduled_end),
                ],
            ))
        if audit.status.value == "CLOSED" and schedule.status.value != "CONFIRMED":
            warnings.append(_warning(
                "closed-audit-unconfirmed-schedule",
                "Closed audit has a non-confirmed schedule",
                "The audit is recorded as CLOSED while its returned schedule is not CONFIRMED. Review the records; no lifecycle action is inferred.",
                [
                    _ref("audit", audit.id, "status", audit.status.value),
                    _ref("schedule", schedule.id, "status", schedule.status.value),
                ],
            ))
    elif audit.status.value in progressed_statuses:
        warnings.append(_warning(
            "missing-progressed-audit-schedule",
            "Lifecycle schedule evidence is missing",
            f"The audit is recorded as {audit.status.value}, but no schedule was returned.",
            [
                _ref("audit", audit.id, "status", audit.status.value),
                _ref("audit", audit.id, "schedule", "none returned by provider"),
            ],
        ))

    for assignment in snapshot.assignments:
        if assignment.orientation_status is None:
            warnings.append(_warning(
                f"orientation-status-unavailable-{assignment.id}",
                "Orientation status is unavailable",
                f"No orientation status was returned for assignment {assignment.id}; the agent cannot determine whether orientation is pending or complete.",
                [_ref("assignment", assignment.id, "orientation_status", "not returned")],
            ))

    for nc in snapshot.non_conformities:
        omitted_fields = [
            field for field in (*_NC_TEXT_FIELDS, "verified_by", "verified_at")
            if not nc.field_was_returned(field)
        ]
        if omitted_fields:
            warnings.append(_warning(
                f"nc-fields-unavailable-{nc.id}",
                f"Non-conformity fields were not returned: {nc.item_code}",
                "The API omitted the listed fields, so their values are unavailable; omitted fields are not treated as blank.",
                [_ref("non_conformity", nc.id, field, "not returned") for field in omitted_fields],
            ))

        for field in (
            "finding", "risk_action", "correction", "corrective_action",
            "preventive_action", "verified_by_name",
        ):
            if _nc_field_state(nc, field) != "empty":
                continue
            required_for_verification = field in {"correction", "corrective_action"}
            both_verification_actions_empty = (
                _nc_field_state(nc, "correction") == "empty"
                and _nc_field_state(nc, "corrective_action") == "empty"
            )
            is_warning = field == "finding" or (
                required_for_verification and both_verification_actions_empty
            )
            title = {
                "finding": "Non-conformity finding is blank",
                "risk_action": "Risk action is blank",
                "correction": "Correction field is blank",
                "corrective_action": "Corrective-action field is blank",
                "preventive_action": "Preventive-action field is blank",
                "verified_by_name": "Verifier display name is blank",
            }[field]
            detail = f"The {field.replace('_', ' ')} field was returned but contains no text."
            if field == "risk_action":
                detail += " Risk action is separate from correction and corrective action."
            elif field == "preventive_action":
                detail += " Whether a preventive action is mandatory has not been established."
            elif field == "verified_by_name":
                detail += " The verifier ID remains the identity reference; no display-name requirement is inferred."
            elif field in {"correction", "corrective_action"} and not both_verification_actions_empty:
                detail += " This field is reported as blank; no rule that it is individually mandatory is inferred."
            warnings.append(Fact(
                id=f"nc-field-empty-{field}-{nc.id}",
                title=title,
                detail=detail,
                source_refs=[_ref("non_conformity", nc.id, field, "empty")],
                kind="warning" if is_warning else "fact",
            ))

        verification_expected = nc.status in {NCStatus.ACCEPTED, NCStatus.REWORK_REQUIRED}
        if verification_expected:
            for field in _NC_VERIFICATION_FIELDS:
                state = _nc_field_state(nc, field)
                if state == "empty":
                    warnings.append(_warning(
                        f"nc-verification-field-empty-{field}-{nc.id}",
                        f"Non-conformity verification field is blank: {nc.item_code}",
                        f"The verification-stage {field.replace('_', ' ')} field was returned but is empty.",
                        [_ref("non_conformity", nc.id, field, "empty")],
                    ))

        action_evidence = _nc_action_presence(nc)
        verification_evidence = (
            nc.field_was_returned("verified_by")
            and nc.verified_by_id is not None
            and nc.field_was_returned("verified_at")
            and nc.verified_at is not None
        )
        if nc.status == NCStatus.ACCEPTED and not (action_evidence is True and verification_evidence):
            action_value = (
                "not returned" if action_evidence is None
                else "recorded" if action_evidence
                else "empty"
            )
            warnings.append(_warning(
                f"accepted-nc-completion-unconfirmed-{nc.id}",
                f"Accepted NC {nc.item_code} lacks completion evidence",
                "The NC is recorded as ACCEPTED, but status alone does not prove completion. The returned record must show at least a correction or corrective action plus verifier identity and verification date; omitted fields remain unknown.",
                [
                    _ref("non_conformity", nc.id, "status", nc.status.value),
                    _ref("non_conformity", nc.id, "correction_or_corrective_action", action_value),
                    _ref("non_conformity", nc.id, "verified_by", nc.verified_by_id if nc.field_was_returned("verified_by") else "not returned"),
                    _ref("non_conformity", nc.id, "verified_at", nc.verified_at if nc.field_was_returned("verified_at") else "not returned"),
                ],
            ))

        if nc.status in {NCStatus.OPEN, NCStatus.SUBMITTED}:
            warnings.append(_warning(
                f"nc-work-incomplete-{nc.id}",
                f"Non-conformity work is not recorded as accepted: {nc.item_code}",
                f"The recorded status is {nc.status.value}; this is an incomplete workflow state, not a judgment about the quality of the recorded action text.",
                [_ref("non_conformity", nc.id, "status", nc.status.value)],
            ))

        if nc.status == NCStatus.REWORK_REQUIRED:
            remarks_state = _nc_field_state(nc, "verification_remarks")
            remarks = (nc.verification_remarks or "").strip()
            if remarks_state == "present":
                detail = f"Recorded verifier remarks: {remarks}"
            elif remarks_state == "empty":
                detail = "The NC requires rework, but the returned verification remarks are blank. Ask the authorized verifier to clarify the requested rework."
            else:
                detail = "The NC requires rework, but verification remarks were not returned and cannot be assessed."
            warnings.append(_warning(
                f"nc-rework-required-{nc.id}",
                f"Non-conformity requires rework: {nc.item_code}",
                detail,
                [
                    _ref("non_conformity", nc.id, "status", nc.status.value),
                    _ref("non_conformity", nc.id, "verification_remarks", remarks if remarks_state == "present" else remarks_state),
                ],
            ))

    if not snapshot.checklist_item_details_available:
        refs = [_ref("agent_capability", audit.id, "checklist_item_details", "unavailable")]
        if snapshot.checklist_progress:
            refs.append(_ref(
                "audit_progress", audit.id, "checklist.item_count",
                snapshot.checklist_progress.item_count,
            ))
        warnings.append(_warning(
            "checklist-item-evidence-incomplete",
            "Checklist item evidence is unavailable",
            "The authorized read interface does not provide checklist-item details to the agent; checklist progress may be aggregate-only or absent.",
            refs,
        ))

    if snapshot.checklist_progress:
        progress = snapshot.checklist_progress
        result_count = progress.compliant + progress.non_compliant + progress.pending
        if result_count != progress.item_count:
            warnings.append(_warning(
                "checklist-progress-counts-inconsistent",
                "Checklist progress counts are inconsistent",
                f"The aggregate reports {progress.item_count} checklist items, but its result counts sum to {result_count}.",
                [
                    _ref("audit_progress", audit.id, "checklist.item_count", progress.item_count),
                    _ref("audit_progress", audit.id, "checklist.compliant", progress.compliant),
                    _ref("audit_progress", audit.id, "checklist.non_compliant", progress.non_compliant),
                    _ref("audit_progress", audit.id, "checklist.pending", progress.pending),
                ],
            ))

    return warnings


def analyze_audit(snapshot: AuditSnapshot, *, as_of: date | None = None) -> AuditAnalysis:
    """Derive audit facts and next-step suggestions without an LLM."""
    review_date = as_of or date.today()
    audit = snapshot.audit
    audit_ref = lambda field, value: _ref("audit", audit.id, field, value)
    facts: list[Fact] = [
        Fact(
            id="audit-status",
            title="Audit status",
            detail=f"{audit.code} is {audit.status.value}.",
            source_refs=[audit_ref("status", audit.status.value)],
        ),
        Fact(
            id="audit-scope",
            title="Audit scope",
            detail=f"{audit.project_name} / {audit.department} / {audit.framework}.",
            source_refs=[
                audit_ref("project_name", audit.project_name),
                audit_ref("department", audit.department),
                audit_ref("framework", audit.framework),
            ],
        ),
    ]
    recommendations: list[Recommendation] = []

    assignment_types = {assignment.assignment_type for assignment in snapshot.assignments}
    missing = [kind for kind in ("PRIMARY", "SECONDARY") if kind not in assignment_types]
    if snapshot.assignments:
        refs = [
            _ref(
                "assignment",
                assignment.id,
                "orientation_status",
                assignment.orientation_status.value if assignment.orientation_status else "not returned",
            )
            for assignment in snapshot.assignments
        ]
        facts.append(Fact(
            id="assignments",
            title="Auditor assignments",
            detail=f"{len(snapshot.assignments)} auditor assignment(s); missing roles: {', '.join(missing) if missing else 'none'}.",
            source_refs=refs or [audit_ref("status", audit.status.value)],
        ))
        pending_orientations = [a for a in snapshot.assignments if a.orientation_status == OrientationStatus.PENDING]
        if pending_orientations:
            recommendations.append(Recommendation(
                id="complete-orientations",
                text="Complete the pending auditor orientation(s) before starting the audit.",
                source_refs=[
                    _ref("assignment", a.id, "orientation_status", a.orientation_status.value)
                    for a in pending_orientations
                ],
            ))
    else:
        facts.append(Fact(
            id="assignments",
            title="Auditor assignments",
            detail="No auditor assignments are recorded.",
            source_refs=[_ref("audit", audit.id, "assignments", "none returned by provider")],
        ))
    if missing and audit.status.value == "PENDING_ASSIGNMENT":
        recommendations.append(Recommendation(
            id="assign-auditors",
            text=f"Assign the missing auditor role(s): {', '.join(missing)}.",
            source_refs=[
                audit_ref("status", audit.status.value),
                _ref("audit", audit.id, "assignments", f"missing {', '.join(missing)}"),
            ],
        ))

    if snapshot.schedule:
        schedule = snapshot.schedule
        schedule_refs = [
            _ref("schedule", schedule.id, "status", schedule.status.value),
            _ref("schedule", schedule.id, "confirmations", ",".join(schedule.confirmations) or "none"),
        ]
        facts.append(Fact(
            id="schedule",
            title="Schedule",
            detail=f"Schedule is {schedule.status.value}; confirmations recorded: {', '.join(schedule.confirmations) or 'none'}.",
            source_refs=schedule_refs,
        ))
        needed_confirmations = {"COMBINED", "INDIVIDUAL"} - set(schedule.confirmations)
        if schedule.status.value != "CONFIRMED" and needed_confirmations:
            recommendations.append(Recommendation(
                id="complete-confirmations",
                text=f"Record the missing confirmation(s): {', '.join(sorted(needed_confirmations))}.",
                source_refs=schedule_refs,
            ))
    else:
        facts.append(Fact(
            id="schedule",
            title="Schedule",
            detail="No audit schedule is recorded.",
            source_refs=[_ref("audit", audit.id, "schedule", "none returned by provider")],
        ))
        if audit.status.value == "ASSIGNED":
            recommendations.append(Recommendation(
                id="schedule-audit",
                text="Create an audit schedule before the assigned auditor starts.",
                source_refs=[audit_ref("status", audit.status.value)],
            ))

    checklist_progress = snapshot.checklist_progress if not snapshot.checklist_items else None
    if checklist_progress:
        counts = Counter({
            ChecklistResult.COMPLIANT.value: checklist_progress.compliant,
            ChecklistResult.NON_COMPLIANT.value: checklist_progress.non_compliant,
            ChecklistResult.PENDING.value: checklist_progress.pending,
        })
        total = checklist_progress.item_count
        checklist_refs = [
            _ref("audit_progress", audit.id, f"checklist.{field}", value)
            for field, value in (
                ("item_count", checklist_progress.item_count),
                ("compliant", checklist_progress.compliant),
                ("non_compliant", checklist_progress.non_compliant),
                ("pending", checklist_progress.pending),
            )
        ]
    else:
        counts = Counter(item.result.value for item in snapshot.checklist_items)
        checklist_refs = [
            _ref("checklist_item", item.id, "result", item.result.value)
            for item in snapshot.checklist_items
        ] or [_ref("audit", audit.id, "checklist_items", "none returned by provider")]
        total = len(snapshot.checklist_items)
    if not snapshot.checklist_items and not checklist_progress and not snapshot.checklist_item_details_available:
        checklist_fact_detail = "Checklist-item details were not available to the agent."
        checklist_refs = [_ref("agent_capability", audit.id, "checklist_item_details", "unavailable")]
    else:
        checklist_fact_detail = ((f"{total} item(s): {counts[ChecklistResult.COMPLIANT.value]} compliant, "
                                 f"{counts[ChecklistResult.NON_COMPLIANT.value]} non-compliant, "
                                 f"{counts[ChecklistResult.PENDING.value]} pending.")
                                 if total else "No checklist items are recorded.")
    facts.append(Fact(
        id="checklist-results",
        title="Checklist results",
        detail=checklist_fact_detail,
        source_refs=checklist_refs,
    ))
    pending_items = [item for item in snapshot.checklist_items if item.result == ChecklistResult.PENDING]
    pending_count = len(pending_items) if snapshot.checklist_items else (checklist_progress.pending if checklist_progress else 0)
    if pending_count:
        recommendations.append(Recommendation(
            id="evaluate-pending-items",
            text=f"Evaluate the {pending_count} pending checklist item(s).",
            source_refs=(
                [_ref("checklist_item", item.id, "result", item.result.value) for item in pending_items]
                if snapshot.checklist_items
                else [_ref("audit_progress", audit.id, "checklist.pending", pending_count)]
            ),
        ))

    nc_refs = [_ref("non_conformity", nc.id, "status", nc.status.value) for nc in snapshot.non_conformities]
    nc_counts = Counter(nc.status.value for nc in snapshot.non_conformities)
    facts.append(Fact(
        id="non-conformities",
        title="Non-conformities",
        detail=(f"{len(snapshot.non_conformities)} total: " + ", ".join(
            f"{status.lower().replace('_', ' ')} {nc_counts[status.value]}"
            for status in NCStatus
            if nc_counts[status.value]
        ) if snapshot.non_conformities else "No non-conformities are recorded."),
        source_refs=nc_refs or [_ref("audit", audit.id, "non_conformities", "none returned by provider")],
    ))
    for nc in snapshot.non_conformities:
        finding_state = _nc_field_state(nc, "finding")
        finding_detail = (
            nc.finding.strip() if finding_state == "present"
            else "Finding field was returned but is blank." if finding_state == "empty"
            else "Finding field was not returned by the provider."
        )
        facts.append(Fact(
            id=f"nc-finding-{nc.id}",
            title=f"Non-conformity finding: {nc.item_code}",
            detail=finding_detail,
            source_refs=[
                _ref("non_conformity", nc.id, "item_code", nc.item_code),
                _ref("non_conformity", nc.id, "finding", nc.finding if finding_state == "present" else finding_state),
            ],
        ))

        if nc.status == NCStatus.ACCEPTED:
            item = next((row for row in snapshot.checklist_items if row.id == nc.checklist_item_id), None)
            if item and item.result == ChecklistResult.NON_COMPLIANT:
                recommendations.append(Recommendation(
                    id=f"recheck-{nc.id}",
                    text=f"Re-evaluate {nc.item_code} after the accepted non-conformity response.",
                    source_refs=[
                        _ref("non_conformity", nc.id, "status", nc.status.value),
                        _ref("checklist_item", item.id, "result", item.result.value),
                    ],
                ))
        if nc.status in {NCStatus.OPEN, NCStatus.SUBMITTED}:
            action_presence = _nc_action_presence(nc)
            if action_presence is False:
                action_text = "Record a correction or corrective action before verification."
                action_refs = [
                    _ref("non_conformity", nc.id, "correction", _nc_field_state(nc, "correction")),
                    _ref("non_conformity", nc.id, "corrective_action", _nc_field_state(nc, "corrective_action")),
                ]
            elif action_presence is True:
                action_text = "Action text is recorded; submit or review it through the QMS process for an authorized verification decision."
                action_refs = [
                    _ref("non_conformity", nc.id, "correction", _nc_field_state(nc, "correction")),
                    _ref("non_conformity", nc.id, "corrective_action", _nc_field_state(nc, "corrective_action")),
                ]
            else:
                action_text = "Action fields were not returned; retrieve the record details before deciding what action remains."
                action_refs = [
                    _ref("non_conformity", nc.id, "correction", "not returned"),
                    _ref("non_conformity", nc.id, "corrective_action", "not returned"),
                ]
            recommendations.append(Recommendation(
                id=f"nc-action-{nc.id}",
                text=f"{action_text} NC {nc.item_code} remains {nc.status.value}.",
                source_refs=[_ref("non_conformity", nc.id, "status", nc.status.value), *action_refs],
            ))
        elif nc.status == NCStatus.REWORK_REQUIRED:
            remarks_state = _nc_field_state(nc, "verification_remarks")
            remarks = (nc.verification_remarks or "").strip()
            if remarks_state == "present":
                rework_text = f"Address the verifier's rework remarks for {nc.item_code}: {remarks}"
            elif remarks_state == "empty":
                rework_text = f"Request clarification of the blank verification remarks, then address the required rework for {nc.item_code}."
            else:
                rework_text = f"Retrieve the omitted verification remarks and address the required rework for {nc.item_code}."
            recommendations.append(Recommendation(
                id=f"nc-rework-{nc.id}",
                text=rework_text,
                source_refs=[
                    _ref("non_conformity", nc.id, "status", nc.status.value),
                    _ref("non_conformity", nc.id, "verification_remarks", remarks if remarks_state == "present" else remarks_state),
                ],
            ))
        elif nc.status == NCStatus.ACCEPTED and not (
            _nc_action_presence(nc) is True
            and nc.field_was_returned("verified_by") and nc.verified_by_id is not None
            and nc.field_was_returned("verified_at") and nc.verified_at is not None
        ):
            recommendations.append(Recommendation(
                id=f"recheck-nc-evidence-{nc.id}",
                text=f"Review the recorded action and verification evidence for accepted NC {nc.item_code}; ACCEPTED status alone does not establish that the evidence is complete.",
                status="informational",
                source_refs=[
                    _ref("non_conformity", nc.id, "status", nc.status.value),
                    _ref("non_conformity", nc.id, "correction", _nc_field_state(nc, "correction")),
                    _ref("non_conformity", nc.id, "corrective_action", _nc_field_state(nc, "corrective_action")),
                    _ref("non_conformity", nc.id, "verified_by", nc.verified_by_id if nc.field_was_returned("verified_by") else "not returned"),
                    _ref("non_conformity", nc.id, "verified_at", nc.verified_at if nc.field_was_returned("verified_at") else "not returned"),
                ],
            ))

    facts.extend(_consistency_warnings(snapshot, review_date))

    if audit.status.value in {"IN_PROGRESS", "PENDING_CLOSURE"} and total:
        all_compliant = counts[ChecklistResult.COMPLIANT.value] == total
        progress_counts_consistent = (
            checklist_progress is None
            or counts[ChecklistResult.COMPLIANT.value]
            + counts[ChecklistResult.NON_COMPLIANT.value]
            + counts[ChecklistResult.PENDING.value] == total
        )
        all_ncs_completion_confirmed = all(
            nc.status == NCStatus.ACCEPTED
            and _nc_action_presence(nc) is True
            and nc.verified_by_id is not None
            and nc.verified_at is not None
            for nc in snapshot.non_conformities
        )
        if all_compliant and progress_counts_consistent and all_ncs_completion_confirmed:
            recommendations.append(Recommendation(
                id="closure-checks-met",
                text="The available checklist and NC data meet the deterministic closure checks; confirm the authorized closer and QMS policy before closing.",
                status="informational",
                source_refs=checklist_refs + (nc_refs or []),
            ))

    category = _category(audit.status.value, recommendations)
    return AuditAnalysis(
        audit_id=audit.id,
        audit_code=audit.code,
        facts=facts,
        recommendations=recommendations,
        unresolved_policies=list(UNRESOLVED_POLICIES),
        explanation=_deterministic_explanation(category),
        explanation_source="deterministic",
        llm_used=False,
    )


def analyze_compliance_gaps(snapshot: AuditSnapshot) -> list[Fact]:
    """Return item-level recorded gaps without using an LLM or other lifecycle data."""
    findings: list[Fact] = []
    for item in snapshot.checklist_items:
        if item.result == ChecklistResult.NON_COMPLIANT:
            refs = [
                _ref("checklist_item", item.id, "item_code", item.item_code),
                _ref("checklist_item", item.id, "result", item.result.value),
            ]
            if item.remarks:
                refs.append(_ref("checklist_item", item.id, "remarks", item.remarks))
            findings.append(Fact(
                id=f"gap-{item.id}",
                title=f"Non-compliant checklist item: {item.item_code}",
                detail=item.question,
                source_refs=refs,
                kind="gap",
            ))
        elif item.result == ChecklistResult.PENDING:
            findings.append(Fact(
                id=f"pending-{item.id}",
                title=f"Unassessed checklist item: {item.item_code}",
                detail=item.question,
                source_refs=[
                    _ref("checklist_item", item.id, "item_code", item.item_code),
                    _ref("checklist_item", item.id, "result", item.result.value),
                ],
                kind="pending",
            ))

    if not snapshot.checklist_items and snapshot.checklist_progress:
        progress = snapshot.checklist_progress
        if progress.non_compliant:
            findings.append(Fact(
                id="aggregate-non-compliant-items",
                title="Non-compliant checklist items recorded",
                detail=(
                    f"The QMS audit progress reports {progress.non_compliant} non-compliant item(s). "
                    "Item-level details are not available through an authorized read endpoint."
                ),
                source_refs=[_ref("audit_progress", snapshot.audit.id, "checklist.non_compliant", progress.non_compliant)],
                kind="gap",
            ))
        if progress.pending:
            findings.append(Fact(
                id="aggregate-pending-items",
                title="Checklist items remain unassessed",
                detail=(
                    f"The QMS audit progress reports {progress.pending} pending item(s). "
                    "Item-level details are not available through an authorized read endpoint."
                ),
                source_refs=[_ref("audit_progress", snapshot.audit.id, "checklist.pending", progress.pending)],
                kind="pending",
            ))

    for nc in snapshot.non_conformities:
        if nc.status != NCStatus.ACCEPTED:
            findings.append(Fact(
                id=f"gap-{nc.id}",
                title=f"Unresolved non-conformity: {nc.item_code}",
                detail=nc.finding,
                source_refs=[
                    _ref("non_conformity", nc.id, "status", nc.status.value),
                    _ref("non_conformity", nc.id, "item_code", nc.item_code),
                ],
                kind="gap",
            ))

    if not findings:
        progress_refs = []
        if snapshot.checklist_progress:
            progress_refs = [
                _ref("audit_progress", snapshot.audit.id, f"checklist.{field}", value)
                for field, value in (
                    ("item_count", snapshot.checklist_progress.item_count),
                    ("non_compliant", snapshot.checklist_progress.non_compliant),
                    ("pending", snapshot.checklist_progress.pending),
                )
            ]
        if not snapshot.checklist_item_details_available and not snapshot.checklist_progress:
            findings.append(_warning(
                "compliance-evidence-incomplete",
                "Compliance evidence is incomplete",
                "The agent cannot determine whether checklist gaps exist because neither item-level checklist evidence nor aggregate checklist progress was returned.",
                [
                    _ref("agent_capability", snapshot.audit.id, "checklist_item_details", "unavailable"),
                    _ref("audit", snapshot.audit.id, "status", snapshot.audit.status.value),
                    *[
                        _ref("non_conformity", nc.id, "status", nc.status.value)
                        for nc in snapshot.non_conformities
                    ],
                ],
            ))
        else:
            findings.append(Fact(
                id="no-recorded-gaps",
                title="No recorded compliance gaps",
                detail="The available checklist evidence and returned non-conformity records contain no non-compliant results or unresolved NCs.",
                source_refs=[
                    _ref("audit", snapshot.audit.id, "status", snapshot.audit.status.value),
                    *progress_refs,
                    *[
                        _ref("checklist_item", item.id, "result", item.result.value)
                        for item in snapshot.checklist_items
                    ],
                    *[
                        _ref("non_conformity", nc.id, "status", nc.status.value)
                        for nc in snapshot.non_conformities
                    ],
                ],
            ))
    return findings


def _category(status: str, recommendations: list[Recommendation]) -> str:
    if status == "CLOSED":
        return "closed"
    if status in {"IN_PROGRESS", "PENDING_CLOSURE"}:
        return "active"
    if recommendations:
        return "attention"
    return "overview"


def _deterministic_explanation(category: str) -> str:
    return {
        "closed": "This audit is recorded as closed. Review the cited facts and unresolved policy note.",
        "active": "This audit is in an active lifecycle stage. The facts and next steps below are derived from the returned QMS records.",
        "attention": "The records show one or more items to address. Review the recommendations and their source references.",
        "overview": "Review the audit facts and cited source records below.",
    }[category]
