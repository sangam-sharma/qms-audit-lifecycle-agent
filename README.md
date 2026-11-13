# QMS AI Audit Agent

This workspace contains an existing Quality Management System (QMS) Internal Audit & Compliance Management application and the project documentation for a planned AI audit agent. The objective is to add an autonomous assistant that supports audit work by integrating with the existing QMS; the existing application remains the system of record.

## What exists today

- **Backend:** Django and Django REST Framework, with Simple JWT authentication.
- **Frontend:** React 19, Vite, React Router, and Axios.
- **Development database:** Existing SQLite database at `Backend/db.sqlite3`.
- **QMS features:** Departments and users, projects and project members, frameworks and master checklists, audits and audit checklists, assignments and orientation, schedules and confirmations, checklist results, non-conformities (NCs), and audit closure.

The separate agent service is **planned**, not implemented. No LangGraph, LangChain, LLM, RAG, or agent tool runtime is present in the current Backend or Frontend dependencies. Version 1 is planned as one LangGraph Audit Orchestrator, a mock data provider first, read-only tools, and deterministic Python for business logic. An LLM will explain results. Django API integration may follow; RAG and multi-agent orchestration are out of scope for Version 1. See the [architecture decisions](docs/architecture/decisions/ADR-001-separate-agent-service.md).

## Technologies

| Area | Current / planned technology |
| --- | --- |
| QMS API | Django, Django REST Framework |
| QMS UI | React, Vite |
| QMS development data | Existing SQLite database |
| Future agent service | Python, LangGraph; LangChain only where useful |
| Future model access | LLM integrations, behind a service boundary |
| Retrieval | RAG only if later justified; not Version 1 |

## Local setup

Setup instructions below describe the existing QMS application. The agent service has no implementation or dependencies to install yet.

### Backend

Requires Python 3.12 or later. From the repository root:

```bash
cd Backend
python -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver
```

The backend serves the API at `http://127.0.0.1:8000/api/`. The project includes a development SQLite database. Preserve it; do not replace or delete it. Run migrations only when intentionally preparing a development environment and after reviewing their effect. Detailed setup and tests: [Local setup](docs/development/local-setup.md), [testing strategy](docs/development/testing-strategy.md).

### Frontend

Requires Node.js 20.19 or later (or 22.12 or later). In another terminal:

```bash
cd Frontend
npm install
npm run dev
```

Vite serves the frontend at `http://localhost:5173`. The API base URL defaults to `http://127.0.0.1:8000/api`; set `VITE_API_URL` to override it. Do not install packages unless asked to do so.

### Demo users

The existing README documents the development password as `Password@123`. Available usernames/roles include `director1` / Director, `qms1` / QMS, and `employee1` through `employee7` / Employee. Treat these as local development credentials only; consult the actual seeded database for current records. Do not use demo credentials outside local development.

## Documentation

Start with the [documentation index](docs/README.md) for the suggested reading order and full map. Important starting points:

- [System overview](docs/architecture/system-overview.md)
- [QMS audit lifecycle](docs/domain/qms-audit-lifecycle.md)
- [Agent architecture](docs/architecture/agent-architecture.md)
- [Implementation roadmap](docs/development/implementation-roadmap.md)
- [Open questions](docs/decisions/open-questions.md)

The repository-wide contribution and safety rules are in [AGENTS.md](AGENTS.md).
