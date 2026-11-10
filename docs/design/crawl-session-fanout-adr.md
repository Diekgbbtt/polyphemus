# Crawl session fan-out: one account, one lifecycle

**Status:** implemented, 2026-11-09.
**Supersedes:** the `crawl_seed_urls` special case that appended `auth_probe` as a second frontier seed.
**Related:** `docs/design/steel-crawl-spec.md`, `docs/design/auth-store-220-decisions.md`, `docs/design/recon-auth-gateway-223-spec.md`, `docs/design/eval-data-dependency-placement-decisions.md`.

## Problem

The first iteration E crawl ran one lifecycle from the public root.
The public root does not link the admin console, so the coverage algorithm could not discover the authenticated backend.
The admin console was known to the auth gateway through the scaffolded `auth_probe`, but the crawl used that URL only for the oracle fetch.
A special-case seed then appended the admin probe as a second frontier root.
That fixed the admin page but left the domain model wrong:

- privilege level was not a session variable;
- one account could expose only one browser context, so the member and admin surfaces could not be crawled in one run;
- the public root, the member centre, and the admin console were treated as one surface;
- the crawl stopped at the first root's frontier instead of running every role's lifecycle.

The 2026-11-08 run made the gap concrete.
The admin oracle passed, but `/index/user/index.html` redirected to the member login because the admin `PHPSESSID` is not a member session.
`/index/User/set.html` sits behind that member login.
Those are role-scoped surfaces, not parser defects.

## Decisions

### D1 - One account is one session

The auth-store account is the session.
An account gains three optional fields:

- `role`: the privilege surface, such as `super_administrator` or `member`;
- `root_url`: the featured entry, a root-relative path in committed data (default `/`);
- `auth_probe`: that session's oracle, a root-relative path in committed data (default the root URL).

`roles` remains the credential-variant map.
The effective session role is `role`, then `default_role`, then no role.
An account with no role starts at `/`.
The existing `browser_context.ref` remains the account's one decoupled browser context.

### D2 - The oracle is per account

The oracle is the account's `auth_probe`.
When the probe is absent or empty, a non-4xx, non-3xx response at the account's `root_url` is the success rule.
The overview's `auth_probe` remains the legacy fallback for an account that declares neither.
The oracle is never shared across roles.
The admin dashboard and the member centre each prove their own session.

### D3 - One lifecycle per session, one pod, bounded threads

The `steel_crawl` pod runs one full `run_live_crawl` lifecycle per valid account.
A `ThreadPoolExecutor` bounds concurrency to `STEEL_CRAWL_MAX_WORKERS` (default `2`, the pool replica count).
The pod joins every thread before it finalizes.
Each lifecycle has its own run id, session name, browser context, root, probe, manifest, ledger, and summary.
No lifecycle starts another session and no lifecycle signs in.

### D4 - Each lifecycle starts at its session root

The lifecycle's `LivePageFactory` loads the session's absolute `root_url`.
It does not start at the public root and walk to the privileged surface.
The published `root_url` is the absolute value the preflight wrote into the pool record.
The crawl reads the loaded session's `role`, `root_url`, and `auth_probe` from the start report.
The auth descriptor is a consistency input, not a second source of truth.

### D5 - Duplicates are deduplicated downstream

Two sessions may capture the same public endpoints, scripts, or parameters.
The pod parses every successful session manifest.
The curator deduplicates by asset identity.
The pod never merges or drops a session manifest before the parse.

### D6 - A failed session is coverage, not a pod failure

One session may fail its oracle, its deadline, its lease, or its manifest parse.
The pod continues the other sessions.
Every successful manifest is ingested.
Every partial or failed session adds one `reduced_crawl_coverage` observation naming the session and the reason.
The pod fails only when no session supplied a usable manifest.

### D7 - No anonymous session by default

The crawl does not add an anonymous session when accounts exist.
An account with no role is already the baseline session at `/`.
The anonymous context-less session exists only when the auth store has no account at all.
If accounts exist but none is usable, the pod does not silently fall back to anonymous; it records the failure.
This keeps an all-stale auth store visible instead of hiding it behind a public crawl.

### D8 - The external preflight mints every session

The auth gateway selects one account for the request jobs and keeps that boundary.
The external preflight mints and verifies every credential-bearing account before the trial.
It writes each absolute `role`, `root_url`, and `auth_probe` into the pool record.
It sets the account `status` to `valid` on success and `not_valid` on failure.
The crawl's session list is the auth store's valid accounts, plus the anonymous fallback only for a zero-account store.

### D9 - Role coverage is documented, not heuristically validated

`overview.technical_conditions` carries one entry per role with the authenticated-request shape.
The authn skill prose covers the sign-in and sign-up procedure for each role.
The validator checks the account/session shapes and the deployment-neutral URLs.
It does not parse prose or score role coverage.

### D10 - Keep the confirmed crawl fixes

The partial-manifest ingestion, the 1800-second default budget, and the 30-second worker settle window remain.
The budget is per session lifecycle.
The settle window is per lease end.

## Rejected alternatives

- **Keep the auth-probe seed.** It covers one privileged surface and leaves the member and baseline sessions out.
- **One merged v2 manifest.** It hides per-session failure and makes the source session of an endpoint ambiguous.
- **One job-agent pod per session.** It bypasses the pod's thread bound and lets the job fan-out overrun the browser pool.
- **Anonymous by default.** It hides a stale or missing auth store and produces a false public-only success.
- **Role as a credential map only.** It cannot express a per-role root, probe, or browser context.

## Implementation

The implemented seams are:

- `app/auth/records.py`: `role`, `root_url`, and `auth_probe` validation.
- `recon/control/auth_feed.py`: `project_sessions` and `resolve_accounts`; `not_valid` accounts are skipped; `project_browser_auth` prefers the account probe and root.
- `kali/steel_pool/store.py`: `BrowserSessionRecord` role/root/probe round-trip.
- `kali/steel_pool/lease.py` and `kali/steel_pool/server.py`: the start report carries the loaded session model.
- `recon/crawl/sessions.py`: the bounded, join-all session orchestrator.
- `recon/crawl/crawl_pod.py`: per-session manifests, per-session coverage observations, and the zero-account fallback.
- `recon/crawl/steel/live.py`: the per-session root/probe and the anonymous verdict.
- `recon/control/pipeline.py`: every valid account is handed to the crawl.
- `docs/experiments/hunt-enhancement/iteration-e-siyucms-2026-11-08/seed_iteration_e.py`: the all-account preflight planner and the admin/member mint dispatch.

The per-component impact map and the residual live validation are in `docs/design/crawl-session-fanout-impact-map.md`.
The TDD seams are the five agreed boundaries:

1. Auth record validation and session projection.
2. `BrowserSessionRecord` and the browser-start payload.
3. The crawl session orchestrator.
4. Crawl-pod multi-manifest ingestion and curator dedup.
5. Preflight all-session minting.

## Evidence

The affected crawl, Kali, app, auth-feed, pipeline-gateway, authn-loop, bootstrap-validator, bootstrap-assessment, preflight-planner, and project-management suites pass: 3,871 passed, 42 skipped.
The full suite collects 8,099 tests; it did not finish inside the 20-minute command window.
The earlier 300-second live smoke proved the auth context and the partial/budget/settle fixes.
It used the removed admin-probe seed, so it is not evidence for this fan-out.
The next live run validates one lifecycle per valid account.

## Probe source label (2026-11-10)

The auth verdict's `probe_source` names the source that actually supplied the probe:

- `session.auth_probe` when the loaded session carries its own oracle;
- `account.auth_probe` when the account's configured probe supplies it;
- `session.root_url` when the root URL is the fallback;
- `overview.auth_probe.url` when the legacy overview probe supplies it;
- `legacy_surface_gate` when the surface gate is the last resort;
- `anonymous` for an anonymous session.

A probe resolved from the loaded session is never labelled as an overview probe.
The resolver is `crawl_session_probe_with_source`; the `AuthOracle` carries the label into the manifest and the trace.

## Request-cookie dedupe (2026-11-10)

The request-material projection dedupes cookies by name.
The snapshot is the broad capture; a repeated snapshot name keeps its first value.
The token list is the explicit auth fact, so a token-located cookie overrides a snapshot cookie of the same name.
The projection is internal to the recon request tools; it is never rendered into an agent prompt.


