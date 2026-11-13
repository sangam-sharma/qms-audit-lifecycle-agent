# Non-conformity tools

**Status: proposed read-only contracts.** No agent NC tool exists. The backend's current NC visibility is QMS, assigned auditor, or audited-project member. Update behavior has role-specific field rules and a UI/backend discrepancy for verification; read [open questions](../../decisions/open-questions.md).

## `list_audit_non_conformities`

- **Purpose:** Return an authorized NC summary for an audit, such as how many await team action, rework, or acceptance.
- **Input:** `audit_id` (integer), optional status filter and bounded pagination.
- **Output:** Counts by status and only minimal per-record fields (NC ID, checklist item ID/code, status, whether corrective text exists, timestamps when needed). Do not include finding/action prose unless requested and approved.
- **Permissions:** QMS, assigned auditor or member of the audited project, following `AuditNCViewSet.get_queryset`; enforce through the authorized Django provider.
- **Errors:** Invalid filter/ID, audit or NC not found/in scope, provider unavailable, malformed status, incomplete page.

## `get_non_conformity_detail`

- **Purpose:** Explain the current recorded state of one NC to a user already authorized to see it.
- **Input:** `audit_id`, `nc_id`; optional approved field selection.
- **Output:** Status and selected fields with provenance: finding, risk action, correction, corrective/preventive action, verification remarks, and checklist context only where necessary. Default to omit free-text fields.
- **Permissions:** Same read scope as NC list. Enforce both audit and NC relationship; IDs from a caller do not prove access.
- **Errors:** Invalid ID, not found/out of scope, forbidden, provider failure, or stale record.

Neither tool can create an NC, edit finding or corrective actions, submit verification, accept/rework, or mark an item compliant. For state logic see [lifecycle](../../domain/qms-audit-lifecycle.md); for role conflict see [open questions](../../decisions/open-questions.md).
