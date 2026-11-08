# One browser tool: live E2E evidence

Date: 2026-11-08.
Host: `ubuntu-16gb-nbg1-1` (aarch64), the eval host.
Instance: `ph-dd131acc`.
Branch: `feat/steel-crawl-agent-browser` (the run started at `e3dfb410`;
the session-name fix landed during the run).
Design: `docs/design/agent-browser-integration-plan.md`.

## Stack

The instance worktree was switched to the branch and the agent image was
rebuilt from it. The stack came up with the four-file set:

```bash
docker compose -p ph-dd131acc \
  -f docker-compose.yml \
  -f docker-compose.dev.yml \
  -f docker-compose.pool.yml \
  -f eval/docker-compose.eval.yml up -d
```

Both Steel workers were healthy. The `.env` carries no `STEEL_API_KEY` and an
empty `STEEL_BROWSER_API_URL`. The agent carries
`KALI_BROWSER_MCP_URL=http://kali:8003/mcp`, and the pool MCP exposes exactly
`browser_start`, `browser_exec`, and `browser_end`.

## One browser tool

`tests/e2e/test_browser_tool_live.py` ran in-network against the live pool.
Both tests passed:

- An anonymous `start(url=...)` rendered the ComfyUI target in a worker; the
  title was readable, and the default `end` reported `context_saved=false`.
- A `start(account=...)` mounted the deterministic context
  `steel-auth-<project>-<account>`; `end(persist_context=true)` reported
  `context_saved=true`; the next start restored one cookie, one origin, and
  six storage keys; the cookie was readable and a default `end` wrote nothing.

## Deterministic crawl

The production `run_pipeline` ran the `steel_crawl` phase inside the agent
container (`eval/steel-crawl-e2e/phase_runner.py`), with the HTTP-history edge
on a loopback port.

Anonymous ComfyUI (`http://t-1fc05262.target/`):

- `steel_crawl` success, `stop_reason=frontier_empty`, no errors.
- 55 kept endpoints, 6 parameters, 514 raw endpoints.
- 537 captured HTTP artifacts, 491 bodies, 8.2 MB.

White Jotter with the decoupled auth context
(`http://t-1618c524.target/`, account `admin-wj-e2e`):

- The context was minted through the pool MCP: start with
  `context_ref=steel-auth-e2e-branch-wj-admin-wj-e2e`, login through the
  target's `/api/login`, oracle `/api/authentication` returned 200, end with
  `persist_context=true` (`context_saved=true`).
- The crawl mounted the same reference, restored the persisted cookie, passed
  the oracle, and completed: 16 endpoints, 5 parameters, 170 artifacts.
- The manifest records
  `run.auth.classification=authenticated`,
  `probe_source=overview.auth_probe.url`, and the target's oracle URL.

## Defect found and fixed

The first crawl failed with
`Browser daemon exited: path must be shorter than SUN_LEN`. The Steel CLI
daemon listens on `/root/.config/steel/daemon-<session>.sock`; Linux
`sun_path` is 108 bytes including the terminator. The derived session name
was 76 characters, which made the socket path exactly 108. The name is now
capped at 75, and `tests/app/test_browser_tools.py` pins the socket-path
budget. The rerun passed both crawls.

## Host-side e2e tier

The `tests/e2e` tier ran from a host venv against the live instance: 99
passed, 40 skipped, 4 failed. The remaining failures are not on the browser
path:

- `test_compaction_live`: the real model's running-summary output sometimes
  fails the `SummaryUpdate` schema (a live-model flake; the pass triggers but
  degrades to `unchanged`).
- `test_compaction_walkthrough`: green on the pinned local venv; the eval-host
  venv is Python 3.14 assembled from the eval scaffold, not the repo pins.
- `test_reprofile_one_pod_walkthrough`: the default target
  `soupmarket.shop` is unreachable from the eval host.
- `test_recon_crawl_katana_depth` failed in the full run on the import-order
  depth coupling and passes with the in-place job pin applied after the run.

The process environment is isolated per test (`tests/e2e/conftest.py`) so a
walkthrough that bridges to host-side service URLs cannot rewrite what a later
`docker compose up` interpolates into a container.

Six files were excluded because they need a disposable or sibling
`polymerhus` topology (the eval instance owns the `172.28.0.0/16` subnet and
the published ports): the blackloop and hunting-wiring walkthroughs, the unit
threat-model walkthrough, the LLM cost override, and the gateway teardown.
`test_stack_smoke` and `test_agent_health` were included; both brought the
instance services up with the four-file set.

Live drifts fixed while running the tier:

- `steel_exec` returns the binary guard's `steel_events` (and
  `shell_returncode` / `error` on a refusal); the envelope assertion now
  accepts them.
- The models.dev catalog renamed `deepseek-v4-flash` to
  `deepseek-v4.1-flash`; the gateway reroute, capability reader, and
  independent-oracle literals were refreshed to the live ids and costs.
- The direct-mode probe now blanks `LLM_GATEWAY_URL` because a gateway
  deployment always sets it.
- The reasoning-replay assertion matches the current
  `llm-response: reasoning replay (agent layer)` line.
- The katana preflight compares the template with `{auth_flags}` expanded, and
  its incoherent-subset probe is `arjun` alone (`katana` alone is a valid
  target-scoped crawl).
- The reprofile host bridge uses the configured role's direct provider when no
  OpenRouter key exists.
- The token-overflow probe asserts the project-wide execution-stop call.
- The SwissAI capability run uses a live namespaced model.
- The direct-runtime guards (`test_steel_interactive_local.py`,
  `test_steel_internal_reachability.py`) were retired; the pool owns session
  creation and rewrites the CDP endpoint, so a direct CLI or SDK session
  cannot reach a worker. `test_browser_tool_live.py` is the replacement.

## Verdict

The one browser tool, the decoupled auth context, the explicit persist, the
default no-write end, and the deterministic crawl all passed against the live
pool with two healthy workers. The live run also found and fixed the
session-name socket-path bound.
