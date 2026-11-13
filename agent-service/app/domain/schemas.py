from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_CLOSURE = "PENDING_CLOSURE"
    CLOSED = "CLOSED"


class AssignmentType(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class OrientationStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class ScheduleStatus(StrEnum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"


class ChecklistResult(StrEnum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class NCStatus(StrEnum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    ACCEPTED = "ACCEPTED"


class TaskObjective(StrEnum):
    AUDIT_ANALYSIS = "audit_analysis"
    PENDING_ACTIONS = "pending_actions"
    COMPLETION_PLAN = "completion_plan"
    COMPLIANCE_GAP_ANALYSIS = "compliance_gap_analysis"
    PORTFOLIO_ANALYSIS = "portfolio_analysis"


class ReadToolName(StrEnum):
    AUDITS = "audits"
    AUDIT = "audit"
    ASSIGNMENTS = "assignments"
    SCHEDULE = "schedule"
    CHECKLIST = "checklist"
    NON_CONFORMITIES = "non_conformities"


class SourceRef(StrictModel):
    entity: str
    record_id: str
    field: str
    value: str


class ToolExecutionContext(StrictModel):
    """Future-safe identity reference passed outside LLM-visible graph state."""

    request_id: str | None = None
    principal_id: str | None = None
    system_id: str = "mock"
    scopes: list[str] = Field(default_factory=list)
    credential_ref: str | None = None


class AuditRecord(StrictModel):
    id: str
    code: str
    project_name: str
    department: str
    framework: str
    planned_start_date: date
    planned_end_date: date
    status: AuditStatus
    created_at: datetime


class AssignmentRecord(StrictModel):
    id: str
    audit_id: str
    auditor_name: str
    assignment_type: AssignmentType
    orientation_status: OrientationStatus | None = None


class ScheduleRecord(StrictModel):
    id: str
    audit_id: str
    scheduled_start: datetime
    scheduled_end: datetime
    status: ScheduleStatus
    confirmations: list[Literal["COMBINED", "INDIVIDUAL"]] = Field(default_factory=list)


class ChecklistItemRecord(StrictModel):
    id: str
    audit_id: str
    item_code: str
    question: str
    result: ChecklistResult
    remarks: str = ""


class ChecklistProgress(StrictModel):
    """Aggregate returned by the QMS audit serializer when item access is unavailable."""

    id: str | None = None
    name: str | None = None
    item_count: int = Field(ge=0)
    compliant: int = Field(ge=0)
    non_compliant: int = Field(ge=0)
    pending: int = Field(ge=0)


class NCRecord(StrictModel):
    id: str
    audit_id: str
    checklist_item_id: str
    item_code: str
    question: str | None = None
    project_name: str | None = None
    status: NCStatus
    finding: str = ""
    risk_action: str | None = None
    correction: str | None = None
    corrective_action: str | None = None
    preventive_action: str | None = None
    correction_submitted: bool = False
    corrective_action_submitted: bool = False
    verified_by_id: str | None = None
    verified_by_name: str | None = None
    verified_at: datetime | None = None
    verification_remarks: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Django serializers normally return all these keys. Keeping the actual
    # key set lets analysis distinguish an omitted key from a returned blank.
    returned_fields: set[str] | None = Field(default=None, exclude=True)

    def field_was_returned(self, field_name: str) -> bool:
        """Whether a normalized field was present in the source response."""
        if self.returned_fields is not None:
            return field_name in self.returned_fields
        aliases = {
            "verified_by": "verified_by_id",
            "verified_by_name": "verified_by_name",
            "verified_at": "verified_at",
        }
        model_field = aliases.get(field_name, field_name)
        return model_field in self.model_fields_set


class AuditSnapshot(StrictModel):
    audit: AuditRecord
    assignments: list[AssignmentRecord] = Field(default_factory=list)
    schedule: ScheduleRecord | None = None
    checklist_items: list[ChecklistItemRecord] = Field(default_factory=list)
    checklist_progress: ChecklistProgress | None = None
    checklist_item_details_available: bool = True
    non_conformities: list[NCRecord] = Field(default_factory=list)


class AnalysisRequest(StrictModel):
    audit_id: str = Field(min_length=1, max_length=64)
    include_explanation: bool = True


class TaskExecutionRequest(StrictModel):
    request_text: str = Field(min_length=5, max_length=1000)
    include_explanation: bool = True


class Fact(StrictModel):
    id: str
    title: str
    detail: str
    source_refs: list[SourceRef]
    kind: Literal["fact", "gap", "pending", "warning"] = "fact"


class Recommendation(StrictModel):
    id: str
    text: str
    status: Literal["recommended", "informational"] = "recommended"
    source_refs: list[SourceRef] = Field(default_factory=list)


class AuditAnalysis(StrictModel):
    audit_id: str
    audit_code: str
    facts: list[Fact]
    recommendations: list[Recommendation]
    unresolved_policies: list[str]
    explanation: str
    explanation_source: Literal["deterministic", "llm-approved-phrase"]
    llm_used: bool


class TaskUnderstanding(StrictModel):
    request_text: str
    audit_reference: str | None = None
    objective: TaskObjective
    objective_summary: str


class LLMTaskProposal(StrictModel):
    """Untrusted intent and read-tool proposal returned by the language model."""

    objective: TaskObjective
    required_tools: list[ReadToolName] = Field(min_length=1, max_length=5)
    rationale: str = Field(min_length=1, max_length=240)


class TaskPlanStep(StrictModel):
    step_id: str
    tool: ReadToolName
    description: str


class ExecutionPlan(StrictModel):
    audit_id: str | None = None
    objective: TaskObjective
    rationale: str
    required_tools: list[ReadToolName]
    steps: list[TaskPlanStep]


class PlannedStepResult(StrictModel):
    step: TaskPlanStep
    status: Literal["planned", "completed", "failed"]


class PortfolioPriorityFactor(StrictModel):
    code: str
    points: int = Field(gt=0)
    reason: str
    source_refs: list[SourceRef]


class RankedAuditInsight(StrictModel):
    rank: int = Field(ge=1)
    audit_id: str
    audit_code: str
    project_name: str
    status: AuditStatus
    priority_score: int = Field(ge=0)
    priority_factors: list[PortfolioPriorityFactor]
    facts: list[Fact]
    recommendations: list[Recommendation]
    source_refs: list[SourceRef]
    unresolved_policies: list[str] = Field(default_factory=list)


class PortfolioAuditFailure(StrictModel):
    audit_id: str
    audit_code: str
    reason: Literal["provider_error", "qms_forbidden", "qms_not_found", "qms_timeout", "analysis_error"]
    message: str


class TaskExecutionResult(StrictModel):
    objective: TaskObjective
    objective_summary: str
    audit_id: str | None
    audit_code: str | None
    plan: ExecutionPlan
    planned_steps: list[PlannedStepResult]
    findings: list[Fact]
    recommendations: list[Recommendation]
    source_refs: list[SourceRef]
    unresolved_policies: list[str]
    explanation: str
    explanation_source: Literal["deterministic", "llm-approved-phrase"]
    llm_used: bool
    planning_source: Literal["llm", "deterministic"] = "deterministic"
    llm_call_count: int = Field(default=0, ge=0)
    llm_latency_ms: int = Field(default=0, ge=0)
    fallback_reason: Literal[
        "not_configured", "authentication_error", "rate_limited", "timeout",
        "provider_error", "invalid_json", "schema_validation_error",
    ] | None = None
    http_status_code: int | None = Field(default=None, ge=100, le=599)
    provider_error_code: str | None = Field(default=None, max_length=64)
    sanitized_error_message: str | None = Field(default=None, max_length=200)
    ranked_audits: list[RankedAuditInsight] = Field(default_factory=list)
    portfolio_failures: list[PortfolioAuditFailure] = Field(default_factory=list)
    portfolio_priority_method: str | None = None


class AuditListItem(StrictModel):
    id: str
    code: str
    project_name: str
    status: AuditStatus
    planned_start_date: date
    planned_end_date: date


class ErrorResponse(StrictModel):
    code: str
    message: str
