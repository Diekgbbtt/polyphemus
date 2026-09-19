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
*The global MODEL-infix-drop env-key rename below stands unchanged.*
*Landed 2026-09-18 (#240, `feat/223-stateful-recon-job-auth`): the rename is complete - every role record, caller, test, compose file, and environment document uses the infix-free `LLM_<NAME>` spelling; the migration-window fallback is removed and no legacy-infix reference remains.*

A new role id is minted for the stateful recon phase specialist; the existing `job_orchestrator` id is NOT reused.
Capability and policy attach to the role id (model, turn mode, `ROLE_SKILLS` surface, compaction, trace tags), so two different agents sharing one id would share one capability set - and sharing would arm the run-level macro-router with the specialist's surface.
The role's exact duty is being redefined in the operator's workflow-overview pass (D223-5); the identity and naming decisions are settled now.

The model-key environment variables drop the redundant `MODEL` infix (the `LLM_<NAME>` spelling): the infix repeats what the `LLM` acronym already says.
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
Settled (#241): the validity key is `status`, closed values `valid | not_valid`, absent until asserted; any other value refuses with the existing in-band coded error (`auth_invalid` naming `account.status`).

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
Settled (#241): the recency key is `updated_at` (an ISO-8601 UTC string from the one `_utcnow_iso` seam, stamped on every account write and operator seed - one stamp per seed, so seeded accounts tie; a client-supplied value is overwritten, never trusted).
Selection is `records.select_recent_usable_account`: most-recent `updated_at` first (a missing stamp sorts oldest), ties fall back to the account's position in the store list, newest last, `not_valid` records skipped as unusable, no usable account yielding None for the gateway's missing-data path.

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

## T3 implementation record (#242, the core auth gateway)

Settled at implementation under the ticket's authority (implementer
settlements, not operator rulings - numbered IR to distinguish them from the
D-series above). All D223-8..D223-19 hold; nothing here amends them.

### IR-1 - The empty-path read retrieves (the unconditional GROUNDED exit)

`detect_transition` maps an empty-path `auth_store` read to `retrieve`, not
`ground`: the full-state payload carries the accounts, and the spec table's
GROUNDED exit ("RETRIEVED on an accounts read", D223-15) is unconditional.
`push_transition` records the grounding evidence from the same payload
alongside. A usable full-state read therefore moves the loop even when the
skill half of grounding is still open; the skill load is then observed
silently. The grounding hint still fires for the classic
overview-then-skill order.

### IR-2 - The validity boundary is the assertion act, not its persistence

`invalidate` / `validate` are detected on the write CALL args (path plus
carried `status`), regardless of the result envelope. Rationale: on an
operator-stamped account the store refuses `operator_immutable` (the trust
split), and the loop must still cross its success/failure boundary - the
validity then rides the verdict instead. The prompt instructs exactly this
(carry on after `operator_immutable`).

### IR-3 - The no-auth-surface marker is `overview.notes`

The D223-17 structural discriminator is settled: `overview.notes` carrying
"no authenticated surface" (case-insensitive; the only free-text overview
field). Gate rule (`classify_gate`): any accounts at all run the loop (even
all-`not_valid` - the loop judges, the gate does not); with no accounts, a
marked or undeclared surface is the expected-shape anonymous path, while a
declared surface (any truthy non-`notes` field) with no accounts is the
missing prerequisite that stops the run.

### IR-4 - Browser-only prunes literally to the Steel crawl

`prune_plan` keeps exactly `steel_crawl` jobs on `browser_only` (D223-11,
implemented literally - discovery included). The pipeline obeys the
verdict's `branch` through this one rule; the verdict carries no separate
job list (sole-decider discipline, D223-8). The verdict `branch` vocabulary
is the collapsed pair (`request` | `browser_only`); the pre-loop manner
directives (`request_browser_first`, `resolve_in_loop`) do not survive the
turn.

### IR-5 - The gateway await is bounded at one hour, never cancels

`GATEWAY_AWAIT_TIMEOUT_S = 3600.0`: a hung turn returns None (fail-open,
loudly) instead of stalling run start. The turn itself is NOT cancelled at
the bound (its harness bounds own turn length); the reply inbox drains
best-effort, and the actor is per-run with a single gateway turn, so no
later consumer can meet a stale reply. The pipeline reaps the actor in its
existing `finally`.

### IR-6 - T3/T4 boundary as built

T3 retires: the per-phase routing turns (actor `response_format` is now the
gateway verdict), the pipeline's per-phase routing calls and exclusion
filter, the `decide_routing` consultation (parameter kept, ignored).
T4 (#243) owns the full REMOVAL, left in place dead or bypassed and marked
`#243 (T4, removal)` at each site: `RoutingDecision` + `_exclusions_map`,
`_phase_exclusions`, the `decide_routing` parameter, `read_steering_signals`
(the read still runs), `extra["steering"]` threading, the settings-blob
`auth_context` path (`select_auth_context`, `{auth_header}` templates, pod
serialization), and the crawler interactive auth path (`steel_await_auth`).
The `use_auth` gate and per-job `extra["auth_context"]` transport are
unchanged; `extra["auth_account"]` (identifier only) rides beside them until
T4 rewires the consumers to lazy resolution.

### IR-7 - In-scope test expectation updates

`test_H5_tool_schemas_ride_the_session_turn` now expects the armed hunter
surface (`auth_store` appended last - the f7e2bfd binding, asserted here).
`test_actor_binds_the_three_tools_plus_load_skill` is renamed to
`test_actor_binds_exactly_the_three_tools`: the hunt orchestrator stays
roster-exempt (no skill surface), so the surface is exactly the three G3
tools. The #223 arming targets `job_orchestrator` only (IR-8).

### IR-8 - The exemption is lifted through the binding, never the roster

`ROLE_SKILLS["job_orchestrator"]` stays `()` (the skill-seam exempt pins
hold; no catalogue skill bears). The arming rides
`auth_capable_binding(..., with_write_skill=True)`, which composes the
`[load_skill, write_skill, auth_store]` surface with the `authn`-only skill
context from the shared skill primitives. The flag is compositional (it
appends `write_skill` on bound roles too); no caller passes it today except
the gateway.

## T4 implementation record (#243, the auth feed and the retirements)

Settled at implementation under the ticket's authority (implementer
settlements, not operator rulings - numbered IR to distinguish them from the
D-series above). All D223-1..D223-19 hold; nothing here amends them.

### IR-9 - The feed: identifier rides, assembly resolves, pod fills

The feed (`recon/control/auth_feed.py`) implements D223-19 as: the verdict's
account IDENTIFIER rides `extra["auth_account"]` for `use_auth` jobs (bound
beside, never instead of, the projection); the pipeline's per-job assembly
resolves the account from the store at that point (per phase, right before
the phase runs - the lazy point of use) and projects the subset: the flat
request material (snapshot headers plus header-located tokens; snapshot
cookies plus cookie-located tokens; storage-located tokens skipped as
browser-bound) through the existing `extra["auth_context"] transport, plus
`extra["steel_profile"]` and the cookie subset for the agent-driven crawl.
The pod serialises the flat projection per tool at fill time into the
`{auth_flags}` template slot. `use_auth` stays the single eligibility gate;
an unresolvable account fails open (unauthenticated, loudly).

### IR-10 - Reconciliation: the slot is renamed, the serialiser moved

D223-19 keeps "the existing `extra["auth_context"]` transport, with the
per-tool serialisation unchanged"; D223-4 and the ticket retire "the
pod-side header serialisation and its flag/reserved-key tables" and "the
command-template auth placeholders". Both are honoured by moving, not
deleting, the mechanism: the serialiser (`_iter_auth_headers`, the
`-H`/`--headers` flag tables, the reserved-key set, the shell quoting)
moves pod-side to the feed module with byte-identical behaviour, and the
template slot is renamed `{auth_header}` to `{auth_flags}` - the blob-era
name is gone from every live template, pod, and feed reference (dated
plan histories intentionally keep it as the record of what was removed)
while the insertion positions the retired mechanism needs (notably the
mid-command slots in the ffuf/arjun chains) are preserved. The reserved set keeps the blob-shape keys (`roles`,
`default_role`, `realm`) as defence in depth: the backward-recon seam
still threads caller-supplied flat credential maps through the same
serialiser. A repo-wide search finds no `{auth_header}` in any live template, pod, or
feed reference, no `select_auth_context`, no settings-blob auth path.

### IR-11 - The crawl mounts the persisted profile through the SDK

The crawl node threads the bound profile key the whole way down - pod
extra to `run_crawl_fn` to `run_crawl` to `get_crawl_tools` to the
provider - which mounts it read-only at session creation (the Steel SDK's
native `profile_id` session-create kwarg, no `persist_profile` write-back,
so concurrent pods never race on one profile's last-writer state; a mount
the platform rejects falls back to the unprofiled session ladder). The
feed-projected cookies still seed the browser context beside the mount.
No interactive path, no credentialed login, no operator prompt (`notify.py`,
the viewer-URL surfacing, the pipeline pass-through, and the provider's
`steel_await_auth` tool with its detection predicates are all removed).
The D23 autonomous credentialed login retires with the crawl path for one
reason: its only credential source was the settings blob, and the ticket
makes the crawl profile-mount only - post-gateway auth is established and
persisted (profile key plus tokens), so a mid-run login is strictly worse.
If a record-sourced credentialed login is wanted back, it is a restoration
with a new source, not a silent shadow.

### IR-12 - Throttle interim posture (the D223-12 sequencing note)

Removing the steering input leaves request phases UNTHROTTLED in the
interim - recorded here, not silently accepted. What remains: arjun's
static `--rate-limit 5` (the measured 5-rps cap, independent of steering)
is the only request cap; the ffuf `{rate_flags}` throttle slot, the
`configure_fn` turn, `PodConfig`, and the per-job steering input are gone
with the steering machinery. The `configurator` ROLE record
(`LLM_CONFIGURATOR`, session mode, roster-exempt) stays in place for the
#238 rate-limit work to bind its profile-driven configuration onto - no new
role is minted then. The pipeline performs no live-database reach per
phase anymore (no signal refresh under the loop).

## T5 verification record (#244, live verification and integration)

Live runs against soupmarket.shop (the juice-shop-remote shape: OWASP Juice
Shop 20.1.1, request branch, operator-seeded shopper account with a freshly
minted JWT) from the worktree stack, 2026-09-18/19. Entries are V-numbered
(verification evidence, not implementer settlements). No secret values are
recorded here; the run rows live in the shared postgres.

### V-1 - Positive run: gateway verdict before phase 0, authenticated collection

Run `9a9161ad-5fb0-47c4-9466-ae43d588cecf` (project
`t5-gateway-verify`, jobs `[httpx, steel_crawl]`, `with_analysis=false`):
the gateway turn ran 00:09:53-00:10:27Z and the pipeline logged
`authenticated as account shopper` at 00:10:27, before phase-0 httpx started
at 00:10:27.5. The httpx command carried the feed-projected live token
(`-H 'Authorization: Bearer <jwt>'`); phase 0 succeeded (16 assets).
Langfuse trace `4d246a1a426fc286071263e0f429e651` (session
`9a9161ad-...:job_orchestrator`, cloud.langfuse.com, 45 observations) shows
the ReAct surface: `auth_store` + `load_skill` reads, `execute_command`
replay probes, the terminal `write_skill` outer-loop call, then the verdict.
No mid-run steering or operator prompt fired (both retired in T4; the trace
carries no such call). The account carries no `status` fact: it is
operator-seeded, so the store refuses the loop's write (`operator_immutable`)
and validity rides the verdict instead (IR-2, observed as designed).

### V-2 - Degraded run: harness failure fails open, loudly, unauthenticated

Run `91a20b6a-f4fc-471d-870a-09385de1f44f` (same project, same jobs):
the gateway turn hit upstream 500s on the configured orchestrator model
(see V-4), retried per the harness schedule, degraded at 00:58:46Z - the
actor posted its no-decision reply and both the gateway client and the
pipeline logged the fail-open (`gateway degraded (no verdict); fail-open:
every phase runs unauthenticated`). Phase-0 httpx then ran with NO auth
flags and succeeded. D223-10 observed live, including the actor-survives
path; the unauthenticated command shape proves no material leaks into the
fail-open run.

### V-3 - Negative run: missing credentials stop the run, loudly, with no collection

Run `4c4a53e2-39e3-4c8d-ac4a-9d8df0195a90` (project
`t5-gateway-negative`: declared auth surface, zero accounts): the gateway
refused within one second (`declares an auth surface but stores no
credentials; stopping the run (fail-close: seed accounts via PUT
.../auth)`), the pipeline logged `stopped by the auth gateway
(fail-close: no credentials)`, and the run reads `failed` with
`current_phase: null` and an empty job list. Authentication that cannot be
established never runs silently anonymous (D223-17).

### V-4 - Environment blockers (no code impact)

- The configured orchestrator/crawler model
  (`opencode:opencode/muse-spark-1.3-contributor-free`) is unusable here:
  the bare id 500s upstream (`Internal server error`) and paid ids refuse
  with `Insufficient balance` on the `API_KEY_OPENCODE` workspace; the
  `API_KEY_OPENCODE_GO` workspace reports `Monthly usage limit reached`.
  Direct provider probes, same results outside the stack.
- Verification substituted `swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731`
  for `LLM_JOB_ORCHESTRATOR` and `LLM_CRAWLER` in the worktree `.env` only
  (gitignored, never committed); the operator's configured defaults and all
  code are untouched.
- The live crawl tool-loop did not run: the #108 capability gate refuses
  models whose registry record lacks `supports_function_calling`, and every
  reachable (funded) model resolves `unknown` - all 106 `true` records sit
  behind the exhausted opencode keys. The steel_crawl pod degraded to the
  empty manifest loudly (`crawl REFUSED the tool-loop ... bind_tools not
  attempted`). The profile-mount path (IR-11) therefore stays covered by the
  unit tier (`tests/recon/crawl`, `test_auth_feed` - 163 passed, 5 skipped);
  a live mount needs a funded tool-capable key and is operator-side work.
- `tests/e2e/fixtures/eval-targets.yaml` exists only outside this branch
  and still describes the retired settings-blob `auth_context` input; the
  runs above seed through the current faces instead (`PUT settings` with
  `target_seed`, `PUT .../auth`, the `skills/authn` bundle).

### V-5 - Integration outcome

`feat/223-stateful-recon-job-auth` pushed to origin per D223-7. `dev` was
NOT fast-forwarded here: `origin/dev` does not contain this branch's base
(`c126f86`), so a true fast-forward is impossible - the lineage conflict is
surfaced, not forced, and `main` was never touched.