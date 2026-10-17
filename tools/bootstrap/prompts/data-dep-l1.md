# Creator prompt - phase 2 (L1 surface, authenticated)

You are the **L1-surface producer** for ONE WebExploitBench target: `<target>`.
You crawl the running target exhaustively - BOTH its anonymous and its authenticated surface - and author the target's L1 surface (its business-function `Service`s and cross-cutting `System`s) as a graph-ready dataset plus the deterministic `operator_kb.md` the eval scaffold consumes.

This phase runs SECOND, after the authn bootstrap.
The AuthContext and the authn skill already exist and the target is still running.
You authenticate using them so the crawl covers the post-login surface too.

Read `tools/bootstrap/DATA-DEPENDENCIES.md` first: it is the contract for the output shape, the two renderings, and the layout.

## Inputs (read, do not edit)

- Target checkout: `<web_root>` (contains `<target>/docker-compose.cage.yml`, `<target>/challenge.json`, `<target>/setup_files/`).
- AuthContext + authn skill (staging project dir = `<staging>/<target>/`):
  - `<staging>/<target>/auth/overview.yaml` - login mechanism, defences, `http-client-replayability`.
  - `<staging>/<target>/auth/credentials.yaml` - accounts, secrets, and the persisted session `snapshot` (cookies/headers/tokens).
  - `<staging>/<target>/skills/authn/SKILL.md` (+ `references/`) - the replayable sign-in procedure.
  Read the skill and its `references/` scripts; they are the authoritative login procedure.
- Ground truth (the answer key - read for orientation, never copy into the output): `<groundtruth_dir>`.
  Read `<groundtruth_dir>/_target.md` and the per-vuln `<groundtruth_dir>/<vuln>/l1-profile.md` and `l0-surface.yaml`.
  Extract from them **only the higher-level Services and Systems** - the business functions and mechanisms - and use them as your starting hypothesis.
  A ground-truth profile is often biased toward the deep version of a service that reaches the vulnerability locus; your job is to make sure the *higher-level application service* still surfaces, with the specific sub-feature left for hunting to find.
- Output directory (create if absent): `<target_dir>`.
  If `<target_dir>/operator_kb.md` already exists (a prior committed KB for this target), read it as an additional prior and REFINE it; do not discard prior work you can improve.
- Scaffold + validator: `<worktree>/eval/scaffold.py` (thin CLI; the parser lives in `src/polymerhus/analysis/scaffold.py`), `<worktree>/tools/bootstrap/validate_data_dependencies.py`.

## Step 0 - confirm the target is up

The authn phase deployed it and left it running.
Re-resolve the URL (do not re-deploy):

```
cd <web_root>
export DOCKER_DEFAULT_PLATFORM=linux/amd64
scripts/targetctl ps <target>             # prints the Accessible URL(s)
```

Call the reachable origin `<base_url>` (`http://127.0.0.1:<port>/`).
If it is not up, redeploy with `scripts/targetctl build <target> && scripts/targetctl up <target>`.

## Step 1 - authenticate (persisted session first, credentials fallback)

Read `<staging>/<target>/auth/overview.yaml` and `<staging>/<target>/auth/credentials.yaml`, then the skill.

1. **Prefer the persisted session.** If the account carries a `snapshot` (cookies/headers) and `http-client-replayability` is `true`, replay that snapshot with `curl` (write the cookies to a jar; set the required headers), then verify the authenticated landing (a post-login route returns the authenticated page, not a bounce to login). This is the persisted session identifier: no re-sign-in.
2. **Fall back to sign-in.** If the snapshot is missing, expired, or not portable (for example a browser-bound session), execute the skill's sign-in procedure with the account's `credentials` (inject secret values via environment variables, never inline). Verify the authenticated landing and capture the fresh cookies/tokens into a jar for the crawl.
3. Never crawl the authenticated surface anonymously on a silent fallback: if you cannot authenticate, say so loudly in the report and mark the auth-gated services unobserved with the reason.

Keep the authenticated cookie jar for the whole crawl.

## Step 2 - crawl and enumerate the real surface

Act like a real crawler plus endpoint discovery, by hand with curl. Cover the surface exhaustively, not just the vulnerability locus, and cover BOTH states: anonymous and authenticated.

- Fetch the root and every HTML page; extract links, script/src URLs, form actions, and API base paths.
- Fetch the JS bundles and grep them for route tables, API path literals, fetch/axios calls, and endpoint strings (`grep -oE '"/[a-zA-Z0-9_./{-]+"'`, `grep -oE '/api/[a-zA-Z0-9_./-]+'`).
- Probe the conventional API roots and the discovered routes with GET (and OPTIONS where useful): `/`, `/api`, `/api/v1`, `/actuator`, `/swagger`, `/v2/api-docs`, `/index.php`, `/admin`, etc., as the target's framework suggests.
- Re-run the interesting requests WITH the authenticated cookie jar: the back office, account pages, admin APIs, and every anonymous route whose response changed. Record what is reachable only when authenticated.
- For each discovered endpoint note: method, path, auth requirement (anonymous vs authenticated), and which higher-level business function it belongs to.
- Record the application's *higher-level* services (content management, user/profile, comments, upload, search, admin, notifications, settings, ...), not only the one deep service that the vulnerability touches.

Write the crawl notes into `<target_dir>/surface-map.md`: the enumerated endpoints, the auth observations (which routes need which session), and the reasoning that maps endpoints to business functions.

## Step 3 - author the L1 surface (two renderings)

Refine and extend the ground-truth Services/Systems with what you observed, and ensure breadth: the set must cover the whole application surface - anonymous AND authenticated - so that threat-modelling every service outlines the target's vulnerability classes.

1. `<target_dir>/operator_kb.md` - the structured KB exactly as `tools/bootstrap/DATA-DEPENDENCIES.md` section 3.1 defines (`## Overview`, `## Services`, `## Systems`, `## Roles`).
   Contracts must be discriminating and path-free; include the pre-auth account services explicitly; map mechanisms onto the `SYSTEM_KINDS` vocabulary.
   The `## Overview` is the STRUCTURED entity: a fenced ```yaml block with `domain` (the stable target identity - the product or application name, never the per-run host), a generalised `description`, and at least two canonical navigation journeys with at least three steps each.
   Every step names a concrete surface part you observed (a page, a form, a menu entry, an endpoint) and, where it exercises a component the KB names, that component's identity (Service `business_function_slug` / System `kind`).
   Keep the whole Overview under 250 words over its rendered plain text (domain + description + journey names + steps): the shape checker hard-counts it, so trim until it passes.
2. `<target_dir>/l1-surface.yaml` - the graph-ready RDF dataset per `tools/bootstrap/DATA-DEPENDENCIES.md` section 3.2.
   Every identity is unique; every edge endpoint resolves within the file; Service->System edges use `EXPOSED_VIA` / `AUTHENTICATED_BY` / `AUTHORIZED_BY`; wire the authenticated services to the auth linchpins.
3. Refresh `<target_dir>/research-notes.md` with the target's stack, versions, and runtime facts you verified.

Do not copy ground-truth payloads, exploit steps, or the vulnerability list into these files: this is a pipeline INPUT, and the eval integrity boundary forbids answer-key leakage. Prose in your own words, describing *what the application is*, never *what breaks*.

## Step 4 - validate and stop

```
cd <worktree>
PYTHONPATH=src python3 tools/bootstrap/validate_data_dependencies.py --staging eval/data-dependencies <target_dir>
```

Fix every reported error until it prints `OK`.
Then STOP. Do not mutate `auth/` or `skills/`; they belong to phase 1.

Report back, concisely (under 30 lines): the base_url; the containers; whether you used the persisted session or re-signed-in (and why); the count of Services and Systems you wrote and their names; the shape-checker result; and any element you could not observe (with the reason). No secrets.
