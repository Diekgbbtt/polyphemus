# Recon job auth phase (#223) - design decisions

*Status: OPEN - living. Rebuilt 2026-09-18 (turn 3): the worktree was rolled back to `c126f86` and the open design decisions are being taken sequentially, each recorded here as it is ruled.*
*Turn 1 recorded D223-1..D223-7; they are carried below and remain in force.*
*The turn-2 workflow model (inner/outer loop layout, anti-bot branches, status tree, pitfalls) remains the working frame; it is being re-ratified decision by decision, and the sequential log starts at D223-8.*
*This document is the ADR equivalent for this change (`docs/agents/domain.md`: design specs under `docs/design/` carry numbered decisions; there is no `docs/adr/`).*
*Base: `feat/220-auth-store` at `c126f86` (the app-owned auth-store root fix), with #221 (`steel_exec` gateway + `skills/steel-browser`), #222/#234 (skill loader, `ROLE_SKILLS`, per-project bundles) and `skills/meta/authn-skill-writing` merged in.*

## Carried from turn 1 (in force)

### D223-1 - A new specialist role and the `LLM_<ROLE>` key naming rule

*Superseded in part (operator ruling, 2026-09-18, carried by the workflow-overview pass and D223-8 / D223-13): no new role id is minted.*
*The auth-gateway duty attaches to the existing `job_orchestrator` role, so the `LLM_RECON_PHASE_SPECIALIST` key does not apply - the gateway uses the orchestrator's model key.*
*The `LLM_MODEL_*` -> `LLM_*` global rename below stands unchanged.*

A new role id is minted for the stateful recon phase specialist; the existing `job_orchestrator` id is NOT reused.
Capability and policy attach to the role id (model, turn mode, `ROLE_SKILLS` surface, compaction, trace tags), so two different agents sharing one id would share one capability set - and sharing would arm the run-level macro-router with the specialist's surface.
The role's exact duty is being redefined in the operator's workflow-overview pass (D223-5); the identity and naming decisions are settled now.

The model-key environment variables are renamed from `LLM_MODEL_<NAME>` to `LLM_<NAME>`: the `MODEL` infix is redundant with the `LLM` acronym.
The rename is global (the established keys in `app/llm/providers.py`, their environment documentation, tests, compose files, and image config; 179 textual occurrences at decision time).
The new role's model key is `LLM_RECON_PHASE_SPECIALIST`.
Reusing an existing model key via many-to-one is the established pattern (the analysis roles share one key), but the operator ruled a dedicated key for this role.

### D223-2 - Authentication failure is fail-open for collection; no fabricated persistence

When the authenticated context cannot be established, the collection runs anyway, without authentication material in the tool-call command lines (concretely: without headers carrying auth material in the CLI options).
Recording the failure would be optimal, but no harness or wider control-plane primitive exists today to persist it; no bespoke persistence or logging machinery is to be fabricated for it.
Only existing primitives (structured logs, Langfuse spans) may carry it, and the exact loudness contract belongs to the workflow-overview pass.
This restates the ticket's "marked unverified, degrades loudly" acceptance criterion pending that pass, and supersedes any design that would block collection on an unverified verdict.

### D223-3 - The sign-in outcome is success or failure; "coverage exhausted" is not a verdict state

Attempting sign-in/sign-up ends in exactly two outcomes: success, which generates the authenticated state to record, or failure.
Exhausting the attempt space is a failed authentication, never a third "unverified" outcome; conversely a successful sign-in always leads to generated state.
The state vocabulary (`failed` vs the ticket's "unverified") is settled in the workflow-overview pass; until then, no design may record "coverage exhausted" as a state.

### D223-4 - The settings blob's `auth_context` is retired; remove its full codebase footprint

`settings["auth_context"]` is obsolete: the per-project auth store is the only auth source.
The full codebase footprint is to be removed as part of this ticket, not merely bypassed: the pipeline's auth injection (`recon/control/pipeline.py:463-470`), the pod-side `{auth_header}` serialization and its tool-flag tables and reserved keys (`recon/domain/pod.py`), the `{auth_header}` placeholders in job command templates (`recon/control/jobs.py`), the project-management `AuthContext` value object and its settings surface (`auth_context.py`, the settings validation), `select_auth_context`, and the corresponding tests and docs.
Whether `JobSpec.use_auth` survives as a marker (likely: which jobs the specialist treats as auth-requiring) is settled in the workflow-overview pass.

Verified before the ruling (falsification attempt, 2026-09-18): the auth store's read path returns account records including token values verbatim - `AuthStore.read` is a `deepcopy` dotted projection of the full state (`app/auth/store.py:153-182`), `_check_tokens` requires non-empty token values and strips nothing (`app/auth/records.py:146-159`), and the `auth_store` tool envelope carries the value unchanged (`app/auth/tool.py:150-153`).
No redaction exists anywhere under `app/`; the only `redact` hit is the unrelated jsluice JS-secret parser.
The one caveat is contextual, not a redaction: the shared tool-output discipline trims very large tool bodies in context (`app/llm/tool_output.py:35-82`), so consumers should read narrow store paths.

### D223-5 - The recon job-specialised agent does not perform authentication

The job-specialised agent does NOT carry the authn duty, and consequently does NOT get `write_skill` (no skill-write capability on it).
The `job_orchestrator` is the agent armed now (it receives the write capability); the rest of its arming is defined by the workflow-overview pass.
This supersedes the forward notes in `auth-store-220-decisions.md` D220-9 and `browser-cli-221-decisions.md` D18 ("the recon job-specific agents take the binding when #223 lands").
It also withdrew the graph design proposed in the first grilling round.

### D223-6 - Rollout is not canary-gated

There is no canary release: the implementation binds all `use_auth` jobs generically from the first implementation; non-`use_auth` jobs do not run the auth path.

### D223-7 - Integration override for #223: no PR

For this ticket the documented pull-request integration flow is overridden by operator instruction: `dev` is fast-forwarded locally and both the feature branch and `dev` are pushed; `main` is not touched.
Sibling worktrees will embed this work and fast-forward `dev` themselves, because they need the skill- and tool-bounding primitives this ticket implements - the separation of concerns the operator requires.
E2E verification on the merged state remains a precondition to the fast-forward and push.

## Sequential decision log (turn 3)

### D223-8 - The orchestrator is the sole auth-gateway decider (F1)

The recon orchestrator (role `job_orchestrator`, actor `ReconOrchestratorActor`) is invoked by the pipeline before phase 0 on run start, and it is the sole decider for both the authn-loop outcome and which phases or jobs the plan drops for the run (the anti-bot gating among them).
The pipeline obeys the typed gateway result; it does not duplicate the decision.
This repairs assumption (b): the actor must be started deterministically at run start, not lazily on the first signal-carrying phase (today the pipeline short-circuits on empty signals and the actor's first possible turn is the top of phase 1).
Consequences carried into the queue: F3 must resolve the actor's fail-open routing policy (a degraded turn today returns `{}`, which under this ruling would silently run request-based phases against an anti-bot target); F2 must settle whether "resume" is in scope, since assumption (b) names start or resume and no recon resume exists today.

### D223-9 - Resume stays out of scope; the forward invariant is recorded (F2)

#223 scopes the auth gateway to run start only.
Recon has no resume path today (the pipeline never consults `recon_jobs` to skip completed work, and stale runs are reaped to `failed`), so nothing in this ticket depends on one.
Forward invariant recorded for whoever builds a recon resume: a resumed run must invoke the auth gateway before any phase (re-validation matters because tokens can expire between runs and persisted state can be stale).
This narrows assumption (b) to "the orchestrator is first on start".

### D223-10 - Gateway failure posture: ride the harness suite; asymptotic behaviour is fail-open, loudly (F3)

No new failure-handling machinery is built for the auth gateway.
The gateway turn rides the existing harness error-handling suite, and when that suite is exhausted the behaviour is fail-open, loudly.

The suite, verified in the code:

1. Turn isolation with an escalating budget: a raising turn is classified (`_is_retryable`, `app/llm/actor.py:168-198`) and retried under the schedule `(300, 600, 900, 2700)s` (`providers.py:133-156`); the first attempt is still bounded by `request_timeout()` when no per-attempt budget is passed (`providers.py:587-589`); a non-retryable raise degrades immediately; the actor survives (`actor.py:256-294`).
2. Exactly one reply per turn: the real result posts via `build_inbox_middleware` (`after_agent`), and a degraded turn posts a no-decision reply via the `degraded_hook` (`actor.py:434-461`); `_await_reply` races the reply against the actor task, so a dead actor cannot hang the client (`orchestrator_agent.py:248-265`).
3. Client-side fail-open is loud: the actor client methods catch everything, warn, and return the neutral decision (`orchestrator_agent.py:244-246`).
4. Structured-output parse failure is non-retryable, so it degrades to a no-decision reply (the actor path through `_turn`; `stateful_turn` carries the same explicit degrade for the pod path, `session.py:530-555`).
5. Tool exceptions cannot kill a turn: the installed langgraph `ToolNode` handles tool errors by default (verified in the environment), on top of this codebase's in-band coded-envelope convention for its own tools.
6. Compaction is fail-open throughout (`app/llm/compaction.py:159,532,557-558,641,724,742`).
7. Run liveness: the pipeline heartbeat keeps the stale-run reaper (`REAP_TTL_SECONDS`, `app/config.py:41`) off a long gateway turn (`pipeline.py:415`).
8. Cancellation: `CancelledError` is re-raised and the actor is reaped in `finally` (`actor.py:270-271`).

Gateway-specific risks found, with their coverage status:

- Hang on an unknown or ignored message (UNCOVERED): a new message kind the handler does not recognise returns `None` (`orchestrator_agent.py:223`), so no turn is taken, no reply and no degrade hook fire, and `_await_reply` has no wall-clock bound while the actor task stays alive - run start would stall indefinitely. Requirement: the gateway call must bound its await in wall-clock time, and a timed-out await must not leave a stale reply for the next consumer (correlate replies by kind, or drain).
- Silent schema mismatch (UNCOVERED, minor): a reply whose content parses to the wrong schema returns `None` with no warning (`orchestrator_agent.py:261-262`). Requirement: log wrong-schema content loudly.
- Reaper window (UNCOVERED): the heartbeat starts just before the phase loop (`pipeline.py:415`); a gateway call inserted before it would run un-heartbeated, and the stale-run reaper can flip the row to `failed` mid-loop. Requirement: start the heartbeat before the gateway call (or bound the gateway under `REAP_TTL`).
- Unbounded loop turns (CARRIED TO L2): the actor takes one turn per inbox message; the auth loop's turn bound is set with L2's debug bounding (`max_turns` exists but is unused today, `actor.py:209,301-303`).
- Trigger gate (IMPLEMENTATION REQUIREMENT, not a failure mode): the gateway must bypass the empty-signal short-circuit the routing path uses (`pipeline.py:70-74`, `orchestrator_agent.py:231-232`).

Accepted residual: on persistent harness failure the run proceeds unauthenticated with all phases, loudly logged - including request-based phases against an anti-bot target.
That hazard is knowingly absorbed into the asymptotic fail-open behaviour by this ruling (D223-8's consequence).

### D223-11 - The consumed attribute contract: null replayability is resolved in-loop (C1)

The gateway's branch selection consumes the operator-written overview facts `anti-bot` and `http-client-replayability` (produced per #237):

1. No defence recorded (including an absent or empty overview): request branch; all phases run; the request-based authn loop.
2. Defence recorded and `http-client-replayability: false`: browser-only branch; every request-based phase is pruned; only `steel_crawl` runs, carrying the browser authn loop.
3. Defence recorded and `http-client-replayability: true`: request branch; the loop runs browser-first validation (mount the account profile, verify the session, compare and persist tokens) before releasing collection.
4. Defence recorded and `http-client-replayability: null` (rare): the orchestrator runs the authn loop anyway, including the replayability check of the fingerprint extracted from the browser state; the loop's verdict then decides whether the request-based phases are released (replayable) or pruned to the browser-only branch (not replayable).

The null-resolution outcome is run-scoped only: the overview is operator-owned and the runtime cannot persist it, so the resolution is recorded loudly (structured log and trace) for the operator to re-seed.
This supersedes the earlier proposed conservative default (turn-2 DP-15, "unknown -> treat as not replayable").
Consequence: the gateway outcome is finalised after the loop's turns, not before them; pruning follows the loop's terminal verdict.

### D223-12 - Mid-run steering is retired as redundant; the orchestrator configures once (C2)

The mid-execution WAF steering is removed from the design as redundant: the external anti-bot and replayability assessment is assumed to be of sufficient quality, so the orchestrator configures the pipeline once at run start from the auth-store state and the authn-loop result, and the run executes without mid-run routing.
Removal footprint (verified in the walkthrough): the per-phase signal refresh (`read_steering_signals`, `pipeline.py:664`), the phase-top routing call (`_phase_exclusions` / `decide_routing`, `pipeline.py:419-421`, `orchestrator_agent.py:225-246`), the `RoutingDecision` exclusion map, and the per-job `extra["steering"]` throttle input (`pipeline.py:502-503`; its pod consumer `decide_pod_selection` is throttle-only, `pod.py:174-179`).
Assessment from the walkthrough: the design is not broken by the orchestrator refactor, but the per-phase protocol is incompatible with it in three places - the empty-signal short-circuit and lazy actor start contradict "deterministic gateway before phase 0"; the actor's `response_format` is fixed to `RoutingDecision` for its lifetime, so a gateway/loop schema needs the routing turns retired; and the in-job throttle loses its only input once steering is removed.
Rate limiting is the one runtime concern a start-time assessment does not cover: the post-authn rate-limit system mapping and bypass-testing loop is filed as #238, whose concrete design arrives from the operator next turn.
Sequencing note: `extra["steering"]` is the only rate-limit adaptation that exists today; removing it before #238's profile-driven configuration lands leaves request phases unthrottled in the interim. The implementation plan must sequence this, not silently accept it.
Stale facts resolve the same way: runtime divergence from the recorded overview can only be logged (structured log and trace), because the overview is operator-owned; re-seeding is the operator's action and no runtime write path is fabricated.

### D223-13 - Full arming of the job_orchestrator in one step (A1/A2)

The orchestrator's roster exemption is lifted and the full auth surface binds to the `job_orchestrator` role in one step:

- `auth_store` (read and write) plus the project-scoped `authn` procedure through the auth-capable binding; the skill is project-only, so it rides the binding's skill context and is never declared statically in `ROLE_SKILLS`.
- `load_skill` and `write_skill`, the D223-11 outer loop and the write capability D223-5 promised.
- The Kali `exec` capability for request-based probes, through the established `execute_command` path rather than a per-site reimplementation.
- The `steel_exec` gateway for the browser and CLI path - #221's guarded tool, bound to no agent until now.

Binding goes through the native `tools=` / `middleware=` / `context=` seams, like every other capability; the actor's tool set is fixed at construction, so there is no per-turn tool surface.
Once the routing turns retire (D223-12), the actor's `response_format` moves from the routing schema to the gateway and loop outcome.
Open: the browser-path profile discipline (the profile key when an account carries none, and the fallback) is the next decision.

### D223-14 - Browser-path profile discipline: project-scoped account key, fail-open to sign-in (A3)

The profile key convention is project-scoped and account-derived: `<project_id>-<account>`, combining the account-derived key with a project scope so profiles never collide across projects on the shared Steel account.
When the loop needs the browser and the account carries no `steel.profile`, or a mounted profile does not yield an authenticated session, the loop fails open: it still enters the browser branch, asserts the account `not_valid` in the store, and proceeds with the sign-in flow.
The sign-in flow mints under the project-scoped key (`start --profile <project_id>-<account> --update-profile`), verifies, and persists the profile key plus the extracted tokens back under the account.
The `not_valid` assertion requires a small account-schema addition (a typed validity fact, e.g. `status: valid | not_valid`); the exact key is settled at implementation because the account key set is closed in `records.py`.

### D223-15 - Loop mechanics: one ReAct gateway turn, hunting-style passive transitions (L1)

The whole gateway phase is ONE session turn on the orchestrator actor: `create_agent`'s internal model<->tool loop (the ReAct engine, as the hunting agent uses), ending with the enforced structured gateway verdict through the actor's `response_format`.
The state tracking copies the hunting pattern as strictly as possible:

- A passive detect-and-push machine: `detect_transition` is a pure function of the status verbatim observed on a specific tool call, never consulting the current state (`hunter_state.py:118-133`); `push_transition` moves state and NEVER gates or rejects a call - the no-block invariant (`hunter_state.py:225-239`); the harness is the sole writer of the tracker.
- The injected transition hint is appended to the TRIGGERING tool result only, inside `<phase-transition-hint>`, and consumed immediately - it must never leak onto a later, unrelated result (`hunting_agent.py:582-587`).
- Intra-turn observations are wired with `wrap_tool_call` middleware over the existing tool surface, the pod-harness precedent (`attack/hunting/pod/harness.py:29-98`).
- The debug span relies on the agent's judgment, not a cap: attempt calls are observed and traced for hints, but never capped or rejected; the only hard bounds are the harness's generic ones (LangGraph's recursion limit and the escalating per-attempt LLM budgets). The terminal `exhausted` verdict is the model's declaration (D223-3); "generic bounds only" is deliberate - see D223-16.
- The outer loop is observable in the same turn: `load_skill` / `write_skill` calls after FINISH are the skill-judging protocol's tool boundary (D223-11), then the gateway verdict is emitted.

Documentation requirement accepted with this decision: every state transition boundary is written out below with its exact observable, and the implementation carries the same table next to the state machine module.

#### State transition boundaries (the table the state machine implements)

| State | Entered on (observable tool call) | Machine action / hint | Exits |
| --- | --- | --- | --- |
| GROUNDED | `auth_store` read of `overview` (or an empty path) AND `load_skill("authn")` both observed | mark grounded; hint: retrieve and select the account | RETRIEVED on an `auth_store` read of the accounts |
| RETRIEVED | `auth_store` read of `accounts` (or an empty read after grounding) observed | mark retrieved; hint: validate the selected account | VALIDATION on the first probe; GENERATION directly when the read returned no account (L3) |
| VALIDATION | first probe call after RETRIEVED: `exec` (request replay) or `steel_exec` (browser mount/navigate) | mark validation; count the probe; hint: conclude valid or not_valid | FINISH when the validity assertion is `valid` or the terminal verdict is; GENERATION when the loop writes the account `status: not_valid` (D223-14) |
| GENERATION | `auth_store` write asserting account `status: not_valid` (D223-14) observed | mark generation; hint: run the sign-in procedure | DEBUG at the second attempt call; FINISH when the sign-in succeeds and persists state |
| DEBUG | second and later attempt calls (`exec` / `steel_exec`) in the sign-in span | observe and trace each attempt; per-attempt hint; NO cap and NO rejection (D223-16) | FINISH on success, or when the model declares the space exhausted (terminal `exhausted` verdict); generic harness bounds backstop |
| FINISH | success: the `auth_store` write asserting `status: valid` for the account, or the terminal gateway verdict; failure: the terminal `exhausted` verdict | record the verdict; run the outer loop (skill judging); return the gateway result | terminal |

The `status: valid` assertion is written on success for the same reason as `not_valid`: it gives the harness a call-level boundary for the success branch instead of inferring it from the terminal verdict.
Verdict vocabulary stays per D223-3: sign-in ends in success (state generated) or failure; "coverage exhausted" is a failed authentication and maps to the terminal `exhausted` verdict, never a third state.

### D223-16 - Debug bounding: no cap, generic bounds only (L2)

No bespoke attempt cap and no duplicate-command rejection are built for the sign-in and debug span.
Attempt calls are observed and traced (so hints and spans carry the debugging trajectory), but the harness never caps or rejects them.
The span ends when the model declares the tweaking space exhausted - the terminal `exhausted` verdict, which D223-3 already defines as a failed authentication - or when a sign-in succeeds and the state is persisted.
The only hard bounds are the harness's generic ones: LangGraph's recursion limit for the ReAct turn and the escalating per-attempt LLM budgets (D223-10).
Rationale: the agent's judgment owns "tweaking space exhausted"; a mechanical cap was judged a false boundary, and the generic bounds already guarantee the turn cannot run forever.

### D223-17 - Missing-data states: no-auth-surface vs un-bootstrapped, and the ordered fallbacks (L3)

The "no accounts AND no `authn` skill" state has two distinct causes, discriminated structurally in the store - never inferred from the target's behaviour:

1. **No authenticated surface.** The target has no authenticated areas at all. Discriminator: the overview is absent, or carries a specific structural value (e.g. a `description` marking "no authenticated surface"; exact field settled at implementation). Ruling: this becomes a first-class gateway state recognised in the orchestrator's outer loop as its own phase-0 path - the authn loop is skipped, the pipeline runs anonymously, and the gateway verdict records the no-auth-surface finding. An empty store is the EXPECTED shape here, not a bootstrap failure.
2. **The external bootstrapper was not run.** The empty store is a missing prerequisite. Ordered handling, worst to best:
   - No credentials at all -> **fail-close: stop the run**, loudly. This is not a gateway failure, so D223-2's fail-open collection does not apply.
   - Credentials present but no `authn` skill -> fail-open self-service: the loop falls back to a request-based default driven by whatever the store's description and procedure carry. The residual risk - a thin description yields a blind sign-in attempt - is accepted and documented, not mitigated.

### D223-18 - Account selection: server-stamped updated_at (L4)

The selection rule is deterministic: the loop picks the most recently updated usable account.
Recency is grounded by a server-stamped `updated_at` written on every account write - seed and agent alike, symmetric with the server-stamped `origin`, so no client can forge the ordering.
This is the second small account-schema addition alongside D223-14's validity fact; both exact shapes are settled at implementation.
Ties (identical timestamps) fall back to the account's position in the store list, newest last.

### D223-19 - Account feeding: the account identifier rides the pipeline state, consumers resolve lazily (H1)

The gateway verdict produces the selected account's **identifier in the auth-context store** as a runtime recon state parameter, bound into the pipeline state - never the material itself.
Each phase's symbolic layer (the tool-configuration logic) resolves that account lazily from the store at the point of use, then projects only the subset of data the respective phase's tools need:

- request-based tools: the resolved auth header / cookies through the existing `extra["auth_context"]` transport, with the per-tool `_auth_header` serialisation unchanged;
- the crawler and browser tools: the account's persisted Steel profile key (D223-14);
- non-auth jobs: nothing - the `use_auth` gate remains the single eligibility check.

This yields a specific new wiring step in the current systematic tool-configuration logic (the seam where per-job `extra` is assembled; exact shape settled at implementation).
Role selection (`roles` / `default_role` are already account-record keys) resolves over the account record at use time, replacing `select_auth_context` over the retired settings blob (D223-4).
The crawler's auth path becomes profile-mount only: the interactive `steel_await_auth` human-in-the-loop path retires together with its `notify_awaiting_auth` operator prompt - post-gateway, auth is already established and a mid-run prompt is strictly worse.

## Open queue (dependency-ordered)

None - the sequential walk is complete.
Consolidated: the spec is `docs/design/recon-auth-gateway-223-spec.md`, published as the rewritten tracker issue #223 (`ready-for-agent`), superseding the ticket's earlier per-job auth-phase framing.
The decision-record and glossary amendments are applied: `auth-store-220-decisions.md` (D220-9 amendment), `browser-cli-221-decisions.md` (D18 amendment), `src/polymerhus/recon/CONTEXT.md` (auth gateway entry + updated store/binding/profile entries), `src/polymerhus/project_management/CONTEXT.md` (AuthContext retired), `docs/design/domain-model.md` (orchestrator activation note).