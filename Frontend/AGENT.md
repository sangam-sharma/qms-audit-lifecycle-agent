QMS Internal Audit & Compliance System

1. Project Objective

This project is an existing QMS Internal Audit & Compliance Management System.

Our objective is to develop an autonomous AI audit agent that integrates with the existing application.

The AI agent should automate appropriate parts of the audit lifecycle while maintaining security, traceability and human oversight.

2. Existing Technology Stack

Backend

* Python
* Django
* Django REST Framework
* SQLite (existing development database)

Frontend

* React
* Vite
* JavaScript

AI Agent (Planned)

* Python
* LangGraph
* LangChain where appropriate
* LLM integrations
* RAG where justified

Do not assume planned technologies are already implemented.

3. Development Environment

* Work exclusively in the local qms-agent-work Git branch.
* Never push changes to GitHub.
* Never modify remote GitHub branches.
* Never change Git remotes.
* Preserve the existing main branch.
* Use local Git commits as development checkpoints when appropriate.

4. Existing Application Protection

* Never rebuild or replace the existing application.
* Understand existing implementations before modifying them.
* Reuse existing Django models, services and APIs where appropriate.
* Never delete existing application code without explicit approval.
* Never delete or reset the existing database.
* Never execute destructive database commands without approval.
* Do not introduce duplicate business logic unnecessarily.

5. AI Agent Development Principles

Build the agent incrementally.

Prioritize:

* Clear agent architecture
* LangGraph orchestration
* Tool calling
* State management
* Persistence
* Django API integration
* Human-in-the-loop approval
* Error handling and retries
* Idempotency
* Logging and observability
* Agent evaluation

Do not introduce multi-agent architecture unless there is a clear technical justification.

Do not introduce RAG unless the actual requirements justify it.

6. Working Method

Before implementing a feature:

1. Inspect the relevant existing code.
2. Explain the proposed architecture.
3. Identify files that need modification.
4. Explain potential risks.
5. Propose a small implementation plan.

Implement only the approved scope.

After implementation:

1. Explain what was implemented.
2. List modified and created files.
3. Run relevant tests.
4. Report test results.
5. Explain any remaining limitations.

7. Learning Requirements

The developer is learning advanced AI agent engineering.

Explain important concepts during implementation.

Teach:

* Why an architectural decision is necessary.
* How the components communicate.
* How data flows through the system.
* How LangGraph manages execution.
* How tools interact with Django.
* How state and persistence work.
* How errors and retries are handled.

Do not simply generate code without explaining its purpose.

8. Dependency Management

* Do not install unnecessary dependencies.
* Explain why a new dependency is required.
* Obtain approval before introducing major production dependencies.
* Respect existing dependency versions.

9. Security

* Never hardcode API keys or credentials.
* Never expose sensitive information in logs.
* Use environment variables for secrets.
* Preserve existing authentication and authorization.
* Enforce permissions for agent operations.

10. Current Development Priority

The immediate priority is:

1. Understand the existing QMS application.
2. Get the backend and frontend running locally.
3. Understand existing audit workflows and APIs.
4. Design the AI agent architecture.
5. Implement the agent incrementally.
6. Integrate it with the existing QMS application.

Do not begin agent implementation before repository analysis is complete.