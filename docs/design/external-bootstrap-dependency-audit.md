# External bootstrap - dependency audit

Status: complete (W2.1, 2026-10-17).
Basis: the reverse-engineered workflow report (`BOOTSTRAP-WORKFLOW-REVERSE-ENGINEERED.md`, 767 lines, from the mined session) plus live probes of every dependency it names.
Purpose: establish exactly what the mechanised bootstrapper needs before its architecture is fixed, and prove each dependency exists and works from the machine that will run the regeneration.

## 1. What the run needs

The mechanised bootstrap runs agents on the Mac (the opencode harness host) against targets that run on the eval server.
The five dependency classes are: procedure sources, the agent harness, the target environments, the data layout, and the operational constraints.

## 2. Procedure sources (all versioned in the repo)

| Source | Path (in this worktree) | Role | Status |
|---|---|---|---|
| Contract | `tools/bootstrap/DATA-DEPENDENCIES.md` | operator-facing contract: what is built, where it lands, phases, order, secrets policy | recovered in W1, updated for the structured Overview |
| Phase-1 prompt | `tools/bootstrap/prompts/data-dep-authn.md` | deploy + authn bootstrap (P0-P6) + staging authoring | recovered, points at the meta-skill by repo-relative path |
| Phase-2 prompt | `tools/bootstrap/prompts/data-dep-l1.md` | authenticated crawl + L1 authoring (two renderings + two notes) | recovered, carries the structured-Overview contract |
| Critic prompt | `tools/bootstrap/prompts/data-dep-critic.md` | two-axis batch review (shape + threat-model coverage) | recovered, capstone for the Overview checks |
| Authn meta-skill | `skills/meta/authn-skill-writing/{SKILL.md,references/bootstrap-workflow.md,references/worked-example.yaml}` | the P0-P6 procedure authority the phase-1 prompt cites | present in the branch |
| Shape validator | `tools/bootstrap/validate_data_dependencies.py` | phase gate: KB scaffold parse, surface schema, auth shapes, structured Overview | recovered, carries the W1 strict Overview gate |
| Deterministic consumer | `src/polymerhus/analysis/scaffold.py` | the real parser the KB must satisfy | platform code, unchanged |
| File-shape ADRs | `docs/design/auth-store-220-decisions.md` (D220-3, D220-12), `docs/design/application-overview-entity-adr.md` | credential/overview shapes + the Overview entity decisions | present |
| Assessment framework | `tools/bootstrap/assessment/` | graded measurement of the outputs (W1.4) | built and baselined |

## 3. Agent harness - opencode v2.0.29, service API

The rebuild uses opencode as the agent harness, and the working integration point is the local background service API, not the CLI batch runner.

Verified facts:

- `opencode serve --service` (pid 10605) listens on `http://127.0.0.1:49374`; the media/JSON API is v2 (`/api/...`), and `opencode api <method> <path>` performs discovery and authentication exactly like the TUI.
- Session lifecycle over the API works end to end: `POST /api/session` creates a session (accepts an explicit `id` matching `^ses`, a `title`, an `agent`, a `model` ref, a `location.directory`, and free-form `metadata`), `POST /api/session/{id}/prompt` enqueues a user turn, and `GET /api/session/{id}/message` returns the transcript.
- A probe session (`ses_eb6f9debdffeOSUVNALj40azzR`) was created, prompted ("Reply with exactly: PONG4"), and answered by `opencode/nemotron-3.5-super-vl-free`; the transcript ended with an `idle` message carrying `outcome: succeeded`.
- `POST /api/experimental/session/{id}/wait` exists for blocking waits; `POST /api/session/{id}/interrupt` exists for timeouts.
- Nested `opencode run` is NOT usable: every variant tried (bare, `--standalone`, explicit `--agent general --model opencode/deepseek-v4.1-flash-free`) fails with a provider-level `FreeTierError` ("OpenCode's free tier can only be used from within OpenCode", HTTP 403) before any model call.
- Models: the service exposes two provider lanes (39 models): the free `opencode` tier and the entitled `opencode-go` lane the operator's own sessions use (`opencode-go/deepseek-v4.1-flash` with low/high/max variants). Each carries reasoning-effort variants; `Model.Ref` is `{providerID, id, variant?}`. The free tier answers interactive probes but rejects automated session dispatches intermittently with a 403 `FreeTierError`, so the module's default worker lane is `opencode-go/deepseek-v4.1-flash#high` (the free tier stays usable as an explicit opt-in; its 403s are classified retryable).
- Agents available: `build` (default primary, no model pin) and `general` (subagent, pinned `opencode/deepseek-v4.1-flash-free`) plus the repo-local subagent definitions; worker sessions should name `general` (or a new dedicated agent) and an explicit model ref so the choice is parametrized.
- Session resume is the state machine: prompt the same session id for every follow-up in a target's phase; the child keeps its context (target up, cookie jars, file paths), which mirrors the mined run's resume mechanics.

Consequence: the module drives `opencode api` calls (subprocess), and it must treat provider errors as retryable-with-backoff plus session resume; the default worker lane is the entitled `opencode-go` provider.

## 4. Target environments

The environment is a parameter; three drivers cover the cases.

### 4.1 Remote server driver (the W2 regeneration path)

| Aspect | Fact | Verified |
|---|---|---|
| Access | ssh alias `eval-server-polyphemus` (`IdentityFile ~/.ssh/polyphemus-eval-server/root_key`, user root) | alias works; the bare IP entry has no key and is denied |
| Host | `ubuntu-16gb-nbg1-1`, aarch64, 15 GiB RAM, 150 GB disk (55 GB free) | probed |
| Target control | `/root/wb <build|up|ps|down> <target>`, a wrapper that pins `DOCKER_DEFAULT_PLATFORM=linux/amd64`, `TARGETCTL_NO_WAIT_DEPS=1`, `TARGETCTL_NO_BUILD=1`, `TARGETCTL_EXCLUDE_SERVICES=evaluator`, `TARGETCTL_NATIVE_SERVICES=redis` and runs `bash scripts/targetctl` in `$HOME/WebExploitBench` | read verbatim; all five environment pins must never be overridden |
| Images | all 8 targets' images are pre-pulled (`ghcr.io/diekgbbtt/webench:<target>-<service>` plus `pentestbench-*` retags) | listed |
| Webroot | `~/WebExploitBench/<target>`: `challenge.json`, `docker-compose.cage.yml`, `setup_files/`, `vulnerability/` (SEALED) | listed per target |
| URL discovery | `/root/wb ps <target>` prints `http://0.0.0.0:<port>/`; the module rewrites `0.0.0.0` to the server IP for workers | white-jotter up at `:48287` |
| Reachability | server target ports answer from the Mac directly (`curl http://46.224.225.245:48287/` -> 200) | probed |
| Teardown | `/root/wb down <target>` only; `docker rm -f $(docker ps -aq)` between targets is allowed; `docker system prune -a` is FORBIDDEN (it destroys the pre-pulled cache; this was the mined run's most expensive mistake) | policy from the report |
| Staging provenance | `/root/eval-dd/{data,staging,kbs}` holds the mined run's artifacts (`data/<target>/{auth,skills,KB}` and `staging/<target>/{auth,skills}`) | listed |
| Agent host | opencode is NOT installed on the server; agents run on the Mac and reach the target over HTTP plus ssh for lifecycle | probed |
| Resource headroom | 9 GiB currently used by an active eval stack (`ph-dd131acc-*`) and two leftover target deployments (`web_white_jotter-*`, `web_comfyui-*`); the regeneration must run one target at a time and tear down before the next | probed; coordinate before W2.6 |

### 4.2 Local driver (optional)

- Docker Desktop runs on the Mac; `polymerhus-postgres/neo4j/kali` are up.
- The WebExploitBench checkout exists at `/Users/diekgbbtt/WebExploitBench` with `scripts/targetctl`; bash 5 is available at `/opt/homebrew/bin/bash` (macOS bash 3.2 collapses compose project names and collides targets).
- Every docker/targetctl invocation needs `DOCKER_DEFAULT_PLATFORM=linux/amd64` (arm64 host, amd64 images, Rosetta emulation); first boots are slow; disk is the scarce resource and is reclaimed with `docker system prune -a -f` locally only.
- The Mac Docker VM cannot hold two heavy targets at once; the mined run used batch 1 for heavy targets.

### 4.3 Attach driver

- Given a `base_url` (any reachable target), the module runs the same phases without lifecycle control.
- This is the driver for testing the module against an already-running target and for environments where the operator owns the lifecycle.

## 5. Data layout and secrets

| Concern | Rule | Enforcement |
|---|---|---|
| Ground truth | `/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/<target>/{_target.md,<target>-NNN/}` is SEALED; only the critic phase may read it; the LLM assessor never reads it | wrappers carry the path only for the critic; worker prompts state the prohibition |
| Server-side sealed paths | `<webroot>/<target>/vulnerability/` and `challenge.json` are never read by any worker | worker prompts state it; no wrapper hands these paths to creator phases |
| Credentials | secret values exist only in `<staging>/<target>/auth/credentials.yaml`; prompts, reports, and logs cite names only | wrapper report budget includes the "No secrets" clause; the module never prints file contents |
| SSH key | `~/.ssh/polyphemus-eval-server/root_key` via the ssh alias; the key is referenced, never copied into artifacts | environment descriptor holds the ssh command only |
| Service password | `~/.config/opencode/service.json` is used by `opencode api` automatically; the module never reads or logs it | module shells out to `opencode api` |
| Staging git hygiene | `eval/data-dependencies/` is gitignored (verified); auth bundles and skills stay out of git by design (operator decision Q7) | `.gitignore` |

## 6. Output layout (the artifacts the run produces)

| Output | Location | Committed? |
|---|---|---|
| L1 KB | `eval/data/webexploitbench/<target>/operator_kb.md` | yes (regenerated set replaces the committed one) |
| Graph rendering | `eval/data/webexploitbench/<target>/l1-surface.yaml` | yes |
| Crawl notes | `eval/data/webexploitbench/<target>/surface-map.md` | yes |
| Claim ledger | `eval/data/webexploitbench/<target>/research-notes.md` | yes |
| Auth bundle | `<staging>/<target>/auth/{overview.yaml,credentials.yaml}` | no (secrets) |
| Authn skill | `<staging>/<target>/skills/authn/{SKILL.md,references/}` | no |
| Critic reports | `<groundtruth>/critic/batch-<n>.md` | no (sealed tree) |
| Run state + logs | the module's run directory (session ids, phase status, per-target reports) | optionally, after secret review |

## 7. Gaps, constraints, and risks

1. Host minting (lack L-1 from the Overview ADR): the eval system mints a per-run Host (`t-<short>.target`) that the crawl never sees; workers reach targets as `http://<ip>:<port>/`. The wrappers must therefore forbid baking any host, port, or IP into artifacts and pin the Overview `domain` to the target's stable identity.
2. Harness constraint: only the service API works (see section 3); the module must own session creation, completion detection, timeouts, and resume over that API.
3. Shared server: an eval stack is currently running on the eval server; the regeneration must not touch its containers and must fit in the remaining RAM one target at a time.
4. Session staleness: snapshots expire between re-instantiation (cookie-name hashes rotate); the L1 phase must verify the persisted session and fall back loudly to re-sign-in, never to a silent anonymous crawl.
5. Heavy targets: dataease (and historically dify) saturate RAM; the wave plan is serial with a long readiness budget; the mined run's server recipe (poll ~60x5s) is the default.
6. Provider lane availability: the free `opencode` tier rejects automated session dispatches intermittently (403 FreeTierError) even though interactive probes pass; the entitled `opencode-go` lane works reliably through the same API. The retry ladder still classifies those 403s as retryable, so a lane outage is bounded and resumable rather than fatal.
7. `l1-surface.yaml` is a review artifact today: endpoint 4 consumes `operator_kb.md` only; the regeneration still produces and validates the YAML rendering.
8. The mined-run staging bundles (`/root/eval-dd/staging`) must not be overwritten by the regeneration; new bundles go to this run's staging root, and the assessment compares the two read-only.

## 8. Decisions the audit fixes for the architecture

- The module is a Python orchestrator under `tools/bootstrap/` that drives the opencode service API through `opencode api` subprocesses and dispatches exactly the wrappers the mined run used.
- One resumable opencode session per (target, and phase where separation helps); the run state on disk is the handoff; a crashed orchestrator resumes from it.
- Target environments are drivers (`ssh-server`, `local`, `attach`) behind one interface: `ensure_up(target) -> base_url`, `ps(target)`, `teardown(target)`; the e2e uses `ssh-server`.
- Phase gates are the validator's own modes (`--auth-only`, `--l1-only`, full); a phase never advances on red.
- Wave policy: serial by default (one target at a time on the shared server), critic per wave with fix rounds dispatched into the creator session.
- The critic is the only ground-truth reader; assessment is ground-truth-free.

## 9. Live-probe log (condensed)

1. `ssh root@46.224.225.245` -> permission denied; `ssh eval-server-polyphemus` -> ok (alias carries the key).
2. Server image list contains all 8 targets' `ghcr.io/diekgbbtt/webench:*` images and the `pentestbench-*` retags.
3. `/root/wb ps white-jotter` -> `http://0.0.0.0:48287/`; `curl http://46.224.225.245:48287/` from the Mac -> 200.
4. `opencode run ...` (three variants) -> `FreeTierError` 403; no model call happens.
5. `opencode api post /api/session` + `prompt` + `message` -> assistant answer, `idle` outcome `succeeded`; harness driver proven.
6. `/api/agent` -> `build`, `general` (pinned `opencode/deepseek-v4.1-flash-free`); `/api/model` -> 10 free models with variants.
7. Local docker up; local WebExploitBench + bash 5 present; `.gitignore` covers `eval/data-dependencies/`.
