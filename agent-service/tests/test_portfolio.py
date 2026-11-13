import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent.graph import AuditOrchestrator
from app.agent.task_planning import create_execution_plan, understand_request
from app.domain.schemas import LLMTaskProposal, TaskObjective
from app.main import create_app
from app.providers.base import ProviderError
from app.providers.django_api import DjangoAPIProvider
from app.providers.mock_qms import MockQMSProvider


class FakePlanner:
    def __init__(self):
        self.calls = []

    def propose(self, request_text):
        self.calls.append(request_text)
        return LLMTaskProposal(
            objective="portfolio_analysis",
            required_tools=["audits"],
            rationale="Rank the accessible audits using their lifecycle records.",
        )


def test_portfolio_request_needs_no_audit_id_and_uses_audits_list_plan():
    understanding = understand_request("Analyze all accessible audits")
    plan = create_execution_plan(understanding)

    assert understanding.objective == TaskObjective.PORTFOLIO_ANALYSIS
    assert understanding.audit_reference is None
    assert plan.audit_id is None
    assert [tool.value for tool in plan.required_tools] == ["audits"]


@pytest.mark.parametrize("request_text", [
    "Which audit needs attention first and why?",
    "Rank audits by urgency",
    "Identify overdue and incomplete audit activities",
    "Prepare a portfolio-wide action plan",
])
def test_portfolio_phrases_are_understood_without_individual_audit_ids(request_text):
    assert understand_request(request_text).objective == TaskObjective.PORTFOLIO_ANALYSIS


def test_mock_portfolio_returns_ranked_facts_recommendations_and_source_refs():
    provider = MockQMSProvider()
    result = AuditOrchestrator(provider).execute_task("Which audit needs attention first and why?")

    assert result.objective == TaskObjective.PORTFOLIO_ANALYSIS
    assert result.audit_id is None and result.audit_code is None
    expected_order = sorted(
        result.ranked_audits,
        key=lambda audit: (
            -audit.priority_score,
            audit.status.value == "CLOSED",
            next(record.planned_end_date for record in provider.list_audits() if record.id == audit.audit_id),
            audit.audit_id,
        ),
    )
    assert [audit.audit_id for audit in result.ranked_audits] == [audit.audit_id for audit in expected_order]
    first = result.ranked_audits[0]
    assert first.rank == 1 and first.priority_score > result.ranked_audits[1].priority_score
    assert {factor.code for factor in first.priority_factors} >= {
        "overdue_audit", "overdue_scheduled_activity", "non_compliant_checklist", "unresolved_non_conformities"
    }
    assert all(factor.source_refs for audit in result.ranked_audits for factor in audit.priority_factors)
    assert all(audit.facts and audit.recommendations and audit.source_refs for audit in result.ranked_audits)
    audit_1001 = next(audit for audit in result.ranked_audits if audit.audit_id == "audit-1001")
    assert {factor.code for factor in audit_1001.priority_factors} >= {"missing_assignments", "pending_checklist"}
    assert "Higher scores rank first" in result.portfolio_priority_method
    assert result.portfolio_failures == []


def test_portfolio_api_serializes_result_and_empty_portfolio():
    class EmptyProvider(MockQMSProvider):
        def list_audits(self, *, context=None):
            return []

    client = TestClient(create_app(provider=EmptyProvider(), explainer=None, task_planner=None))
    response = client.post("/api/tasks/execute", json={"request_text": "Analyze all accessible audits"})

    assert response.status_code == 200
    body = response.json()
    assert body["objective"] == "portfolio_analysis"
    assert body["ranked_audits"] == []
    assert body["portfolio_failures"] == []
    assert "No accessible audits" in body["explanation"]
    assert body["fallback_reason"] == "not_configured"


def test_portfolio_llm_is_called_once_not_once_per_audit():
    planner = FakePlanner()
    result = AuditOrchestrator(MockQMSProvider(), task_planner=planner).execute_task(
        "Which audit needs attention first and why?"
    )

    assert len(planner.calls) == 1
    assert result.planning_source == "llm"
    assert result.llm_call_count == 1
    assert result.llm_used is True
    assert len(result.ranked_audits) == 3


def test_portfolio_timeout_falls_back_once_and_still_analyzes_the_portfolio():
    class FailingPlanner:
        def propose(self, request_text):
            raise TimeoutError("private provider failure")

    result = AuditOrchestrator(MockQMSProvider(), task_planner=FailingPlanner()).execute_task(
        "Rank audits by urgency"
    )

    assert result.planning_source == "deterministic"
    assert result.fallback_reason == "timeout"
    assert result.llm_call_count == 1
    assert result.llm_used is False
    assert len(result.ranked_audits) == 3


def test_partial_snapshot_failure_excludes_only_that_audit_without_inventing_facts():
    class OneAuditUnavailableProvider(MockQMSProvider):
        def get_checklist(self, audit_id, *, context=None):
            if audit_id == "audit-1002":
                raise ProviderError("private provider detail")
            return super().get_checklist(audit_id, context=context)

    result = AuditOrchestrator(OneAuditUnavailableProvider()).execute_task("Analyze all audits")

    assert {audit.audit_id for audit in result.ranked_audits} == {"audit-1001", "audit-1003"}
    assert len(result.portfolio_failures) == 1
    failure = result.portfolio_failures[0]
    assert (failure.audit_id, failure.audit_code) == ("audit-1002", "IA-2026-002")
    assert failure.reason == "provider_error"
    assert "private provider detail" not in repr(result)


def test_django_forbidden_audit_is_excluded_and_permission_is_not_bypassed():
    calls = []
    row = {
        "id": 37, "audit_code": "IA-2026-037", "project": 8,
        "project_name": "Northwind ERP", "department": 3, "framework": 2,
        "framework_name": "ISO 9001:2015", "planned_start_date": "2026-11-10",
        "planned_end_date": "2026-11-12", "status": "IN_PROGRESS",
        "created_at": "2026-10-01T10:30:00Z", "progress": {},
    }

    def handle(request):
        calls.append(request)
        if request.url.path == "/api/auth/me/":
            return httpx.Response(200, json={"id": 12, "username": "qms-user", "role": "QMS"}, request=request)
        if request.url.path == "/api/audits/":
            return httpx.Response(200, json=[row], request=request)
        if request.url.path == "/api/audits/37/":
            return httpx.Response(403, json={"detail": "sensitive permission response"}, request=request)
        return httpx.Response(404, json={}, request=request)

    provider = DjangoAPIProvider(
        "http://qms.test/api/", "test-token",
        transport=httpx.MockTransport(handle),
    )
    provider.validate_identity()
    try:
        result = AuditOrchestrator(provider).execute_task("Analyze all accessible audits")
    finally:
        provider.close()

    assert result.ranked_audits == []
    assert result.portfolio_failures[0].reason == "qms_forbidden"
    assert all(request.method == "GET" for request in calls)
    assert "/api/audits/37/" in [request.url.path for request in calls]
    assert "sensitive permission response" not in repr(result)

