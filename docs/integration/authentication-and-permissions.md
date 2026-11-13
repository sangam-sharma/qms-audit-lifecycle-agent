# Authentication and permissions

## Existing QMS authentication

The backend configures `JWTAuthentication` as the DRF default (`Backend/config/settings.py`) and Simple JWT token endpoints through `/api/auth/login/` and `/api/auth/token/refresh/`. Current configured lifetimes are 30 minutes for access and one day for refresh. Login response includes a serialized user with role and department. `GET /api/auth/me/` returns the current authenticated user.

The frontend stores access token, refresh token and user in `localStorage`, attaches `Authorization: Bearer <access>` and refreshes after a 401 (`Frontend/src/api/client.js`). On refresh failure it clears storage and redirects to login. Browser role checks in `Frontend/src/permissions.js` are UI gating only; backend permission classes and view querysets are the security boundary.

## Existing role scopes (high level)

| Role | Current intended/system behavior |
| --- | --- |
| Director | Manage own projects and project membership. Read own project audits. Can edit master checklists in current code. |
| QMS | Broad audit visibility; create audits; assign auditors; manage scheduling/confirmations; maintain frameworks/checklists depending on endpoint. |
| Employee | Read audits when assigned as auditor or a member of the audited project. An employee acts as auditor only while assigned. |

Per-resource permissions differ. In particular the backend currently treats NC as read-only for QMS and grants audit closure/NC verification paths to assigned auditors, despite frontend comments describing QMS as verifier/closer. Resolve this before granting an agent access based on those workflows. See [audit lifecycle](../domain/qms-audit-lifecycle.md) and [open questions](../decisions/open-questions.md).

## Future service identity (unresolved)

There is no current agent authentication contract. Before the API provider exists, decide whether each request carries a delegated, short-lived user credential or uses another service identity plus an explicit user-scope authorization check. A static service token alone must not be treated as the user's access rights. Never share Django's `SECRET_KEY` or database file with the service. Do not accept caller role, audit permissions, or ownership assertions from model output.

For Version 1, tools are read-only and should request only data the initiating user is allowed to see. Preserve authorization failures as errors; do not ask the model to infer or summarize inaccessible data.

## Security configuration limits

Current settings show development configuration: `DEBUG = True`, an in-source development secret, localhost CORS entries and a development ngrok host. They are not a production deployment recipe. Before exposure beyond local development, configure secrets, hosts, TLS, CORS, logging, token storage and deployment controls for the target environment.
