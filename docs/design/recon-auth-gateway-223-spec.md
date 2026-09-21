# Recon auth gateway - spec (the orchestrator's authn loop)

*Status: accepted, published as tracker issue #223 (`ready-for-agent`). This is the persisted repo copy of that specification; the tracker issue remains the work authority.*
*Decision ledger: `docs/design/recon-job-auth-223-decisions.md` (D223-1..D223-19, all in force; plus the T3 #242 implementation record IR-1..IR-8, the T4 #243 record IR-9..IR-12, and the T5 #244 verification record V-1..V-6). Amendments landed in `auth-store-220-decisions.md` (D220-9 amendment), `browser-cli-221-decisions.md` (D18 amendment), `src/polymerhus/recon/CONTEXT.md`, `src/polymerhus/project_management/CONTEXT.md`, and `docs/design/domain-model.md`.*
*Implementation: T3 (#242) landed - the gateway turn, the armed surface, the verdict, and the pipeline treatment are built (`recon/control/authn_loop.py`, `recon/control/orchestrator_agent.py`, `recon/control/pipeline.py`); T4 (#243) landed - the lazy auth feed (`recon/control/auth_feed.py`: identifier rides, assembly resolves, pod fills `{auth_flags}`) with the settings-blob, interactive-crawl, and mid-run-steering retirements removed with their footprints (ledger IR-9..IR-12 record the settlements). T5 (#244) verified live - gateway verdict before phase 0 with authenticated collection, loud fail-open on harness failure, loud fail-close with no collection on missing credentials (ledger V-1..V-6 record the runs, the trace pointer, the environment blockers, and the e2e-tier precondition).*
*Scope: the auth gateway itself - the orchestrator's pre-pipeline authn loop - plus the feed path from the shared auth store to the pipeline's consumers.*

## Problem Statement

A recon run can collect without ever authenticating.
The pipeline injects an operator-declared `auth_context` blob into `use_auth` jobs, and nothing verifies it at runtime: a stale cookie runs like a fresh one, a half-authenticated state runs like a full one, and an anonymous run is indistinguishable from a genuinely negative result.
The material has no runtime provenance: no validity fact, no recency, no failure signal the operator can act on.
The browser fallback is human-in-the-loop - an operator prompt mid-run (`steel_await_auth`) - and browser profiles were minted ad hoc with no project-scoped identity.
Sign-in knowledge lives nowhere the agents can improve it, so every run rediscovers the same defences.
Authentication is a phase that must happen before collection; today it is an assumption the system never checks.

## Solution

The recon orchestrator wakes as the **auth gateway**: before the pipeline is configured, it runs one stateful gateway turn - the **authn loop**, used by this role only - that establishes or validates the run's auth state against the shared auth store and the project's `authn` skill, then emits a structured verdict.
The pipeline configures from that verdict and obeys it: the selected account's identifier rides the pipeline state, each phase resolves the material it needs lazily, phases the verdict excludes are pruned, and collection runs to completion from the upfront configuration alone - no mid-run steering, no operator prompts.
Authentication failure is explicit and loud, never silent-anonymous; the no-authenticated-surface case is a first-class outcome; a missing credential prerequisite stops the run so the operator knows to seed.

## User Stories

1. As the operator, I want every recon run to authenticate before any collection happens, so that results are never silently anonymous.
2. As the operator, I want a failed authentication to be explicit and loud, so that I never mistake anonymous results for real coverage.
3. As the operator, I want auth established once up front by a single gateway turn, so that mid-run operator prompts and mid-run steering disappear.
4. As the operator, I want the selected account chosen deterministically (most recently updated usable account), so that repeated runs pick the same account given the same store.
5. As the operator, I want account validity recorded as a typed fact on the record, so that I can see what the system believes and when.
6. As the operator, I want agent writes to merge into the store (the overview and operator-stamped accounts alike), so that verified facts persist while my ground truth and its provenance stamp survive (D220-12).
7. As the operator, I want the no-authenticated-surface case recognised structurally, so that simple targets do not look like bootstrap failures.
8. As the operator, I want a run with no credentials at all to stop loudly, so that I know the bootstrap prerequisite was missing.
9. As the operator, I want the stored overview facts (anti-bot defence, HTTP-client replayability) to steer the gateway's branch choice, so that the topology is respected without mid-run guessing.
10. As the orchestrator, I want one ReAct gateway turn with a hunting-style passive state machine over my own tool calls, so that the loop's progress is machine-observable without micromanaging my judgment.
11. As the orchestrator, I want transition hints injected onto the triggering tool result only, so that my context carries one clear next step per transition.
12. As the orchestrator, I want to validate a request-replayable account by replaying its stored request state first, so that a live session is proven, not assumed.
13. As the orchestrator, I want a null replayability fact resolved in-loop by attempting the fingerprint replay, so that the unknown case ends in evidence rather than a guess.
14. As the orchestrator, I want browser-only targets to run exclusively through the Steel crawl path, so that request-tool shortcuts never contaminate a browser-only surface.
15. As the orchestrator, I want to mint a project-scoped browser profile (`<project_id>-<account>`) with `--update-profile` and persist the key plus extracted tokens to the account, so that the next run rebinds instead of re-authenticating.
16. As the orchestrator, I want a missing or unauthenticated profile to fail open into sign-in with the account asserted `not_valid`, so that the system never lies about validity.
17. As the orchestrator, I want failed sign-in attempts bounded by my own judgment (no mechanical cap) and the harness's generic bounds, so that a false cap never cuts a viable tweak short.
18. As the orchestrator, I want to declare the tweaking space exhausted through the terminal verdict, so that exhaustion is a recorded failure mode rather than a hang.
19. As the orchestrator, I want an outer skill-judging loop in the same turn, so that what I learned about this target's sign-in is written back through `write_skill`.
20. As the orchestrator, I want to run the gateway even when the target has no authenticated surface, so that every run has exactly one pre-collection decision point.
21. As a job-specialised agent, I want to receive already-resolved auth material without touching the store's internals, so that my tool surface stays narrow.
22. As the crawler, I want to mount the account's persisted profile instead of prompting a human mid-run, so that authenticated crawling is autonomous.
23. As the pipeline, I want to prune the phases and jobs the gateway's verdict excludes, so that a run never collects against a surface the gateway ruled out.
24. As the pipeline, I want to run to completion from the upfront configuration alone, so that no mid-run WAF steering is needed to keep it going.
25. As the external bootstrapper, I want to author the project's `authn` skill and seed accounts through the operator faces, so that I never need polymerhus internals.
26. As a maintainer, I want exactly one auth path (the shared store), one configurator (the orchestrator), and one procedure (the project's `authn` skill), so that debugging auth means inspecting one place.
27. As a maintainer, I want the authn loop's transitions documented and testable as a pure contract, so that the state machine can evolve without archaeology.
28. As a maintainer, I want the settings-blob auth path, mid-run steering, and the interactive crawl auth removed with their footprints, so that no shadow path can silently return.
29. As a future resume implementation, I want the forward invariant recorded - any resumed run re-runs the gateway first - so that resume cannot reintroduce silent anonymity.

## Implementation Decisions

### The gateway and its authority

- The orchestrator is the **sole auth-gateway decider** (D223-8): the pipeline awaits the gateway turn before phase 0; the actor decides the loop outcome AND the phase/job pruning; the pipeline obeys. No second decision point exists downstream.
- The account identifier is the **runtime recon parameter produced by the orchestrator and bound to the pipeline state** (D223-19) - never the material itself. Each phase's symbolic layer (the tool-configuration logic) resolves the account lazily from the store at the point of use and projects only the subset its tools need: request tools get the resolved header/cookies through the existing per-job auth transport, the crawler and browser tools get the persisted Steel profile key, non-auth jobs get nothing.
- Role selection (`roles` / `default_role`, already record keys) resolves over the resolved account record, replacing the retired settings-blob selector.
- The gateway is start-only in this scope (D223-9); no resume. The forward invariant is recorded: any future resume re-runs the gateway first.

### The authn loop (the core)

The whole gateway phase is ONE session turn on the orchestrator actor: `create_agent`'s internal model-tool loop, ending with the enforced structured gateway verdict (D223-15).
State tracking copies the hunting pattern strictly:

- a passive detect-and-push machine: transition detection is a pure function of the status verbatim observed on a specific tool call, never consulting current state; state moves never gate or reject a call (the no-block invariant); the harness is the sole writer of the tracker;
- the injected transition hint rides the TRIGGERING tool result only (never leaks onto a later result);
- observations are wired with the harness's tool-call middleware over the existing tool surface;
- the outer skill-judging loop is observable in the same turn: `load_skill` / `write_skill` calls after FINISH, then the gateway verdict.

The state machine implements exactly this transition table:

| State | Entered on (observable tool call) | Machine action / hint | Exits |
| --- | --- | --- | --- |
| GROUNDED | `auth_store` read of `overview` (or an empty path) AND `load_skill("authn")` both observed | mark grounded; hint: retrieve and select the account | RETRIEVED on an `auth_store` read of the accounts |
| RETRIEVED | `auth_store` read of `accounts` (or an empty read after grounding) observed | mark retrieved; hint: validate the selected account | VALIDATION on the first probe; GENERATION directly when the read returned no account |
| VALIDATION | first probe call after RETRIEVED: exec (request replay) or steel exec (browser mount/navigate) | mark validation; count the probe; hint: conclude valid or not_valid | FINISH when the validity assertion is `valid` or the terminal verdict says so; GENERATION when the loop writes the account `status: not_valid` |
| GENERATION | `auth_store` write asserting account `status: not_valid` observed | mark generation; hint: run the sign-in procedure | DEBUG at the second attempt call; FINISH when the sign-in succeeds and persists state |
| DEBUG | second and later attempt calls in the sign-in span | observe and trace each attempt; per-attempt hint; NO cap and NO rejection | FINISH on success, or when the model declares the space exhausted (terminal `exhausted` verdict); generic harness bounds backstop |
| FINISH | success: the `auth_store` write asserting `status: valid`, or the terminal gateway verdict; failure: the terminal `exhausted` verdict | record the verdict; run the outer loop; return the gateway result | terminal |

- The `status: valid` assertion is written on success for the same reason as `not_valid`: it gives the harness a call-level boundary instead of inferring it from the verdict.
- The consumed attribute contract (D223-11) has four branches: no defence (including absent or empty overview) -> request path; defence present with replayability false -> browser-only path, exclusively the Steel crawl; defence present with replayability true -> request path with a browser-first validation; defence present with replayability null -> the orchestrator resolves it in-loop by attempting the fingerprint replay, and the verdict then releases or prunes the run. The resolution is logged loudly and persisted to the overview by the loop (D220-12); disagreement is still recorded, never silently patched.
- Debug bounding (D223-16): no bespoke attempt cap, no duplicate-command rejection; attempt calls are observed and traced; the terminal `exhausted` verdict is the model's declaration; the only hard bounds are the harness's generic ones (the ReAct turn's recursion limit and the escalating per-attempt LLM budgets).
- Missing-data states (D223-17) are discriminated structurally in the store:
  - no authenticated surface (overview absent or carrying the structural no-auth marker): its own path - authn loop skipped, pipeline run anonymously, verdict records the finding; an empty store is the EXPECTED shape here;
  - external bootstrapper not run: with no credentials at all -> fail-close, stop the run loudly (this is a missing prerequisite, not a gateway failure, so fail-open collection does not apply); with credentials but no `authn` skill -> fail-open self-service: a request-based default driven by the store's description and procedure, with the thin-description risk accepted as a documented residual risk.
- Failure posture (D223-10): the gateway rides the existing harness failure suite (retry/degrade, exactly-one-reply, client fail-open with a warning, structured-parse degrade, tool-error handling, compaction fail-open, heartbeat vs reaper, cancellation semantics); asymptotic behaviour is fail-open, loudly. The uncovered gateway-specific risks carry implementation requirements: the heartbeat must start before the gateway (reaper window); a hang on an unknown or ignored message has no wall-clock bound today; silent schema mismatch must be made loud; the empty-signal short-circuit must not bypass the trigger gate.
- Authentication failure is fail-open for collection with no fabricated persistence (D223-2); the verdict vocabulary is success or failure, and "coverage exhausted" is a failed authentication, never a third state (D223-3).

### Account state and the store

- The account record gains two server-stamped facts, exact shapes settled at implementation: a typed validity status (`valid | not_valid`, D223-14) and `updated_at` (D223-18).
- Selection is deterministic: the most recently updated usable account; ties fall back to list position, newest last.
- The browser path mints with `steel start --profile <project_id>-<account> --update-profile` and persists the profile key plus the extracted tokens back to the account (D223-14).
- The operator seed faces (`PUT` / `GET /projects/{project_id}/auth`) are unchanged; the operator section is agent-writable - agent writes merge and keep the `origin: operator` stamp as provenance (D220-12) - and the agent section is the agents' own.

### Arming and roles

- The orchestrator is **fully armed in one step** (D223-13): the roster exemption is lifted and `auth_store`, the project's `authn` skill, `load_skill`, `write_skill`, kali exec, and the Steel exec tool bind together through the native tool/middleware/context seams. The actor's response format moves from the retired routing schema to the gateway/loop outcome once the routing turns retire.
- The job-specialised agents deliberately never authenticate and never take the binding (D223-5).
- The gateway attaches to the existing orchestrator role (`job_orchestrator`); no new role id is minted (D223-1 superseded in part). The global MODEL-infix-drop env-key rename stands, landed in #240 (D223-1).

### Retirements

- The settings blob's `auth_context` is retired with its full footprint (D223-4), including the settings-side selector - landed in T4 (#243): the pipeline injection, the blob-side role selector, the project-management value object and its settings validation, and the blob-era `{auth_header}` template name are gone; the per-tool header serialisation lives on in the feed, re-sourced from the store.
- Mid-run steering is retired as redundant (D223-12): the signal reader, the phase-exclusion/routing machinery, and the steering payload are removed; the pod throttle went with them as the recorded orphan - request phases run unthrottled in the interim (arjun's static cap excepted) until the rate-limit work (#238) lands its profile-driven configuration.
- The crawler's interactive auth path retires (D223-19): profile-mount only - the persisted cookies seed the browser context, the profile key rides for the profile-capable tooling; the operator-prompt notification path and the autonomous credentialed login went with it.

### Rollout and integration

- Rollout is not canary-gated (D223-6); all `use_auth` jobs ride the gateway once it lands.
- Integration override for this work (D223-7): the branch fast-forwards `dev` and pushes both; no pull request; `main` is never touched; the live e2e precondition still applies.

## Testing Decisions

- The gateway is the **first pipeline phase**, not an injectable collaborator: tests exercise the real boundary. No gateway injection seam is introduced for testability.
- Test tiers are the final-result seams: unit tests for the pure transition contract of the authn loop and the record validation; integration tests at the pipeline phase boundary (gateway-before-phase-0, verdict-driven pruning, account-id-in-state, no mid-run steering); end-to-end tests against the live eval targets (`tests/e2e/fixtures/eval-targets.yaml`).
- Good tests assert external behaviour only - the tool calls the phase makes, the verdict it emits, the phases pruned, the material resolved per consumer - never internal wiring or private helpers.
- Modules under test: the authn loop's state machine (pure transitions and hints), the gateway phase in the pipeline, the auth-store records (new facts, server stamping), and the consumers (per-job configuration projection, crawler profile mount).
- Prior art: the hunting state-machine tests, the recon pipeline tests, the auth-store tests, and the eval-target e2e runs.
- Contract and e2e assertion authoring belongs to the development pipeline stretch that follows the `/to-assertions` procedure after this spec; assertions are not enumerated here.
- Integration precondition (ledger V-6): `tests/e2e/fixtures/eval-targets.yaml` does not exist on this branch and still describes the retired settings-blob `auth_context`, so the live e2e assertion tier for the gateway is unverified on-branch and must be brought current (seed faces plus the `skills/authn` bundle) before mechanical evals run.

## Out of Scope

- Rate-limit system mapping and bypass testing (#238) - the post-authn loop that measures the target's throttling and feeds the pipeline configuration.
- The anti-bot classification and replayability additions to the overview contract and the meta skill procedure (#237).
- Proxy support (#196).
- Resume of a recon run (D223-9 records only the forward invariant).
- Canary rollout (D223-6).
- Pull-request-based integration for this work (D223-7: the integration override applies).
- The hunting module (its agent already carries statefulness; nothing here changes it).
- The context-memory scaffold that also reserves the orchestrator role.

## Design Risks

### Network identity is not persisted with the browser profile (2026-09-21)

User stories 15, 16, and 22 rest on one profile key standing for the account's browser identity across runs, and D223-14 mints `<project_id>-<account>` with `--update-profile` and rebinds it later.
That key persists **browser** identity (cookies, storage, history) but not **network** identity: Steel states it directly ("Profiles persist browser identity, not network identity - pair with a dedicated IP for account-based agents"), and the observable consequence is the "impossible travel problem" - the same cookies return from a new origin, which is how accounts get challenged or flagged.
Measured on 2026-09-21: three sessions in one sitting egressed from three distinct datacenter ASNs (`216.246.40.79` CacheFly, `152.233.48.155` Datacamp, `64.34.81.170` Latitude.sh), with and without the profile mounted, while the browser reported one stable user-agent and `America/New_York`.
The session proxy is disabled by default and this spec puts proxy support out of scope, so nothing in the current design pins an egress; the store holds no network-identity fact and the profile key cannot express one.
Impact on this spec's design: every rebind is a same-cookies/new-IP event, and the fail-open branch (user story 16) then performs the single most score-punished action - a fresh credential login - from yet another new origin.
A magnific.com bootstrap on 2026-09-21 was held by a visible reCAPTCHA Enterprise challenge after exactly that sequence; a mount-and-verify of the same stored profile reached the authenticated landing with no challenge at all, so the risky path was also the unnecessary one.
The gateway's browser sign-in path additionally carries no humanization (`--stealth`, whose automatic CAPTCHA-solving half is excluded by operator ruling), no interaction-cadence discipline, no challenge protocol, and a 10-minute session cap that expires while a human solves, so a low score has no recovery.
The crawl path is separate: the Steel crawl provider sets `humanize_interactions` through the SDK and rotates its region per session, neither of which the CLI sign-in path can reach.
Remediation, and where each half landed: mount-and-verify with a warm write-back is implemented in the external bootstrap (#237, D237-15); one stable egress origin and a consistent environment are the subject of #245 (a local Steel open-source runtime deployment), because no proxy work in this repo supplies an egress; and Steel-side CAPTCHA solving is excluded by operator ruling, being costly and not portable to a local runtime.
Full evidence and the reproducible probe: `docs/design/authn-antiblock-replayability-237-decisions.md` D237-14 and `tests/e2e/harness/recaptcha_challenge_probe.py`.

## Further Notes

- The authn loop is used by the orchestrator only; this spec supersedes the earlier per-job auth-phase framing of this ticket (stateful job agents each running an auth phase). The job-specialised agents never authenticate (D223-5).
- The external bootstrapper authors the project's `authn` skill and seeds the store through the seed faces; the meta skill `skills/meta/authn-skill-writing/` is its entry point, and #237 owns its next revision.
- The decision ledger is the authoritative record for every ruling compiled here; where this spec and the ledger disagree, the ledger wins and the spec is corrected.
