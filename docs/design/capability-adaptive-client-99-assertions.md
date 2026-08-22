# Assertions - capability-adaptive client #99
**Source:** docs/design/capability-adaptive-client-99-spec.md + decisions.md ADR A1/A5
**Seams under assertion:** `negotiate_method` / `negotiate_thinking` / `result_validates` / `resolve_method` / `probe_with_invoker` (`src/polymerhus/app/llm/negotiation.py`); `CapabilityProfile` + `resolve_capability` + `classify_reasoning_options` (`src/polymerhus/app/llm/capability.py` / `sync_mapping.py`); `build_chat_model` / `_thinking_wire_form` (`src/polymerhus/app/llm/providers.py`); `gateway/litellm_config.yaml` (`drop_params` / `allowed_openai_params`); one-shot `invoke_role` and session `response_format` / `ToolStrategy` construction seams

## Contract predicates (integration)

- **C1 - tools-bound invariant.** seam: `negotiate_method` / session `response_format` | delivery: success (only rung)
  input: `no_tools_bound=False` with any profile (all-None, structured true, neither, unknown None)
  observable: returns `function_calling` exactly; no profile field changes it; no probe cache read
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C01_tools_bound_always_function_calling`

- **C2 - no-tools unknown semantic default.** seam: `negotiate_method` vs `CapabilityProfile` | delivery: empty/unknown (D7 fail-open)
  input: `no_tools_bound=True`, profile `None` or all-None (D5 Rule 1 absent = unknown)
  observable: returns `json_schema` (one-shot semantic default); session still starts, never gates
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C02_unknown_no_tools_defaults_json_schema`

- **C3 - structured-output asserted -> json_schema.** seam: `negotiate_method` | delivery: success
  input: `no_tools_bound=True`, `supports_structured_output=True`, `schema_shape` `closed` and `open` both
  observable: returns `json_schema` for both shapes (`strict=False` unconditional, open-dict tolerant)
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C03_structured_true_is_json_schema_both_shapes`

- **C4 - no structured but tool-calling -> function_calling.** seam: `negotiate_method` | delivery: degradation (first degrade step)
  input: `no_tools_bound=True`, `supports_structured_output=False|None`, `supports_tool_calling=True`
  observable: returns `function_calling` (forced-tool dict path, open-dict proven)
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C04_no_structured_but_tools_is_function_calling`

- **C5 - neither capability -> json_mode (one-shot only).** seam: `negotiate_method` / one-shot `invoke_role` | delivery: degradation (last rung)
  input: `no_tools_bound=True`, both flags `False` (#44-absorbed)
  observable: returns `json_mode` with mandatory `result_validates` guard downstream
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C05_neither_is_json_mode_one_shot`

- **C6 - session-seam json_mode incapacity rider.** seam: session `create_agent` `response_format` (ToolStrategy|ProviderStrategy|AutoStrategy) | delivery: degradation
  input: `no_tools_bound=True`, neither capability, session path (not one-shot)
  observable: json_mode rung resolves to `ToolStrategy` (function_calling-equivalent); never emits `{"type":"json_object"}`; no NotImplementedError
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C06_session_neither_resolves_to_tool_strategy`

- **C7 - fixed degrade chain order and next_rung.** seam: `DEGRADE_CHAIN` / `next_rung` (`negotiation.py`) | delivery: success + ordering
  input: walk `json_schema` -> `function_calling` -> `json_mode` -> `None`
  observable: `DEGRADE_CHAIN == ("json_schema","function_calling","json_mode")`; `next_rung` steps in order; end `None`; unknown raises `ValueError`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C07_degrade_chain_and_next_rung_order`

- **C8 - parse-validation companion.** seam: `result_validates` (companion predicate) | delivery: success + malformed (silent wrong-shape)
  input: (a) `parsed=None` any schema, (b) dict vs Pydantic class valid/invalid, (c) dict-schema non-None
  observable: (a) False, (b) `model_validate` true/false correctly, (c) dict target True when non-None; never parses vendor error strings
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C08_result_validates_companion`

- **C9 - schema_shape total-contract input.** seam: `schema_shape_of` / `negotiate_method` (Literal["closed","open"]) | delivery: success + empty-valid
  input: pydantic class with nested `dict[str,Any]` free-form (open, e.g. `Observation.anchor`) vs fully-typed (closed) vs non-model
  observable: `schema_shape_of` returns `open` for free-form/self-referential at any depth, `closed` otherwise, `open` for non-model; both shapes map to identical rung table
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C09_schema_shape_both_map_same_rung`

- **C10 - unknown/None/absent provenance gating.** seam: `CapabilityProfile` / `resolve_capability` (D5 Rule 1) | delivery: empty/unknown
  input: gateway record absent `capability_source` tag or field absent/wrong-typed (bool/int/str)
  observable: field degrades to `None` (unknown) not `False`; `_unknown_profile` true; negotiate takes semantic default
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C10_absent_field_is_unknown_not_false`

- **C11 - thinking off maps to none-slot or omit.** seam: `negotiate_thinking` | delivery: success (off semantics)
  input: `declared="off"` with (a) offered containing `"none"`, (b) without `"none"` (toggle/budget/always-on)
  observable: (a) `("effort","none","off-maps-to-offered-none-slot")`, (b) `("omit",None,"off-omit")`; non-off never picks `"none"`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C11_off_maps_to_none_slot_or_omit`

- **C12 - thinking exact match wins.** seam: `negotiate_thinking` | delivery: success
  input: `declared in offered` e.g. `declared="medium"` with `control="effort"`, `efforts=("minimal","low","medium","high")`
  observable: returns `("effort","medium","exact-match")`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C12_thinking_exact_match`

- **C13 - fallback NEAREST-AT-LEAST-AS-MUCH.** seam: `negotiate_thinking` / `_fallback_effort` (ADR A5) | delivery: degradation (upward fallback)
  input: `declared="medium"` offered `[high,max]`; ordering `off<minimal<low<medium<high<xhigh<max`
  observable: picks lowest offered >= declared (`medium`+`[high,max]`->`high`); never downgrades; provenance `fallback-nearest-at-least-as-much`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C13_fallback_nearest_at_least_as_much`

- **C14 - fallback none-at-or-above -> omit.** seam: `negotiate_thinking` | delivery: degradation (fail-open, never downgrade)
  input: `declared="high"` offered `("low",)` or `declared="max"` offered `[low,high]`
  observable: returns `("omit",None,"fallback-none-at-or-above-declared-omit")` not the lower level
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C14_fallback_none_when_no_level_at_or_above`

- **C15 - toggle-only non-off -> toggle on, off -> omit.** seam: `negotiate_thinking` (toggle kind) | delivery: success
  input: `reasoning_control="toggle"`, offered `None`, `declared="medium"` vs `declared="off"`
  observable: non-off -> `("toggle","on","toggle-on")`; off -> `("omit",None,"off-omit")`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C15_toggle_only_semantics`

- **C16 - budget_tokens canonical map + clamp.** seam: `negotiate_thinking` / `THINKING_BUDGET` / `_budget_form` vs `thinking_budget_bounds` | delivery: success
  input: `control="budget_tokens"`, declared `medium/high/xhigh` with `bounds=(2000,10000)`
  observable: `medium=4096` stays `4096`, `high=16384` clamped to `10000`, `minimal=1024` clamped to lo; provenance `budget-canonical-clamped`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C16_budget_canonical_map_and_clamp`

- **C17 - empty/unknown thinking -> always-on omit or fail-open keep.** seam: `negotiate_thinking` / `CapabilityProfile` (A5 Rule 1) | delivery: empty/unknown
  input: `reasoning_control=None/"none"` or all A5 fields `None` (unknown) with any declared; `[]` always-on `control="none"`
  observable: always-on -> `("omit",None,"always-on-or-unknown-omit")`; unknown non-off -> `("effort",declared,"unknown-profile-declared-kept")` never drops reasoning
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C17_always_on_and_unknown_thinking_fail_open`

- **C18 - null/none off-slot canonicalization.** seam: `classify_reasoning_options` -> `CapabilityProfile.reasoning_efforts` -> `negotiate_thinking` | delivery: success
  input: models.dev `reasoning_options: [{"type":"effort","values":[null,"low","high"]}]` canonicalized to `("none","low","high")`
  observable: `declared="off"` maps to `"none"` slot; `declared="low"` exact-matches not none; non-off never selects `"none"` via rank filter
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C18_null_canonicalized_to_none_off_slot`

- **C19 - always-on [] -> control none and omit.** seam: `classify_reasoning_options` / `negotiate_thinking` | delivery: empty-valid
  input: `reasoning_options=[]` -> `("none",None,None)`; negotiate any non-off declared
  observable: `classify` yields `("none",None,None)`; `negotiate_thinking` yields `("omit",None,"always-on-or-unknown-omit")` (nothing to send)
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C19_always_on_empty_list_is_omit`

- **C20 - invalid budget bounds degrade to None.** seam: `classify_reasoning_options` / `_typed_budget_bounds` | delivery: malformed + empty-valid
  input: `budget_tokens` with missing/min=-1/max absent or `max<min` or non-int
  observable: `thinking_budget_bounds` stays `None`; clamps use `THINKING_BUDGET` alone (`minimal=1024, low=2048, medium=4096, high=16384, xhigh=32768, max=40000`)
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C20_invalid_budget_bounds_degrade_to_none`

- **C21 - cross-product orthogonal independence.** seam: `negotiate_method` x `negotiate_thinking` via `build_chat_model` | delivery: success (cross product)
  input: method rungs (`json_schema`/`function_calling`) paired with thinking levels (`off`..`max`) and forms (`effort`/`budget`/`toggle`/`omit`)
  observable: method unchanged when thinking varies; thinking unchanged when method varies (no shared state, A1 corrigendum); both resolved together
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C21_method_and_thinking_orthogonal_cross_product`

- **C22 - resolve-and-hold + probe cache hit.** seam: `resolve_method` / `_PROBE_CACHE` (per provider,model,schema-class) | delivery: duplicate/idempotent (D6 hold)
  input: unknown profile, first `probe_with_invoker` wins `json_schema`, second `resolve_method` same key without invoker
  observable: second returns winner with provenance `probe-cache-hit`; no second LLM call; key via `module.qualname` or dict repr truncated
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C22_probe_cache_hit_reused_without_probe`

- **C23 - all-miss probe caches None, next holds json_schema.** seam: `probe_with_invoker` / `_PROBE_CACHE` (Q4) / `resolve_method` | delivery: degradation (all-rung miss)
  input: unknown profile, invoker returns `None` or raises for every rung in `DEGRADE_CHAIN`
  observable: `probe_with_invoker` caches `None` and returns `None`; next `resolve_method` yields `json_schema` semantic default; only probe writes cache, session never bare-writes
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C23_all_miss_caches_none_next_is_json_schema`

- **C24 - cold-start session without probe -> unvalidated sentinel.** seam: `resolve_method` session seam (no invoker, Q2) | delivery: degradation (cold-start observable)
  input: unknown profile, `no_tools_bound=True`, `invoker=None`, cache empty for key
  observable: returns `json_schema` with provenance `semantic-default-unvalidated; no prior probe entry` and emits langfuse span/log; never writes shared cache
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C24_cold_start_session_unvalidated_sentinel`

- **C25 - gateway transport forwards adapted reasoning_effort.** seam: `gateway/litellm_config.yaml` (`drop_params: true` + `allowed_openai_params: ["reasoning_effort"]`) via `build_chat_model` | delivery: success + degradation
  input: `_thinking_wire_form` adapts to `("effort","high")` or `("omit",None)`; generic `openai/` deployment through gateway
  observable: adapted `reasoning_effort` survives to upstream wire (whitelisted); `omit` sends nothing (provider default); unknown param still stripped; wire fake asserts presence/absence per form
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C25_gateway_forwards_reasoning_effort`

- **C26 - thinking wire forms emit correct extra.** seam: `_thinking_wire_form` / `build_chat_model` (`providers.py`) vs `negotiate_thinking` form | delivery: success (wire mapping)
  input: forms `effort`/`budget`/`toggle`/`omit` with values (level str / int budget / "on" / None)
  observable: `effort`->`{"reasoning_effort": level}`, `budget`->`{"extra_body":{"thinking":{"type":"enabled","budget_tokens": int}}}`, `toggle`->`{"extra_body":{"thinking":{"type":"enabled"}}}`, `omit`->`{}`; exception fail-open keeps declared as `reasoning_effort`
  yields: `tests/integration/test_capability_adaptive_matrix.py::test_C26_thinking_wire_forms_emit_correct_extra`

## Walkthrough predicates (end-to-end) - DEFERRED

No e2e tests in this work item (integration-only). The following 6 intents are deferred to the next harness work item which will stand up live providers and the gateway.

- **E1 - DEFERRED: deepseek thinking adapts medium to high via gateway.** grounds: spec story 13 + ADR A5 fallback NEAREST-AT-LEAST-AS-MUCH
  entry: `invoke_role` / `build_chat_model` for `triager` declared `medium` against `deepseek-v4-flash` offering `[high,max]` first-party; live edge: opencode zen gateway to real deepseek upstream; path: resolve profile -> `negotiate_thinking` picks `high` -> `_thinking_wire_form` emits `reasoning_effort=high` -> gateway `allowed_openai_params` forwards it; terminal: wire is `high` not `medium`; completion non-empty with reasoning; observed: wire/gateway log + payload

- **E2 - DEFERRED: vLLM without tool-call-parser degrades to json_mode and validates.** grounds: spec story 2 (+ #44) + ADR A1 last rung
  entry: one-shot `invoke_role` with `Observation`-like open schema against vLLM lacking both capabilities; live edge: vLLM endpoint (SwissAI/Qwen) via gateway; path: `negotiate_method` -> `json_mode` -> `result_validates` catches wrong shape; terminal: bootstrap completes with validated result, no 400; observed: requested method and parsed result

- **E3 - DEFERRED: mainline provider stays GREEN (no regression).** grounds: spec story 3 (OpenAI/OpenRouter GLM-4.7-Flash proven path)
  entry: same one-shot and session tool-loop paths against mainline with both capabilities true; live edge: OpenAI-compatible upstream via gateway; path: no-tools -> `json_schema` strict=False, tools-bound -> `function_calling`; terminal: both succeed byte-identical to pre-#99; observed: wire strict flag and tool_choice vs response_format

- **E4 - DEFERRED: unknown model probe-on-miss converges then holds.** grounds: spec story 4 + ADR A2 try-in-order + D7/D6
  entry: unknown model not in registry, first one-shot with invoker; live edge: live LLM via gateway (unknown id); path: `probe_with_invoker` walks `json_schema`->`function_calling`->`json_mode` validating parsed result per rung, caches winner; terminal: winner serves second session turn via cache hit; langfuse probe span emitted; no mid-session re-probe; observed: span log, second turn method

- **E5 - DEFERRED: toggle-only and budget_tokens adapt live.** grounds: spec story 15-16 + ADR A5 kind-semantics
  entry: role declared `medium` against toggle-only model and against `budget_tokens` model with bounds; live edge: provider exposing each control kind via gateway; path: `negotiate_thinking` -> `toggle`/`budget` -> `_thinking_wire_form` emits `extra_body.thinking`; terminal: toggle sees thinking ON (no 400), budget sees `budget_tokens` clamped token count matching `THINKING_BUDGET`; observed: wire extra_body

- **E6 - DEFERRED: budget clamp live respects min/max.** grounds: spec story 14 + A5 canonical budgets `minimal=1024 ... max=40000`
  entry: declared `xhigh` against model with `budget_tokens` min=4000 max=12000; live edge: real provider via gateway; path: `THINKING_BUDGET[xhigh]=32768` clamped to `12000` -> `extra_body.budget_tokens=12000`; terminal: request carries `12000`; upstream does not reject; completion returns; observed: wire budget_tokens value
