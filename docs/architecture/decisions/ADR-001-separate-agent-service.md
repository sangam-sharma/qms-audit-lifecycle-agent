# ADR-001: Use a separate Python agent service

- **Status:** Accepted as the project direction for planned work.
- **Scope:** Agent architecture decision; service code and integration are not implemented.

## Context

The workspace already contains a Django/DRF QMS application with business rules, JWT auth, role-specific permissions, and a SQLite development database. The planned AI work uses Python and LangGraph, with LLM integrations. The project must integrate with the QMS without rebuilding or replacing it.

## Decision

Build the agent as a separate Python service. Use one LangGraph Audit Orchestrator initially. Start with a mock data provider; add a Django API-backed provider later. Start with read-only tools. Use deterministic Python for business logic and an LLM for explanations. Do not use RAG or multi-agent architecture in Version 1.

## Consequences

- The Django QMS remains the system of record and owner of permissions and state transitions.
- Agent dependencies and runtime can be isolated from the existing React and Django applications.
- Mock fixtures enable workflow development without database or API access.
- A later provider requires a secure caller identity/authorization contract and API-level integration; it must not read the SQLite file directly.
- The service introduces an operational boundary (deployment, monitoring, secrets, timeouts) that must be designed.
- Generated explanations are advisory; the service cannot write audit, checklist or NC state in Version 1.

## Alternatives considered

- **Embed orchestration inside Django:** rejected for the initial direction because it couples agent-specific runtime/dependencies to the existing application and blurs the service boundary.
- **Direct shared SQLite access:** rejected because it bypasses Django authorization, serializers and business logic.
- **Multiple cooperating agents or RAG in Version 1:** rejected as unnecessary scope before a validated simple workflow and source data boundary exist.

## Revisit when

Revisit if deployment or latency needs make a separate process impractical, or evidence shows multiple specialized agents/RAG are needed. Such change requires a new decision and threat/data review. See [open questions](../../decisions/open-questions.md).
