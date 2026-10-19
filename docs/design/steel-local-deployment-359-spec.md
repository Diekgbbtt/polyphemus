# Local Steel deployment and the address seam (#359) - spec

*Status: draft, awaiting the operator's seam confirmation (G4). Decision ledger: `docs/design/steel-local-deployment-359-decisions.md` (D359-1..D359-9).*
*Parent: #245. This spec covers the non-internet reachability requirement plus the address seam and the #245 portability boundary.*
*Glossary: `src/polymerhus/recon/CONTEXT.md` (Steel endpoint, exec gateway), `src/polymerhus/app/CONTEXT.md` (the shared endpoint rule).*

## Problem Statement

The operator runs polymerhus against targets that the public internet cannot route to: eval-instance targets behind the eval front, lab hosts, and intranet applications.
The Steel cloud pool egresses from the public internet, so browser-based recon cannot reach them.
Every part of the product that drives a browser - the authn browser path through `steel_exec` and the `steel_crawl` job through the Steel SDK - points at Steel's cloud endpoint, and there is no deployment-level way to point them at a runtime on the operator's own network.
The operator therefore loses browser coverage on exactly the targets that matter, and the loss is silent.

## Solution

Deploy the minimal Steel open-source runtime (the API container alone) on the operator's own server, which egresses from the operator's network and so can reach the internal targets.
Add one deployment-level value, `STEEL_BROWSER_API_URL`, that selects the runtime. It is unset by default, so an unconfigured deployment keeps using the remote Steel cloud unchanged.
When it is set, the CLI runs against the local runtime in `--local` mode and the SDK provider addresses it through its `base_url`.
The client choice is deliberately neutral: whether the recon browser phase drives the SDK or the CLI, both read the one value, so the #360/#362 rewrite does not re-fork the address.

## User Stories

1. As the operator, I want browser-based recon to reach a target that the public internet cannot route to, so that internal eval instances, lab hosts, and intranet applications are covered.
2. As the operator, I want a single deployment-level value to select the Steel runtime, so that I never edit module code to move the stack.
3. As the operator, I want the value unset by default, so that an unconfigured deployment reaches the remote Steel cloud exactly as today.
4. As the operator, I want the `steel` CLI to address the local runtime in `--local` mode when the value is set, so that the authn browser path and every `steel_exec` caller reach it without per-command edits.
5. As the operator, I want the Steel SDK consumer to read the same value, so that `steel_crawl` and the CLI never disagree about the endpoint.
6. As the operator, I want the runtime deployed as the API container alone, so that the stack stays minimal and reproducible and no dashboard or UI ships.
7. As the operator, I want the API port reachable only from the polymerhus stack and my admin address, so that an unauthenticated browser service is not open to the internet.
8. As the operator, I want durable browser state (profiles, snapshots, sessions) on a persistent volume, so that state survives a container restart.
9. As the operator, I want the whole deployment pinned by digest in the repository, so that it is reproducible and revertible.
10. As the operator, I want the local runtime to reach the eval front's internal target, so that a browser session lands on a rendered internal page.
11. As the operator, I want the portability boundary recorded, so that I know which cloud capabilities do not travel to the local runtime.
12. As the operator, I want a regression check that fails when a session cannot reach an internal target, so that the capability cannot silently regress.
13. As a maintainer, I want one resolver for the endpoint, so that no consumer owns the address and the future client rewrite cannot fork it.
14. As a maintainer, I want the deployment declared as one repository artifact, so that the deployed stack is reviewable and revertible.

## Implementation Decisions

### The address seam (one value)

- Add `STEEL_BROWSER_API_URL` as a deployment-level value. Unset means remote Steel (byte-identical to today); set means the self-hosted base URL.
- The value is the CLI's canonical self-hosted endpoint, and it carries the `/v1` path: `http://<host>:<port>/v1`. The CLI appends the operation path to the value (`{base_url}{path}`), and the API mounts every route under `/v1` (verified in the CLI source and the API route table).
- A thin resolver in the shared `app` layer returns the SDK-native base URL: the value with one terminal `/v1` removed. The Python SDK appends `/v1` itself, so the origin form reaches the same routes. The resolver is the one construction point for the SDK side, and it is the one place the form is adapted. It is not owned by recon, because the Steel browser capability is shared infrastructure, not a recon-only knob (D359-1, D359-4).
- The CLI reads the same name natively (precedence step 2). No new CLI-side name is invented.
- `steel_exec` injects the global `--local` flag into a command-mode invocation when the value is set; script-mode callers and a bare CLI pass `--local` themselves, and the browser skill states the rule.
- The SDK consumer passes the resolver's value as `base_url` and uses `session.websocket_url` for the CDP connect, falling back to the cloud pattern only when the field is absent (D359-5).

### The deployment

- The declared artifact is a compose file in the repository: the API image pinned by digest, port 3000 published, a durable `/app/.cache` volume, and the target-host alias for the internal target search path.
- No `ui` container; port 5173 is never published. Port 9223 stays container-internal (D359-2).
- The API base URL (`DOMAIN`) is set to `<host>:<port>`, so the session's `websocket_url` is `ws://<DOMAIN>/` and names a reachable host.
- Access to port 3000 is restricted to the eval server IP and the admin IP at Docker's `DOCKER-USER` chain (D359-3).
- The internal target is reached by aliasing the target's synthetic host to the eval server IP in the Steel compose, mirroring the eval harness's kali alias (D359-6).

### The portability boundary (#245)

Recorded as D359-7: no Steel-managed residential proxies, no dedicated IPs, no managed CAPTCHA handling, no Credentials API, no Files API, concurrency 1, extensions by build-time injection.
The internal-reachability case needs no public-egress proxy: the runtime egresses from the operator's network.

### Documentation

- `eval/OPERATOR.md` documents the seam: how a portable polymerhus stack points at the deployed runtime, and how to move the stack between hosts.
- The owning glossary gains the "Steel endpoint" term; the app context gains the shared-endpoint rule.

## Testing Decisions

- A good test asserts external behaviour only: the value the resolver returns for a given environment, and the endpoint the CLI and the SDK actually address. It never inspects a private helper.
- Contract tier (integration): the resolver seam - unset returns no base URL; set returns the value verbatim; a consumer sees the same value; the CLI's `--local` injection is present exactly when the value is set.
- Walkthrough tier (e2e, live): a Steel session against the deployed local runtime navigates the internal `comfyui` target end to end and lands on a rendered page; the evidence is a session id, a final URL, and a screenshot or HAR.
- The regression check is red-capable: the same walkthrough fails when a session cannot reach the internal target (for example with the runtime stopped, or the target not routable), and it has been observed red then green.
- Prior art: the crawl-provider tests with injected fakes; the `steel_exec` gateway unit tests with a stubbed binary; the eval e2e targets (`tests/e2e/fixtures/eval-targets.yaml`).

## Out of Scope

- The recon browser-phase rewrite (#360/#362). This spec keeps the seam stable across it; it does not pre-empt the client choice.
- Steel-managed proxies, dedicated IPs, and managed CAPTCHA solving (excluded by operator ruling, D237-15 and D359-7).
- The Steel UI and dashboard.
- CDP network-capture enrichment (#360).
- Rate-limit system mapping (#238).

## Further Notes

- The Steel CLI pin is `0.5.0-preview.6`, the first release that contains upstream PR #95 (`timeout: 0` from a self-hosted runtime means "no expiry", #395); a bump is a skill-review event (D10, #221).
- The deployment host is fixed; the polymerhus stack is portable, and mutual reachability is the invariant (D359-1).
- The `steel_crawl` provider change is minimal on purpose; the rewrite may keep the SDK or move to the CLI, and the resolver serves either.
- The interactive CLI path works against the local runtime (D359-10, #395).
  The local API still ignores a create-time timeout (upstream issue #350), so the daemon enforces `--session-timeout` and releases the session when it exits.
  One-shot `steel scrape` and the SDK path are unaffected.
