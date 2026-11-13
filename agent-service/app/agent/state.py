from typing import TypedDict

from app.domain.schemas import (
    AuditAnalysis,
    AuditRecord,
    AuditSnapshot,
    ExecutionPlan,
    Fact,
    TaskExecutionResult,
    TaskUnderstanding,
)


class AgentState(TypedDict, total=False):
    audit_id: str
    include_explanation: bool
    snapshot: AuditSnapshot
    analysis: AuditAnalysis
    error_code: str
    error_message: str
    request_text: str
    understanding: TaskUnderstanding
    plan: ExecutionPlan
    audit_record: AuditRecord
    tool_results: dict[str, object]
    executed_tools: list[str]
    task_findings: list[Fact]
    task_result: TaskExecutionResult
    task_llm_used: bool
    planning_source: str
    llm_call_count: int
    llm_latency_ms: int
    fallback_reason: str | None
    http_status_code: int | None
    provider_error_code: str | None
    sanitized_error_message: str | None
    portfolio_audits: list[object]
    portfolio_failures: list[object]
