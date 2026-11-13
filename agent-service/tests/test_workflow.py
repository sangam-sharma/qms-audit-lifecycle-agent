from app.agent.graph import AuditOrchestrator, OrchestratorError
from app.domain.lifecycle import analyze_audit
from app.domain.schemas import NCStatus, ToolExecutionContext
from app.llm.openai_compatible import PHRASES
from app.providers.mock_qms import MockQMSProvider
from app.tools.qms_tools import ReadOnlyQMSTools


def test_three_sample_audits_complete_the_langgraph_workflow():
    orchestrator = AuditOrchestrator(MockQMSProvider())

    first = orchestrator.analyze("audit-1001")
    second = orchestrator.analyze("audit-1002")
    third = orchestrator.analyze("audit-1003")

    assert first.audit_code == "IA-2026-001"
    assert {rec.id for rec in first.recommendations} >= {"assign-auditors"}
    assert second.audit_code == "IA-2026-002"
    assert {rec.id for rec in second.recommendations} >= {"complete-orientations", "complete-confirmations"}
    assert third.audit_code == "IA-2026-003"
    assert {rec.id for rec in third.recommendations} >= {
        "evaluate-pending-items", "nc-action-nc-1003-1", "nc-rework-nc-1003-2"
    }
    assert all(not result.llm_used for result in (first, second, third))


def test_facts_have_source_references_and_separate_unresolved_policy():
    result = AuditOrchestrator(MockQMSProvider()).analyze("audit-1003")

    assert result.facts
    assert all(fact.source_refs for fact in result.facts)
    assert all(recommendation.source_refs for recommendation in result.recommendations)
    assert result.unresolved_policies
    assert result.explanation_source == "deterministic"


def test_unknown_audit_returns_safe_not_found_error():
    orchestrator = AuditOrchestrator(MockQMSProvider())

    try:
        orchestrator.analyze("missing-audit")
    except OrchestratorError as exc:
        assert exc.code == "audit_not_found"
        assert exc.message == "Audit was not found."
    else:
        raise AssertionError("Expected a typed not-found error")


def test_tools_are_read_only_and_each_domain_tool_returns_data():
    tools = ReadOnlyQMSTools(MockQMSProvider())

    assert len(tools.list_audits()) == 3
    assert tools.get_audit("audit-1002").status.value == "ASSIGNED"
    assert len(tools.get_checklist("audit-1003")) == 4
    assert len(tools.get_assignments("audit-1002")) == 2
    assert tools.get_schedule("audit-1002").status.value == "SCHEDULED"
    assert len(tools.get_non_conformities("audit-1003")) == 2
    assert not any("write" in name or "update" in name or "delete" in name for name in dir(tools))


def test_future_execution_context_is_forwarded_outside_agent_state():
    class ContextProvider(MockQMSProvider):
        seen = None

        def get_audit(self, audit_id: str, *, context=None):
            self.seen = context
            return super().get_audit(audit_id, context=context)

    provider = ContextProvider()
    context = ToolExecutionContext(
        request_id="req-42", principal_id="user-7", system_id="qms-mock",
        scopes=["audit:read"], credential_ref="secret-store:credential-7",
    )
    result = AuditOrchestrator(provider, tool_context=context).analyze("audit-1003")

    assert result.audit_id == "audit-1003"
    assert provider.seen == context
    assert "credential_ref" not in str(result.model_dump())


def test_accepted_nc_with_non_compliant_item_recommends_recheck():
    tools = ReadOnlyQMSTools(MockQMSProvider())
    snapshot = tools.get_audit_snapshot("audit-1003")
    accepted_ncs = [
        nc.model_copy(update={"status": NCStatus.ACCEPTED})
        for nc in snapshot.non_conformities
    ]
    updated_snapshot = snapshot.model_copy(update={"non_conformities": accepted_ncs})

    result = analyze_audit(updated_snapshot)

    assert {rec.id for rec in result.recommendations} >= {"recheck-nc-1003-1", "recheck-nc-1003-2"}


class BrokenExplainer:
    def explain(self, category: str) -> str:
        raise TimeoutError("provider unavailable")


class HallucinatingExplainer:
    def explain(self, category: str) -> str:
        return "The audit is CLOSED and approved by QMS."


def test_llm_failure_falls_back_to_deterministic_result():
    result = AuditOrchestrator(MockQMSProvider(), BrokenExplainer()).analyze("audit-1003")

    assert result.llm_used is False
    assert result.explanation_source == "deterministic"
    assert "IN_PROGRESS" in next(f.detail for f in result.facts if f.id == "audit-status")


def test_llm_cannot_supply_business_facts_or_free_form_words():
    result = AuditOrchestrator(MockQMSProvider(), HallucinatingExplainer()).analyze("audit-1003")

    assert result.llm_used is False
    assert result.explanation_source == "deterministic"
    assert "approved by QMS" not in result.explanation
    assert result.explanation in PHRASES["active"].values() or result.explanation.startswith("This audit is in an active")


class ApprovedPhraseExplainer:
    def explain(self, category: str) -> str:
        return PHRASES[category]["review"]


def test_valid_llm_provider_only_selects_a_locally_approved_phrase():
    result = AuditOrchestrator(MockQMSProvider(), ApprovedPhraseExplainer()).analyze("audit-1003")

    assert result.llm_used is True
    assert result.explanation_source == "llm-approved-phrase"
    assert result.explanation == PHRASES["active"]["review"]
    assert "IN_PROGRESS" in next(f.detail for f in result.facts if f.id == "audit-status")
