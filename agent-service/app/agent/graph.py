import json
import time
from uuid import uuid4

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agent.state import AgentState
from app.domain.lifecycle import _category, analyze_audit, analyze_compliance_gaps
from app.domain.portfolio import PRIORITY_METHOD, rank_portfolio
from app.domain.schemas import (
    AuditAnalysis,
    AuditSnapshot,
    ExecutionPlan,
    PortfolioAuditFailure,
    RankedAuditInsight,
    ReadToolName,
    Recommendation,
    SourceRef,
    TaskExecutionResult,
    TaskObjective,
    TaskPlanStep,
    ToolExecutionContext,
)
from app.agent.task_planning import TaskParseError, create_execution_plan, understand_request, understand_request_with_proposal
from app.llm.base import ExplanationProvider
from app.llm.openai_compatible import LLMPlannerFailure, PHRASES
from app.domain.schemas import LLMTaskProposal
from app.providers.base import AuditNotFound, ProviderError, QMSDataProvider
from app.tools.qms_tools import ReadOnlyQMSTools


def _planner_fallback_reason(exc: Exception) -> str:
    """Map an internal planner failure to one safe, fixed public category."""
    if isinstance(exc, LLMPlannerFailure):
        allowed = {
            "authentication_error", "rate_limited", "timeout", "provider_error",
            "invalid_json", "schema_validation_error",
        }
        return exc.reason if exc.reason in allowed else "provider_error"
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in {401, 403}:
            return "authentication_error"
        if exc.response.status_code == 429:
            return "rate_limited"
        return "provider_error"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, (ValidationError, TaskParseError)):
        return "schema_validation_error"
    return "provider_error"


def _planner_failure_details(exc: Exception) -> dict[str, object]:
    if isinstance(exc, LLMPlannerFailure):
        return {
            "fallback_reason": _planner_fallback_reason(exc),
            "http_status_code": exc.http_status_code,
            "provider_error_code": exc.provider_error_code,
            "sanitized_error_message": exc.sanitized_error_message,
        }
    reason = _planner_fallback_reason(exc)
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    safe_messages = {
        "authentication_error": "Provider authentication failed.",
        "rate_limited": "Provider quota or rate limit was exceeded.",
        "timeout": "LLM provider request timed out.",
        "invalid_json": "Provider response was not valid JSON.",
        "schema_validation_error": "Provider JSON did not match the task proposal schema.",
        "provider_error": "LLM provider request failed.",
    }
    return {
        "fallback_reason": reason,
        "http_status_code": status,
        "provider_error_code": None,
        "sanitized_error_message": safe_messages[reason],
    }


class AuditOrchestrator:
    """One LangGraph workflow over read-only tools and deterministic domain logic."""

    def __init__(
        self,
        provider: QMSDataProvider,
        explainer: ExplanationProvider | None = None,
        task_planner=None,
        tool_context: ToolExecutionContext | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._tools = ReadOnlyQMSTools(provider, context=tool_context)
        self._explainer = explainer
        self._task_planner = task_planner
        self._tool_context = tool_context
        self._checkpointer = checkpointer
        self._graph = self._build_graph(checkpointer)
        self._task_graph = self._build_task_graph(checkpointer)

    def _build_graph(self, checkpointer: BaseCheckpointSaver | None = None):
        workflow = StateGraph(AgentState)
        workflow.add_node("load_context", self._load_context)
        workflow.add_node("analyze", self._analyze)
        workflow.add_node("explain_or_fallback", self._explain_or_fallback)
        workflow.add_node("handle_error", self._handle_error)
        workflow.add_edge(START, "load_context")
        workflow.add_conditional_edges(
            "load_context",
            lambda state: "handle_error" if state.get("error_code") else "analyze",
            {"handle_error": "handle_error", "analyze": "analyze"},
        )
        workflow.add_conditional_edges(
            "analyze",
            lambda state: "handle_error" if state.get("error_code") else "explain_or_fallback",
            {"handle_error": "handle_error", "explain_or_fallback": "explain_or_fallback"},
        )
        workflow.add_edge("explain_or_fallback", END)
        workflow.add_edge("handle_error", END)
        return workflow.compile(checkpointer=checkpointer)

    def _build_task_graph(self, checkpointer: BaseCheckpointSaver | None = None):
        workflow = StateGraph(AgentState)
        workflow.add_node("understand_request", self._understand_task)
        workflow.add_node("create_plan", self._create_task_plan)
        workflow.add_node("execute_portfolio", self._execute_portfolio)
        workflow.add_node("format_portfolio_result", self._format_portfolio_result)
        workflow.add_node("execute_audit", self._execute_audit_tool)
        for tool in (ReadToolName.ASSIGNMENTS, ReadToolName.SCHEDULE, ReadToolName.CHECKLIST, ReadToolName.NON_CONFORMITIES):
            workflow.add_node(f"execute_{tool.value}", self._make_task_tool_node(tool))
        workflow.add_node("analyze_task", self._analyze_task)
        workflow.add_node("explain_task_or_fallback", self._explain_or_fallback)
        workflow.add_node("format_task_result", self._format_task_result)
        workflow.add_node("handle_error", self._handle_error)

        workflow.add_edge(START, "understand_request")
        workflow.add_conditional_edges(
            "understand_request",
            lambda state: "handle_error" if state.get("error_code") else "create_plan",
            {"handle_error": "handle_error", "create_plan": "create_plan"},
        )
        workflow.add_conditional_edges(
            "create_plan",
            lambda state: "execute_portfolio" if state["plan"].objective == TaskObjective.PORTFOLIO_ANALYSIS else "execute_audit",
            {"execute_portfolio": "execute_portfolio", "execute_audit": "execute_audit"},
        )
        workflow.add_conditional_edges(
            "execute_portfolio",
            lambda state: "handle_error" if state.get("error_code") else "format_portfolio_result",
            {"handle_error": "handle_error", "format_portfolio_result": "format_portfolio_result"},
        )
        workflow.add_edge("format_portfolio_result", END)
        workflow.add_conditional_edges("execute_audit", self._next_task_node, self._task_route_map())
        for tool in (ReadToolName.ASSIGNMENTS, ReadToolName.SCHEDULE, ReadToolName.CHECKLIST, ReadToolName.NON_CONFORMITIES):
            workflow.add_conditional_edges(f"execute_{tool.value}", self._next_task_node, self._task_route_map())
        workflow.add_conditional_edges(
            "analyze_task",
            lambda state: "handle_error" if state.get("error_code") else "explain_task_or_fallback",
            {"handle_error": "handle_error", "explain_task_or_fallback": "explain_task_or_fallback"},
        )
        workflow.add_edge("explain_task_or_fallback", "format_task_result")
        workflow.add_edge("format_task_result", END)
        workflow.add_edge("handle_error", END)
        return workflow.compile(checkpointer=checkpointer)

    @staticmethod
    def _task_route_map():
        return {
            "handle_error": "handle_error",
            "execute_assignments": "execute_assignments",
            "execute_schedule": "execute_schedule",
            "execute_checklist": "execute_checklist",
            "execute_non_conformities": "execute_non_conformities",
            "analyze_task": "analyze_task",
        }

    @staticmethod
    def _next_task_node(state):
        if state.get("error_code"):
            return "handle_error"
        completed = set(state.get("executed_tools", []))
        for tool in state["plan"].required_tools:
            if tool.value not in completed:
                return f"execute_{tool.value}"
        return "analyze_task"

    def _understand_task(self, state: AgentState) -> AgentState:
        request_text = state["request_text"]
        if self._task_planner is None:
            try:
                return {
                    "understanding": understand_request(request_text),
                    "task_llm_used": False,
                    "planning_source": "deterministic",
                    "llm_call_count": 0,
                    "llm_latency_ms": 0,
                    "fallback_reason": "not_configured",
                    "http_status_code": None,
                    "provider_error_code": None,
                    "sanitized_error_message": None,
                }
            except TaskParseError as exc:
                return {
                    "error_code": exc.code,
                    "error_message": exc.message,
                    "planning_source": "deterministic",
                    "llm_call_count": 0,
                    "llm_latency_ms": 0,
                    "fallback_reason": "not_configured",
                    "http_status_code": None,
                    "provider_error_code": None,
                    "sanitized_error_message": None,
                }

        started = time.perf_counter()
        try:
            proposal = self._task_planner.propose(request_text)
            if not isinstance(proposal, LLMTaskProposal):
                proposal = LLMTaskProposal.model_validate(proposal)
            understanding = understand_request_with_proposal(request_text, proposal)
            return {
                "understanding": understanding,
                "task_llm_used": True,
                "planning_source": "llm",
                "llm_call_count": 1,
                "llm_latency_ms": max(0, int((time.perf_counter() - started) * 1000)),
                "fallback_reason": None,
                "http_status_code": None,
                "provider_error_code": None,
                "sanitized_error_message": None,
            }
        except Exception as exc:
            diagnostics = _planner_failure_details(exc)
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
        try:
            understanding = understand_request(request_text)
            return {
                "understanding": understanding,
                "task_llm_used": False,
                "planning_source": "deterministic",
                "llm_call_count": 1,
                "llm_latency_ms": elapsed_ms,
                **diagnostics,
            }
        except TaskParseError as exc:
            return {
                "error_code": exc.code,
                "error_message": exc.message,
                "planning_source": "deterministic",
                "llm_call_count": 1,
                "llm_latency_ms": elapsed_ms,
                **diagnostics,
            }

    def _create_task_plan(self, state: AgentState) -> AgentState:
        plan = create_execution_plan(state["understanding"])
        return {"plan": plan, "tool_results": {}, "executed_tools": []}

    def _execute_portfolio(self, state: AgentState) -> AgentState:
        try:
            audits = self._tools.list_audits()
        except ProviderError as exc:
            return {"error_code": exc.code, "error_message": exc.public_message}
        except Exception:
            return {"error_code": "provider_error", "error_message": "QMS audit list could not be loaded."}

        snapshots: list[AuditSnapshot] = []
        failures: list[PortfolioAuditFailure] = []
        for audit in audits:
            try:
                snapshots.append(self._tools.get_audit_snapshot(audit.id))
            except ProviderError as exc:
                reason = exc.code if exc.code in {"qms_forbidden", "qms_not_found", "qms_timeout"} else "provider_error"
                failures.append(PortfolioAuditFailure(
                    audit_id=audit.id,
                    audit_code=audit.code,
                    reason=reason,
                    message="Required audit data could not be read; this audit was excluded from ranking.",
                ))
            except Exception:
                failures.append(PortfolioAuditFailure(
                    audit_id=audit.id,
                    audit_code=audit.code,
                    reason="provider_error",
                    message="Required audit data could not be read; this audit was excluded from ranking.",
                ))

        try:
            ranked = rank_portfolio(snapshots)
        except Exception:
            return {"error_code": "analysis_error", "error_message": "Portfolio analysis could not be completed."}
        return {
            "portfolio_audits": ranked,
            "portfolio_failures": failures,
            "executed_tools": [*state.get("executed_tools", []), ReadToolName.AUDITS.value],
        }

    def _format_portfolio_result(self, state: AgentState) -> AgentState:
        ranked: list[RankedAuditInsight] = state.get("portfolio_audits", [])
        failures: list[PortfolioAuditFailure] = state.get("portfolio_failures", [])
        plan: ExecutionPlan = state["plan"]
        all_recommendations = [recommendation for audit in ranked for recommendation in audit.recommendations]
        recommendations = list({
            (rec.id, rec.text, tuple((ref.entity, ref.record_id, ref.field, ref.value) for ref in rec.source_refs)): rec
            for rec in all_recommendations
        }.values())
        findings = [fact for audit in ranked for fact in audit.facts]
        refs = [ref for audit in ranked for ref in audit.source_refs]
        source_refs = list({(ref.entity, ref.record_id, ref.field, ref.value): ref for ref in refs}.values())
        if not ranked and not failures:
            explanation = "No accessible audits were returned by the QMS provider."
        else:
            explanation = (
                f"Ranked {len(ranked)} accessible audit(s) using the documented deterministic priority factors. "
                f"{len(failures)} audit(s) could not be fully read and were excluded from ranking."
            )
        result = TaskExecutionResult(
            objective=TaskObjective.PORTFOLIO_ANALYSIS,
            objective_summary=state["understanding"].objective_summary,
            audit_id=None,
            audit_code=None,
            plan=plan,
            planned_steps=[{"step": step, "status": "completed"} for step in plan.steps],
            findings=findings,
            recommendations=recommendations,
            source_refs=source_refs,
            unresolved_policies=list(dict.fromkeys(policy for audit in ranked for policy in audit.unresolved_policies)),
            explanation=explanation,
            explanation_source="deterministic",
            llm_used=state.get("task_llm_used", False),
            planning_source=state.get("planning_source", "deterministic"),
            llm_call_count=state.get("llm_call_count", 0),
            llm_latency_ms=state.get("llm_latency_ms", 0),
            fallback_reason=state.get("fallback_reason"),
            http_status_code=state.get("http_status_code"),
            provider_error_code=state.get("provider_error_code"),
            sanitized_error_message=state.get("sanitized_error_message"),
            ranked_audits=ranked,
            portfolio_failures=failures,
            portfolio_priority_method=PRIORITY_METHOD,
        )
        return {"task_result": result}

    def _execute_audit_tool(self, state: AgentState) -> AgentState:
        try:
            audit = self._tools.get_audit(state["understanding"].audit_reference)
            results = dict(state.get("tool_results", {}))
            results[ReadToolName.AUDIT.value] = audit
            return {
                "audit_record": audit,
                "tool_results": results,
                "executed_tools": [*state.get("executed_tools", []), ReadToolName.AUDIT.value],
            }
        except AuditNotFound:
            return {"error_code": "audit_not_found", "error_message": "Audit was not found."}
        except ProviderError as exc:
            code = "tool_execution_failed" if exc.code == "provider_error" else exc.code
            message = "Unable to read audit data." if exc.code == "provider_error" else exc.public_message
            return {"error_code": code, "error_message": message, "failed_tool": "audit"}
        except Exception:
            return {"error_code": "tool_execution_failed", "error_message": "Audit tool returned an invalid response.", "failed_tool": "audit"}

    def _make_task_tool_node(self, tool: ReadToolName):
        def execute(state: AgentState) -> AgentState:
            try:
                audit_id = state["audit_record"].id
                operation = {
                    ReadToolName.ASSIGNMENTS: self._tools.get_assignments,
                    ReadToolName.SCHEDULE: self._tools.get_schedule,
                    ReadToolName.CHECKLIST: self._tools.get_checklist,
                    ReadToolName.NON_CONFORMITIES: self._tools.get_non_conformities,
                }[tool]
                value = operation(audit_id)
                results = dict(state.get("tool_results", {}))
                results[tool.value] = value
                if tool == ReadToolName.CHECKLIST:
                    results["checklist_progress"] = self._tools.get_checklist_progress(audit_id)
                return {
                    "tool_results": results,
                    "executed_tools": [*state.get("executed_tools", []), tool.value],
                }
            except ProviderError as exc:
                code = "tool_execution_failed" if exc.code == "provider_error" else exc.code
                message = f"Unable to read {tool.value.replace('_', ' ')} data." if exc.code == "provider_error" else exc.public_message
                return {
                    "error_code": code,
                    "error_message": message,
                    "failed_tool": tool.value,
                }
            except Exception:
                return {
                    "error_code": "tool_execution_failed",
                    "error_message": f"{tool.value.replace('_', ' ').capitalize()} tool returned an invalid response.",
                    "failed_tool": tool.value,
                }
        return execute

    def _analyze_task(self, state: AgentState) -> AgentState:
        try:
            results = state["tool_results"]
            plan = state["plan"]
            snapshot = AuditSnapshot(
                audit=state["audit_record"],
                assignments=results.get(ReadToolName.ASSIGNMENTS.value, []),
                schedule=results.get(ReadToolName.SCHEDULE.value),
                checklist_items=results.get(ReadToolName.CHECKLIST.value, []),
                checklist_progress=results.get("checklist_progress"),
                checklist_item_details_available=self._tools.checklist_item_details_available,
                non_conformities=results.get(ReadToolName.NON_CONFORMITIES.value, []),
            )
            analysis = analyze_audit(snapshot)
            if plan.objective == TaskObjective.COMPLIANCE_GAP_ANALYSIS:
                relevant_prefixes = ("evaluate-pending-items", "nc-action-", "nc-rework-", "recheck-")
                analysis = analysis.model_copy(update={
                    "recommendations": [
                        recommendation for recommendation in analysis.recommendations
                        if recommendation.id.startswith(relevant_prefixes)
                    ]
                })
            findings = (
                analyze_compliance_gaps(snapshot)
                if plan.objective == TaskObjective.COMPLIANCE_GAP_ANALYSIS
                else analysis.facts
            )
            if plan.objective == TaskObjective.COMPLIANCE_GAP_ANALYSIS:
                findings.extend(fact for fact in analysis.facts if fact.kind == "warning")
            return {
                "snapshot": snapshot,
                "analysis": analysis,
                "task_findings": findings,
                # Task requests reserve their single model call for intent and planning.
                "include_explanation": False,
            }
        except Exception:
            return {"error_code": "analysis_error", "error_message": "The requested audit analysis could not be completed."}

    def _format_task_result(self, state: AgentState) -> AgentState:
        plan: ExecutionPlan = state["plan"]
        analysis: AuditAnalysis = state["analysis"]
        findings = state["task_findings"]
        recommendations: list[Recommendation] = analysis.recommendations
        all_refs = [
            ref
            for item in [*findings, *recommendations]
            for ref in item.source_refs
        ]
        unique_refs = list({
            (ref.entity, ref.record_id, ref.field, ref.value): ref
            for ref in all_refs
        }.values())
        executed = set(state.get("executed_tools", []))
        step_results = [
            {"step": step, "status": "completed" if step.tool.value in executed else "planned"}
            for step in plan.steps
        ]
        result = TaskExecutionResult(
            objective=plan.objective,
            objective_summary=state["understanding"].objective_summary,
            audit_id=state["audit_record"].id,
            audit_code=state["audit_record"].code,
            plan=plan,
            planned_steps=step_results,
            findings=findings,
            recommendations=recommendations,
            source_refs=unique_refs,
            unresolved_policies=analysis.unresolved_policies,
            explanation=analysis.explanation,
            explanation_source=analysis.explanation_source,
            llm_used=analysis.llm_used or state.get("task_llm_used", False),
            planning_source=state.get("planning_source", "deterministic"),
            llm_call_count=state.get("llm_call_count", 0),
            llm_latency_ms=state.get("llm_latency_ms", 0),
            fallback_reason=state.get("fallback_reason"),
            http_status_code=state.get("http_status_code"),
            provider_error_code=state.get("provider_error_code"),
            sanitized_error_message=state.get("sanitized_error_message"),
        )
        return {"task_result": result}

    def _load_context(self, state: AgentState) -> AgentState:
        try:
            return {"snapshot": self._tools.get_audit_snapshot(state["audit_id"])}
        except AuditNotFound:
            return {"error_code": "audit_not_found", "error_message": "Audit was not found."}
        except ProviderError as exc:
            code = "provider_error" if exc.code == "provider_error" else exc.code
            message = "QMS data provider could not load this audit." if exc.code == "provider_error" else exc.public_message
            return {"error_code": code, "error_message": message}
        except Exception:
            return {"error_code": "provider_error", "error_message": "QMS data provider returned an invalid response."}

    def _analyze(self, state: AgentState) -> AgentState:
        try:
            return {"analysis": analyze_audit(state["snapshot"])}
        except Exception:
            return {"error_code": "analysis_error", "error_message": "Audit analysis could not be completed."}

    def _explain_or_fallback(self, state: AgentState) -> AgentState:
        analysis: AuditAnalysis = state["analysis"]
        if not state.get("include_explanation", True) or self._explainer is None:
            return {}
        try:
            category = _category(state["snapshot"].audit.status.value, analysis.recommendations)
            explanation = self._explainer.explain(category)
            if explanation not in PHRASES[category].values():
                raise ValueError("Explanation provider returned unapproved wording")
            return {"analysis": analysis.model_copy(update={
                "explanation": explanation,
                "explanation_source": "llm-approved-phrase",
                "llm_used": True,
            })}
        except Exception:
            # The model is optional; retain complete deterministic facts and wording.
            return {}

    def _handle_error(self, state: AgentState) -> AgentState:
        return state

    def analyze(self, audit_id: str, include_explanation: bool = True) -> AuditAnalysis:
        config = None
        if self._checkpointer is not None:
            config = {"configurable": {
                "thread_id": (self._tool_context.request_id if self._tool_context and self._tool_context.request_id else str(uuid4()))
            }}
        state = self._graph.invoke({
            "audit_id": audit_id,
            "include_explanation": include_explanation,
        }, config=config)
        if state.get("error_code"):
            raise OrchestratorError(state["error_code"], state["error_message"])
        if "analysis" not in state:
            raise OrchestratorError("analysis_error", "Audit analysis could not be completed.")
        return state["analysis"]

    def list_audits(self):
        """Return provider-visible audits through the same read-only tool facade."""
        return self._tools.list_audits()

    def execute_task(self, request_text: str, include_explanation: bool = True) -> TaskExecutionResult:
        config = None
        if self._checkpointer is not None:
            config = {"configurable": {
                "thread_id": (self._tool_context.request_id if self._tool_context and self._tool_context.request_id else str(uuid4()))
            }}
        state = self._task_graph.invoke({
            "request_text": request_text,
            "include_explanation": include_explanation,
        }, config=config)
        if state.get("error_code"):
            raise OrchestratorError(state["error_code"], state["error_message"])
        if "task_result" not in state:
            raise OrchestratorError("analysis_error", "The requested audit task could not be completed.")
        return state["task_result"]


class OrchestratorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
