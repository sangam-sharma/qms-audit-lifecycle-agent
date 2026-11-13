# State management

## Status

The state described here is a proposed, per-invocation LangGraph value. It is not implemented, not a Django model and not authoritative lifecycle state. Django remains the system of record.

## Proposed state shape

```python
class AgentRunState(TypedDict, total=False):
    request_id: str
    audit_id: int
    caller_context: CallerContext  # trusted server-side context, never model-authored
    analysis_type: Literal["overview", "checklist", "non_conformities"]
    audit_snapshot: AuditSnapshot
    deterministic_facts: list[Fact]
    missing_data: list[str]
    explanation: str
    source_refs: list[SourceRef]
    error: AgentError | None
```

Names and types are illustrative contracts to define during implementation; they do not match an existing source file.

## State rules

- Keep state scoped to one request and one audit unless a separately approved use case requires otherwise.
- Pass immutable normalized values between nodes; avoid Django ORM objects, tokens and model clients in graph state.
- Do not store secrets, passwords, raw JWTs, or unnecessary personal information in state or checkpoints.
- Preserve source IDs and field provenance for facts so explanations can be reviewed.
- Use explicit error and missing-data fields; do not encode a fetch failure as an empty checklist.
- Do not persist conversation memory or graph checkpoints in Version 1 without a retention and access decision.
- Bound free text, arrays, state size and lifetime.

## Why separate facts and prose?

If an audit has 3 pending checklist items, that count should be calculated from QMS data by deterministic code. The LLM can explain what that means, while the UI can show the underlying count and source. Mixing model prose with calculated status makes it harder to verify where an answer came from.

Related: [workflow](langgraph-workflow.md) · [provider](data-provider.md) · [security](../architecture/security.md)
