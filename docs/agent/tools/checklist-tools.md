# Checklist tools

**Status: proposed read-only contracts.** The current API has checklist retrieval for assigned auditors only while an audit is `IN_PROGRESS`; do not assume all roles can view item details.

## `get_audit_checklist`

- **Purpose:** Retrieve audit-specific checklist rows for a focused, authorized explanation.
- **Input:** `audit_id` (integer), optional bounded `item_ids` or page/limit to select rows.
- **Output:** Audit checklist ID/name and rows with item ID/code, question only if needed and authorized, order, result, remarks only when specifically needed, and source references.
- **Permissions:** Follow Django's `/api/audits/{id}/checklist/` rule: authenticated assigned auditor, and audit must be `IN_PROGRESS`. The existing endpoint currently returns the full checklist; this tool should still minimize what it passes to the model.
- **Errors:** Invalid input, not found, forbidden/not assigned, not in progress, missing checklist, API timeout, malformed item response.

## `summarize_checklist_results`

- **Purpose:** Calculate counts by `PENDING`, `COMPLIANT`, and `NON_COMPLIANT` using Python. Example output can report 4 compliant, 1 non-compliant and 2 pending rows.
- **Input:** Authorized checklist rows or `audit_id` resolved via provider.
- **Output:** Counts, total, consistency indicator, and source IDs/range. Empty or partial data must be explicitly marked, not represented as a complete zero count.
- **Permissions:** Inherit the visibility of the underlying checklist retrieval. This does not authorize the caller to view rows they otherwise cannot access.
- **Errors:** Invalid result values, incomplete fetch, authorization failure or provider failure.

No tool may update an item result or remarks. Django enforces that a compliant item cannot be re-evaluated and a non-compliant item becomes compliant only after its NC is accepted. Related: [audit lifecycle](../../domain/qms-audit-lifecycle.md) · [API integration](../../integration/django-api-integration.md).
