"""Request-scoped, read-only adapter for the existing Django QMS API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from urllib.parse import quote

import httpx

from app.domain.schemas import (
    AssignmentRecord, AssignmentType, AuditRecord, AuditStatus, ChecklistItemRecord,
    ChecklistProgress, NCRecord, NCStatus, OrientationStatus, ScheduleRecord,
    ScheduleStatus, ToolExecutionContext,
)
from app.providers.base import (
    AuditNotFound, ProviderEndpointNotAllowed, ProviderError, ProviderForbidden,
    ProviderNotFound, ProviderTimeout, ProviderUnauthorized, ProviderUnavailable,
)


# Only named, fixed routes are accepted by _get. Mutating verbs are never exposed.
ENDPOINT_ALLOWLIST = frozenset({
    "identity", "audit_list", "audit_detail", "assignments", "schedule",
    "confirmations", "orientations", "non_conformities",
})
_ROUTES = {
    "identity": "auth/me/",
    "audit_list": "audits/",
    "audit_detail": "audits/{audit_id}/",
    "assignments": "audits/{audit_id}/assignments/",
    "schedule": "audits/{audit_id}/schedule/",
    "confirmations": "audits/{audit_id}/confirmations/",
    "orientations": "orientations/",
    "non_conformities": "audits/{audit_id}/ncs/",
}


class DjangoAPIProvider:
    """Maps Django API responses to agent schemas; instantiate once per request."""

    checklist_item_details_available = False

    def __init__(
        self,
        base_url: str,
        jwt: str,
        *,
        timeout: float = 8.0,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if not jwt or any(ch in jwt for ch in "\r\n"):
            raise ValueError("A valid bearer credential is required")
        self._identity_validated = False
        self._audit_cache: dict[str, tuple[AuditRecord, dict[str, Any]]] = {}
        self._client = client or httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {jwt}", "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
        )

    def __repr__(self) -> str:
        return "DjangoAPIProvider(jwt=[REDACTED])"

    def close(self) -> None:
        self._client.close()

    def _get(self, endpoint: str, **path_values: str) -> Any:
        if endpoint not in ENDPOINT_ALLOWLIST or endpoint not in _ROUTES:
            raise ProviderEndpointNotAllowed()
        try:
            safe_values = {key: quote(str(value), safe="") for key, value in path_values.items()}
            path = _ROUTES[endpoint].format(**safe_values)
        except (KeyError, ValueError) as exc:
            raise ProviderEndpointNotAllowed() from exc
        try:
            response = self._client.get(path)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout() from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable() from exc
        if response.status_code == 401:
            raise ProviderUnauthorized()
        if response.status_code == 403:
            raise ProviderForbidden()
        if response.status_code == 404:
            raise ProviderNotFound()
        if response.is_error:
            raise ProviderUnavailable()
        try:
            return response.json()
        except (ValueError, TypeError) as exc:
            raise ProviderUnavailable() from exc

    def validate_identity(self) -> dict[str, Any]:
        data = self._get("identity")
        if not isinstance(data, dict) or data.get("id") is None:
            raise ProviderUnavailable()
        self._identity_validated = True
        return data

    def _require_identity(self) -> None:
        if not self._identity_validated:
            raise ProviderUnauthorized()

    @staticmethod
    def _rows(data: Any) -> list[dict[str, Any]]:
        # DRF may return a plain array or a paginated {results: [...]} object.
        if isinstance(data, dict):
            data = data.get("results")
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ProviderUnavailable()
        return data

    @staticmethod
    def _audit_record(row: dict[str, Any]) -> AuditRecord:
        try:
            return AuditRecord(
                id=str(row["id"]), code=str(row["audit_code"]),
                project_name=str(row["project_name"]), department=str(row["department"]),
                framework=str(row.get("framework_name") or row.get("framework") or ""),
                planned_start_date=date.fromisoformat(str(row["planned_start_date"])[:10]),
                planned_end_date=date.fromisoformat(str(row["planned_end_date"])[:10]),
                status=AuditStatus(row["status"]), created_at=row["created_at"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable() from exc

    def list_audits(self, *, context: ToolExecutionContext | None = None) -> list[AuditRecord]:
        self._require_identity()
        return [self._audit_record(row) for row in self._rows(self._get("audit_list"))]

    def get_audit(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> AuditRecord:
        self._require_identity()
        cached = self._audit_cache.get(str(audit_id))
        if cached is not None:
            return cached[0]
        rows = self._rows(self._get("audit_list"))
        match = next((row for row in rows if str(row.get("id")) == str(audit_id)), None)
        if match is None:
            match = next((row for row in rows if str(row.get("audit_code", "")).casefold() == audit_id.casefold()), None)
        if match is None:
            raise AuditNotFound()
        resolved_id = str(match["id"])
        try:
            detail = self._get("audit_detail", audit_id=resolved_id)
        except ProviderNotFound as exc:
            raise AuditNotFound() from exc
        if not isinstance(detail, dict):
            raise ProviderUnavailable()
        record = self._audit_record(detail)
        self._audit_cache[resolved_id] = (record, detail)
        self._audit_cache[str(audit_id)] = (record, detail)
        self._audit_cache[record.code] = (record, detail)
        return record

    def get_checklist(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[ChecklistItemRecord]:
        # Item-level audit checklist routes are intentionally not authorized for QMS users.
        self.get_audit(audit_id, context=context)
        return []

    def get_checklist_progress(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> ChecklistProgress | None:
        self.get_audit(audit_id, context=context)
        record, detail = self._audit_cache[str(audit_id)]
        progress = (detail.get("progress") or {}).get("checklist")
        if not isinstance(progress, dict):
            return None
        try:
            return ChecklistProgress(
                id=str(progress["id"]) if progress.get("id") is not None else None,
                name=progress.get("name"), item_count=progress["item_count"],
                compliant=progress["compliant"], non_compliant=progress["non_compliant"],
                pending=progress["pending"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable() from exc

    def get_orientations(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> dict[str, OrientationStatus | None]:
        self.get_audit(audit_id, context=context)
        rows = self._rows(self._get("orientations"))
        result: dict[str, OrientationStatus | None] = {}
        for row in rows:
            if str(row.get("audit_code", "")).casefold() != self._audit_cache[str(audit_id)][0].code.casefold():
                continue
            try:
                status = OrientationStatus(row["status"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderUnavailable() from exc
            result[str(row["assignment"])] = status
        return result

    def get_assignments(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[AssignmentRecord]:
        audit = self.get_audit(audit_id, context=context)
        rows = self._rows(self._get("assignments", audit_id=audit.id))
        orientations = self.get_orientations(audit.id, context=context)
        try:
            return [AssignmentRecord(
                id=str(row["id"]), audit_id=audit.id,
                auditor_name=str(row.get("auditor_name") or ""),
                assignment_type=AssignmentType(row["assignment_type"]),
                orientation_status=orientations.get(str(row["id"])),
            ) for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable() from exc

    def get_confirmations(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[Literal["COMBINED", "INDIVIDUAL"]]:
        audit = self.get_audit(audit_id, context=context)
        rows = self._rows(self._get("confirmations", audit_id=audit.id))
        try:
            return [row["confirmation_type"] for row in rows]
        except (KeyError, TypeError) as exc:
            raise ProviderUnavailable() from exc

    def get_schedule(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> ScheduleRecord | None:
        audit = self.get_audit(audit_id, context=context)
        data = self._get("schedule", audit_id=audit.id)
        rows = self._rows(data) if isinstance(data, (list, dict)) and (isinstance(data, list) or "results" in data) else [data]
        if not rows:
            return None
        row = rows[0]
        confirmations = self.get_confirmations(audit.id, context=context)
        try:
            return ScheduleRecord(
                id=str(row["id"]), audit_id=audit.id,
                scheduled_start=datetime.fromisoformat(str(row["scheduled_start"]).replace("Z", "+00:00")),
                scheduled_end=datetime.fromisoformat(str(row["scheduled_end"]).replace("Z", "+00:00")),
                status=ScheduleStatus(row["status"]), confirmations=confirmations,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable() from exc

    def get_non_conformities(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[NCRecord]:
        audit = self.get_audit(audit_id, context=context)
        rows = self._rows(self._get("non_conformities", audit_id=audit.id))
        try:
            nc_text_fields = (
                "finding", "risk_action", "correction", "corrective_action",
                "preventive_action", "verification_remarks", "verified_by_name",
            )
            mapped = []
            for row in rows:
                returned_fields = {
                    field for field in (
                        "id", "checklist_item_id", "item_code", "question", "project_name",
                        *nc_text_fields, "status", "verified_by", "verified_at", "created_at", "updated_at",
                    ) if field in row
                }
                text_values = {
                    field: (str(row[field]) if row[field] is not None else None)
                    for field in nc_text_fields
                    if field in row
                }
                correction = row.get("correction")
                corrective_action = row.get("corrective_action")
                mapped.append(NCRecord(
                    id=str(row["id"]), audit_id=audit.id,
                    checklist_item_id=str(row.get("checklist_item_id") or ""),
                    item_code=str(row.get("item_code") or ""), status=NCStatus(row["status"]),
                    question=(str(row["question"]) if row.get("question") is not None else None),
                    project_name=(str(row["project_name"]) if row.get("project_name") is not None else None),
                    finding=str(row.get("finding") or ""),
                    risk_action=text_values.get("risk_action"),
                    correction=text_values.get("correction"),
                    corrective_action=text_values.get("corrective_action"),
                    preventive_action=text_values.get("preventive_action"),
                    correction_submitted=bool(str(correction or "").strip()),
                    corrective_action_submitted=bool(str(corrective_action or "").strip()),
                    verified_by_id=(str(row["verified_by"]) if row.get("verified_by") is not None else None),
                    verified_by_name=text_values.get("verified_by_name"),
                    verified_at=row.get("verified_at"),
                    verification_remarks=text_values.get("verification_remarks"),
                    created_at=row.get("created_at"),
                    updated_at=row.get("updated_at"),
                    returned_fields=returned_fields,
                ))
            return mapped
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderUnavailable() from exc
