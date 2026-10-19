# Local Steel deployment and the address seam (#359) - decisions

*Status: recorded during the #359 grilling round (2026-10-19). The spec is `docs/design/steel-local-deployment-359-spec.md`; the tracker issues carry the work authority.*
*Parent: #245 (the local Steel open-source stack). This ticket adds the non-internet reachability requirement.*
*Glossary: `src/polymerhus/recon/CONTEXT.md` (browser capability), `src/polymerhus/app/CONTEXT.md` (the shared configuration rule).*

The deployment exists so browser-based recon can reach targets that the public internet cannot route to.
Steel's cloud pool egresses from the public internet, so it cannot reach eval-instance targets, lab hosts, or intranet applications.
A Steel runtime on the operator's own server egresses from the operator's network, so it can.

## Grounding facts (measured 2026-10-19)

- The Steel runtime runs on `dj-viscon-workshop-1.vsos.ethz.ch` (192.33.91.87).
  It is internet-exposed (SSH 22, HTTP 80, HTTPS 443 answer from the public internet).
- The polymerhus stack runs on `eval-server-polyphemus` (46.224.225.245), which carries the `dev` checkout at `/opt/polymerhus-dev`.
  The two hosts reach each other at about 10 ms round-trip.
- The pinned Steel CLI is `0.5.0-preview.6` (#395). Its endpoint precedence is `--api-url` -> `STEEL_BROWSER_API_URL` -> `STEEL_LOCAL_API_URL` -> `browser.apiUrl` -> `http://localhost:3000/v1`.
  `--local` and `--api-url` are global flags. An environment variable supplies the base URL only; it cannot select local mode.
- The Steel API image is `ghcr.io/steel-dev/steel-browser-api`. Only the `latest` tag is published; the index digest `sha256:eb8567bac2221d2856923184cf693a08df9a488680431ebded73cab63aa181eb` pins it (amd64 `sha256:683ace5122e6d6a0852da2c5ac44c39045f743470be1d2c15b169680bf513880`, 729 MB compressed).
- The API serves the browser CDP over its own WebSocket on port 3000 (`websocketUrl` = `ws://<DOMAIN>/`). Port 9223 is not needed by a remote client.

## D359-1 - The Steel runtime is a portable deployment; the endpoint is a deployment value

The Steel runtime stays fixed on `dj-viscon-workshop-1`.
The polymerhus stack is interchangeable: it may run on the operator's machine, on the eval server, or on another server.
The invariant is mutual reachability between the host that runs the `kali` container (the only Steel CLI client) and the host that runs the Steel server.
The chosen endpoint is therefore a deployment setting, never a recon-owned constant.
_Consequence_: the configuration value must serve any reader (the CLI today, an SDK client today or after the #360/#362 rewrite) without assuming a module.

## D359-2 - The minimal stack is the API container alone

Deploy the API image only.
Do not deploy the `ui` container; do not publish 5173.
Publish the Sessions API (3000). Keep the Chrome debug port (9223) container-internal, because the CLI's CDP connect URL rides the API WebSocket on 3000.
Persist the browser cache and caller-owned artifacts on a durable volume mounted at `/app/.cache`.
The local API has no profile store; its default Chrome user-data-dir is `/tmp/steel-chrome`, and session state is carried explicitly through `sessionContext` (D359-11).
Pin the image by digest; never deploy `latest`.
The declared artifact is a compose file in the repository (D359-9).

## D359-3 - Exposure: the API port is allowlisted; the surface conflicts are cleared

`dj-viscon-workshop-1` is internet-exposed, so port 3000 must not be open to everyone.
Restrict inbound TCP 3000 to the eval server IP and the operator's admin IP, at Docker's `DOCKER-USER` chain.
Free the canonical port by removing the two local surfaces the operator named: the `juice-shop` container (holding `127.0.0.1:3000`) and the systemd `nginx` reverse proxy (holding 80/443, answering 502).
The Steel API has no built-in authentication; the allowlist is the access control.

## D359-4 - One address value: `STEEL_BROWSER_API_URL`

Add one deployment-level value, `STEEL_BROWSER_API_URL`.
It is unset by default, so an unconfigured deployment keeps using the remote Steel cloud servers exactly as today.
When it is set, it names the self-hosted endpoint in the CLI's canonical form: `http://<host>:<port>/v1`.
The value carries the `/v1` path because the CLI appends the operation path to it (`{base_url}{path}`), and the API mounts every route under `/v1` (CLI `src/config/mod.rs`, `src/api/client.rs`; API `steel-browser-plugin.ts`).
The CLI reads this name natively (its precedence step 2). A thin shared resolver in the `app` layer exposes the same value to any SDK consumer.
The resolver returns the SDK-native origin form: it drops one terminal `/v1` and any trailing slash, because the Python SDK appends `/v1` to `base_url` itself (`steel/_client.py`, `sessions.py`).
The resolver is therefore the one place the form is adapted, and it stays the single construction point for the SDK side.
`steel_exec` injects the global `--local` flag into a command-mode invocation when the value is set, because the CLI selects local mode only through a flag.
Script-mode callers (and a bare CLI) pass `--local` themselves; the skill states the rule.
_Wiring must stay neutral to the future client choice_: whether the recon browser phase drives the Steel SDK or the Steel CLI, both read the same one value.

## D359-5 - The SDK consumer reads the same value and the session's own connect URL

`SteelCrawlProvider` passes the resolver's value as the SDK client `base_url` (session create and release).
It uses `session.websocket_url` for the CDP connect, falling back to the cloud `wss://connect.steel.dev?...` pattern only when the field is absent.
This makes the provider work against a local runtime without changing the cloud path.
The change is deliberately minimal: the recon browser phase is scheduled for a rewrite (#360/#362), and D359-4 keeps the seam stable across it.

## D359-6 - The internal target is reached over the eval front

The walkthrough target is `comfyui` on the eval server, matching the eval settings.
The Steel container on `dj-viscon` reaches it through the eval front (`ph-eval-front`, published `:80`) by aliasing the target's synthetic host (`t-<short>.target`) to the eval server IP in the Steel compose (`extra_hosts`), mirroring the kali alias the eval harness already writes.
The traffic is outbound from the Steel host; no allowlist on `dj-viscon` is needed for it.

## D359-7 - Portability boundary (what does not port from cloud)

Recorded for #245, without a public-egress proxy:

- Steel-managed residential proxies: not available. Steel Local supports bring-your-own proxy only.
- Dedicated IPs: not available. The egress is the operator host's own address.
- Managed CAPTCHA handling: not available; it stays excluded by operator ruling (D237-15).
- The Credentials API: not supported in Steel Local.
- The Files API: not supported in Steel Local.
- The Profiles API: not available. `profileId` and `persistProfile` are stripped from the create body and `/v1/profiles` is absent; local state rides `sessionContext` (D359-11, #395).
- Concurrency: 1 (one session at a time).
- Extensions load by build-time injection under `api/src/extensions/`, not by API call.

The internal-reachability case needs no public-egress proxy: the runtime egresses from the operator's network, which is the whole point.

## D359-8 - The regression check has two tiers

A deterministic contract predicate at the resolver seam: unset -> no base URL (cloud unchanged); set -> the base URL is returned verbatim to every consumer.
A live walkthrough predicate: a Steel session navigates the internal `comfyui` target end to end.
The walkthrough is red-capable: it fails when a session cannot reach the internal target, and it has been observed red then green.

## D359-9 - The deployment is pinned in the repository

The declared artifact is `eval/deploy/steel/docker-compose.steel.yml`: the API image pinned by digest, the API port published, the `.cache` volume, the `DOMAIN` setting, and the target-host alias.
`eval/OPERATOR.md` documents the seam (how to point a portable polymerhus stack at the deployed runtime).

## Operator rulings (G6, 2026-10-19)

- The assertion catalogue (`docs/design/steel-local-deployment-359-assertions.md`) is approved: contract predicates C1..C11 and walkthrough predicates E1..E7.
- Allowlist sources: the eval server address `46.224.225.245` and the admin egress IPv6 `2a04:ee40:214a:f500:9ce6:f07f:fafd:4b6b`. The admin IPv4 is read from `SSH_CLIENT` on `dj-viscon-workshop-1` at deploy time.
- Negative probe: no outside source host is guaranteed. E1 uses a temporary top-of-chain `DOCKER-USER` DROP for TCP 3000, confirms the eval server probe times out, and removes the DROP.
- Destructive host changes are approved for T4: remove the `juice-shop` container, stop and disable the systemd `nginx` proxy.
- The operator adds `STEEL_BROWSER_API_URL` to the eval instance `.env` once the value form is confirmed: `http://192.33.91.87:3000/v1`.
- The current `STEEL_API_KEY` stays for the E4 cloud-path check.

## D359-10 - The CLI interactive path is fixed by the pin bump (#395)

*Resolved 2026-10-19. The original defect and the measured diagnosis follow; the fix is the last paragraph.*

Steel CLI v0.4.4 could not run its interactive daemon against the local API image.
The API's create response carries `timeout: 0`, because the local runtime is single-session and has no session-expiry concept.
`get_session_timeout` returned `Some(0)`, so the daemon's deadline was `createdAt + 0 - 30 s`, already in the past.
The daemon shut down on its first loop (`[daemon] Session timeout reached, shutting down`) and closed its Unix socket, so `browser start` answered `Connection reset by peer`.
`steel scrape` does not use the daemon and worked; the SDK path worked; the address seam was unaffected.

The cause is a released-version gap, not a network or browser failure:

- The CLI sends `{"timeout": <ms>}` in `POST /v1/sessions`, and the self-hosted API strips it (no field in `CreateSession`) and returns `timeout: 0` (upstream issue steel-dev/steel-browser#350, still open).
- The CLI defect is fixed upstream in PR steel-dev/cli#95 (merged 2026-07-06): the timeout helpers collapse `0` to `None`, so the requested `--session-timeout` applies.
- No stable release contains that fix: v0.4.4 is the latest stable tag. The fix ships in `0.5.0-preview.6` (2026-09-12).
- The failure reproduces over loopback on the API host itself, and the preview binary succeeds over the same wire, so the network path is not a cause.
  Evidence and traces: `docs/design/evidence/steel-359/t395-cli-timeout-root-cause.md`.

The pin is now `0.5.0-preview.6`, the first release with the fix.
`--session-timeout` is enforced by the daemon; when the daemon exits it releases the session.
The server still does not expire a session on its own (upstream #350); that residual is accepted for a single-session local runtime, and a stable release replaces the preview pin when upstream publishes one.

## D359-11 - The runtime reaps Chromium and preserves state across teardown (#395)

The API runs Node as PID 1 and does not reap the Chromium children it reparents, so launch/release cycles leaked zombies.
The deployment sets `init: true`, so Docker's tini reaps every orphan (measured: 108 zombies after six cycles without it, 0 with it).
Teardown is state-first: capture `GET /v1/sessions/<id>/context`, store it atomically, then `POST /v1/sessions/<id>/release`, which is also the endpoint that kills the browser.
The client is `src/polymerhus/app/steel_session_state.py`, and it always releases, even when the capture fails.
Restore feeds the stored JSON back through the create call's `sessionContext`.
The full capability fingerprint and client design are in `docs/design/steel-session-lifecycle-395-decisions.md`.

## Open queue

None - the grilling round is complete.
