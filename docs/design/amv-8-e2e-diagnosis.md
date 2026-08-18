# AMV-8 live e2e — diagnosis of param-yield and restapi-profiling failure modes

Target: local OWASP Juice Shop behind the aliased `https://soupmarket.shop` (nginx proxy, self-signed cert).
Run: project `ff6ef8f2`, run `2360b8c0`, 2026-07-24. Full recon minus domain-name discovery and steel_crawl.
Method: /systematic-debugging + /langfuse (traces + TOOL spans) + graph census + direct tool reproduction.

## Result recap
- 100 Endpoints, all katana. AMV-8's six targeted noise categories: 0/100 (baseline 31%).
- 3 Parameters total. 1 BaseURL (`soupmarket.shop`, profile=`webapp`). kiterunner + graphql-cop skipped.

## Item 3 — why so few Parameters (root cause)

Param-producing tools and their measured outcome:
- **katana**: 3 query-string Parameters (`to` on /redirect, `email` on /rest/user/security-question, `current` on /rest/user/change-password). Inherently few — Juice Shop is a JSON-body SPA, not a query-param app.
- **jsluice**: 0 by design — `_parse_url_entry` strips query params (`url_to_deltas(...)[:2]`).
- **ffuf**: 0 by design (produces only Endpoints) and was `degraded` this run.
- **arjun**: **0** — the failure to diagnose.

### arjun root cause (NOT what it first looked like)
Langfuse TOOL spans: every one of ~100 arjun pods returned `{"stdout":"{}","returncode":0,"duration_ms":~10000}`. The `printf '{}'` seed file is never overwritten → 0 params → returncode 0 → pod marked **success** (the AMV-14 "empty == success" trap).

Direct reproduction in the kali container (correct PATH `/opt/venv/bin`):
- `arjun -u .../api/Products` → `Probing the target for stability` → `Skipped ... due to errors`, ~11s.
- `arjun -u .../rest/user/login` → same skip, ~78s.
- **`arjun -u .../rest/user/whoami` (a healthy 200/0.3s endpoint) → full scan (103 chunks, 42s), FOUND parameter `callback`.**

**First hypothesis (self-signed TLS) was DISPROVEN by the discriminating test**: arjun completed a real scan against the self-signed target on the healthy endpoint, so TLS is not the blocker (`requests` verify=True raises SSLError, but arjun tolerates it). 

**Actual root cause:** arjun skips any endpoint whose *stability probe* returns errors/timeouts. During the arjun phase the target was overloaded (Juice Shop holds ~1.96 GiB of the 3.83 GiB host and had just served the torn-down run): measured live — root `/` 200 in **9.8s**, `/api/Products` **times out (000)**, `/rest/products` **500**, only `/rest/user/whoami` healthy (200/0.3s). So arjun's probe failed on nearly every endpoint → "skipped due to errors" → 0 params.
Contributing: arjun also ran against many non-param endpoints (GET on POST-only login, `/zone.js`, `/ftp/*.url`, the `{{href}}` artifact).

**Systemic finding (not target-specific):** a throttled/blocked/slow-target arjun is *indistinguishable from "found nothing"* — returncode 0, empty seed file, pod `success`. This is exactly AMV-14 (empty == success) compounded by AMV-17 (no adaptive backoff). The pipeline cannot currently tell "arjun was prevented from looking" from "no params exist".

## Item 4 — why no endpoint profiled as restapi (root cause)

**Layering verified correct:** `httpx_reprofile` runs in a phase AFTER every BaseURL producer (naabu→httpx→katana/ffuf/paramspider→jsluice→**httpx_reprofile**→kiterunner→arjun). It re-probed the one BaseURL.

**Root cause is granularity, not execution.** `classify_profile(content_type, url)` returns `restapi` only when the **BaseURL/host** root response is JSON *or* the host has an api/rest/graphql *hostname label*. Evidence (Langfuse + graph):
- phase-1 httpx probed `https://soupmarket.shop` → 200, **content_type `text/html`**, title "OWASP Juice Shop" → `classify_profile` → **webapp**.
- There is exactly **one** BaseURL (single-host app). `/api/*` and `/rest/*` (43 endpoints) are *paths under that host*, never themselves profiled.
- Host labels `{soupmarket, shop}` contain no api/rest label.

So it is *structurally impossible* for this single-host, path-prefixed-API target to yield a `restapi` BaseURL, and kiterunner (gated `profile == restapi`) is therefore correctly `skipped`. This is a **design limitation of D16** (host-granular profiling vs path-granular APIs), not a reprofile bug.

**Secondary observability finding:** this run's `httpx_reprofile` pod returned **empty stdout in 55s** (returncode 0) — it silently produced nothing against the slow target and re-profiled nothing. It didn't matter here (phase-1 httpx had already set `webapp`), but it is the same AMV-14 pattern on the reprofile path.

## Recommendations (each its own bounded change, outside AMV-8 scope unless noted)
1. **AMV-8 scope (doing now):** extend the ticket-5 fragment filter to the residual crawl-artifact class this run exposed — dotted minified-JS-expression segments (`/i.document.do`, `/l.number`, `/r.dom.offsetHeight`) and `{{...}}` template placeholders (`/%7B%7Bhref%7D%7D`).
2. **Profiling granularity (D16):** to make kiterunner/graphql-cop fire on single-host path-prefixed APIs, profile must consider endpoint paths (e.g. an endpoint under `/api`/`/rest` returning JSON marks an api-surface), not only the host root. Design decision — needs operator ratification.
3. **Yield/liveness gate (AMV-14):** a pod that returns empty in a fraction of the expected time (arjun 10s vs ~52s; httpx_reprofile empty) should be `degraded`, not `success`; add a target-liveness precondition before a run.
4. **arjun robustness (AMV-17):** feed arjun only healthy endpoints (skip known-error/method-mismatch), and add the adaptive backoff ladder; disable TLS verification for self-signed internal targets.
