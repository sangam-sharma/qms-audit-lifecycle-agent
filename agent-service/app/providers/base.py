from typing import Literal, Protocol

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


class ProviderError(Exception):
    """Expected provider failure that can be returned without leaking internals."""

    code = "provider_error"
    public_message = "QMS data provider request failed."


class ProviderUnauthorized(ProviderError):
    code = "qms_unauthorized"
    public_message = "QMS rejected the supplied bearer token."


class ProviderForbidden(ProviderError):
    code = "qms_forbidden"
    public_message = "The authenticated user is not allowed to read this QMS resource."


class ProviderNotFound(ProviderError):
    code = "qms_not_found"
    public_message = "The requested QMS resource was not found or is not visible to this user."


class ProviderTimeout(ProviderError):
    code = "qms_timeout"
    public_message = "QMS did not respond before the request timed out."


class ProviderUnavailable(ProviderError):
    code = "qms_unavailable"
    public_message = "QMS is unavailable or returned an unexpected response."


class ProviderEndpointNotAllowed(ProviderError):
    code = "endpoint_not_allowed"
    public_message = "That QMS endpoint is not enabled for agent reads."


class AuditNotFound(ProviderNotFound):
    """No audit exists for the requested identifier."""

    code = "audit_not_found"
    public_message = "Audit was not found or is not visible to this user."


class QMSDataProvider(Protocol):
    def list_audits(self, *, context: ToolExecutionContext | None = None) -> list[AuditRecord]: ...

    def get_audit(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> AuditRecord: ...

    def get_checklist(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[ChecklistItemRecord]: ...

    def get_checklist_progress(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> ChecklistProgress | None: ...

    def get_assignments(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[AssignmentRecord]: ...

    def get_schedule(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> ScheduleRecord | None: ...

    def get_confirmations(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[Literal["COMBINED", "INDIVIDUAL"]]: ...

    def get_orientations(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> dict[str, OrientationStatus | None]: ...

    def get_non_conformities(self, audit_id: str, *, context: ToolExecutionContext | None = None) -> list[NCRecord]: ...
