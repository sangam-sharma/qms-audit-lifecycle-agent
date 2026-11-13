from app.domain.schemas import AuditSnapshot, ToolExecutionContext
from app.providers.base import QMSDataProvider


class ReadOnlyQMSTools:
    """Narrow read-only operations exposed to the orchestrator."""

    def __init__(self, provider: QMSDataProvider, context: ToolExecutionContext | None = None) -> None:
        self._provider = provider
        self._context = context

    def list_audits(self):
        return self._provider.list_audits(context=self._context)

    def get_audit(self, audit_id: str):
        return self._provider.get_audit(audit_id, context=self._context)

    def get_checklist(self, audit_id: str):
        return self._provider.get_checklist(audit_id, context=self._context)

    def get_checklist_progress(self, audit_id: str):
        return self._provider.get_checklist_progress(audit_id, context=self._context)

    def get_assignments(self, audit_id: str):
        return self._provider.get_assignments(audit_id, context=self._context)

    def get_orientations(self, audit_id: str):
        return self._provider.get_orientations(audit_id, context=self._context)

    def get_schedule(self, audit_id: str):
        return self._provider.get_schedule(audit_id, context=self._context)

    def get_confirmations(self, audit_id: str):
        return self._provider.get_confirmations(audit_id, context=self._context)

    def get_non_conformities(self, audit_id: str):
        return self._provider.get_non_conformities(audit_id, context=self._context)

    @property
    def checklist_item_details_available(self) -> bool:
        return bool(getattr(self._provider, "checklist_item_details_available", True))

    def get_audit_snapshot(self, audit_id: str) -> AuditSnapshot:
        """Collect one snapshot from individual read-only QMS operations."""
        return AuditSnapshot(
            audit=self.get_audit(audit_id),
            assignments=self.get_assignments(audit_id),
            schedule=self.get_schedule(audit_id),
            checklist_items=self.get_checklist(audit_id),
            checklist_progress=self.get_checklist_progress(audit_id),
            checklist_item_details_available=self.checklist_item_details_available,
            non_conformities=self.get_non_conformities(audit_id),
        )
