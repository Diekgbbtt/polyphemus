# LLM role architecture - agent prompt for the #93 design hole

*Status: RATIFIED 2026-08-07 (operator), implemented on `feat/hunting-94-session-agents` (#94).*
*This document is the deliverable the #93 ticket carries: the description of the hole, the vocabulary it needs, and the prompt that the fixed role architecture must satisfy.*
*The original proposal (sections 1-5) is retained below for the reasoning trace; the ratified decisions and their implementation are in section 0.*

## 0. Ratified decisions (2026-08-07) and where they live

- **The role record** is `Role(role_id, model_key, agent_mode)` in `src/polymerhus/app/llm/providers.py`.
  `role_id` is the cognitive-job identity (the observability label); `model_key` is the env var selecting the model and is MANY-to-one (every analysis role_id shares `LLM_MODEL_ANALYSER` for now, so a per-agent split is a one-line `model_key` edit); `agent_mode` is `one_shot | session`.
- **Terminology.** The turn-mode values are `one_shot` and `session` (not "resumable"); a session agent's memory is carried in LangGraph checkpointer thread-state, not in the conversation-as-prompt.
- **`analyser` is split** per cognitive job (`bootstrapper`, `assigner`, `mechanism_typist`, `data_modeller`, `anatomy`, `curation`, `sweep`, `anti_cluttering`); the hunting roles (`hunting_orchestrator`, `hunting_hunter`) live in `HUNTING_ROLES`, validated at the hunting module bootstrap, NEVER app boot (operator ruling 2026-08-06).
- **The session path** is `src/polymerhus/app/llm/session.py::run_session_turn` / `arun_session_turn`, built on `langchain.agents.create_agent`: a long-horizon **tool_calling** agent (via `bind_tools`), checkpointer-backed short-term memory keyed by `thread_id = f"{run_id}:{role_id}"`, `response_format` for structured output.
  The one_shot path stays on `invoke_role`.
- **`function_calling` is retired from the session path** (it is the one-shot-oriented, provider-fragile mechanism - see #44's SwissAI HTTP 400); the one_shot `invoke_role` keeps it, and its provider-aware replacement is owned by the dynamic inference-method-configuration workstream, not #94.
- **Two capabilities are seams #94 exposes but does NOT build** (designed-not-built):
  - context-window compaction + memory (#98/#99) plug in as `create_agent` `middleware` (`after_model` after an LLM turn, `wrap_tool_call` after tool output) and via the `store` seam (#85);
  - dynamic inference-method / tool-capability configuration (which catches a non-tool-capable model early / degrades it) also plugs in as `middleware` - #94 never hardcodes the method or asserts a provider capability (SwissAI is an outlier: only some of its models are tool-callable).
- **Async-native parents.** The greatest benefit of async is the parent/coordinator being decoupled from any single child so it can monitor exhaustively and later fuse live cross-unit insight from persisted memory.
  Ratified scope: `arun_session_turn` exists now; the **hunt-orchestrator is the first and (for now) only** async-native parent - DELIVERED as `hunt_orchestrator.arun_orchestration`, which runs the fail-open pass off the event loop (`asyncio.to_thread`) so an async coordinator can `await` a hunt pass without stalling its loop, single-sourcing the O1-O10 canon (never re-implementing it); the concurrent-independent-hunts loop + the coordinator's cross-unit memory-read (`store`, #85) are the explicit designed-not-built follow-up.
  The other parents stay async-task-ready but are not converted until #85 gives them cross-unit insight to integrate.
  The data-dependent analysis proposer chain (`assigner -> mechanism_typist -> data_modeller`) stays sequential; it is not made async.

## 0.1 The three-axis agent model and the stateful migration (operator-corrected 2026-08-07)

An earlier draft here proposed keeping the analysis proposers and the recon configurator/triager on `invoke_role`, reasoning that they externalise their write-state to the L1 graph.
The operator CORRECTED this: `invoke_role` rebuilds the prompt from scratch every call, so the context window is never progressively updated - there is NO agent memory.
The L1 graph is only the WRITE side (facts committed); it is not the agent's reasoning memory.
So the agents below must be genuinely STATEFUL session agents (checkpointer-backed, context grows across turns), and #94 is not "done" until they are - and until their memory is addressed by a collision-free key.

Three INDEPENDENT axes (do not conflate them):

1. **Turn mode** (`agent_mode`): `one_shot` (a stateless `invoke_role` structured call) vs `session` (a checkpointer-backed agent whose context progressively grows).
2. **Execution model**: a **sync leaf** (a callee) vs an **async actor** (an independent unit - own loop + mailbox, wakes on sub-agent updates via post-call hooks; `app/llm/actor.py`). The async actors are, per operator: every orchestrator across the 3 modules + the hunting agent + the per-recon-phase agent.
3. **Structured-output method**: `ToolStrategy` (tool-calling, the `function_calling` equivalent) vs `ProviderStrategy` (the provider's native json_schema). #94 uses `ToolStrategy` for every structured session agent, because native json_schema strict-mode 400s on open `dict` fields (`Observation.anchor`, #44) - the same reason `invoke_role` pins `method="function_calling"`.

| Agent (role_id) | Turn mode | Execution | Stateful session address (`session_thread_id`) |
| --- | --- | --- | --- |
| `configurator`, `triager` (recon pod) | **session** (corrected) | sync leaf, inside an async-actor pod | `run:{phase}:{job}:{input_asset_url}:{role}` — per CONCURRENT pod (`pod.py::pod_session_thread_id`) |
| `assigner`, `mechanism_typist`, `data_modeller` | **session** (corrected) | sync leaf, inside the async supervisor actor | `run:{role}` — serialized (`ANALYSER_PASS_SEMAPHORE=1`, one graph/run), so run+role is already unique |
| `hunting_hunter` (hunting agent) | session | **async actor** | `run:{hunt_id}:hunting_hunter` — per hunt |
| `hunting_orchestrator`, analysis supervisor, recon-orchestrator, recon-phase agent | session | **async actor** | keyed by the coordinator's own run/instance |
| #84 test-executor pod (variant tool-loop) | session | sync leaf | `run:{hunt_id}:{spec_hash}:pod` — per spec/variant |
| `bootstrapper`, `anatomy`, `curation`, `sweep`, `anti_cluttering` | one_shot | sync leaf | n/a — stateless post-processing, stays on `invoke_role` |
| `crawler` | session/tool-loop | sync leaf | kept on its tuned `crawl_agentic.py` loop (a `create_agent` rewrite would drop the manifest-drain); its accumulator is the MCP `crawl_id` |

### The collision-free addressing scheme (the fix for the mis-routing the operator flagged)

`thread_id = f"{run_id}:{role_id}"` collides across the several pods/hunts of one run that share a role, so the checkpointer would load one instance's memory into another.
The fix is a set of TYPED, per-module value objects in `app/llm/session_address.py` (a `SessionAddress` structural `Protocol` + frozen dataclasses `AnalysisSession`, `PodSession`, `HuntSession`), each exposing `.thread_id`.
Per-module TYPES rather than one `(run, *path, role)` builder because the three modules discriminate a concurrent instance by structurally different things (analysis: none - serialized; pod: phase+tool+asset; hunt: hunt_id[+spec]); a single type could only span them with a union-of-optionals, which reproduces an untyped positional path in field form.
They share only a CONTRACT (yield a `thread_id`, expose `role_id`), so the shape is a Protocol, not a base class - each address is an independent frozen dataclass (chosen over pydantic deliberately: the value is naming + immutability + one escaped composer, none of which needs a validation framework).
The one string the checkpointer requires is produced by `.thread_id` (segment-escaped, hash-bounded, via the single private `_compose`); no call site hand-builds it.
Recon's per-pod discriminator (the `input_asset` url with a stable-hash fallback) is resolved in `pod.py::pod_session` (recon owns HOW a pod is discriminated; `PodSession` only holds the resolved token, so `app/llm` never imports recon).
The out-of-band ContextVars (recon `triage_fn`, hunting `author`/`judge`) carry a typed `SessionContext(address, checkpointer)`, not a stringly tuple.

### The #85 split (why #94 owns the addressing but not the fusion)

The memory ADDRESSING (the collision-free key) is #94's and BLOCKING - a stateful agent with a colliding key mis-routes context regardless of #85.
The cross-unit FUSION (a parent actor READING a child's persisted memory) is #85's deferred delivery; the seams are already scaffolded (the actor `AgentInbox` + post-call `inbox_post_hook` / `build_inbox_middleware`, and the `store` param on the session seam).

### Known dependency risk (surfaced, not yet resolved)

Statefulness grows the context window every turn; compaction (#98/#99) is scheduled AFTER #94.
So a long run (many chunks/turns) can grow a session past the model's window before compaction lands.
The session seam exposes the compaction hook points (the `middleware` seam) today; until #98/#99 fills them, a long stateful run is a live risk to weigh when enabling statefulness in production.
Also: the session path uses the client per-turn retry, not the #73 escalating-timeout retry `invoke_role` owns - porting that onto the session path is a robustness follow-up.

### The ubiquitous stateful pattern (how every stateful agent is invoked)

One helper, used identically everywhere: `session.py::stateful_turn(role_id, thread_id, messages, *, checkpointer, schema=None)`.
It is `structurally sync` (agents are dispatched sequentially, so no async), yet STATEFUL (resumes its `thread_id`), with structured output via `ToolStrategy`.
`thread_id` MUST come from `session_thread_id(...)` so each instance has a DISTINCT checkpoint.
The backing store is the PROCESS-WIDE POOLED checkpointer `checkpoints.py::get_session_checkpointer()` - a `PostgresSaver` over a `psycopg_pool.ConnectionPool`, opened at app startup (`setup_session_checkpointer`) and closed at shutdown; it degrades fail-open to a shared in-process `InMemorySaver` when Postgres is absent.
A pool (not a per-run connection) is required because up to `MAX_PODS` recon pods run their stateful agents concurrently.
Where a call site cannot pass the instance identity through its seam contract (the recon `triage_fn`; the hunting `author`/`judge`), the owning node sets `(thread_id, checkpointer)` on a ContextVar that the live implementation reads - the seam contract stays untouched (its test doubles ignore it).

### Delivered on this branch

- The collision-free addressing (`session_thread_id` + recon `pod_session_thread_id`), tested.
- The ubiquitous stateful pattern (`stateful_turn`) + the process-wide POOLED checkpointer (`checkpoints.py`, wired into `app/main.py` startup/shutdown), tested.
- **Analysis proposers STATEFUL** (on by default): `assigner`/`mechanism_typist`/`data_modeller` run via `stateful_turn` on their own per-run thread (`run:{role}`), `ToolStrategy` output, over the shared pooled checkpointer. Tested.
- **Recon triager STATEFUL**, keyed per concurrent pod (`run:{phase}:{tool}:{input_asset_url}:triager`): `run_id`/`phase` now ride `PodState`; the triager node sets the per-pod session on a ContextVar (leaving the 25+ injected `triage_fn` contracts untouched); the live `default_triage_fn` runs `stateful_turn` (`ToolStrategy` keeps the `Observation.anchor` path). Tested.
- **Hunting agent (hunter) STATEFUL**, keyed `run:{hunt_id}:hunting_hunter`: the agent binds a hunt-session ContextVar around a hunt's `author`/`judge`/re-entry turns, so they resume ONE per-hunt thread; `attack/hunting/llm.py` reads it (`hunt_session`). Tested.
- The `actor.py` persistent-agent runtime + post-call-hook delivery scaffold; the hunting bootstrap + role wiring; `arun_orchestration` (async parent seam). Tested.

### Remaining

- The recon `configurator` role is REGISTERED BUT UNWIRED (no LLM consumer today); it adopts the pattern when it is built.
- The hunter's production DRIVER (which calls `build_hunting_agent` with the real `author`/`judge`) is #83's; the seam is stateful-ready. Test-executor pod key `run:{hunt_id}:{spec_hash}:pod` reserved for #84.
- Robustness follow-up: port the #73 escalating-timeout retry onto the session path so a migrated agent keeps it (today the session path uses the client per-turn retry).
- Compaction of the now-growing stateful context is #98/#99 (the `middleware` seam is exposed for it).

## 1. The hole

`src/polymerhus/app/llm/providers.py` keys every LLM-gated agent by a role string in the `ROLES` tuple: `("configurator", "triager", "job_orchestrator", "crawler", "analyser")`.
Each role maps to exactly one model environment variable (`LLM_MODEL_ANALYSER` and so on) and is invoked single-shot through `invoke_role(role, messages, schema=...)` (`src/polymerhus/app/llm/roles.py`).

Two facts do not fit the vocabulary:

1. One `analyser` key gates several DISTINCT agents with different cognitive jobs (the mechanism-typist, the assigner, the data-modeller; the hunting agent was nearly forced into the same key).
   The role key conflates "which model to use" with "which cognitive job is running".
2. The role vocabulary has no property for whether the agent is ONE-SHOT (a single LLM call, stateless, e.g. the assigner's assignment turn) or RESUMABLE (a semi-stateful agent that must resume its working set across invocations, e.g. the hunting agent's decision tree, whose candidate set and decision-point records must survive between turns).
   `invoke_role`'s single-shot convention is the only mechanism today; a resumable agent must smuggle its state through the conversation history because the role offers no state seam.

The consequence is a choice between two bad options: either every new agent reuses an existing role key (model coupling, no cognitive distinction, no state seam), or every new agent mints a new key (key proliferation, N model env vars, no shared vocabulary).

## 2. The fixed vocabulary (proposal for #93)

The role record should carry three independent properties:

- `role_id`: the stable identity of the cognitive job (e.g. `mechanism_typist`, `assigner`, `hunting`).
- `model_key`: the environment variable selecting the model (e.g. `LLM_MODEL_ANALYSER`, `LLM_MODEL_HUNTING`).
- `agent_mode`: `one_shot` | `resumable`.

`one_shot`: a stateless single call; the conversation is complete in one invocation; nothing persists between calls.
`resumable`: a semi-stateful agent; each invocation receives a working set (the durable state) and returns an updated working set; the caller persists it; a resumed invocation must be able to continue from where the previous one ended without rebuilding.

`model_key` is a many-to-one mapping: several `role_id`s may share one model key.
`agent_mode` is a property of the role, not of the model.

## 3. The prompt the fixed vocabulary must satisfy

### 3.1 The hunting role (the first consumer, #83)

Role record: `role_id: "hunting"`, `model_key: "LLM_MODEL_HUNTING"`, `agent_mode: "resumable"`.

The hunting agent's system prompt is the stable cognitive-architecture prompt ratified in `docs/design/hunting-83-hunting-agent-implementation.md` section 4.1-4.6 (decision tree, passes, loop discipline, working set, few-shot examples); its user prompt is the per-invocation grounding (HuntConfig parts, KB retrieval, working set state).

The resumable mode contract, as consumed by the hunting agent:
- The working set (ordered candidate set with statuses, decision-point records, spec canonical hashes, experiment log, derived verdicts) is passed in the user prompt on every invocation and returned by the invocation as the new working set.
- The invocation may resume at GROUND (fresh hunt), at the candidate-evaluation sub-loop (a pod result to consume), at D5 (the continuation judgment), or at a re-entry point (a routed back-edge result).
- The caller persists the returned working set; the agent never rebuilds state from the conversation alone.

### 3.2 The general contract for any resumable role

- The prompt declares where the invocation may resume and what state it receives.
- The state is explicit (a typed working set), never implicit in the conversation history.
- The prompt declares the termination rule: the invocation either returns a final result (the hunt's verdict, the assignment, the classification) or an updated working set with a resume point.
- The one-shot roles keep the existing single-turn contract unchanged; only the resumable roles gain the state seam.

## 4. What #93 must decide

- Ratify the three-property role record and the `one_shot`/`resumable` vocabulary.
- Decide whether `resumable` carries the working set in the prompt (as the hunting agent does) or through a dedicated state seam in `invoke_role`.
- Decide whether `LLM_MODEL_ANALYSER` stays as the shared model key for the three analysis roles (many-to-one) or is split.
- Migrate `ROLES` and `validate_llm_config` (`providers.py`) accordingly, with the hunting role as the proof case.

## 5. Non-goals

- This ticket does not build the resumable-state persistence (the hunt store #68 owns the durable records).
- It does not change the `invoke_role` failure semantics (the escalating timeout retry, #73).
- It does not re-key existing roles beyond what the ratified vocabulary requires.
