# Documentation index

This documentation distinguishes **Implemented** behavior verified in `Backend/` or `Frontend/src/`, **Planned** agent work, and **Unresolved** items requiring a decision. Django is the authority for access control and QMS state transitions; a UI label or planned agent behavior cannot grant permission.

## Suggested reading order

1. [Project overview](../README.md)
2. [System overview](architecture/system-overview.md)
3. [QMS audit lifecycle](domain/qms-audit-lifecycle.md)
4. [Database models](domain/database-models.md)
5. [Separate service decision](architecture/decisions/ADR-001-separate-agent-service.md)
6. [Agent architecture](architecture/agent-architecture.md)
7. [Data flow](architecture/data-flow.md)
8. [LangGraph workflow](agent/langgraph-workflow.md) and [state management](agent/state-management.md)
9. [Django API integration](integration/django-api-integration.md) and [authentication/permissions](integration/authentication-and-permissions.md)
10. [Development setup](development/local-setup.md), [testing](development/testing-strategy.md), and [roadmap](development/implementation-roadmap.md)
11. [Open questions](decisions/open-questions.md)

## By topic

### Architecture

- [System overview](architecture/system-overview.md)
- [Agent architecture](architecture/agent-architecture.md)
- [Data flow](architecture/data-flow.md)
- [Security](architecture/security.md)
- [ADR-001: Separate agent service](architecture/decisions/ADR-001-separate-agent-service.md)

### QMS domain

- [Audit lifecycle](domain/qms-audit-lifecycle.md)
- [Database models](domain/database-models.md)
- [Glossary](glossary.md)

### Agent design

- [Agent overview](agent/README.md)
- [LangGraph workflow](agent/langgraph-workflow.md)
- [State management](agent/state-management.md)
- [Data provider](agent/data-provider.md)
- [LLM and token efficiency](agent/llm-and-token-efficiency.md)
- [Tool index](agent/tools/README.md)
- [Audit tools](agent/tools/audit-tools.md)
- [Checklist tools](agent/tools/checklist-tools.md)
- [Non-conformity tools](agent/tools/non-conformity-tools.md)

### Integration and development

- [Django API integration](integration/django-api-integration.md)
- [Authentication and permissions](integration/authentication-and-permissions.md)
- [Local setup](development/local-setup.md)
- [Testing strategy](development/testing-strategy.md)
- [Implementation roadmap](development/implementation-roadmap.md)
- [Open questions](decisions/open-questions.md)

## Source of truth and status

Implemented QMS behavior is documented from the Django models, serializers, views, URL configuration, settings, frontend API client, UI workflow, and existing tests. The current source does **not** contain an agent service, LangGraph graph, mock provider, agent-specific endpoints, or AI tools. Documents describe those as proposals based on the agreed architecture, not existing software.

Where existing user interface descriptions differ from backend behavior, the backend implementation is the source of truth and the mismatch is called out as an open question. See [open questions](decisions/open-questions.md).
