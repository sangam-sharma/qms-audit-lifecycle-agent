def phrase_selection_prompt(category: str) -> str:
    """Tiny prompt for choosing style only; facts never enter the model context."""
    return (
        "Choose the phrase id that reads most naturally for the supplied category. "
        "Return JSON only: {\"choice\": \"brief\"} or {\"choice\": \"review\"}. "
        f"Category: {category}. Allowed ids: brief, review."
    )


def task_understanding_prompt(request_text: str) -> str:
    return (
        "Classify this QMS audit request and select the read tools needed. "
        "Return JSON only with objective (audit_analysis, pending_actions, completion_plan, "
        "compliance_gap_analysis, portfolio_analysis), required_tools (audits, audit, assignments, "
        "schedule, checklist, non_conformities), and a short rationale. Use audits for portfolio_analysis. "
        "Do not infer audit facts or permissions. "
        "Use the complete relevant tool set for the objective.\nRequest: "
        + request_text[:1000]
    )
