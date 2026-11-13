# Agent tools

## Status and shared contract

All tools below are **proposed**, not implemented functions or new Django endpoints. Version 1 tools are read-only. The orchestrator invokes typed tools based on validated request flow; do not give the model unrestricted API, database, shell or network access.

For each tool, enforce caller scope in the provider/API, validate IDs and bound returned data. A client-supplied role is not authorization. Tool-level “permissions” below describe required QMS visibility; service identity/delegation is unresolved. Errors should distinguish invalid input, not found, forbidden, unavailable and invalid source data without leaking records across scope.

## Index

- [Audit tools](audit-tools.md): audit summary and lifecycle readiness facts.
- [Checklist tools](checklist-tools.md): checklist data and deterministic result counts.
- [Non-conformity tools](non-conformity-tools.md): scoped NC summary/detail.

No tool may create/assign/start/close audits, edit checklist results, create NCs, modify actions, verify NCs, or change statuses. See [lifecycle](../../domain/qms-audit-lifecycle.md) and [API integration](../../integration/django-api-integration.md).
