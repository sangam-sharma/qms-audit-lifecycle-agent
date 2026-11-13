# Implementation roadmap

This sequence follows the workspace instructions: understand the existing QMS and its audit lifecycle before introducing an agent. All agent phases are **planned**; this documentation creates no implementation.

## Phase 1: establish source-of-truth map

- Trace Django model, serializer, service and endpoint behavior for each audit phase.
- Compare API guards with frontend affordances and resolve who verifies NCs and closes audits.
- Confirm checklist snapshot/history requirements and identify data minimization needs.
- Keep audit state transitions in Django.

**Exit:** lifecycle, role matrix and mismatches are agreed and recorded.

## Phase 2: design provider and contracts

- Define an analysis use case, request/response schema, typed audit snapshot and error model.
- Decide caller identity and permission propagation before API access.
- Specify mock fixtures and data minimization.

**Exit:** reviewed provider contract and concrete test cases, no Django coupling.

## Phase 3: mock-first deterministic analysis

- Create isolated Python service/package only after design review.
- Add mock provider and read-only audit/checklist/NC tools.
- Implement deterministic counts and prerequisite explanations with pure Python.
- Test authorization/error branches using synthetic data.

**Exit:** reproducible tests without Django or model credentials.

## Phase 4: single LangGraph orchestration

- Add one Audit Orchestrator graph with validate, load, calculate, explain, validate-output and return/failure paths.
- Use an LLM only to explain facts; enforce output schema and token/time budgets.
- Keep LangChain optional and justified by concrete integration requirements.
- Exclude RAG and multi-agent architecture.

**Exit:** bounded graph tests pass; no write capability and unsupported claims are rejected.

## Phase 5: Django API provider

- Implement an authorized API adapter only after identity model and endpoint contract are accepted.
- Add timeouts, response limits, data minimization and authorization tests.
- Avoid shared database access and do not add broad bypass endpoints.

**Exit:** provider preserves per-user access and does not mutate QMS records.

## Phase 6: user experience and operational readiness

- Decide whether and where the current React UI invokes the agent; document explicit advisory behavior.
- Define deployment, secrets, monitoring, logging, retention, limits and rollback.
- Complete end-to-end checks and a staged rollout plan before enabling real users.

**Exit:** approved security review and verified failure/rollback behavior.

At each implementation step, explain the design and code flow first, keep changes incremental, teach the concepts, and run relevant tests after implementation as required by [AGENTS.md](../../AGENTS.md). Do not install dependencies or change source code as part of documentation-only work.
