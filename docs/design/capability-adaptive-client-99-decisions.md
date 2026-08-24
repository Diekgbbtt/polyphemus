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

**Operator-ratified increment-2 refinement (2026-08-21, corrects the session-seam construction):** Q1 the probe applies to UNKNOWN models ONLY - a known profile (a gateway record / models.dev sync entry) NEVER probes. Q2 the session seam shares the one-shot `_PROBE_CACHE` and makes NO extra LLM call at construction - the failure risk it accepts is documented AT GENERATION TIME: a cold-start session holding the unvalidated semantic default `json_schema` (no prior one-shot probe primed the cache) emits its langfuse span/log with provenance marked `semantic-default-unvalidated`, so a degraded negotiation is observable, not silent. Q3 the cache key stays per (provider, model, schema-class) as implemented (`module.qualname` for class schemas, repr-truncated for dict schemas). Q4 there is ONE shared `_PROBE_CACHE` for both seams; an all-miss probe caches the `None` sentinel; callers fail open to the json_schema semantic default - `session.py` never writes a bare `json_schema` into the cache, only `probe_with_invoker` writes entries (winner method or None). Q5 the cold-start probe pays at most 1-3 LLM calls at one-shot construction, each validated, each with a `capability-probe` langfuse span and provenance log, off the #73 axis.

## A3 - `steering.resolve_model` is zombie code: scope it OUT of #99, retire it in a separate cleanup

The audit confirmed: `resolve_model` (`steering.py:59`) has exactly ONE caller - the legacy sync `decide_routing` rollback seam (`orchestrator_agent.py:110`), which `pipeline.py:339-341` only uses when the actor path is NOT injected (superseded OUTLIER-3). The production `ReconOrchestratorActor` passes `ToolStrategy(RoutingDecision)` directly (`orchestrator_agent.py:209`) and routes through the session seam.

**Decision**: #99 does NOT build the selector for `resolve_model`. The hardcoded `method="function_calling"` at `orchestrator_agent.py:110-112` is left untouched (it is not the production path), and `resolve_model` + the sync `decide_routing` seam are **retired as dead code in a separate follow-up ticket** (A3 ticket, opened alongside this ADR). This keeps #99 scoped to the real P1 seams (`invoke_role`, the session seam) exactly as D4's additive-blast-radius discipline expects.

## A5 - Thinking-effort adaptation: a SECOND capability dial, the SAME component-profile pattern (increment-3)

The declared `thinking` baseline per role (`Role.thinking`, `providers.py`) is translated to the OpenAI `reasoning_effort` param UNCONDITIONALLY when non-`off` (`build_chat_model`, `providers.py:490-491`) - it is never checked against what the provider/model actually offers. Grilled 2026-08-22; the concern is REAL and the heterogeneous server behavior is verified:

**Server-side failure handling is NOT uniform** (research-cited): OpenAI/Anthropic REJECT with `400 invalid_request_error` and specific error semantics (`unsupported_value`/`unsupported_parameter`, dot-notation params like `reasoning.effort`) - never clamp; OpenRouter CLAMPS to nearest supported effort; DeepSeek first-party NORMALIZES (`medium|high|xhigh -> high`, 200 with changed behavior); vLLM/NVIDIA silently IGNORE (unknown top-level fields warn-logged server-side, some parsers silently run full thinking regardless). There is no reliable server-side fallback - the same model id exposes DIFFERENT literal level lists per provider in models.dev (e.g. `deepseek-v4-flash`: `[low,high,max]` first-party vs `[high,max]` on a relay), so a declared `medium` can 400, clamp, normalize, or silently vanish depending on the host. **Client-side adaptation is required**, not optional.

**Gateway transport finding (verified in litellm 1.96.0 source + this repo's config):** the gateway already sets `drop_params: true` (`gateway/litellm_config.yaml:67`) because the openai-compatible upstream wire has no `reasoning_effort` param and litellm rejected it with `UnsupportedParamsError` (400, verified live 2026-08-18). With `drop_params: true`, litellm SILENTLY DROPS `reasoning_effort` before routing for generic `openai/` deployments (the openai provider class's supported-params list excludes it), and an ABSENT effort is never synthesized by litellm - the provider's own default applies. So today, through this gateway, the declared effort hint reaches NO openai-compatible upstream: it is stripped, and reasoning runs at the provider default (deepseek default effort `high`). The operator's point-3 assumption ("empty already done automatically by the gateway") is CONFIRMED with precision: `drop_params: true` maps empty/unsupported to "silently absent", i.e. provider default - no 400, no intervention. The capability-adaptive workstream must therefore also ensure an ADAPTED level is actually FORWARDED (a transport concern the increment verifies, not assume `drop_params` silently kills the dial - see the transport consequence below).

**Ratified decision - the SAME pattern as method negotiation, applied consistently as a second dial:**

1. **Fallback policy covering ALL levels** (`off`..`xhigh`): a pure selector `negotiate_thinking(declared_level, profile) -> (form, value, provenance)` (operator-ratified signature 2026-08-22), mirroring `negotiate_method`. The 3-tuple codomain keeps the FORM (`effort` / `budget` / `toggle` / `omit`) distinct from the VALUE the seam emits (an effort level string, a canonical budget int, the toggle-on marker, or nothing) - exact match when the level is offered; otherwise the policy picks the best offered level (see fallback matrix below); `omit` when the model cannot express the level (or thinking is not controllable) - `omit` is a first-class output, mirroring the `off`/absent semantics. Never parses vendor error strings.
2. **Offered levels from models.dev**: the per-provider `reasoning_options` array is the catalog surface - `[{"type":"toggle"}]`, `[{"type":"effort","values":[...]}]` (values may include `null`/`none`/`minimal`/`low`/`medium`/`high`/`xhigh`/`max`/`default`), `[{"type":"budget_tokens",min?,max?}]`, combinations, or `[]` (always-on, no caller control). Provider-scoped and already base_model-resolved; read verbatim next to the existing `resolved.get("reasoning")`.
3. **A thinking profile within the layer**: the capability record/profile carries the new surface (`reasoning_control`, `reasoning_efforts`, `thinking_budget_bounds`), authored by the sync, provenance-gated exactly like the existing fields (D5 Rule 1: absent = unknown). The client configures the request client-side from the profile, resolve-and-hold (D6), off the #73 axis (D7), observed with a langfuse span/log (D11).

**Ratified kind-semantics** (operator, 2026-08-22):

- **`toggle` only** (no effort values): non-`off` declared -> emit the thinking-ON wire form (`reasoning_effort` set, or the provider-native toggle); `off` declared -> OMIT. The toggle is "turned on when reasoning is requested".
- **`budget_tokens`**: the mapping matrix ALSO carries a per-level token budget (coherent canonical values, de facto standard): the capability profile pairs each level with its budget, and the adaptor maps the selected level to `budget_tokens`, clamped to the model's declared `min`/`max` when present.
- **`effort` values incl. `null`/`none`**: `null`/`none` in the offered list IS the "off" slot - a declared `off` maps to that value (or OMIT); a non-`off` declared never picks it. Empty effort list (`[]` = always-on, no caller control) -> OMIT for non-`off`, nothing to send.
- **empty/absent request**: verified handled at the gateway (point 3 above) - empty = provider default, no 400.

**Canonical budget-token values (operator-ratified 2026-08-22):** `minimal=1024, low=2048, medium=4096, high=16384, xhigh=32768, max=40000`. `THINKING_BUDGET` is the fixed canonical map in the substrate; a model's own `min`/`max` clamps it (hard floor 1024, batch-only above 32k where the model declares that).

**Fallback matrix (operator-ratified 2026-08-22 - NEAREST-AT-LEAST-AS-MUCH):** when the exact declared level is NOT offered, pick the LOWEST offered level that is at least as much thinking as declared (declared `medium`, offered `[high, max]` -> `high`). Reasoning only ever stays at or above what the operator declared - never silently downgraded. `off` declared -> only `OMIT` or the literal `none`/`null` slot; unknown profile (no authored surface) -> keep the declared baseline unchanged and logged (fail-open D7 - never drop reasoning the operator asked for).

**Transport outcome (operator-ratified 2026-08-22 - GATEWAY WHITELIST):** the increment MUST ALSO configure the gateway forwarding so the adapted level reaches the wire: `litellm_settings.allowed_openai_params: ["reasoning_effort"]` (litellm 1.96.0's force-forward for a dropped key; `passthrough_unknown_openai_params` does not exist in this version), applied to the reasoning-capable deployments the sync registers. The adapted level reaching the upstream's wire is ASSERTED (integration-level test through the gateway surface), never assumed - `drop_params: true` stays the safety net for genuinely unknown params, `allowed_openai_params` overrides it for `reasoning_effort` specifically.

**Where it lands:** `build_chat_model` is the SINGLE construction seam (both the one-shot `invoke_role` and the session path reach it via `chat_model_for`/`thinking_for`), so the adaptor resolves ONCE per (provider, model) alongside the capability profile and feeds the `extra["reasoning_effort"]` (or budget/toggle form) the client sends. The reasoning-replay orthogonality (A1 corrigendum) is preserved: method selection and thinking level remain two independent dials, both solved by the same component-profile pattern.

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