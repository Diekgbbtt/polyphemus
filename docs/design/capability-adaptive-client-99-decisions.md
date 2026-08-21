# Capability-adaptive LLM client (#99) - Architectural Decision Records

Decisions taken (operator-authoritative, grilled 2026-08-20) for ticket #99: the capability-adaptive LLM client (structured-output / tool-calling negotiation across providers).
Companion to `docs/design/llm-gateway-100-decisions.md` (the substrate ADR D1-D11 this ticket extends) and the `dynamic-llm-gateway-design-spec.md`.
These records are **authoritative over** any earlier grilling shorthand and the implementer prompt where they clash - the promoter is corrected in the same change.
Where a record and the live code disagree, the code wins and the record is stale.

The grilling ran against the #100 substrate and the live agent roster. Four shaping points were resolved; each decision below is the ratified answer with rationale and the load-bearing nuance.

## A1 - The structured-output method negotiation: semantic-first, profile-corrected (increment-1)

**The primary axis is the call site's semantics, not the provider table:** a call either binds tools (a tool loop: the langgraph session seam, `bind_tools`/crawl) or it is a pure one-shot extraction with NO tools bound (`invoke_role`). `function_calling` is the better method for tool loops; `structured_output` (json_schema) is the better method for fixed-shape extraction.

Two ratified rungs, chosen at call-construction:

1. **No tools bound** (one-shot `invoke_role` and any pure structured call): use **structured output** `response_format=json_schema` with `strict=False` - the SOTA method for fixed-shape extraction (OpenAI/gemini compatible; accepts open-dict fields under `strict=False`; thinking models accept `response_format`). **This flips the current hardcoded `method="function_calling"` default at `roles.py:41`** (and the conceptually-separated legacy seam, see A3).
2. **Tools bound** (the langgraph `ToolStrategy` / `bind_tools` session seam, crawl): `function_calling`/native tool-choice is the ONLY tool-loop option - there is no silent fallback to a non-tool method inside a tool loop. The T5 gate (`crawl_agentic.py:158`) already refuses crawl on unsupported/unknown and is NOT rebuilt.

The profile then corrects the rung in a **fixed degrade chain** when the profile shows the chosen rung unsupported, each rung validating the parsed Pydantic result:
`json_schema (structured output)` -> `function_calling` -> `json_mode`.

- For a **no-tools** call on a profile that lacks structured-output support but has tool-calling: degrade to `function_calling` (forced tool returns dict; matches today's proven behavior for open-dict fields, `pod.py:436-441`).
- For a profile with neither: `json_mode` + mandatory result validation (the #44-absorbed path; only for profile-authorized models, still off the #73 axis).
- **Unknown profile degrades to `function_calling`** for the sessions/crawl (proven mainline) and **`structured_output` for the one-shot seam as the semantic default** - capability never gates starting a session (D7 fail-open; D6 resolve-and-hold).

**Reasoning is orthogonal by operator corrigendum:** `reasoning_effort` is a separate dial and NEVER a factor in method selection. Thinking models call tools fine; the ticket's deepseek 400 is a zen/vLLM provider quirk, not a general property of "reasoning models". The T3 `reasoning_in_response`/`reasoning_field` surface stays exactly as D11 authored it.

**Where the decision lands.** Exactly two seams:
- the one-shot path: `_structured_response_format` / `invoke_role` (`roles.py`);
- the session path: the seam's `response_format`/`ToolStrategy` wrapper (`session.py`), resolved at session construction per D6.

The negotiation is a **pure function**: `(capability_profile, no_tools_bound: bool, schema_shape) -> method`. It is fully unit-testable with the LLM mock - no live model, no live gateway (TDD tier, `test_llm_capability.py` pattern).

**What this is NOT**: this is NOT a per-provider strategy registry, NOT a build-time banner, NOT the #73 retry axis. The degrade is at construction time, single-shot, resolve-and-hold (D6) - never a runtime retry loop, never nested inside the timeout wrapper. `extra_body`-based request shaping (the vLLM guided-json path) is deferred: use the negotiation rather than a raw SDK escape hatch, and only open a `guided_json` escape hatch behind a test that proves the gateway surface needs it (grill element; parked, not built speculative).

## A2 - Probe-on-miss: validate-in-order at session construction (OFF the #73 axis)

T3 seeds known models from the sync table; `unknown` models need a probe. Ratified protocol:

- **Try-in-order + validate the parsed result** (`json_schema` -> `function_calling` -> `json_mode` as ordered in A1), and validate by **Pydantic parse**, never by parsing vendor error strings (no machine-readable unsupported-capability code in the OpenAI standard).
- **Cadence**: once, at session construction (the degenerate one-call session for one-shot). Never repeated mid-session - D6 resolve-and-hold, keep capability resolution off the #73 retry axis (#32's multiplied-retry defect).
- **Cost bounds**: cold-start only, no retry budget spent on the #73 axis; a probe failure degrades per the chain and the session still starts (fail-open D7).
- **Observability**: each resolution gets a langfuse span/trace (D11 langfuse discipline); the probe's chosen method and its provenance are logged.

## A3 - `steering.resolve_model` is zombie code: scope it OUT of #99, retire it in a separate cleanup

The audit confirmed: `resolve_model` (`steering.py:59`) has exactly ONE caller - the legacy sync `decide_routing` rollback seam (`orchestrator_agent.py:110`), which `pipeline.py:339-341` only uses when the actor path is NOT injected (superseded OUTLIER-3). The production `ReconOrchestratorActor` passes `ToolStrategy(RoutingDecision)` directly (`orchestrator_agent.py:209`) and routes through the session seam.

**Decision**: #99 does NOT build the selector for `resolve_model`. The hardcoded `method="function_calling"` at `orchestrator_agent.py:110-112` is left untouched (it is not the production path), and `resolve_model` + the sync `decide_routing` seam are **retired as dead code in a separate follow-up ticket** (A3 ticket, opened alongside this ADR). This keeps #99 scoped to the real P1 seams (`invoke_role`, the session seam) exactly as D4's additive-blast-radius discipline expects.

## A4 - The unpinned-SDK risk: pin inside #99, not a separate ticket

`langchain-openai`/`langgraph` are under-pinned in `requirements-app.txt` (floor-bounds only). The residual risk after the Dockerfile fix (2026-08-20: container builds from `python:3.11-slim` with `requirements-app.txt` as the canonical manifest; the untracked-base-image concern retired):

- a floor-bound allows a **silent resolution jump** (e.g. `langchain-openai` 1.3.2 -> 1.5.x) that can change `with_structured_output` semantics (already changed across 0.3.12/0.3.21) under a passing suite;
- the T6 `ReasoningPreservingChatOpenAI` (`providers.py:352`) **pins langchain-openai 1.3.x internals** (`_create_chat_result`, `_get_request_payload`; the docstring says so), so the reasoning-replay and the method negotiation both live on that exact seam.

**Decision**: pin exact versions **inside the #99 branch** (`langchain-openai==1.3.2`, `langgraph==1.2.x` per the resolved lock) in `requirements-app.txt`, landed with the increment that exercises `with_structured_output` so the T6 pin-behavior tests ship against the pinned resolution. This is deliberate over the "separate ticket" option because the pin is load-bearing for #99's own negotiation tests, not a general hygiene item.

---

## Spec corrections (land in the same change as the code)

- The implementer prompt's item 1 candidate ("universal `json_schema, strict=False`") is **superseded** by A1's semantic-first + profile-corrected negotiation, which keeps `function_calling` as the proven mainline default for the session/tool rung.
- The implementer prompt's item 4 scope (`steering.resolve_model`) is **superseded** by A3: `resolve_model` is out of #99; the last hardcoded `method="function_calling"` stays as-is and the seam is retired separately.
- The implementer prompt's item 5 ("file unpinned-SDK risk as its own small ticket") is **superseded** by A4: pin inside #99.
- **`schema_shape` encoding (T1, ratified-rung clarification):** the selector's third input is `Literal["closed", "open"]` - whether the target schema carries free-form `dict` fields (`open`, e.g. `Observation.anchor`) or is fully typed (`closed`). Under A1 rung 1, `strict=False` is UNCONDITIONAL and accepts open dict fields, so BOTH shapes resolve to the IDENTICAL ratified rung table - the shape is a total-contract input of `negotiate_method` (the seam records the call's schema class) and must NEVER reopen a method swap inside a tool loop. Its construction consequence is locked by the pin tests: on the pinned langchain-openai 1.3.2, `strict=False` reaches the wire ONLY for a DICT schema - the pydantic-CLASS path silently defaults to `"strict": true` (the exact 400 the negotiation exists to avoid), so the construction seam passes `model_json_schema()` dicts for the json_schema rung.
- **The parse-validation companion (T1 contract split):** the negotiation contract's "each rung validates the parsed Pydantic result" lands as a companion pure predicate `result_validates(parsed, schema)` (`app/llm/negotiation.py`) alongside `DEGRADE_CHAIN` + `next_rung`; `negotiate_method` picks the STARTING rung, the caller validates the parsed result per rung and descends `next_rung` on a miss - parsing the result, never catching vendor error strings (A2).
- **Session-seam `json_mode` incapacity (T3, operator-confirmed 2026-08-21):** on the SESSION path (`create_agent`), the response_format vocabulary is `ToolStrategy | ProviderStrategy | AutoStrategy` ONLY - there is no json_mode strategy. Empirically verified on the pinned 1.3.2: a model pre-bound with `with_structured_output(method="json_mode")` passed to `create_agent` with `response_format=None` raises `NotImplementedError` when the graph coerces the parsed pydantic instance back into a message, and `ProviderStrategy` hardcodes `json_schema` (it cannot emit the `{"type":"json_object"}` json_mode wire form). So on the session seam the ADR A1 degrade chain's `json_mode` rung is NOT expressible; a neither-capability (no structured-output, no tool-calling) no-tools session turn resolves its json_mode rung to `ToolStrategy` (the function_calling-equivalent) - the current safe default that keeps a structured session turn working. `json_mode` remains a ONE-SHOT-seam-only rung. This is a documented limitation, not a silent deviation.