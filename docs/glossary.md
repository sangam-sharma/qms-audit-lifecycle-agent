# Glossary

| Term | Meaning in this project |
| --- | --- |
| Audit | A QMS record for a project, framework, department, planned dates, and lifecycle status. |
| Audit checklist | The audit-specific checklist created from active master checklist items when a QMS user creates an audit. It records each item result and remarks. |
| Audit Orchestrator | Planned single LangGraph workflow that coordinates read-only audit analysis. |
| Auditor | An Employee user temporarily assigned as PRIMARY or SECONDARY auditor for an audit; there is no permanent auditor role. |
| Checklist item | A master question (`ChecklistItem`) or its audit execution record (`AuditChecklistItem`), depending on context. |
| Data provider | Planned adapter supplying audit context to the agent. Version 1 starts with mock data; a Django API-backed provider is a later step. |
| Department | QMS organizational unit referenced by users, projects, checklists, and audits. |
| Director | Role that manages owned projects and, in current source, can manage master checklists. |
| Evidence | Information supporting an audit conclusion. The current model stores checklist result and remarks but has no general evidence/file model. |
| Framework | A named compliance framework associated with master checklists. |
| LLM | Large language model; planned for explanations, not authoritative business decisions. |
| NC | Non-conformity record linked one-to-one with a non-compliant audit checklist item. |
| POC | Project point of contact, represented by a project membership with PRIMARY, SECONDARY, ADDITIONAL, or NONE type. |
| QMS | Quality Management System; also the current `QMS` application role responsible for central audit administration. |
| RAG | Retrieval-augmented generation: retrieval of relevant reference material to provide context to an LLM. Excluded from Version 1. |
| Read-only tool | Planned agent operation that reads or summarizes data and cannot mutate QMS records. |
| Snapshot | Audit-specific copy of the active checklist's currently active items, created at audit creation time. |
| State | Planned typed data carried between LangGraph steps for one agent run; it is not persisted QMS workflow state. |
| Tool | A narrow planned agent capability such as retrieving audit context or deterministically summarizing checklist results. |
| Version 1 | The agreed first scope: one orchestrator, mock provider first, read-only tools, deterministic Python rules, LLM explanations, no RAG, no multi-agent design. |
