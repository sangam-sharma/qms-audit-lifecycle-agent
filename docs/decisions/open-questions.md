# Open questions

This is a decision queue, not a claim that the following behavior already exists. Resolve these before building the affected integration. Keep answers here or record durable decisions as ADRs.

## Existing QMS behavior that needs reconciliation

- **NC verification role:** `AuditNCViewSet.partial_update` in `Backend/audits/views.py` grants QMS read-only access and accepts verification fields from an assigned auditor. `Frontend/src/api/endpoints.js` comments and UI labels describe QMS verification. Which role is intended to accept or request rework? Align API, UI and business rules before an agent recommends action.
- **Audit closure role:** `AuditViewSet.close` checks that the requester is an assigned auditor, while frontend text and API comments describe QMS closure. Confirm intended owner and align implementation before integrating a close recommendation.
- **`PENDING_CLOSURE`:** This status is present in the model, but current closure code transitions directly from `IN_PROGRESS` to `CLOSED`; clarify whether this status should be used.
- **Audit department:** Creation derives department from the selected project even though the serializer exposes it read-only. Confirm that project department is always the intended audit scope.
- **Checklist selection:** `create_audit_checklist` uses the first active checklist matching framework and department. A uniqueness constraint currently limits one such checklist; confirm selection and versioning requirements for future revisions.

## Agent service and API

- Where should the separate service run in local and production environments, and what network boundary should it have?
- What exact user experience invokes the agent: dashboard summary, audit detail assistant, or an explicit analysis request?
- Which audit fields and remarks are necessary for an analysis, and what is the minimum data returned to the provider?
- How will the separate service receive and validate the initiating user's identity and effective permissions? No service credential, delegated-token contract, or agent endpoint exists yet.
- Should the service call existing Django endpoints directly, or should a narrowly scoped backend integration endpoint be added? Avoid database sharing and do not bypass Django serializers/permissions.
- Which Django API resources and response fields are stable enough for provider contracts? There is no formal OpenAPI contract in the current source.

## LLM, privacy and operation

- Which model provider, deployment region, retention terms, and secret-management approach are approved?
- Which fields can be sent to the model? Should user names, project identifiers, remarks or NC descriptions be redacted or pseudonymized?
- What response schema, citation/provenance format, timeout, retry, cost, and token limits should apply?
- What must be logged for auditability, and what sensitive prompt/context data must not be logged?
- What human review language and limitations should accompany generated explanations?

## Testing and delivery

- What confidence and regression criteria are required before enabling the agent for any role?
- Which real audit cases can be safely represented in mock fixtures without exposing personal or confidential data?
- What are the deployment, monitoring, availability and rollback expectations for a separately operated service?
