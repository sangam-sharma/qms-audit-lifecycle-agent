# Testing strategy

## Current QMS tests

The Django apps include tests in `Backend/audits/tests.py`, `Backend/frameworks/tests.py`, `Backend/projects/tests.py`, and `Backend/accounts/tests.py`. Existing audit tests cover lifecycle behavior, NC closure conditions, permissions, department derivation, checklist creation and project deletion constraints. Framework tests cover checklist permissions and item CRUD. Run the backend suite from `Backend/` with:

```bash
python manage.py test
```

Frontend `package.json` exposes `lint` and `build` scripts but no test script or test framework in current dependencies:

```bash
npm run lint
npm run build
```

These commands are documented for future development; they were not run for this documentation-only task.

## Planned agent test layers

1. **Pure unit tests:** lifecycle fact calculations, checklist/NC counts, DTO validation, output schema checks. Use synthetic input.
2. **Tool contract tests:** valid input, invalid IDs, out-of-scope access, missing data, malformed responses, and bounded output. No live LLM call.
3. **Graph tests:** each success and failure branch with mocked provider/model; verify model cannot mutate state or cause writes.
4. **Provider contract tests:** mock provider fixtures first. Later, Django API provider tests against controlled test API data, including 401/403/404, timeout and malformed payload.
5. **LLM evaluations:** curated synthetic audit questions with expected source facts, unsupported-claim checks, and reviewed explanation quality. Keep provider calls isolated and opt-in.
6. **End-to-end checks:** only after a user/API entry point exists; verify per-role data visibility and that no agent path changes QMS data.

## Test safety

Use Django's test database and synthetic agent fixtures. Do not run migrations or test commands against the development DB as a substitute for isolated tests. Tests must verify the backend remains authoritative, sources are attached to claims, and failures do not become fabricated empty records. Do not add or run tests unless the implementation task asks for verification.

Related: [roadmap](implementation-roadmap.md) · [permissions](../integration/authentication-and-permissions.md)
