# Spec - #99 capability-adaptive LLM client

Operator-rationalised spec for ticket #99 ("LLM client is not capability-adaptive across providers").
Grilled 2026-08-20; the four ratified answers live in `docs/design/capability-adaptive-client-99-decisions.md` (ADR A1-A4), which is authoritative where this spec and the ADR differ.
Absorbs #44. The #73 latency/timeout axis and the #32 multiplied-retry defect are non-negotiables this spec is built around, never entangled.

## Problem Statement

The LLM client hard-codes ONE capability preset: `method="function_calling"` on every one-shot structured call and native `bind_tools`/`ToolStrategy` on every tool loop.
That preset is correct for mainline OpenAI but fails at the provider boundary for reasoning models (deepseek 400 "Thinking mode does not support this tool_choice"), vLLM without `--tool-call-parser` (Qwen/Apertus 400s, #44), and any provider whose structured-output or tool-calling surface differs - every swap fails during bootstrap's first structured call, before recon/analysis can run.
`json_mode` fails silently (HTTP 200, wrong shape) when it is used. There is no single globally-correct method: the right choice depends on the provider/model AND on whether the schema is closed or carries open `dict` fields (e.g. `Observation.anchor`) AND on whether the call is a tool loop or a pure extraction.

## Solution

Make the client capability-adaptive: choose the structured-output / tool-calling method at call-construction time per (provider, model, call shape), seeded from the gateway's synced capability records (the #100 substrate), probe-on-miss for unknown models, and hold the choice for the session - never resolved mid-turn, never multiplied with the #73 retry.
The choice is **semantic-first**: a call that binds tools (session/crawl tool loops) uses native tool calling; a pure one-shot extraction with no tools uses structured output (`json_schema`, `strict=False`).
The capability profile then corrects within a fixed degrade chain (`json_schema` -> `function_calling` -> `json_mode`), each rung validating the parsed Pydantic result; `reasoning_effort` is orthogonal to method and never a factor.

## User Stories

1. As an operator, I want to swap a role's model to a reasoning/"thinking" model (e.g. deepseek) and have bootstrap's first structured extract succeed, so that pipeline verification no longer stops at the LLM boundary.
2. As an operator, I want to swap to a vLLM model without `--tool-call-parser` (e.g. Qwen3.6-27B, Apertus-70B on SwissAI) and have the structured calls negotiate `json_schema`/`json_mode` instead of 400ing, so #44's defect is absorbed and resolved.
3. As an operator, I want the already-working mainline path (OpenAI/OpenRouter, GLM-4.7-Flash) to keep its current validated behavior on the upgrade, so the fix never regresses the proven provider.
4. As an operator, I want a model not present in the gateway's registry to still drive a session via a semantic-default method rather than crash, so unknown and brand-new models are not a hard blocker.
5. As an operator, I want the resolution to happen once at session construction and be held, so multi-turn P2 sessions do not pay a capability probe per turn.
6. As an operator, I want the correct method to survive the langchain/openai conversion boundary, so the choice proven in the negotiation is the choice that reaches the wire (and comes back parseable).
7. As an operator, I want capability resolution kept strictly off the #73 escalating-timeout retry axis, so the #32 multiplied-retry defect is never re-introduced.
8. As an operator, I want the parsed result validated - not just the exception path - so `json_mode`'s silent wrong-shape failure is caught and renegotiated rather than accepted.
9. As an operator, I want the chosen method and its provenance observable in langfuse/logs, so a degraded negotiation is visible, not silent.
10. As an operator, I want the open `dict` fields our schemas carry (e.g. `Observation.anchor`) to survive whichever negotiated method is chosen, so the negotiation does not trade one provider's failure for an open-schema 400 on another.
11. As an operator, I want the crawl tool-loop path unchanged: unsupported/unknown tool-calling still refuses to an empty manifest (T5 gate), since a 30-turn native-tool loop has no method-swap fallback.
12. As an operator, I want the unpinned `langchain-openai`/`langgraph` floors pinned to exact versions inside this work, so the `with_structured_output` semantics the negotiation relies on cannot silently drift.

## Implementation Decisions

### Seam (one seam, per the least-seams ideal)

The negotiation lands at ONE construction seam: the place that builds the structured-output wrapper. Concretely the pure-function selector is co-located with `with_structured_output`/`ToolStrategy` construction inside the llm layer (`app/llm`), reached from the two existing call shapes:
- the one-shot path via `invoke_role` (the `schema is not None` branch);
- the session path via the `response_format`/`ToolStrategy` construction (`stateful_turn` and the session turn builders).

The selector is a **pure function**: `(capability_profile, no_tools_bound: bool, schema_shape) -> method`, unit-testable with LLM and gateway mocked - no live model, no live gateway in the unit tier.

### Method negotiation (ADR A1, ratified)

- **No tools bound** (one-shot extraction): default to `structured_output` `json_schema`, `strict=False`. `strict=False` is the load-bearing bit: it accepts open `dict` fields (the `Observation.anchor` case that hard `json_schema` 400s on) and uses `response_format` rather than forced `tool_choice`, so thinking models accept it.
- **Tools bound** (session/crawl tool loop): `function_calling`/native tool choice is the ONLY option - no silent method-swap inside a tool loop. The T5 gate (`crawl_agentic.py`) already refuses crawl on unsupported/unknown and stays.
- **Profile-corrected degrade chain** (each rung validates the parsed Pydantic result): `json_schema` -> `function_calling` -> `json_mode`.
  - On a profile with structured output but unknown/absent tool calling and no tools bound: `json_schema`.
  - On a profile with tool calling but unknown/absent structured output and no tools bound: degrade to `function_calling` (forced tool returns a dict; matches today's proven open-dict behavior).
  - On a profile with neither: `json_mode` plus mandatory result validation (the #44-absorbed path), only when a recognized/authorized model, still off the #73 axis.
  - **Unknown profile** (no gateway, no record, no tag): semantic default - `json_schema` for the no-tool one-shot seam, `function_calling` for the session/tool rung (proven mainline). Capability never gates session start (D7 fail-open).
- **Reasoning is orthogonal**: `reasoning_effort` is a separate dial and NEVER a factor in method selection. Thinking models call tools fine; the ticket's deepseek 400 is a provider quirk.

### Capability surface (extends the #100 substrate)

- The `CapabilityProfile` reader gains `supports_structured_output: bool | None`, provenance-gated exactly like `supports_tool_calling` (D5 Rule 1: absent tag or absent field = `None`/unknown). The sync (`sync_mapping.py`) ALREADY authors `supports_structured_output` on the record and into `model_info`; only the reader surface + typed wire read are new.
- The reader's resolve-and-hold (process-lifetime cache, D6/D7) is unchanged; resolution happens ONCE at construction and is held. Nothing re-queries mid-session.

### Probe-on-miss (ADR A2, increment-2)

- Models unknown to the registry get a probe: **try-in-order + validate the parsed result**, in the A1 chain order, never parsing vendor error strings (no machine-readable unsupported-capability code exists in the OpenAI standard).
- Cadence: once, at session construction (the degenerate one-call session for one-shot). Never repeated mid-session. Off the #73 axis: cold-start only, no retry budget spent on it; probe failure degrades per the chain and the session still starts.
- Observability: each resolution emits a langfuse span/trace; the chosen method and provenance are logged.

### `extra_body` / raw-SDK escape hatch (grill element)

The `extra_body` open question (does `extra_body` reach `create()` through `with_structured_output` kwargs for the vLLM `guided_json` path?) is NOT built speculatively. The negotiation (json_schema/flattened) is the answer; a `guided_json` raw escape hatch only opens BEHIND a test that proves the gateway surface needs it. Parked.

### SDK pinning (ADR A4, lands inside #99)

Pin exact versions in `requirements-app.txt` (`langchain-openai==1.3.2`, `langgraph` at the resolved lock) landed WITH the increment that exercises `with_structured_output`, so the T6 pin-behavior tests ship against the pinned resolution. Rationale: the `ReasoningPreservingChatOpenAI` subclass pins langchain-openai 1.3.x internals (`_create_chat_result`, `_get_request_payload`), and `with_structured_output` behavior changed across 0.3.12/0.3.21 - a floor-bound is not a pin.

### Out of scope in the seams (ADR A3)

- `steering.resolve_model` is ZOMBIE code (single caller is the superseded sync `decide_routing` rollback seam, `orchestrator_agent.py:110`; the production actor passes `ToolStrategy(RoutingDecision)` directly). It is NOT wired into the selector; the hardcoded `method="function_calling"` there is left untouched and the whole seam is retired in separate ticket #144.

## Testing Decisions

What makes a good test: it proves the negotiation is a pure function of (profile, no-tools-bound, schema-shape) AND that the chosen method survives the langchain/openai conversion boundary - the exact defect class of the ticket (the chosen capability never reaches the wire). Tests exercise external behavior (the warped method on the resulting structured-output wrapper / the invoked request payload), not the internal degrade-chain bookkeeping.

- **Unit tier** (mocked; no live model, no live gateway, no DB): the selector's method resolution across the profile/unknown matrix; the degrade chain order including the validation-triggered rung change; `CapabilityProfile.supports_structured_output` wire parsing + provenance gating; the `invoke_role` one-shot and the session `stateful_turn`/response_format construction both route through the selector. Prior art: `tests/test_llm_capability.py`, `tests/test_llm_reasoning.py::test_preserving_client_*` (real conversion-boundary tests on the pin - the pattern for proving a strategy choice survives the langchain boundary).
- **Integration tier** (contract catalogue): the seams' contract predicates - a one-shot structured call with tools absent, a session tool loop with tools bound, an unknown profile, a json_mode rung. Prior art: the gateway reasoning-passthrough wire-shape tests (`tests/test_gateway_reasoning_passthrough.py`).
- **E2E tier**: a live walkthrough that boots each known-broken model (deepseek thinking via json_schema; vLLM Qwen/Apertus via json_schema/json_mode degrade) and asserts bootstrap clears - run in-network against the stack built from `dev` per the loop constraints. Assert the mainline provider stays GREEN (no regression). Only run where live providers are available.
- **Pin-behavior test**: `with_structured_output` semantics on the pinned exact version (T6 pattern), red-on-purpose if the pin moves.

## Out of Scope

- Axis (B) latency/timeout coherence - #73's twin of this ticket; never entangled.
- Re-engineering the crawl tool-loop answer - T5's gate is the resolved strategy; do not rebuild it.
- Building strategy-fallbacks (native vs text-scaffolded tools) nothing uses yet - YAGNI.
- The `extra_body`/guided_json raw escape hatch until a test proves the gateway needs it.
- `steering.resolve_model` and the sync `decide_routing` seam - retired in #144.
- The #95 context-window compaction consumer and the #98 context-management work - this ticket only extends the capability surface they share.
- Per-provider strategy registries, hardcoded method tables, build-time banners.

## Further Notes

- The environment is SOLO (operator ruling 2026-08-12): integration is a local fast-forward of the ticket branch into `dev` and push, no PRs. Land the branch with `Closes #99`.
- Commit granularity follows the increment structure: increment-1 (method negotiation at the two seams + profile surface + pin) then increment-2 (probe-on-miss), each verifier-gated, landing in the same `feat/capability-adaptive-client-99` branch.
- Living documents: the ADR `capability-adaptive-client-99-decisions.md`, the domain-model capability-client note, and this spec are updated IN THE SAME change as the code that sharpens a term - do not defer.