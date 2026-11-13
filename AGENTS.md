# Project Instructions

## Project objective

Build an autonomous AI audit agent that integrates with the existing QMS Internal Audit & Compliance Management System.

## Existing application stack

- **Backend:** Django and Django REST Framework.
- **Frontend:** React and Vite.
- **Database:** The existing SQLite development database.

## Planned AI technologies

- Python.
- LangGraph for agent workflows.
- LangChain where it is appropriate.
- LLM integrations.
- Retrieval-augmented generation (RAG) where justified by the use case.

Choose AI technologies to fit the existing application and specific requirements; do not add them without a clear integration need.

## Development rules

- Never rebuild or replace the existing QMS application.
- Never delete existing code or databases.
- Understand existing implementations before modifying them.
- Reuse existing APIs and business logic wherever possible.
- Never push to GitHub.
- Do not initialize a new Git repository without the user's permission.
- Work exclusively within this local workspace.
- Do not install dependencies unless the user asks.

## Teaching and implementation

- Explain architectural decisions before making substantial design or implementation changes.
- Teach relevant concepts while implementing.
- Explain code flow and how components interact.
- Work incrementally, keeping each change understandable and reviewable.
- Run relevant tests after implementation and explain what they cover and their results.
- Never produce a large implementation without first explaining its design.

## Development priority

Proceed in this order:

1. Analyze the existing application.
2. Understand its audit lifecycle.
3. Identify integration points in the existing system.
4. Design the AI agent architecture around those findings.
5. Implement the agent incrementally, reusing the existing application wherever possible.
