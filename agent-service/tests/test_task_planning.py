import pytest
import httpx
from fastapi.testclient import TestClient

from app.agent.graph import AuditOrchestrator, OrchestratorError
from app.agent.task_planning import create_execution_plan, understand_request
from app.domain.schemas import ReadToolName, TaskObjective
from app.domain.schemas import LLMTaskProposal
from app.llm.openai_compatible import LLMPlannerFailure, OpenAICompatibleTaskPlanner, configured_task_planner
from app.main import create_app
from app.providers.base import ProviderError
from app.providers.mock_qms import MockQMSProvider


class FakePlanner:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = []

    def propose(self, request_text):
        self.calls.append(request_text)
        if isinstance(self.proposal, Exception):
            raise self.proposal
        return self.proposal


def test_llm_understands_natural_language_and_preserves_audit_identifier_exactly():
    code = "IA-2026-003"
    proposal = LLMTaskProposal(
        objective="pending_actions",
        required_tools=["audit", "assignments", "schedule", "checklist", "non_conformities"],
        rationale="Find remaining work across audit lifecycle records.",
    )
    planner = FakePlanner(proposal)
    result = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        f"Could you tell me what work is still outstanding for {code}?"
    )

    assert result.objective == TaskObjective.PENDING_ACTIONS
    assert result.plan.audit_id == code
    assert result.audit_code == "IA-2026-003"
    assert result.llm_used is True
    assert result.planning_source == "llm"
    assert result.llm_call_count == 1
    assert result.llm_latency_ms >= 0
    assert result.fallback_reason is None
    assert planner.calls == [f"Could you tell me what work is still outstanding for {code}?"]


def test_invalid_llm_tool_selection_is_rejected_and_deterministic_parser_is_used():
    planner = FakePlanner(LLMTaskProposal(
        objective="compliance_gap_analysis",
        required_tools=["audit"],
        rationale="Read the audit only.",
    ))
    result = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )

    assert result.objective == TaskObjective.COMPLIANCE_GAP_ANALYSIS
    assert {tool.value for tool in result.plan.required_tools} == {"audit", "checklist", "non_conformities"}
    assert result.llm_used is False
    assert result.planning_source == "deterministic"
    assert result.llm_call_count == 1
    assert result.fallback_reason == "schema_validation_error"


@pytest.mark.parametrize("failure", [RuntimeError("quota"), TimeoutError("slow")])
def test_provider_errors_and_timeouts_fall_back_without_exposing_error(failure):
    result = AuditOrchestrator(MockQMSProvider(), task_planner=FakePlanner(failure)).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert result.objective == TaskObjective.COMPLIANCE_GAP_ANALYSIS
    assert result.llm_used is False
    assert result.planning_source == "deterministic"
    assert result.llm_call_count == 1
    assert "quota" not in repr(result)


def test_no_key_leaves_task_planner_disabled(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert configured_task_planner() is None


def test_unconfigured_planner_reports_zero_calls_and_not_configured():
    result = AuditOrchestrator(MockQMSProvider()).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert result.planning_source == "deterministic"
    assert result.llm_call_count == 0
    assert result.llm_latency_ms == 0
    assert result.fallback_reason == "not_configured"


def test_task_api_serializes_planning_diagnostics_without_changing_result():
    client = TestClient(create_app(
        provider=MockQMSProvider(), explainer=None, task_planner=None,
    ))
    response = client.post("/api/tasks/execute", json={
        "request_text": "Find compliance gaps for audit audit-1003",
        "include_explanation": False,
    })
    body = response.json()
    assert response.status_code == 200
    assert body["objective"] == TaskObjective.COMPLIANCE_GAP_ANALYSIS.value
    assert body["planning_source"] == "deterministic"
    assert body["llm_call_count"] == 0
    assert body["llm_latency_ms"] == 0
    assert body["fallback_reason"] == "not_configured"
    assert body["llm_used"] is False
    assert body["http_status_code"] is None
    assert body["provider_error_code"] is None
    assert body["sanitized_error_message"] is None


@pytest.mark.parametrize(
    ("status", "reason"),
    [(401, "authentication_error"), (403, "authentication_error"), (429, "rate_limited"), (503, "provider_error")],
)
def test_http_status_failures_are_sanitized_in_task_response(monkeypatch, status, reason):
    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    provider_code = {400: "INVALID_ARGUMENT", 401: "UNAUTHENTICATED", 403: "PERMISSION_DENIED", 429: "RESOURCE_EXHAUSTED", 503: "UNAVAILABLE"}[status]
    response = httpx.Response(status, request=request, json={
        "error": {
            "code": status,
            "status": provider_code,
            "message": "raw body must never be returned; api-key-must-not-leak",
        }
    })
    monkeypatch.setattr("app.llm.openai_compatible.httpx.post", lambda *args, **kwargs: response)
    planner = OpenAICompatibleTaskPlanner("api-key-must-not-leak", "https://provider.invalid/v1", "model")

    result = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert result.fallback_reason == reason
    assert result.llm_call_count == 1
    assert result.planning_source == "deterministic"
    assert result.http_status_code == status
    assert result.provider_error_code == provider_code
    assert "raw body" not in repr(result)
    assert "api-key-must-not-leak" not in repr(result)
    assert result.sanitized_error_message
    assert "api-key-must-not-leak" not in repr(result)


def test_timeout_invalid_json_and_schema_errors_have_distinct_reasons(monkeypatch):
    planner = OpenAICompatibleTaskPlanner("key", "https://provider.invalid/v1", "model")

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("Authorization: Bearer secret")

    monkeypatch.setattr("app.llm.openai_compatible.httpx.post", timeout)
    timed_out = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert timed_out.fallback_reason == "timeout"
    assert timed_out.http_status_code is None
    assert timed_out.provider_error_code is None
    assert "secret" not in repr(timed_out)

    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    monkeypatch.setattr(
        "app.llm.openai_compatible.httpx.post",
        lambda *args, **kwargs: httpx.Response(200, request=request, text="not-json"),
    )
    malformed = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert malformed.fallback_reason == "invalid_json"
    assert malformed.http_status_code == 200

    monkeypatch.setattr(
        "app.llm.openai_compatible.httpx.post",
        lambda *args, **kwargs: httpx.Response(200, request=request, json={
            "choices": [{"message": {"content": '{"objective":"bad","required_tools":[],"rationale":"x"}'}}]
        }),
    )
    invalid_schema = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert invalid_schema.fallback_reason == "schema_validation_error"
    assert invalid_schema.http_status_code == 200


def test_unrecognized_planner_failure_text_is_never_returned():
    planner = FakePlanner(LLMPlannerFailure("Bearer secret-key-text"))
    result = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )
    assert result.fallback_reason == "provider_error"
    assert "secret-key-text" not in repr(result)


def test_openai_compatible_task_planner_sends_compact_request_and_validates_json(monkeypatch):
    seen = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"objective":"audit_analysis","required_tools":["audit","assignments","schedule","checklist","non_conformities"],"rationale":"Review all lifecycle records."}'}}]}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("app.llm.openai_compatible.httpx.post", post)
    planner = OpenAICompatibleTaskPlanner("test-secret", "https://free.example/v1", "free-model")
    proposal = planner.propose("Review audit IA-2026-003")

    assert proposal.objective == TaskObjective.AUDIT_ANALYSIS
    assert seen["url"] == "https://free.example/v1/chat/completions"
    assert seen["json"]["model"] == "free-model"
    assert seen["json"]["response_format"] == {"type": "json_object"}
    assert seen["timeout"] == 8.0
    assert seen["json"]["max_tokens"] == 120
    assert "temperature" not in seen["json"]
    assert "test-secret" not in repr(seen["json"])
    assert seen["headers"]["Authorization"] == "Bearer test-secret"


def test_adapter_http_errors_and_invalid_json_propagate_to_orchestrator_fallback(monkeypatch):
    planner = OpenAICompatibleTaskPlanner("key", "https://free.example/v1", "free-model")

    def provider_error(*args, **kwargs):
        raise RuntimeError("provider quota exhausted")

    monkeypatch.setattr("app.llm.openai_compatible.httpx.post", provider_error)
    with pytest.raises(LLMPlannerFailure) as failure:
        planner.propose("Find gaps for audit audit-1003")
    assert failure.value.reason == "provider_error"

    class InvalidResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"objective":"audit_analysis","required_tools":["write_audit"],"rationale":"bad"}'}}]}

    monkeypatch.setattr("app.llm.openai_compatible.httpx.post", lambda *args, **kwargs: InvalidResponse())
    with pytest.raises(Exception):
        planner.propose("Find gaps for audit audit-1003")


@pytest.mark.parametrize(
    ("request_text", "objective", "expected_tools", "expected_audit_id"),
    [
        (
            "Analyze audit audit-1001",
            TaskObjective.AUDIT_ANALYSIS,
            {"audit", "assignments", "schedule", "checklist", "non_conformities"},
            "audit-1001",
        ),
        (
            "Identify pending actions for audit audit-1002",
            TaskObjective.PENDING_ACTIONS,
            {"audit", "assignments", "schedule", "checklist", "non_conformities"},
            "audit-1002",
        ),
        (
            "Create an audit completion plan to finish audit IA-2026-003",
            TaskObjective.COMPLETION_PLAN,
            {"audit", "assignments", "schedule", "checklist", "non_conformities"},
            "audit-1003",
        ),
        (
            "Find compliance gaps for audit IA-2026-003",
            TaskObjective.COMPLIANCE_GAP_ANALYSIS,
            {"audit", "checklist", "non_conformities"},
            "audit-1003",
        ),
    ],
)
def test_all_task_types_are_understood_planned_and_executed(request_text, objective, expected_tools, expected_audit_id):
    understanding = understand_request(request_text)
    plan = create_execution_plan(understanding)
    result = AuditOrchestrator(MockQMSProvider()).execute_task(request_text, include_explanation=False)

    assert understanding.objective == objective
    assert plan.objective == objective
    assert {tool.value for tool in plan.required_tools} == expected_tools
    assert result.objective == objective
    assert result.audit_id == expected_audit_id
    assert result.planned_steps
    assert all(step.status == "completed" for step in result.planned_steps)
    assert result.findings
    assert result.source_refs
    assert result.llm_used is False


@pytest.mark.parametrize("audit_reference", [
    "audit-1001",       # existing mock ID
    "audit_1001",       # existing separator variant
    "audit 1001",       # existing separator variant
    "IA-2026-003",      # existing QMS audit code format
    "AUD-2026-Q2",      # Django QMS audit code format
])
def test_all_supported_audit_reference_formats_are_preserved(audit_reference):
    understanding = understand_request(f"Analyze audit {audit_reference}")
    plan = create_execution_plan(understanding)

    assert understanding.audit_reference == audit_reference
    assert plan.audit_id == audit_reference


def test_compliance_gaps_are_item_level_and_sources_are_preserved():
    result = AuditOrchestrator(MockQMSProvider()).execute_task(
        "Find compliance gaps for audit audit-1003", include_explanation=False
    )

    gaps = [finding for finding in result.findings if finding.kind == "gap"]
    assert {finding.id for finding in gaps} >= {"gap-item-1003-2", "gap-item-1003-3", "gap-nc-1003-1", "gap-nc-1003-2"}
    assert all(finding.source_refs for finding in gaps)
    assert {tool.value for tool in result.plan.required_tools} == {
        ReadToolName.AUDIT.value,
        ReadToolName.CHECKLIST.value,
        ReadToolName.NON_CONFORMITIES.value,
    }


def test_conditional_plan_skips_unneeded_assignment_and_schedule_tools():
    class TrackingProvider(MockQMSProvider):
        calls = []

        def get_assignments(self, audit_id, *, context=None):
            self.calls.append("assignments")
            return super().get_assignments(audit_id, context=context)

        def get_schedule(self, audit_id, *, context=None):
            self.calls.append("schedule")
            return super().get_schedule(audit_id, context=context)

        def get_checklist(self, audit_id, *, context=None):
            self.calls.append("checklist")
            return super().get_checklist(audit_id, context=context)

        def get_non_conformities(self, audit_id, *, context=None):
            self.calls.append("non_conformities")
            return super().get_non_conformities(audit_id, context=context)

    provider = TrackingProvider()
    AuditOrchestrator(provider).execute_task("Find compliance gaps for audit audit-1003")

    assert provider.calls == ["checklist", "non_conformities"]


@pytest.mark.parametrize(
    "request_text",
    [
        "Analyze this audit",  # missing audit reference
        "Export a report for audit audit-1001",  # unsupported objective
        "audit-1001",  # no objective
        "   ",  # invalid request
    ],
)
def test_invalid_requests_are_rejected_without_tool_execution(request_text):
    with pytest.raises(OrchestratorError) as error:
        AuditOrchestrator(MockQMSProvider()).execute_task(request_text)
    assert error.value.code == "invalid_task_request"


def test_missing_audit_is_a_typed_error():
    with pytest.raises(OrchestratorError) as error:
        AuditOrchestrator(MockQMSProvider()).execute_task("Analyze audit audit-9999")
    assert error.value.code == "audit_not_found"


class FailingChecklistProvider(MockQMSProvider):
    def get_checklist(self, audit_id, *, context=None):
        raise ProviderError("fixture tool failure")


def test_read_tool_execution_failure_stops_the_plan_safely():
    with pytest.raises(OrchestratorError) as error:
        AuditOrchestrator(FailingChecklistProvider()).execute_task(
            "Find compliance gaps for audit audit-1003"
        )
    assert error.value.code == "tool_execution_failed"
    assert error.value.message == "Unable to read checklist data."


def test_natural_language_api_and_existing_analysis_api_both_work():
    client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))

    task = client.post("/api/tasks/execute", json={
        "request_text": "Identify pending actions for audit audit-1002",
        "include_explanation": False,
    })
    old_analysis = client.post("/api/audits/audit-1002/analysis?include_explanation=false")

    assert task.status_code == 200
    assert task.json()["objective"] == TaskObjective.PENDING_ACTIONS.value
    assert task.json()["planned_steps"]
    assert old_analysis.status_code == 200
    assert old_analysis.json()["audit_code"] == "IA-2026-002"


def test_task_api_returns_typed_invalid_missing_and_tool_errors():
    invalid_client = TestClient(create_app(provider=MockQMSProvider(), explainer=None))
    invalid = invalid_client.post("/api/tasks/execute", json={"request_text": "Tell me a joke about audit-1001"})
    missing = invalid_client.post("/api/tasks/execute", json={"request_text": "Analyze audit audit-9999"})

    failing_client = TestClient(create_app(provider=FailingChecklistProvider(), explainer=None))
    tool_error = failing_client.post("/api/tasks/execute", json={"request_text": "Find compliance gaps for audit audit-1003"})

    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_task_request"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "audit_not_found"
    assert tool_error.status_code == 502
    assert tool_error.json()["detail"]["code"] == "tool_execution_failed"
