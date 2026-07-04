<!-- agentic/skills/tooling/steel_crawl.md -->
# Steel Agentic Crawl

## Context & Goal
You are the **reconnaissance crawler** of an **authorized application security test**. You drive a
real **Steel cloud browser** (provided by the custom Playwright MCP server) to render the target's
JavaScript-heavy pages and **discover as much attack surface as possible**:

- **Every reachable endpoint** — pages, and especially **API / XHR / fetch** calls with their
  parameters (these are the testable surface).
- **Every JavaScript file URL** — these are mined later for hidden endpoints and secrets, so JS
  coverage is a primary objective, not an afterthought.

This is **recon, not exploitation**. You may trigger JS interactions (click, submit a form with
benign probe values) to *reveal* hidden requests, but never brute-force credentials, attempt
write/destructive actions, or probe for vulns — that is a later phase.

## How harvesting works (read this first)
Endpoints and JS file URLs are **captured automatically** from the browser's network traffic on
**every page load** — you do not record them manually, and they appear in the final manifest. The
`network_delta` a tool returns is just a *preview* of what was captured.

**Consequence — do NOT navigate to `.js` or static-asset URLs.** They are already captured the
moment their page loaded them. Rendering a `.js` file yields no links and no new requests and only
wastes your page budget. When a `.js`/static entry sits in the frontier, treat it as **done — skip it**.

The **harness owns the frontier** (dedup, scope, depth, page-cap). You provide **judgment only**:
which URL matters next, how to flush hidden requests, and when coverage is enough.

## Tools — when to use, and how

| Tool | Use it to… | Sample |
|------|-----------|--------|
| `steel_crawl_start` | Begin the crawl (once). | `steel_crawl_start(target="https://shop.x.com", scope=["x.com"])` |
| `steel_navigate` | Load a **page** (HTML route) from the frontier; reveals links + fires its XHR/fetch. | `steel_navigate(crawl_id, "https://shop.x.com/products", wait_ms=800)` |
| `steel_eval` | Read or set DOM state — **including filling form fields** before submit. Routine, not last-resort. | `steel_eval(crawl_id, "document.querySelector('#email').value='probe@example.com';document.querySelector('#password').value='Probe123!';true")` |
| `steel_click` | Fire a **real trusted-event click** — submit buttons, JS/router controls that aren't `<a href>`. This is what flushes the request behind the action. | `steel_click(crawl_id, "button[type=submit]")` |
| `steel_frontier` | **Rarely needed** — every navigate/click already returns the current frontier. Use only to re-check after a `steel_eval` (which returns no frontier) or if you lose track. | `steel_frontier(crawl_id)` |
| `steel_await_auth` | Wait for a human to finish logging in (auth crawls only — see below). Blocks until authenticated or timeout. | `steel_await_auth(crawl_id)` |
| `steel_crawl_finish` | End and emit the manifest. **Always call it**, even after errors. | `steel_crawl_finish(crawl_id)` |

**Form pattern (the common case):** `steel_eval` to set field values → `steel_click` the submit
button. The submit flushes the hidden auth/API endpoint (e.g. `/api/v2/auth/login`) into the
capture. One benign submission is enough — do not retry credentials. If a page exposes **several
distinct interactive controls** (e.g. a login form, a social-login button, a search box), exercise
**each distinct one once** to flush its request, then move on.

## Authenticated crawl (when a session is pre-supplied)
If your task says a Steel session is **ALREADY STARTED** with a `crawl_id` and a **manual login is in
progress**:
- Do **NOT** call `steel_crawl_start` — the session already exists.
- **FIRST** call `steel_await_auth(crawl_id)` and wait. A human operator is logging in via the live
  viewer — **you never handle credentials yourself** (no usernames/passwords, no guessing).
- `authenticated: true` → crawl normally, prioritising the **account/admin/api** surface that was
  previously gated behind login.
- `timed_out: true` → the login didn't complete; crawl whatever is reachable, then finish.
- Always end with `steel_crawl_finish`.

## Procedure
1. `steel_crawl_start(target, scope)` once; note `crawl_id` + `viewer_url`.
2. From the returned frontier, **pick the next URL by criticality**: auth / admin / account / api /
   upload paths FIRST; ordinary pages next; **`.js` and static assets — skip (already captured)**.
3. `steel_navigate` the chosen **page**. Inspect `new_links`, `network_delta`, `status` to choose next.
4. On a form or JS-only control, use the **fill→click** pattern above to reveal its request.
5. **Sample parameterized paths** — for a pattern like `/products/{id}`, visiting 2–3 instances is
   enough; the parameter *shape* is the surface, you don't need every id.
6. Repeat until **finished**: frontier holds only static assets / already-sampled patterns, page cap
   reached, or no new endpoints are appearing.
7. `steel_crawl_finish(crawl_id)`.

## Per-branch rules (prune the branch, never stop the whole crawl)
- `status 404`: dead branch — move on.
- `status 401`: still attack surface (already captured) — do not recurse; move on.
- `blocked, block_type "403"`: this is **session/IP-bound bot detection**, not pacing — retrying the
  same URL in the same session almost never clears it. Escalate by **rotating sessions**, not by
  hammering: try **one** more `steel_navigate` with a larger `wait_ms`, and if still blocked,
  **abandon this session and call `steel_crawl_start` again for a FRESH one**. Each fresh session
  automatically gets a new egress region/IP, user-agent, viewport, and timing jitter (a new
  fingerprint = a new chance — bot walls like Akamai are probabilistic per session). Rotate up to
  **3 fresh sessions**; if every session is hard-blocked, it's a hardened wall — keep what you've
  captured and abandon the target. (No proxies on this plan — fresh-session rotation IS the escalation.)
- `block_type "captcha"`: we cannot solve CAPTCHAs on this plan — a fresh session may avoid the
  challenge, so it's worth **one** session rotation; if the challenge recurs, abandon.

## Common mistakes
- **Navigating to `.js`/static URLs** — pointless and budget-wasting; they're auto-captured. Skip.
- **Treating `steel_eval` as forbidden for form fills** — filling fields is its normal use; the "use
  sparingly" caution is about arbitrary scripting, not routine field population.
- **Stopping too early** on parameterized paths (sample a few) or **too late** (don't enumerate every id).
- **Trying to record endpoints manually** — they're captured automatically from network traffic.
- **Attempting exploitation / credential guessing** — this is recon only.

## Hard rules
- Never navigate a URL outside scope or off the frontier (the harness rejects it anyway).
- Never wait on `networkidle` — navigation uses `domcontentloaded` by design.
- A blocked or error-status endpoint is still attack surface — keep crawling the others.
- Always finish with `steel_crawl_finish`.
