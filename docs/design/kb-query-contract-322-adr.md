# ADR: #322 - single-source the KB-query args contract on `QuerySpecV1`

*Status: implemented in this change. Profile: narrow/local (schema drift), no new spec.*

## Context

The hunter's `kb_query` tool carried a local args model, `KbQuerySpec`, described in its own docstring as a "LOCAL minimal mirror" of the lightrag branch's `QuerySpecV1`.
The mirror predates the LightRAG integration: it was written when the real tool was config-gated by `HUNTING_LIGHTRAG_TOOL`.
As of #197 the gate is removed and the real `query_lightrag` tool is always attempted, but the mirror stayed and drifted.
It never gained `schema_version` or `expected_no_hypothesis`, and it set `extra="forbid"`.

The shared usage skill `skills/lightrag-query/SKILL.md` is bound to the hunter, the pod runner, and the pod triager, and it documents the real `QuerySpecV1` fields - including `expected_no_hypothesis`.
The pod wrapper and the real tool both bind `QuerySpecV1`; only the hunter bound the stale mirror.
So the model was taught one contract and handed another.

The observed failure (run `09c0f4c8`, 2026-10-04T19:38:12Z and 20:32:54Z): the model passed fields the skill documents, `KbQuerySpec` rejected them as extra inputs, and every hunter `kb_query` degraded to the deterministic `tool_failed` fallback.
The fallback removed the hunter's methodology grounding on every call.

## Decision

Retire the local args mirror and single-source the KB-query contract on the real `QuerySpecV1`.

- The hunter's `KbQueryTool.args_schema` is `lightrag.query_spec.QuerySpecV1` - the same contract the pod wrapper and the real `query_lightrag` tool bind.
- The local `KbQuerySpec`, `HunterRetrievalConfig`, and `HunterEvidenceRef` models are deleted.
- Only the response keeps a tolerant local envelope, `KbAnswerBundle`, which accepts the injected seam's dict and the real tool's `AnswerBundleV1` JSON alike.
- The canonical description `QUERY_LIGHTRAG_DESCRIPTION` now names `QuerySpecV1` and appends its field list, read from `QuerySpecV1.model_fields` so the description cannot drift from the schema.
- The usage skill `skills/lightrag-query/SKILL.md` names only real `QuerySpecV1` fields, drops the stale `supposed_payload_vectors` mapping (removed from `HuntConfig` by #202), and states that the config's vulnerability class and fault class are not top-level query fields.
- A regression test (`tests/lightrag/test_kb_query_contract.py`) pins the agreement: the hunter schema is `QuerySpecV1`, the tool validates `expected_no_hypothesis`, the description cites every field, and the skill documents only real fields.

This keeps the `extra="forbid"` discipline for the hunter's own store/exec schemas, but not for the KB args: the KB args contract is the lightrag pipeline's cross-seam contract (`QuerySpecV1`, `extra="ignore"`), shared by the hunter, the pod, and the real tool.
A second, stricter schema on one seam is exactly the drift this ADR removes.

## Consequences

- The hunter's `kb_query` validates the documented fields and returns a real KB bundle; the `tool_failed` degradation is gone.
- The schema the model is handed, the description, and the usage skill cite one contract and cannot disagree.
- A field the model invents (for example the config's `vulnerability_class`) is ignored by `QuerySpecV1` rather than failing the call; the skill steers the model to fold it into `concern`.
- `KbQuerySpec`, `HunterRetrievalConfig`, and `HunterEvidenceRef` are removed from `hunter_tools.__all__`; no production or test code referenced them.
- The regression test fails on any future re-introduction of a divergent mirror or a stale skill field.
