# ADR: checkpoint serde allow-list for checkpointed pydantic entities

## Status

Accepted (2026-10-12).

## Context

The v2 comfyui eval logged, repeatedly:

```
WARNING langgraph.checkpoint.serde.jsonplus: Blocked deserialization of
polymerhus.analysis.reasoning_workflow.AnalysisTurn - not in allowed_msgpack_modules
```

`AnalysisTurn` is the ONE structured envelope every analysis proposer turn binds (`analysis/reasoning_workflow.py`), a pydantic model subclassing `L1DeltaBatch`.
The reasoning workflow carries it in the checkpoint state's `turns` map, so the checkpointer serialises it.
LangGraph's `JsonPlusSerializer` serialises an unknown type as a msgpack ext-type.
The app runs with `LANGGRAPH_STRICT_MSGPACK=true`, so the serializer allows only its own `SAFE_MSGPACK_TYPES` plus any `allowed_msgpack_modules`, and it BLOCKS an unlisted type at load (`msgpack_blocked`).
A blocked load silently loses the value on a resumed turn.

Production avoids this only because it leaves `LANGGRAPH_STRICT_MSGPACK` unset (permissive).
The eval deployment inherits `LANGGRAPH_STRICT_MSGPACK=true` from `.env.example`.

The app never constructed its serde explicitly: it used the langgraph default, which has no place to name a consumer context's entity.

## Decision

Add ONE serde construction point, `app/llm/checkpoints.py::checkpoint_serde()`, returning a `JsonPlusSerializer` whose `allowed_msgpack_modules` is `_ALLOWED_MSGPACK_MODULES`.
That constant lists the checkpointed pydantic entities as `(module, name)` tuples, currently `("polymerhus.analysis.reasoning_workflow", "AnalysisTurn")`.

The dotted `(module, name)` form is deliberate: `app` must never import the analysis context, so the allow-list names the type without importing its owner.

Every checkpointer construction point uses the ONE serde: the module facade (`_module_scoped_saver`), the per-thread bounded in-memory saver (`_bounded_saver`), the version scratch saver (`_version_saver`), and the pooled PG flush target (`PostgresSaver`).
Strict msgpack stays ON, so the safe default is preserved.

## Alternatives rejected

- **Set `LANGGRAPH_STRICT_MSGPACK=false` in the eval instance `.env`.**
  Rejected: it disables the safe default for every type, not just the one entity, and it leaves production and the eval diverging on a security-relevant setting.
- **Have `app` import the analysis type.**
  Rejected: analysis depends on app, never the reverse; a direct import inverts the dependency direction.
- **Convert `AnalysisTurn` to a plain dict before checkpointing.**
  Rejected: the structured envelope is the turn's contract, and dict-ing it in the state would lose the typed re-hydration the reasoning workflow depends on.

## Consequences

- A resumed analysis reasoning turn re-hydrates `AnalysisTurn` under strict msgpack.
- A future checkpointed pydantic entity is added to `_ALLOWED_MSGPACK_MODULES` in one place.
- The setting stays strict in every deployment.
