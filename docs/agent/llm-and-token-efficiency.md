# LLM and token efficiency

## Version 1 boundary

LLM integration is planned, not implemented. The model explains validated deterministic facts; Python and Django remain responsible for business logic, source data and authorization. There is no RAG in Version 1 and no model-selected write action.

## QMS example

Given deterministic facts that an audit is `ASSIGNED`, the schedule is `SCHEDULED`, and the individual confirmation is missing, Python identifies the missing confirmation. The model can explain that the start action is not yet available. It must not fabricate confirmation dates or say it recorded one.

## Minimize tokens and exposure

- Fetch only data needed for the requested analysis; do not send the full audit list or user directory.
- Compute checklist/NC counts in Python and send compact facts rather than every record when item-level detail is unnecessary.
- Include free text only if needed to explain a specific finding; redact or pseudonymize under a policy that is still to be decided.
- Bound input text length, number of checklist items/NCs, model output tokens and request time.
- Use concise prompts and a fixed output schema; avoid repeated system/domain text in each call where provider supports reusable configuration.
- Do not include tokens, credentials, unrelated departments, or other audits.
- Record usage metadata (model, token counts, request ID) only under an approved logging/retention policy.

## Reliability controls

Treat LLM output as untrusted. Validate response shape and output length; ground claims in supplied facts and source references. Do not allow user-authored remarks to override instructions. Define a bounded timeout/retry policy and an approved deterministic-only fallback. Provider, retention, region, prompt logging and fallback decisions remain open in [open questions](../decisions/open-questions.md).

Related: [security](../architecture/security.md) · [workflow](langgraph-workflow.md) · [data provider](data-provider.md)
