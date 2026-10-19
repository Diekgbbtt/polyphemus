# Assertions - work item "local Steel runtime and the one address seam (#359)"

**Source:** `docs/design/steel-local-deployment-359-spec.md` and `docs/design/steel-local-deployment-359-decisions.md` (D359-1..D359-10).
**Tickets:** #390 (T1), #391 (T2), #392 (T3), #393 (T4), #394 (T5).

## Seams under assertion

- S1 `src/polymerhus/app/steel_endpoint.py::steel_browser_api_url` - the one construction point for the SDK side.
- S2 `kali/mcp_server.py::_steel_exec_sync` - the `--local` injection for command-mode invocations.
- S3 `src/polymerhus/recon/crawl/steel_provider.py` - the SDK `base_url` and the session CDP URL.
- S4 `docker-compose.yml`, `docker-compose.dev.yml`, `eval/docker-compose.eval.yml` - the optional passthrough into `kali` and `agent`.
- S5 `eval/deploy/steel/docker-compose.steel.yml` - the pinned deployment artifact.
- S6 `eval/deploy/steel/allowlist.sh` - the `DOCKER-USER` rules for TCP 3000.
- S7 the live Steel API container on `dj-viscon-workshop-1` - the deployed runtime.
- S8 the live internal `comfyui` target on the eval server, reached through the eval front.
- S9 `skills/steel-browser/SKILL.md` - the stated rule for script mode and the bare CLI.
- S10 the pinned CLI binary in `kali` - the interactive daemon path fixed by the `0.5.0-preview.6` pin (#395).

## Contract predicates (host-side unit tier)

The resolver and gateway seams are pure process behaviour, so their predicates run in the host unit suite (the `tests/test_steel_exec.py` stubbed-binary precedent), not the live integration tier.
The live wiring is covered by C7 and the walkthrough tier.

| id | seam | tier | input | observable | yields |
|---|---|---|---|---|---|
| C1 | S1 | unit | the variable absent; then present with surrounding whitespace; then present as `http://h:3000/v1`; then present as `http://h:3000/v1/`; then present as `http://h:3000` | absent returns `None`; whitespace-only returns `None`; the `/v1` forms return `http://h:3000`; the origin form returns `http://h:3000`; one terminal `/v1` is removed and no other path is touched | `tests/test_steel_endpoint.py` and `tests/test_steel_exec.py` (stub binary) |
| C2 | S2 | unit | the variable set to `http://h:3000/v1`; a command-mode invocation `steel browser start --session s`; a command already carrying `--local`; a command already carrying `--api-url` | set injects exactly one `--local` immediately after the leading `steel` token and leaves the value for the CLI to read; unset leaves the command byte-identical; a command carrying `--local` or `--api-url` is not rewritten | `tests/test_steel_exec.py` (stub binary, no live Steel) |
| C3 | S2 | unit | the gateway imported in a process where `polymerhus` cannot be imported | the module imports and the injection still reads the variable name directly, so the kali image needs no package dependency | same module |
| C4 | S3 | unit | a fake SDK client factory; the variable set to `http://h:3000/v1`; then unset | set passes `http://h:3000` as `base_url` on session create; unset passes no `base_url` override | `tests/test_steel_provider.py` |
| C5 | S3 | unit | a fake SDK client factory; the variable set | session release passes the same value as `base_url` | same module |
| C6 | S3 | unit | a fake session with `websocket_url`; a fake session without it | present uses the field verbatim for the CDP connect; absent falls back to the `wss://connect.steel.dev?...` pattern | same module |
| C7 | S4 | unit | the rendered configuration of the base file and the dev file, plus the parsed eval overlay | `kali` and `agent` receive `STEEL_BROWSER_API_URL` as an optional passthrough; the unset render is an empty value (both readers treat empty as unset), no non-empty default is invented; the variable is absent from services that do not consume it; the eval overlay passes it through optionally without leaking other keys into `kali` | `tests/test_compose_config.py` |
| C8 | S5 | unit | the parsed `eval/deploy/steel/docker-compose.steel.yml` | the image is a digest pin; `latest` appears nowhere; only port 3000 is published; the volume mounts at `/app/.cache`; `DOMAIN` is required; the target alias defaults to an inert pair; the restart policy is set | `tests/eval/test_steel_deployment_contract.py` |
| C9 | S6 | unit | the allowlist script run twice with a stub `iptables` on `PATH`; two allowed sources | both allow rules and the drop rule are applied once; the second run changes nothing | same module |
| C10 | S9 | unit | the rendered `skills/steel-browser/SKILL.md` | the skill states that the gateway injects `--local` in command mode, and that script mode and the bare CLI pass it themselves | `tests/test_steel_skill_rule.py` |
| C11 | S5 | unit | the rendered `eval/OPERATOR.md` | the deploy, allowlist, teardown, and move sections exist; the portability boundary lists the five excluded cloud capabilities, concurrency 1, and build-time extensions | `tests/eval/test_steel_deployment_contract.py` |

## Walkthrough predicates (end-to-end tier)

| id | grounds | entry seam | input | live edge | path | observed | yields |
|---|---|---|---|---|---|---|---|
| E1 | D359-3 - the API is allowlisted | the published port 3000 on `dj-viscon-workshop-1` | the eval server address, the admin addresses (IPv4 and IPv6), and a temporary top `DOCKER-USER` drop rule | S7, S6 | connect from each allowed address; insert a temporary DROP for TCP 3000, connect again from the eval server, then remove the DROP | allowed addresses complete a TCP handshake and answer the API; with the drop rule in place the same probe times out; the drop rule is removed | `tests/e2e/test_steel_internal_reachability.py` plus the recorded allowlist check |
| E2 | #359 acceptance criterion 1, D359-4 - the CLI path reaches an internal target | `steel_exec` from the `kali` container with `STEEL_BROWSER_API_URL` set | the internal `comfyui` target alias and a rendered-page marker | S7, S8 | start a named session; navigate the target through the eval front; read a page marker; close the session | the session id, the final URL on the internal host, and a screenshot or HAR are recorded; the page marker is present | same module |
| E3 | D359-5 - the SDK path reaches the same target | a minimal `SteelCrawlProvider` call from the `agent` container with the variable set | the same target alias and marker | S7, S8 | create a session through the SDK; connect over CDP; navigate; read the marker; release | the create and release calls carry `base_url`; the CDP connect uses `session.websocket_url`; the marker is present | same module |
| E4 | D359-4 - an unset deployment keeps the cloud path | `steel browser sessions --json` from `kali` with the variable unset | the cloud key already in the environment | the Steel cloud API | list sessions; do not start a browser | the call succeeds against the cloud endpoint, so the default is unchanged | same module |
| E5 | D359-8 - the guard is red-capable | E2 with the local container stopped | the same inputs as E2 | S7 stopped | run E2; start the container; run E2 again | the stopped run fails with a connection error and no silent cloud fallback; the restarted run passes | same module, both runs recorded in #394 |
| E6 | D359-2 - the cache volume is durable | restart the local API container | a marker written under `/app/.cache` before the restart | S7 and its `.cache` volume | write the marker; restart; read it back | the marker survives the restart | same module |
| E7 | D359-7 - the boundary is real | a live session against the local runtime | one capability the boundary excludes, for example the Credentials API | S7 | call the excluded capability | the call fails or is absent, matching the recorded boundary | manual evidence in #392, not a repeatable test |
| E8 | D359-10, #395 - the interactive daemon starts | the pinned CLI in `kali` with `STEEL_BROWSER_API_URL` set | a unique session name, `--session-timeout 120000`, `--local`, and the endpoint | S10, S7 | `browser start --json`; then `browser navigate ... about:blank --json` over the same daemon socket; then `browser stop` | start returns `success:true` with a positive `remainingMs`; navigate returns `success:true`, so the daemon socket stayed open; the session is stopped | `tests/e2e/test_steel_interactive_local.py`; the 0.4.4 red run and the preview green run are recorded in `docs/design/evidence/steel-359/t395-cli-timeout-root-cause.md` |
| E9 | D359-7, #395 - the profile boundary is real | the local API on S7 | a create with `profileId` and `persistProfile`; a `GET /v1/profiles` | S7 | POST the create; read the response; probe the profile route | the session is created but carries no `profile_id`; the route answers 404 | `docs/design/evidence/steel-359/t395-local-capability-profile-gap.md` |

## Bootstrap only the operator can supply

- The admin addresses for the allowlist: the IPv4 egress used for the dj-viscon ssh session, and the IPv6 egress. E1 and C9 need them.
- One address outside the allowlist for the E1 negative probe. If no such host exists, E1 falls back to the temporary top-of-chain DROP probe, which needs no outside host.
- The current `comfyui` synthetic host alias on the eval front, and the eval server IP for the Steel `extra_hosts` alias.
- Approval to add `STEEL_BROWSER_API_URL` to the eval instance `.env`, and the instance path.
- The go for the destructive host changes on `dj-viscon-workshop-1`: remove `juice-shop`, stop and disable the systemd `nginx` proxy.
- Confirmation of ssh access as `ubuntu`, and that Docker is usable without sudo.
- A decision on the cloud key: the current `STEEL_API_KEY` was echoed into a transcript during S1. E4 uses it, so either rotate it first or accept the risk explicitly.

## Gate notes

- The catalogue is derived from the spec and stays red until its path is built.
- The contract tier runs in the TDD loop.
- The walkthrough tier runs only at the verification gate, against the live runtime.
- A live-tier run without the endpoint fails with a clear message; it does not skip.
- The live tier does not start a billable cloud browser. E4 lists sessions only.
