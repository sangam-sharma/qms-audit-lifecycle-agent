import json
from pathlib import Path
from typing import Literal

from app.domain.schemas import (
    AssignmentRecord,
    AuditRecord,
    ChecklistItemRecord,
    ChecklistProgress,
    NCRecord,
    OrientationStatus,
    ScheduleRecord,
    ToolExecutionContext,
)
from app.providers.base import AuditNotFound


class MockQMSProvider:
    """Read-only provider backed by synthetic JSON fixtures."""

    checklist_item_details_available = True

    def __init__(self, fixture_path: Path | None = None) -> None:
        path = fixture_path or Path(__file__).resolve().parents[2] / "data" / "sample_audits.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._audits: dict[str, AuditRecord] = {}
        self._assignments: dict[str, list[AssignmentRecord]] = {}
        self._schedules: dict[str, ScheduleRecord | None] = {}
        self._items: dict[str, list[ChecklistItemRecord]] = {}
        self._ncs: dict[str, list[NCRecord]] = {}
        for row in raw:
            audit = AuditRecord.model_validate(row["audit"])
            self._audits[audit.id] = audit
            self._assignments[audit.id] = [AssignmentRecord.model_validate(x) for x in row["assignments"]]
            schedule = row["schedule"]
            self._schedules[audit.id] = ScheduleRecord.model_validate(schedule) if schedule else None
            self._items[audit.id] = [ChecklistItemRecord.model_validate(x) for x in row["checklist_items"]]
            self._ncs[audit.id] = [NCRecord.model_validate(x) for x in row["non_conformities"]]

    def list_audits(self, *, context: ToolExecutionContext | None = None) -> list[AuditRecord]:
        return sorted(self._audits.values(), key=lambda audit: audit.id)

    def get_audit(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> AuditRecord:
        if audit_id in self._audits:
            return self._audits[audit_id]
        for audit in self._audits.values():
            if audit.code.casefold() == audit_id.casefold():
                return audit
        raise AuditNotFound(audit_id)

    def get_checklist(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[ChecklistItemRecord]:
        self.get_audit(audit_id, context=context)
        return list(self._items[audit_id])

    def get_checklist_progress(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> ChecklistProgress | None:
        self.get_audit(audit_id, context=context)
        items = self._items[audit_id]
        if not items:
            return None
        return ChecklistProgress(
            item_count=len(items),
            compliant=sum(item.result.value == "COMPLIANT" for item in items),
            non_compliant=sum(item.result.value == "NON_COMPLIANT" for item in items),
            pending=sum(item.result.value == "PENDING" for item in items),
        )

    def get_assignments(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[AssignmentRecord]:
        self.get_audit(audit_id, context=context)
        return list(self._assignments[audit_id])

    def get_orientations(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> dict[str, OrientationStatus | None]:
        self.get_audit(audit_id, context=context)
        return {
            assignment.id: assignment.orientation_status
            for assignment in self._assignments[audit_id]
        }

    def get_schedule(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> ScheduleRecord | None:
        self.get_audit(audit_id, context=context)
        return self._schedules[audit_id]

    def get_confirmations(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[Literal["COMBINED", "INDIVIDUAL"]]:
        self.get_audit(audit_id, context=context)
        schedule = self._schedules[audit_id]
        return list(schedule.confirmations) if schedule else []

    def get_non_conformities(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[NCRecord]:
        self.get_audit(audit_id, context=context)
        return list(self._ncs[audit_id])
