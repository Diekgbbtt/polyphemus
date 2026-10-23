# ADR: the analysis-side read-only auth-store view

## Status
Accepted (2026-10-18).
Resolves #364 (found by the arm-J re-pass measurement; related #224, #243, #239).

## Context
- The arm-J measurement answered the operator's question ("do the typist and the assigner have access to the auth context?") with **no access, yes HTTP-history usage**: `_surface_tools` (`src/polymerhus/analysis/proposer_turn.py`) bound the assigner the HTTP-history pair only and the typist `graph_view` + that pair + `exec`; the Langfuse census showed zero `auth_store` calls from analysis roles on both arm-J targets, while the typist reconstructed request shapes by inferring them (URL filters, `Set-Cookie contains JSESSIONID`, `text=firebase`, ...).
- `auth_store` was bound recon-side only, and `recon/CONTEXT.md` carried the ruling as a flat prohibition ("the analysis-domain agents never bind it"). D223-5 forbids the authenticate/write capability, not the read of the store.
- Two walls stand between the ticket's instruction ("reuse the `auth_capable_binding` pattern") and a literal reuse, and both are facts of the code, not preferences:
  1. `ROLE_SKILLS` declares `assigner`/`mechanism_typist` EXEMPT, so `auth_capable_binding(role)` returns an inert binding - and it is pinned by a test.
  2. The analysis proposers deliberately carry NO skill surface (operator ruling 2026-09-17), so the gateway's `with_write_skill` arming path - the only exempt path that attaches `auth_store` today - is the wrong door: it brings `load_skill`, `write_skill`, and the `authn` procedure with it.
- Production wiring needs no store handle: the recon orchestrator takes `auth_store=None` and the store resolves lazily inside the tool factory (`AuthStore()` over the app-owned `DATA_ROOT`). The analysis process receives its collaborators the same way - nothing is passed down from `QueuedAnalysisFeed`.

## Decision
- **D364-1 (one tool, one name).** The view is the SHARED `auth_store` tool, built by the same factory (`build_auth_store_tool(project_id, store, read_only=True)`), keeping the tool name: the ticket's measurement counts anonymous calls by tool name, so the analysis-side read must be the same name the census already reports. The read-only form is a mode of one implementation, never a second tool face (`recon/CONTEXT.md`, "the auth-store tool": _avoid_ a second tool face).
- **D364-2 (redaction level - the record the ticket asks for).** The read-only view carries NAMES, SHAPES, AND STATUSES, never secret values. Redaction is applied to the FULL state BEFORE the dotted projection, so a narrow path cannot address a raw leaf either.

  | slot | read-only view |
  |---|---|
  | `accounts.<name>.credentials.password`, `accounts.<name>.roles.<role>.password` | `<redacted>` |
  | `credentials.username`, `roles.*.username`, `login_url`, `domain`, form selectors | kept - identity and request SHAPE (the username is already the account name by the store's naming rule) |
  | `tokens.<name>` (`location`, `target`, `expiry`), the token NAME | kept - this is the "cookie names / token status" the ticket asks for |
  | `tokens.<name>.value` | `<redacted>` |
  | `snapshot.cookies[].name` | kept |
  | `snapshot.cookies[].value` | `<redacted>` (the decided level: the cookie NAME is the request shape, the value is the reusable credential) |
  | `snapshot.headers.<name>` value, `snapshot.params.<key>` value | `<redacted>`, name/key kept |
  | `snapshot.captured_at`, `steel.profile` | kept - a timestamp and a reference key, not secrets |
  | `overview.*` (`login_endpoint`, `required_headers` header NAMES, `mechanism`, `defences`, `fingerprinting`, `technical_conditions`, `notes`) | kept verbatim - the overview carries no secret slot by the record contract |
  | `status`, `updated_at`, `procedure`, `origin`, `notes` | kept |
- **D364-3 (argument surface).** Bound handle: project id plus store, bound at build time - no identity parameter (the recon precedent). Request fields: `path` (the dotted projection) and `command` (default `read`). The `value` field is NOT on the read-only schema, so a write-shaped payload cannot be expressed; every command but `read` refuses in-band with a new coded envelope `auth_readonly`, raised BEFORE the store is touched - the code names the mode, so a refused write is never confusable with a store failure.
- **D364-4 (binding site).** Through the ONE auth-capability seam: `auth_capable_binding(role_id, ..., with_readonly_auth_store=True)` gains the store-only arming for a skill-exempt role (the read-only `auth_store` tool alone: empty middleware, empty skill context, no `authn` skill, no `load_skill`, no `write_skill`). The analysis turn binds it from `proposer_turn._surface_tools`, on EVERY turn of both roles, so the tool set stays constant across a role's reflection and extraction turns (the cache rule). No analysis module ever constructs the auth tool itself, so there is no second auth binding site to drift.
- **D364-5 (how the process obtains the store).** Same shape as the recon binding: an optional injected handle (`auth_store`) threaded through `analyse_chunked`/`run_analyser_chunked` -> each role's `stateful_invoke_fn` -> `proposer_turn.session_invoke_fn` -> `_surface_tools`, with the production default resolved LAZILY inside the tool factory (`AuthStore()` over `DATA_ROOT`). Production passes nothing, exactly as the recon orchestrator passes nothing.
- **D364-6 (fail-open, D223-5 preserved).** Absent project scope, an unbuildable auth seam, or an absent store binds nothing and the turn still starts (the `_surface_tools` contract); the surface tools survive an auth-seam failure and vice versa. No write or authenticate capability is bound: the read-only mode never builds the skill tools, and the bound tool refuses any command but `read` before touching the store.

## Considered options
- **A second tool name (`auth_view`)**: rejected - the census name continuity is what makes the arm-K trial measurable, and a second face over one store is the documented anti-pattern.
- **`command`-less schema**: rejected in favour of keeping `command` (default `read`): the refusal is explicit and testable, and the call shape stays identical to every other `auth_store` call in the system.
- **Redacting inside `AuthStore.read`**: rejected - the recon gateway and the job-specialised agents replay the RAW material (D223-19); the redaction is the analysis-side view's policy, so it lives with the tool, not in the shared store.

## Consequences and residual risks
- The analysis proposers can now type a request shape against the recorded session material, and the only channel to it carries no values.
- The redaction is a deny-list over the record contract's secret slots, and the store's account key set is CLOSED (every write path re-validates through the T1 seam), so the list is complete for anything the store itself accepted. A hand-edited bucket file carrying an unknown key is out of contract and is passed through: accepted, not defended.
- Acceptance criterion 3 ("no auth material leaks into graph deltas") stays a TRIAL-level observation: the typist also binds `search_http_history`, whose recorded responses may carry `Set-Cookie` values verbatim, so a leak through that channel is still possible by prompt failure alone. The redacted store view removes the store as a leak channel; it does not make the whole turn leak-proof.
- Neither role's PROMPT names the view (the tool's own description carries the contract, like every other bound tool); whether the model reaches for it is what the arm-K trial measures. A one-line nudge would belong in `analysis/prompts/technical-system.md` (assigner: `analysis/prompts/assigner.md`) if the trial shows it is not found.
- `overview.notes` and `technical_conditions[].check` are free text written by an operator or a prior agent; a secret pasted there would be visible. The record contract gives them no secret slot, so this is accepted, not defended.
- The read-only mode is honoured on the exempt-arming path; the flag is also threaded into a bound role's tool build so the mode stays total if a roster change ever un-exempts the analysis roles.

## Amendment 2026-10-23 - the modeller arming is read-only

The threat modeller uses the shared auth-capability seam's `arm_exempt_surface` path.
That path previously bound the full read/write `auth_store` contract.
It now binds `build_auth_store_tool(..., read_only=True)`.

This is distinct from D364-4:

- `with_readonly_auth_store=True` on a skill-exempt role binds the store-only read view, with no `authn` skill and no `load_skill`.
- `arm_exempt_surface=True` binds the project `authn` skill, `load_skill`, and the read-only `auth_store`.
  It is the modeller's shape, not the analysis proposer's shape.

The read-only contract is the same one the analysis roles use.
The full write contract remains for the recon gateway and the operator seed path.
The change is pinned by `tests/app/test_auth_seams.py::test_the_modeller_arming_binds_the_read_only_auth_contract`.

See `docs/design/hunting-context-dedup-2026-10-23-adr.md` D7.
