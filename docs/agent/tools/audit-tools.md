# Audit tools

**Status: proposed read-only contracts.** These names are conceptual, not existing Python functions or API routes.

## `get_audit_overview`

- **Purpose:** Fetch a compact authorized audit snapshot for an explanation, such as why audit `AUD-101` cannot yet start.
- **Input:** `audit_id` (integer); trusted caller context supplied by service middleware, not a tool argument controlled by the model.
- **Output:** Audit ID/code/status, project/framework identifiers or names where authorized, planned dates, Django progress summary (assignments/orientations, schedule/confirmations, checklist and NC counts), and source references. Return only fields required by requested analysis.
- **Permissions:** Caller must be able to retrieve that audit under Django's role-scoped queryset; provider must enforce scope. QMS sees all; a Director sees audits for owned projects; an Employee sees assigned audits or project-member audits, per current `AuditViewSet.get_queryset`.
- **Errors:** Invalid ID; audit not found or outside caller scope; API unavailable/timeout; malformed or incomplete source response. Avoid disclosing which out-of-scope IDs exist.

## `explain_start_readiness`

- **Purpose:** Calculate known prerequisites and explain whether a particular assigned auditor can call the existing start action.
- **Input:** `audit_id`; caller identity from trusted context. Do not infer the acting auditor from arbitrary model-generated text.
- **Output:** Deterministic checks for assignment, that user's orientation, schedule existence/status, checklist existence, and audit status, each with evidence/source field. This is advisory; Django rechecks all guards on `POST /api/audits/{id}/start/`.
- **Permissions:** Must establish the same user's assignment and only reveal their own orientation. If no caller identity is established, return an incomplete/error result rather than user-specific readiness.
- **Errors:** Same provider errors as overview, plus caller not assigned, missing orientation data, or unsupported state. A missing field is not equivalent to “false”.

No write permission exists for these tools. Related: [lifecycle](../../domain/qms-audit-lifecycle.md) · [workflow](../langgraph-workflow.md).
