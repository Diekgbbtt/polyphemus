# Auth store (#220) - design decisions

Status: decided.
This document is the decision ledger for ticket #220 (per-project shared auth store, read/write tool, operator seed path), grilled with the operator 2026-09-10.
It is the ADR equivalent for this change (`docs/agents/domain.md:42-49` - design specs carry numbered decisions, there is no `docs/adr/`).
Parent ticket: #220.
Blocking dependency for the skill half: #222 (runtime skill-load + data-section convention, OPEN at decision time).
Skill authorship (auth procedures, `references/` automation scripts, prompt coupling) is #220-owner follow-up work after #222 lands; it is not built here.

## D220-1 - Home: `src/polymerhus/app/auth/` subpackage

The AuthStore and the `auth_store` tool factory live in a dedicated `app` submodule (`src/polymerhus/app/auth/` with `store.py` + `tool.py` plus the T1 `records.py` seam and `__init__.py`), beside `clients/`, `llm/`, and `observability/`.
Skill data lives in the repo-root `skills/` directory, never in a bounded-context module, so the store never holds skill bodies - only the coupling hook (D220-2).
Two earlier homes were rejected for documented reasons.
`project_management/` was rejected because every consumer (recon, analysis, hunting agents) sits below it: homing shared state there would make the first upward dependency in the codebase, against the acyclic graph `project_management -> {recon (lazy), app}`, `recon -> app`, `analysis -> {recon.types (ACL), app}` (`docs/design/module-restructure.md:45-46`, verified import-clean in D220-8).
`recon/control/` (the implementer's earlier proposal) was superseded by operator ruling: shared auth components belong in `app`, not in any single bounded context.
The home imposes three hard constraints, all tested: `app/auth/` imports only stdlib, `yaml`, `threading`, and `langchain_core` - never `recon`, `analysis`, or `project_management` (an `app -> domain` import would cycle, since those modules already import `app`); every live collaborator (graph view, Steel resolver) is an injected callable with an absent-degraded default (CODING_STANDARD section 6); record validation is mirrored with citation, never imported upward (D220-7).
As-built 2026-09-11: the seam needs no injected collaborators at all - `steel` and `snapshot` are opaque validated blobs the agent resolves at use time (see the D220-4 supersession), so the injection constraint holds vacuously; `store.py` / `records.py` import only stdlib, `yaml`, `threading` (plus the app-layer path helper `app.data_root`, which imports only `pathlib` and performs no I/O at import - not one of the forbidden `recon` / `analysis` / `project_management` modules), and `tool.py` adds `langchain_core` / `pydantic`.
`project_management` keeps only the operator seed face: thin `PUT`/`GET /projects/{project_id}/auth` handlers plus repository use-cases delegating down into `app/auth/` (D220-5).

## D220-2 - `replay-manner` deleted; optional `technical_conditions`; procedures live in one future skill

The `replay-manner` enum from the first grill was wrongly designed and is deleted.
Its real role is a set of technical procedure conditions that must be asserted when a login fails unexpectedly while following the procedure in the overview, and it is optional.
The store carries it as `technical_conditions`: an optional overview-level list of `{name, check}` entries, absent by default.
All procedural knowledge (password-login flow, priv-esc variants such as a mass-assignment `role=admin` endpoint, registration flows) belongs in ONE auth skill, not in the store: a skill by technical definition embeds procedural knowledge, and this stream funds that pattern in the system.
That skill implies agent read/write/generation capability, which lands with #222; until then #220 builds no skill machinery.
The store-to-skill coupling is a per-account `procedure` label naming the skill procedure that minted or serves the account, plus the reserved `references/` convention: optionally configurable credential-bound scripts automating request-based login (where no anti-bot defence blocks it), end-to-end Steel-CLI browser login, and registration automation - one script per method, all authored with the skill.
`location: cookie | header | storage` on token records is retained: it is where a token lives, orthogonal to how a procedure uses it.

### D220-2 amendment (#223 - the header fact single-sources on the overview)

The header fact lives in `overview.required_headers` (the operator-owned login-mechanism fact, a list of `"Name: value"` strings); the account snapshot carries the point-in-time cookies (`+ captured_at`) and never duplicates the required headers.
The request-material projection (`recon/control/auth_feed.py::project_request_auth`) reads headers from the overview (parsed on the first colon; a malformed entry is skipped loudly, never fatal) and cookies from the snapshot, with header-located tokens overriding/merging as before.
Rationale: one fact, one owner - routing two fields of differing reliability doubles the divergence surface for no gain.

## D220-3 - Simplified two-file bucket layout

The bucket is `data/<project_id>/auth/` under the app-owned data root (`app.data_root.DATA_ROOT`, `<repo>/data/`, no env var; explicit-root constructor for tests), resolved through the one layout owner `app.data_root.project_dir` so the auth bucket sits beside `skills/` and `hunting/`; the fixed bucket dir joins `PROJECT_SCAFFOLD`, so `ensure_project` creates it at project creation like every other module bucket. It is lazily created at the first write.
SUPERSEDED (as-built 2026-09-11): the earlier `AUTH_STORE_ROOT = src/polymerhus/app/auth/data/` (a package-local root) was wrong - it contradicted the one app-owned data root every other store writes under (`SkillStore`, `HuntStore`, `HunterMemoryStore`, `PodMemoryStore`), so the store now defaults to `DATA_ROOT` and derives its bucket through `project_dir`.
It holds exactly two files.
`credentials.yaml` maps account names to per-account bundles holding credentials, tokens, and Steel browser-state together: `{accounts: {<name>: {origin, procedure?, credentials?, tokens: {<token_name>: {value, location, target?, expiry?}}, steel?, snapshot?, notes?, roles?, default_role?}}}`.
SUPERSEDED (as-built 2026-09-11): the `graph_evidence?` slot in the earlier shape is replaced by the concrete `snapshot?` (`{headers, cookies, params, captured_at}` per `records._check_snapshot`) - there are no stored graph queries in the store.
`roles?` / `default_role?` ride the account as the FR-AUTH mirror (each role set validated by the same credential rules, `default_role` naming a configured role).
`overview.yaml` is the operator-owned login-mechanism header: `{login_endpoint?, required_headers?, mechanism?, defences?, fingerprinting?, technical_conditions?, notes}` with `notes` as its distinct field.
There is no `produced/`/`consumed/` topology: it is an inbox-dispatch protocol with a mover consumer, and auth records are durable named state with no consumer (first grill, unchanged).
There is no separate tokens file and no separate notes file: per-account notes ride the account, shared notes ride the overview, and note content should graduate into the overview or `technical_conditions` wherever it generalises.
Record identity is the account/token name; file names never encode identity.

## D220-4 - Steel refs only; concrete snapshots, never stored queries

The durable reference form is reserved for Steel browser-state (`steel: {profile}` - the minimal cloud profile key, `records._check_steel` requiring only a non-empty `profile` string), whose keys are cloud-persisted and long-lived.
SUPERSEDED (as-built 2026-09-11): there is no injected Steel resolver in the store seam and no `steel_unresolved` coded miss - the store holds the profile key as an opaque validated blob and the agent rebinds it at use time through its browser tool.
Graph entities are never stored as placeholder-substitution queries: static programmed queries against a changing surface fail silently open, which is the failure this decision exists to prevent.
SUPERSEDED (as-built 2026-09-11): the resilient-stored-query half (`{cypher, params}` executed verbatim at read time through an injected read-only view) is deleted - no `cypher` lives in the store and there is no injected graph view.
Each account carries at most one concrete snapshot (`snapshot: {headers, cookies, params, captured_at}` - explicitly a point-in-time capture, strictly validated by `records._check_snapshot`).
Anything else in `steel` / `snapshot` position is a loud `auth_invalid` rejection.

## D220-5 - Seed API: new endpoints with explicit delivery semantics on errors

Operator seeding is a new REST face over the store, not an extension of `PUT /settings`: extending the settings blob would re-collapse the trust boundary D220-3 exists to create.
`PUT /projects/{project_id}/auth` accepts `{overview?, accounts?}`; present sections replace the operator-owned state (value-object replace semantics), absent sections are untouched, and agent-minted accounts are never modified or removed by a seed.
`GET /projects/{project_id}/auth` reads the full state back for the operator.
Every failure has an explicit delivery semantic, and each is tested: unknown project is 404; any shape violation is 400 `{ok: false, error: "auth_invalid", detail}` naming the offending field; the tool surface never raises into the turn - every failure is a coded JSON envelope (`duplicate_auth`, `duplicate_identity`, `auth_invalid`, `store_unavailable`; `operator_immutable` retired by D220-12); reading an unseeded project is a valid empty state, never an error.
SUPERSEDED (operator ruling recorded in the #220 spec - "replace, never 409"): the 409 `{ok: false, error: "auth_conflict", detail}` seed-collision path from the earlier grill is deleted.
The as-built `AuthStore.replace_operator_state` replaces operator-owned state wholesale while preserving agent-stamped accounts, and a seeded operator name colliding with a live agent record warn-drops the operator entry (the agent record wins) - the seed face (`seed_auth` / `seed_project_auth`) carries no conflict path.
SUPERSEDED (as-built 2026-09-11): the `steel_unresolved` tool envelope is deleted with the injected-resolver half of D220-4. SUPERSEDED further by D220-12: `operator_immutable` is retired, so the four live envelopes are `duplicate_auth`, `duplicate_identity`, `auth_invalid`, `store_unavailable`.

## D220-6 - Concurrency: per-project lock, atomic writes, novelty gates (unchanged)

Two writers cannot fork a record: a per-project `threading.Lock` covers every check-then-write and read-modify-write critical section (the `hunt_store` I2 pattern); every file write is atomic via temp-file plus `os.replace` (the I1 pattern); the first writer wins per record name and a duplicate create fails with the denoted `DuplicateAuthError` dedup signal (the G4 pattern); an agent name may never shadow an operator name.
The recon pipeline is untouched: the settings blob is not migrated and `use_auth` injection keeps working exactly as today.

## D220-7 - Validation mirrored at the home, never imported upward

The operator section keeps the `auth_context.py` shape rules (D23 credential fields, `{name, value}` cookies, RFC-7230 header names, no literal `Cookie` header, no CR/LF, roles-shape discipline where applicable) plus the new closed enums and reference shapes - but the rules live in `app/auth/store.py`, mirrored with a citation comment, because importing `project_management.auth_context` from `app` would point the shared bottom at the operator surface.
The `pod.py` reserved-key mirror is the precedent for this direction of duplication.
The settings-blob contract stays independent: it governs a different bucket.

## D220-8 - Recon-import investigation: no bug, no ticket

The suspicion that `attack/` and `analysis/` must not import `recon/` was investigated against the full import list (worktree evidence, 2026-09-10) and does not hold: every import is production code on a sanctioned seam, and the graph is acyclic.
`analysis -> recon.domain.types` is the anti-corruption seam itself (CODING_STANDARD section 2: `analysis -> recon.domain.types as the ACL`; e.g. `analysis/chunking.py:40`, `analysis/feed.py:51`, `analysis/l0_stream.py:29`).
`skill_for` from `recon/domain/skills.py` is the single-loader discipline consumed wherever a role bakes a prompt (`analysis/assigner.py:443`, `analysis/bootstrap.py:677`, `analysis/mechanism_typist.py:432`, `analysis/curation.py:178`, `analysis/data_modeller.py:654`, `attack/hunting/hunting_agent.py:145`, `attack/hunting/llm.py:234,240`).
`recon/control/targeted.py` is Interface Agreement B, documented as a reused seam in the hunting context (`attack/hunting/hunt_orchestrator.py:72`, `attack/hunting/llm.py:57`, `analysis/anatomy.py:144`).
`EXEC_TIMEOUT_S` / `MAX_POD_ITERS` from `recon/config.py` are the canonical exec-budget constants reused, not re-literalised (`attack/hunting/hunter_tools.py:67`, `attack/hunting/pod/config.py:23`, `attack/hunting/pod/tools.py:40`).
`default_exec_fn` from `recon/domain/pod.py` is the pod-template reuse (`attack/hunting/pod/tools.py:61`); `run_coro_blocking` from `recon/control/async_bridge.py` is the shared sync/async bridge (`attack/hunting/hunting_agent.py:635`, `attack/hunting/hunt_orchestrator.py:1453`, `attack/hunting/pod/tools.py:302`); `fetch_project_graph` from `recon/domain/graph_read.py` is analysis reading the published L0 substrate (`analysis/pod.py:54`); the L0 curator legs in `analysis/anatomy.py:325` write observations through the sole-writer seam, which is the sanctioned crossing.
The upward direction is clean: no module under `recon/` or `app/` imports `project_management`, `analysis`, or `attack` at module top level - the only crossings are the documented lazy ones (`recon/control/pipeline.py:357,374` into `analysis.feed`/`analysis.lifecycle`, the analysis-feed seam; `app/main.py:10,77` composition-root wiring).
`analysis/anatomy.py:386` (`select_auth_context` consumption) is operator-declared dead code and was struck as evidence; its cleanup is out of scope for #220 and no action is taken here.
No ticket is filed: there is no defect, only a suspicion closed by this decision.

## D220-9 - Project scope is tool-owned; the auth tool binds on the established patterns

The store keeps `project_id` on every call, but neither the `auth_store` tool nor the skill tools require an agent harness to thread it: `build_auth_store_tool(project_id=None)` and `build_load_skill_tool(project_id=None)` default to the control-plane project (`config.PROJECT_ID`, the deployment's single project - the recorded "effectively single-project execution" ruling), resolved LAZILY inside the factory so import touches no config/env (CODING_STANDARD section 6).
The auth capability binds to the stateful fleet exactly as the skills surface and the steel tool do: `auth_capable_binding(role_id)` (`app/auth/seams.py`) is the auth-capable extension of `skill_agent_binding`, adding the `auth_store` tool and the per-project `authn` procedure to the bounded set through the native `tools=` / `middleware=` / `context=` seams, never a per-site reimplementation.
The analysis-domain agents (assigner, mechanism_typist, data_modeller) never bind authentication capability; the recon job-specific agents take it when #223 lands.
The `authn` skill is project-authored (no canonical catalogue copy), so its L1 index line renders only when its bundle exists at `<data_root>/<project_id>/skills/authn/SKILL.md` - the project-scoped index resolution (`SkillStore.meta` + the `dynamic_prompt` middleware reading the context's `project_id`).
Full record: `docs/design/browser-cli-221-decisions.md` D18.

## D220-10 - Overview contract extended by #237

The overview key set gains `anti-bot` (the defence type, a free-form vendor/challenge name or null) and `http-client-replayability` (a real boolean; unset means UNKNOWN, distinct from false), validated by `validate_overview` and round-tripped by the read face; the closed-key refusal (D220-5) makes the extension explicit and tested.
The seed body is unchanged (`Any`-typed), so no new code path is introduced.
The full decisions for the producing procedure and the meta skill live in `docs/design/authn-antiblock-replayability-237-decisions.md` (D237-0..D237-8); this ledger records only that the overview contract it owns now carries these two facts.

### D220-9 amendment (#223, 2026-09-18)

The binding this record anticipated lands, and it lands on the recon orchestrator ONLY.
The auth gateway is fully armed in one step (D223-13): the roster exemption lifted, `auth_store` + the per-project `authn` procedure + `load_skill` / `write_skill` + kali `exec` + `steel_exec` bind together through the native `tools=` / `middleware=` / `context=` seams.
This supersedes the line above: the recon job-specific agents deliberately never take the binding (D223-5) - there is no per-job auth loop.

Two server-stamped facts join the account record for the gateway's bookkeeping (settled #241: the keys are `status` and `updated_at`): a typed validity status (`valid | not_valid`, D223-14) and `updated_at` for recency-based selection (D223-18).
The selected account's IDENTIFIER - never its material - rides the pipeline state, and each phase's tool configuration resolves the account lazily from the store, projecting only the subset its tools need; role selection (`roles` / `default_role`, already record keys) resolves over that record, replacing selection over the settings blob D223-4 retires (D223-19).

Full record: `docs/design/recon-job-auth-223-decisions.md` D223-1..D223-19; spec `docs/design/recon-auth-gateway-223-spec.md`.

## D220-11 - Credential-identity uniqueness gate (hard, at the store seam)

An account is keyed by the credential identity it authenticates, not by its name: the store refuses to create (or seed) an account whose credential username already belongs to another account.
The identity set is the default `credentials.username` plus every `roles.*.username`, so the gate compares per credential set, never per account (the `roles` shape is why).
The refusal is the new `DuplicateIdentityError` (`duplicate_identity`), raised inside `AuthStore.write`'s create path and inside `AuthStore.replace_operator_state` (each incoming seeded account is checked against the merged set, so a seed that forks itself or that collides with a kept agent account refuses; a pre-existing agent fork never blocks a later seed).
The repair the error names is role assignment: access for a known identity is a new ROLE on the existing account (`accounts.<name>.roles.<role>`), never a second account - the failure mode is an agent that has not understood the role-assignment aspect of the record.
Delivery semantics are explicit and distinct from the recoverable shape violation: the in-process `auth_store` tool returns the `duplicate_identity` coded envelope (never a raise), and the operator seed face `PUT /projects/{project_id}/auth` returns 500 with `{ok: false, error: "duplicate_identity", detail}` and lands nothing.
500 - not the 400 `auth_invalid` of a shape violation, and not a 409 (the "replace, never 409" ruling stands for name collisions) - because a fork is a HARD contract breach the operator must see, not a recoverable field error.
The gate covers both write faces because it lives at the shared store seam both delegate to; the account NAME stays the record identity, so the existing `DuplicateAuthError` name gate is unchanged and still fires first on a same-name create.
Forced by the #237 e2e defect recorded in `docs/design/authn-antiblock-replayability-237-decisions.md` D237-12.

## D220-12 - The operator section is writable; the trust-boundary refusal is retired

Operator ruling (2026-09-19): auth-store immutability is a DEFECT.
Neither the overview, nor the credentials (accounts), nor the project authn skill may be immutable to an agent.
This SUPERSEDES the `operator_immutable` refusal of D220-5, the "operator section stays agent-immutable" line of D220-3, and the D220-6 shadowing clause insofar as it refused merges.
It also supersedes #223 requirement 6 ("operator-seeded accounts stay immutable by agents, so that my ground truth remains trustworthy"), which requirement 15 (persist the profile key plus extracted tokens back to the account) cannot satisfy: the two requirements contradict, and 15 is the system's core loop.

The replacement, decided and stated:
- every agent write MERGES, into the overview and into operator-stamped accounts alike (tokens, status, snapshot, steel.profile, notes);
- `origin` is a PROVENANCE LABEL only (still server-stamped; an operator account keeps `origin: operator` through agent writes);
- `updated_at` refreshes on every write and seed (the store owns it, D223-18);
- `duplicate_auth` still protects account names and `duplicate_identity` still protects credential identities;
- `replace_operator_state` still never removes or modifies agent-stamped accounts (a seed replaces the operator section wholesale, so an agent's edits inside a seeded account are replaced by the next seed - accepted: the operator's ground truth wins on reseed).

The `OperatorImmutableError` class and the `operator_immutable` envelope are RETIRED ENTIRELY (operator ruling): the store no longer raises it, `app/auth/tool.py` no longer maps it, and `app/auth/__init__.py` no longer exports it.
The live envelopes are `duplicate_auth`, `duplicate_identity`, `auth_invalid`, `store_unavailable`; the coded-envelope discipline is unchanged.
Unchanged by this decision: `records.validate_account` / `validate_overview`, the per-project lock and atomic writes, the duplicate-create gate (any origin), and the server-stamped `origin` / `updated_at`.

### Coupled #223 interface change (APPLIED on this branch)

The #223 gateway consumer text flips from "never persist" to "persist", and the flip is applied on this branch: `recon/control/prompts/auth-gateway.md` (sections 1, 3, 4, 5 - the store is agent-writable, the validity assertion lands, the resolved replayability fact is persisted, and the prompt names the concrete `auth_store` and `write_skill` calls), `recon/control/orchestrator_agent.py` (the resolve_in_loop hint and its loud warning), `recon/control/authn_loop.py` (the boundary comment and the `GatewayVerdict` docstring), `docs/design/recon-job-auth-223-decisions.md` (D223-11, D223-12, IR-2, V-1), and `docs/design/recon-auth-gateway-223-spec.md` (requirement 6 and the account-resolution line).
The gateway harness itself never writes: persistence is the loop model's in-turn `auth_store` / `write_skill` calls, and the test pins exactly that split.

## Follow-up: AUTH-SKILL-1 RESOLVED

AUTH-SKILL-1 is delivered as the META skill `skills/meta/authn-skill-writing/` (meta family: exempt from the usage-protocol append by loader path, `is_meta_skill`), which the operator's external agent runs to author a TARGET PROJECT's `authn` procedure.
The procedure lives in that project's bundle (`<data_root>/<project_id>/skills/authn/`), is coupled to the store by the account `procedure` label, and rides every auth-capable agent's system prompt through the L1 skill index (D220-9; 221-D18).
The store built under this ledger carries only the hooks (`procedure`, `technical_conditions`, `steel` refs) and no skill bodies, exactly as D220-2 requires.

## Glossary candidates (ratify into `CONTEXT.md` with the implementation, not here)

Auth store (the per-project `data/<project_id>/auth/` bucket), account record (one named bundle of credentials, tokens, and Steel browser-state), operator section vs agent section (the trust split inside `credentials.yaml` plus the operator-owned overview), technical condition (an optional assertable procedure condition for unexpected login failure), browser-profile reference (the minimal durable Steel profile key), concrete snapshot (point-in-time captured request state, never a stored query), operator seed (the `PUT /auth` replace-operator-state operation), procedure label (the store-to-skill coupling name).
Owning glossary: `src/polymerhus/recon/CONTEXT.md` (auth is recon execution vocabulary: `use_auth` jobs, selection, and now the store the tool serves); `src/polymerhus/project_management/CONTEXT.md` keeps the seed-endpoint pointer beside the existing `AuthContext` entry.
`app/` itself gets no `CONTEXT.md` (helper rule, `CONTEXT-MAP.md`), following the session-seam precedent.
