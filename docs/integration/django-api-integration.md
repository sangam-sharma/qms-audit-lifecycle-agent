# Django API integration

## Status

**Implemented:** Existing QMS endpoints described below. **Planned:** A future agent provider that reads these endpoints. No agent endpoint, provider, service credential or OpenAPI document exists in the current source.

## Existing API surface relevant to an agent

All paths are under `/api/`; all listed business reads require JWT unless an endpoint is the login/refresh endpoint.

| Resource | Relevant routes | Notes |
| --- | --- | --- |
| Authentication | `POST /auth/login/`, `POST /auth/token/refresh/`, `GET /auth/me/` | Login returns access, refresh and serialized user. |
| Users/departments | `GET /auth/users/`, `GET /auth/departments/` | Active records; authenticated. Avoid fetching user directories for agent analysis. |
| Projects | `GET /projects/`, `GET /projects/{id}/` | Queryset: Director's owned projects; QMS all; Employee none. Writes are Director only. |
| Frameworks/checklists | `GET /frameworks/`, `GET /checklists/`; checklist items at `/checklists/{id}/items/` | Reads authenticated; checklists can be edited by Director or QMS; framework writes QMS only. |
| Audits | `GET /audits/`, `GET /audits/{id}/`, `POST /audits/`, `POST /audits/{id}/start/`, `GET /audits/{id}/checklist/`, `POST /audits/{id}/close/` | List/detail are role-scoped. Create QMS only. Start/checklist require assigned auditor under additional state guards. Close checks assigned auditor in current backend. |
| Assignments | `GET/POST /audits/{id}/assignments/`, `GET /audits/{id}/assignments/{assignment_id}/` | Create QMS only; read is authenticated and query-scoped. |
| Orientation | `GET /orientations/`, `GET /orientations/{id}/`, `POST /orientations/{id}/complete/` | QMS can list all; others see own assignment orientations. A user can complete own only. |
| Schedule | `GET/POST /audits/{id}/schedule/`, `GET/PATCH/PUT /audits/{id}/schedule/{schedule_id}/` | QMS writes; reads are scoped by role/queryset. At most one schedule per audit. |
| Confirmation | `GET/POST /audits/{id}/confirmations/`, `GET /audits/{id}/confirmations/{id}/` | QMS creates; read scope is role/queryset. Both confirmation types are required for CONFIRMED. |
| Audit checklist items | `GET/PATCH /audits/{id}/checklist-items/{item_id}/` | Read route does not independently check assignment in queryset; PATCH checks assignment and IN_PROGRESS. Prefer the checklist action for supported retrieval. |
| Non-conformities | `GET /audits/{id}/ncs/`, `GET/PATCH /audits/{id}/ncs/{nc_id}/` | Read scoped to QMS, assigned auditor, audited-project member. PATCH field/role rules in view; current UI/backend verification mismatch. |

Routes are assembled in `Backend/config/urls.py` and app URL files. This table is a navigation aid, not a complete API contract. Read serializers and current tests before relying on exact payload shape.

## Provider integration design

Recommended sequence:

1. Complete mock fixtures and provider contract without contacting Django.
2. Decide the caller identity and authorization model; never trust a `role` supplied by the browser or LLM.
3. Define a minimum DTO and exact calls needed for an analysis.
4. Add an HTTP provider that calls Django endpoints over an approved authenticated channel, with timeouts, response bounds and typed errors.
5. Test using synthetic records and Django API test credentials; test 401/403, not-found, timeout, malformed and partial responses.

Do not read Django ORM models from the agent process, connect to the SQLite file, add agent tables, or bypass DRF permissions. An agent service credential that can read everything would defeat the current per-user scope unless separately designed and controlled.

## Data and error mapping

Convert responses to typed provider DTOs at the boundary. Keep source IDs and status strings; validate known enum values. Distinguish 401 (invalid/expired auth), 403 (not authorized), 404 (not found or hidden by scope), 429 (rate limit if introduced), 5xx/network timeout, and invalid response. Do not silently retry writes (none are allowed for Version 1).

Related: [authentication and permissions](authentication-and-permissions.md) · [provider](../agent/data-provider.md) · [open questions](../decisions/open-questions.md)
