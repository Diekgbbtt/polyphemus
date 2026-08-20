# Implementer prompt - #99 capability-adaptive LLM client

*Feed this verbatim to the agent that will address #99. It specialises the agent on the development discipline (grilling -> to-spec -> to-tickets -> to-assertions -> implements), grounds it in the domain/architecture/standard, states the component rationale, brainstorms the useful skills, and pins the loop's termination conditions.*

---

You are the implementer agent for ticket **#99 - "LLM client is not capability-adaptive across providers (structured output / tool-calling)"** in the polymerhus repo.

Read the ticket first (`gh issue view 99`): it generalises and absorbs **#44** (SwissAI/json_mode). It captures axis (A) capability compatibility; axis (B) latency/timeout coherence is **#73's** and stays separate - never entangle them.

## 1. Component rationale (the design intent to honour)

The client hard-codes one capability preset (`method="function_calling"` on the one-shot seam, native `bind_tools` on the session seam) and every non-mainline provider fails at the LLM boundary, not in pipeline logic. You are building the capability-adaptive layer: resolve what each (provider, model, schema-shape) actually supports, choose the structured-output/tool-calling strategy at call-construction time, and hold it for the session. The ratified selection is semantic-first + profile-corrected (ADR A1): no-tools one-shot extraction -> `structured_output` json_schema `strict=False`; tool-bound session/crawl -> `function_calling` (T5 gate); degrade chain `json_schema` -> `function_calling` -> `json_mode`, each validating the parsed result; `reasoning_effort` is orthogonal to method.

The load-bearing principles, all ratified - do not silently deviate:

- **Session-scoped profile, resolve-and-hold**: a capability profile resolves ONCE per session at construction and is held; the session must never resolve capability mid-turn (D6). P1 one-shot calls are the degenerate one-call session. This keeps capability resolution **off the #73 retry axis** - never nest a capability retry inside the latency retry (#32's multiplied-retry defect). Fail-open (D7): ANY resolution failure degrades to a safe conservative default - a session must always start.
- **Provenance-gated trust (D5 Rule 1)**: a capability field is trusted only when it carries the `capability_source` provenance tag. Absence = `None`/unknown, never asserted true, never asserted false. Unknown degrades (crawl refuses to an empty manifest, not a crash).
- **The profile reads from the gateway surface, never from hardcoded per-provider tables**: the capability record is authored by the sync pipeline (T2) from the models.dev registry and pushed into the LiteLLM gateway (`model_info`); the reader (`capability.py`) is the only client-side consumer. Any NEW capability field #99 needs must be authored in `sync_mapping.py` (D5 - the only place product-specific field names live), provenance-tagged, and surfaced through `CapabilityProfile` - never invented at implementation time.
- **Validate the parsed result, not just exceptions**: `json_mode` fails silently (HTTP 200, wrong shape). The probe/fallback chain validates the Pydantic parse.
- **Never parse vendor error strings** to classify a failure (the OpenAI standard has no machine-readable unsupported-capability code). Try-in-order + validate, or degrade.
- **P2 stateful sessions are first-class**: the langgraph tool loops hold client configuration in memory across turns; capability must resolve at session construction and be held, not probed per turn.
- **The crawl P2 tool-loop answer is already built (T5)**: `supports_tool_calling` gated at `crawl_agentic.py:158` - refusal to an empty manifest when unsupported/unknown. Do NOT re-engineer it; #99 carries that as the resolved tool-loop strategy for crawl and extends the pattern where needed, not where it already exists.

**What the #100 stream already delivered - build ON it, do not rebuild:**

- **The gateway surface** (T1): LiteLLM proxy container, `GET /model/info` returning `{"data": [{"model_name": ..., "model_info": {...}}]}`; `model_info` carries `max_input_tokens`, `max_output_tokens`, `supports_function_calling`, and provenance tags, plus the D11 reasoning keys (`reasoning_in_response` bool, `reasoning_field` `reasoning_content`|`reasoning_details`).
- **The sync pipeline** (T2): stateless fetch -> join -> map -> validate -> diff -> push CLI authors the capability records the reader consumes; requirements-`gateway.txt` pins `litellm[proxy]==1.96.0`, `fastapi==0.140.6`.
- **The capability reader** (T3): `CapabilityProfile` (frozen dataclass) + `resolve_capability(provider, model)` at `capability.py:295` - process-lifetime resolve-and-hold, provenance-gated, fail-open. This IS #99's recommended session-scoped profile substrate.
- **The routing seam** (T4): `build_chat_model` in `providers.py` is now the SOLE construction site (roles.py:18,35 route through it), honoring `LLM_GATEWAY_URL` (direct mode hermetic; `API_KEY_<PROVIDER>` still required, D3), and returns T6's `ReasoningPreservingChatOpenAI`.
- **The reasoning surfaces** (T6/D11): reasoning survives only on the wire - `reasoning_content` at message level, `reasoning_details` via `provider_specific_fields`; the preserving client captures and re-emits them.
- The T3 session-pattern decision: profile resolved at **turn construction, before invoke, never after** (enforced by the T6 REDO round).

## 2. First step - a grilling session (reduce the key risks to a residual minimum)

Run the **grilling** skill with the operator before any code; drive it to a solution for each of the ticket's shaping points. These are the residual risks:

1. **The structured-output method negotiation for P1** (the ticket's increment-1): which of `json_schema` / `function_calling` / `json_mode` per (provider, model, schema-shape class), with what universal fallback ordering (the ticket's candidate: `json_schema, strict=False`) - and exactly WHERE the decision lands: `_structured_response_format`/`invoke_role` on the one-shot path and the session seam's `response_format`/`ToolStrategy` on the session path.
2. **Probe-on-miss**: T3 seeds known models from the sync table only; `unknown` models need a probe. Decide the probe protocol (try-in-order + validate parsed result, never error-string parsing), its cadence (session-construction once, per the D6 resolve-and-hold), and its cost bounds (off the #73 axis; cold-start only).
3. **The `extra_body` open question**: does `extra_body` reach `create()` through `with_structured_output` kwargs (the vLLM `guided_json` path)? If not, use `bind_tools(response_format=...)` or a targeted raw-SDK escape hatch.
4. **Scope**: only the seams that already fail + the P2 sites that share the construction path (`invoke_role`, the session seam). Do not speculatively build strategy-fallbacks nothing uses yet.
5. **The unpinned-SDK risk** (the ticket's step 4): `langchain-openai`/`langgraph` are under-pinned in repo-tracked requirements - decide whether to file it as its own small ticket (likely yes; the T6 tier pinned behavior under 1.3.x).

Record the grilling outcome (the `grill-with-docs` variant writes the ADR + glossary entries in the same change). Do not start coding until the operator confirms a shared understanding.

**THIS GRILLING IS COMPLETE (2026-08-20) - the four decisions are ratified in `docs/design/capability-adaptive-client-99-decisions.md` (A1-A4). READ THAT ADR AND HONOUR IT; the items above are the question set that produced it, and A1/A3/A4 explicitly supersede the ticket's candidate "universal `json_schema, strict=False`" default, the item-4 scope (`steering.resolve_model` is OUT of #99, retired separately), and the item-5 "separate small ticket" for the SDK pin (pinned inside #99 instead).**

## 3. Grounding - read these directly from the filesystem before designing

- `CLAUDE.md`, `CONTEXT-MAP.md`, `CODING_STANDARD.md` - the DDD paradigm, bounded contexts, sole-writer discipline, slim typed interface agreements, dependency injection for testability, no I/O at import (section 6), fail-open (section 12). NOTE the `CONTEXT-MAP.md` ruling: **llm-client is a helper module, never a context** - it gets no `CONTEXT.md`.
- `loop-constraints.md` (the sole work authority - read it verbatim), `loop-budget.md` (token cap; report-only at 80%), `STATE.md` (High Priority: kill switch, escalations).
- `docs/agents/issue-tracker.md`, `docs/agents/triage-labels.md`, `docs/agents/domain.md` - the ticket vocabulary, the workflow, and the domain-glossary mechanics.
- `docs/design/llm-gateway-100-decisions.md` - **the ADR: D1-D11 read in full**. D5 (record mapping + provenance keys), D6 (gateway surface + resolution at construction), D7 (fail-open profile reader), D8 (prompt caching + byte-identical replay prefix), D11 (reasoning surfaces `reasoning_in_response`/`reasoning_field` and the metadata/langfuse surface). These are the contracts your changes must extend, not contradict.
- `docs/design/domain-model.md` - the living reasoned model (the `llm` layer's session/reasoning-cache primitives; reasoning-replay note added 2026-08-12).
- `src/polymerhus/app/llm/capability.py` - `CapabilityProfile` (fields: `context_limit`, `output_limit`, `supports_tool_calling`, `reasoning_in_response`, `reasoning_field`, `source`, `synced_at`), `resolve_capability`, the `/model/info` wire parsing, the provenance gating.
- `src/polymerhus/app/llm/sync.py`, `sync_mapping.py` - the D5 mapping layer; the ONLY place new capability field names get authored.
- `src/polymerhus/app/llm/providers.py` - `build_chat_model` (sole construction site; gateway routing; `ReasoningPreservingChatOpenAI`), `invoke_with_escalating_timeout` (the SINGLE retry layer - never multiplied).
- `src/polymerhus/app/llm/roles.py` - `invoke_role` (P1 one-shot seam) vs `chat_model_for` (session path) - the two interface agreements your negotiation must fit.
- `src/polymerhus/app/llm/session.py` - `run_session_turn`/`arun_session_turn`/`stateful_turn` and the `response_format`/`ToolStrategy` wrapper; profile resolved at turn construction (session.py:276,309).
- `src/polymerhus/recon/control/steering.py:59-69` (`resolve_model`) - the recon P1 site outside roles.py.
- `src/polymerhus/recon/crawl/crawl_agentic.py:158` - the T5 gate you must NOT rebuild but must stay consistent with.
- The adverse-testing precedent: `tests/test_gateway_reasoning_passthrough.py` (wire shapes), `tests/test_llm_capability.py`, `tests/test_llm_reasoning.py::test_preserving_client_*` (real conversion-boundary tests on the pin - the pattern for proving a strategy choice survives the langchain boundary).
- The tickets: `gh issue view 99` (this ticket), `gh issue view 44` (absorbed), `gh issue view 73` (the retry axis that must not entangle), `gh issue view 32` (the anti-pattern), `gh issue view 93` (role vocabulary), `gh issue view 104`/`106`/`107`/`108`/`109` (T1/T3/T4/T5/T6 of the stream that delivered the substrate).

## 4. Skills - open each SKILL.md from the filesystem when its situation arises

Skills are user-invokable only; you cannot load them through a skill loader. Open each skill's `SKILL.md` directly from the filesystem when its situation arises:

- `grilling` - `/Users/diekgbbtt/.claude/skills/grilling/SKILL.md` - the FIRST step (section 2); the `grill-with-docs` variant (`/Users/diekgbbtt/.claude/skills/grill-with-docs/SKILL.md`) records the ADR + glossary in the same change.
- `to-spec` - `/Users/diekgbbtt/.claude/skills/to-spec/SKILL.md` - turns the grilling outcome into the spec (seams chosen at the top; no interview, synthesize what was grilled).
- `to-tickets` - `/Users/diekgbbtt/.claude/skills/to-tickets/SKILL.md` - breaks the spec into tracer-bullet tickets, each declaring its blocking edges.
- `to-assertions` - `/Users/diekgbbtt/.claude/skills/to-assertions/SKILL.md` - projects the spec/tickets into contract + walkthrough predicates at the seams to-spec chose; mechanised in the integration/e2e tiers, never in the unit red/green loop.
- `implement` - `/Users/diekgbbtt/.claude/skills/implement/SKILL.md` - the overall TDD/typecheck/review workflow for each ticket slice.
- `test-driven-development` - `/Users/diekgbbtt/.claude/skills/test-driven-development/SKILL.md` - red/green/refactor at the seams.
- `prompt-engineering-patterns` - `/Users/diekgbbtt/.claude/skills/prompt-engineering-patterns/SKILL.md` - if any probe/fallback logging or operator-surfacing text is crafted, treat it as prompt content (system-vs-user split, structured outputs, template systems), not invented text.
- `langgraph-docs` - `/Users/diekgbbtt/.claude/skills/langgraph-docs/SKILL.md` - when the P2 session seam's `ToolStrategy`/agent wiring is touched.
- `langfuse` - `/Users/diekgbbtt/polymerhus/.claude/skills/langfuse/SKILL.md` - capability resolution must stay observable (a langfuse span/trace per resolution); callbacks flow from construction (D3).
- The litellm SDK skill - `/Users/diekgbbtt/polymerhus/.claude/skills/litellm/SKILL.md` - if the grilling decides a raw-`create()`/`extra_body` escape hatch; the proxy-ops suite (`/Users/diekgbbtt/.claude/skills/litellm/`) if testing against a live gateway instance.
- `verification-before-completion` - `/Users/diekgbbtt/.claude/skills/verification-before-completion/SKILL.md` - evidence before assertions.
- `code-review` / `requesting-code-review` / `receiving-code-review` - review the branch before finishing; respond with technical rigor, never performative agreement.
- `using-git-worktrees` - `/Users/diekgbbtt/.claude/skills/using-git-worktrees/SKILL.md` - the worktree discipline (section 5).
- `domain-modeling` / `codebase-design` - the living-documents rule (glossary + `domain-model.md` updated in the same change as any term sharpening).

## 5. Workflow discipline and termination conditions

- **The discipline is fixed: grilling -> to-spec -> to-tickets -> to-assertions -> implements.** Run the stages in that order, each gated: grilling (operator confirms shared understanding) -> to-spec (spec published, `ready-for-agent` applied) -> to-tickets (tracer-bullet slices, blocking edges declared) -> to-assertions (contract + walkthrough predicates at the to-spec seams) -> implements (one ticket slice at a time, TDD).
- **Worktree first**: branch off **`dev`** (the running stack's source - never `main`, never the default branch) into a NEW git worktree; name the branch `feat/capability-adaptive-client-99` (or per the issue-tracker convention).
- TDD at the seams: the unit tier drives the pure mechanics (method/strategy resolution, the probe try-order + validation, the fallback chain, the profile surface) with the LLM and the gateway mocked - the unit tier touches no live model, no live gateway, no DB. The contract catalogue lives in integration; a live walkthrough (a real provider's capability records through the sync -> gateway -> reader path) lives in e2e.
- Run typechecking and single test files regularly (`.venv/bin/python -m pytest tests/<file> -q`); the full suite at the end. Live tiers run IN-NETWORK against the stack built from `dev` - merge your branch into `dev` (the only merge you perform - never to `main`), rebuild, and run e2e in-network per `loop-constraints.md`, BEFORE requesting green light.
- Living documents: land any glossary / `domain-model.md` / ADR / spec corrections in the SAME change (do not defer).
- Maker/checker: you never mark your own work done and never self-approve. When green, run the `code-review` skill over your branch, fix findings, then dispatch a SEPARATE `loop-verifier` sub-agent with the assertion catalogue as the checklist.
- **Termination**: verifier APPROVAL, then the operator's green light. Current operating mode is SOLO (operator ruled 2026-08-12: PRs cancelled, no integration pipeline) - integration is a local fast-forward of the ticket branch into `dev` and push, exactly as the #108/#109 stream landed (90d6a6f, 2a9d2c8). If the operator has re-enabled the PR pipeline by the time you land, follow `docs/agents/issue-tracker.md` (one PR against `main`, `Closes #99` in the body; merging to `main` is a human action - never merge).
- Max 3 fix attempts per area; escalate with full context in `STATE.md` High Priority after that.
- Never commit secrets, never edit `.env`/infra configs, never weaken/skip/disable a test to go green.