import re

from app.domain.schemas import (
    ExecutionPlan,
    LLMTaskProposal,
    ReadToolName,
    TaskObjective,
    TaskPlanStep,
    TaskUnderstanding,
)


_AUDIT_REFERENCE = re.compile(
    r"\b(?:audit[-_ ]\d{3,}|IA-\d{4}-\d{3,}|AUD-\d{4}-Q[1-4])\b",
    re.IGNORECASE,
)

_INTENTS: tuple[tuple[TaskObjective, tuple[str, ...], str], ...] = (
    (TaskObjective.PORTFOLIO_ANALYSIS, (
        r"\bportfolio(?:[- ]wide)?\b", r"\ball accessible audits\b", r"\ball audits\b",
        r"\brank audits?\b", r"\bwhich audits?\b.*\battention first\b",
        r"\bneeds? attention first\b", r"\baudits? .*urgency\b",
        r"\boverdue\b.*\bincomplete\b.*\baudit activities\b",
    ), "Rank accessible audits by documented urgency and summarize the actions supported by their records."),
    (TaskObjective.COMPLETION_PLAN, (
        r"\bcompletion\b", r"\bcompletion plan\b", r"\bplan (?:to|for) (?:complete|finish|close)\b",
        r"\bfinish(?:ing)?\b", r"\bcomplete\b", r"\bclose\b", r"\bready to close\b",
    ), "Plan the remaining work to complete the audit lifecycle."),
    (TaskObjective.COMPLIANCE_GAP_ANALYSIS, (
        r"\bcompliance gap(?:s)?\b", r"\bgap analysis\b", r"\bnon[- ]?compliant\b",
        r"\bnon[- ]?conformit(?:y|ies)\b", r"\bdeficienc(?:y|ies)\b",
    ), "Identify recorded checklist and non-conformity gaps."),
    (TaskObjective.PENDING_ACTIONS, (
        r"\bpending action(?:s)?\b", r"\boutstanding action(?:s)?\b", r"\bnext action(?:s)?\b",
        r"\bwhat(?:'s| is) pending\b", r"\bwhat remains\b", r"\bunresolved action(?:s)?\b", r"\bpending\b",
    ), "Identify outstanding lifecycle actions and their source records."),
    (TaskObjective.AUDIT_ANALYSIS, (
        r"\banaly[sz](?:e|e|is|ing)\b", r"\banalysis\b", r"\boverview\b", r"\bsummar(?:y|ize|ise)\b",
        r"\breview\b", r"\bstatus\b",
    ), "Summarize the audit state, supporting records and recommendations."),
)

_TOOL_PLANS = {
    TaskObjective.PORTFOLIO_ANALYSIS: (
        [ReadToolName.AUDITS],
        "List only audits visible to the current provider context, then analyze each available read-only lifecycle snapshot.",
    ),
    TaskObjective.AUDIT_ANALYSIS: (
        [ReadToolName.AUDIT, ReadToolName.ASSIGNMENTS, ReadToolName.SCHEDULE, ReadToolName.CHECKLIST, ReadToolName.NON_CONFORMITIES],
        "A complete audit overview needs lifecycle, checklist and NC context.",
    ),
    TaskObjective.PENDING_ACTIONS: (
        [ReadToolName.AUDIT, ReadToolName.ASSIGNMENTS, ReadToolName.SCHEDULE, ReadToolName.CHECKLIST, ReadToolName.NON_CONFORMITIES],
        "Pending work can exist at each audit, orientation, schedule, checklist or NC stage.",
    ),
    TaskObjective.COMPLETION_PLAN: (
        [ReadToolName.AUDIT, ReadToolName.ASSIGNMENTS, ReadToolName.SCHEDULE, ReadToolName.CHECKLIST, ReadToolName.NON_CONFORMITIES],
        "Completion planning needs every read-only lifecycle area and checks its prerequisites.",
    ),
    TaskObjective.COMPLIANCE_GAP_ANALYSIS: (
        [ReadToolName.AUDIT, ReadToolName.CHECKLIST, ReadToolName.NON_CONFORMITIES],
        "Compliance gaps are evaluated from checklist results and linked non-conformities; assignment and schedule data are not required.",
    ),
}

_TOOL_DESCRIPTIONS = {
    ReadToolName.AUDITS: "List audits visible to the current QMS provider context.",
    ReadToolName.AUDIT: "Read the audit identity, scope, dates and lifecycle status.",
    ReadToolName.ASSIGNMENTS: "Read assigned auditors and orientation status.",
    ReadToolName.SCHEDULE: "Read schedule state and confirmation records.",
    ReadToolName.CHECKLIST: "Read checklist questions, results and remarks.",
    ReadToolName.NON_CONFORMITIES: "Read linked non-conformity status and action indicators.",
}


class TaskParseError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def understand_request(request_text: str) -> TaskUnderstanding:
    """Extract a supported objective and audit reference without an LLM call."""
    text = request_text.strip()
    if len(text) < 5:
        raise TaskParseError("invalid_task_request", "Request must contain an audit reference and a supported objective.")

    normalized = text.casefold()
    objective = None
    summary = ""
    for candidate, patterns, candidate_summary in _INTENTS:
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
            objective = candidate
            summary = candidate_summary
            break
    if objective is None:
        raise TaskParseError(
            "invalid_task_request",
            "I could not identify the objective. Ask for audit analysis, pending actions, completion planning, or compliance gap analysis.",
        )

    reference_match = _AUDIT_REFERENCE.search(text)
    if objective != TaskObjective.PORTFOLIO_ANALYSIS and not reference_match:
        raise TaskParseError("invalid_task_request", "Include an audit ID such as audit-1003 or IA-2026-003.")

    return TaskUnderstanding(
        request_text=text,
        audit_reference=reference_match.group(0) if reference_match and objective != TaskObjective.PORTFOLIO_ANALYSIS else None,
        objective=objective,
        objective_summary=summary,
    )


def understand_request_with_proposal(request_text: str, proposal: LLMTaskProposal) -> TaskUnderstanding:
    """Combine validated model intent with an audit reference parsed locally."""
    text = request_text.strip()
    match = _AUDIT_REFERENCE.search(text)
    if proposal.objective != TaskObjective.PORTFOLIO_ANALYSIS and not match:
        raise TaskParseError("invalid_task_request", "Include an audit ID such as audit-1003 or IA-2026-003.")
    objective_summary = next(summary for objective, _, summary in _INTENTS if objective == proposal.objective)
    understanding = TaskUnderstanding(
        request_text=text,
        audit_reference=match.group(0) if match and proposal.objective != TaskObjective.PORTFOLIO_ANALYSIS else None,
        objective=proposal.objective,
        objective_summary=objective_summary,
    )
    try:
        return apply_llm_proposal(understanding, proposal)
    except ValueError as exc:
        raise TaskParseError("invalid_task_request", "The requested audit plan is not supported.") from exc


def create_execution_plan(understanding: TaskUnderstanding) -> ExecutionPlan:
    tools, rationale = _TOOL_PLANS[understanding.objective]
    steps = [
        TaskPlanStep(step_id=f"read-{tool.value}", tool=tool, description=_TOOL_DESCRIPTIONS[tool])
        for tool in tools
    ]
    return ExecutionPlan(
        audit_id=understanding.audit_reference,
        objective=understanding.objective,
        rationale=rationale,
        required_tools=tools,
        steps=steps,
    )


def apply_llm_proposal(understanding: TaskUnderstanding, proposal: LLMTaskProposal) -> TaskUnderstanding:
    """Accept an LLM objective only with the deterministic complete tool set.

    The audit reference and source request always come from the original text.
    Canonical tool requirements prevent a model from omitting relevant records.
    """
    expected_tools, _ = _TOOL_PLANS[proposal.objective]
    if len(proposal.required_tools) != len(set(proposal.required_tools)):
        raise ValueError("duplicate tools")
    if set(proposal.required_tools) != set(expected_tools):
        raise ValueError("unsupported or incomplete tool selection")
    return understanding.model_copy(update={
        "objective": proposal.objective,
        "objective_summary": next(summary for objective, _, summary in _INTENTS if objective == proposal.objective),
    })
