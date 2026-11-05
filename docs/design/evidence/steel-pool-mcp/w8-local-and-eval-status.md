# W8 status: the pool path passes locally; the White Jotter gate is blocked

Date: 2026-11-05.
Scope: #359 W8.

## What passed

Two concurrent MCP clients through one browser MCP process, against two
labelled v0.5.5 workers on `127.0.0.1:3110` and `127.0.0.1:3111`.

- `prototype/steel_pool_mcp/probe_two_agents.py`
  Each client mounted a distinct worker (one live session per worker), both
  navigated the worker's own `/v1/health` concurrently, both ends reported
  `captured`, `saved`, and `stopped` true, the store held `two-a.json` and
  `two-b.json` at `0600`, and both workers settled with no live session.
- `prototype/steel_pool_mcp/probe_hunter_binding.py`
  The real `open_browser_tools` binding opened one MCP session, loaded exactly
  `browser_start` / `browser_exec` / `browser_end`, drove them through
  `invoke_tool`, and saved the record at `0600`.

The Kali entrypoint lane also passed live in the real image: the browser MCP
started beside the exec server, served the three tools, saved a record under
the mounted store, and released on `browser_end`.

## What is blocked on the eval server

1. The White Jotter target `web_white_jotter-wj-1` is crash-looping.
   On 2026-11-05 it had 536 restarts, and `https://127.0.0.1:46271/` on the
   eval host answered a broken pipe.
   The target must answer locally before any browser path can use it.
2. The eval host accepts only TCP 22 from the pool host.
   Ports 80, 443, and 46271 are closed to the pool host, so a worker cannot
   reach the target even when the target is healthy.
   The operator must admit the pool host to the target port, or publish the
   target through an allowed front.
3. The live eval instance `ph-dd131acc` is on branch `eval-ca` at `f020dafd`.
   Its `hunting_agent.py` diverged from this branch, its Kali tree has no
   browser MCP, and its agent image predates W7/W8.
   Recreating it needs a source merge and an image rebuild, which is an
   operator decision on a live stack.

## Operator steps to finish W8

1. Fix the White Jotter target and verify it answers on the eval host.
2. Admit the pool host to the target port, or put the target behind an
   allowed front.
3. Update the eval instance to this branch, rebuild `agent`, and recreate
   `kali` and `agent` with `docker-compose.pool-overlay.yml`.
4. Run the tunnel inside the eval Kali (`eval/deploy/steel/POOL-RUNBOOK.md`
   step 4).
5. Run the two-client probe against the eval Kali MCP, then navigate the
   White Jotter target through `browser_exec` and read the title.

## Local commands and evidence

```bash
STEEL_CLI=<cli-0.5.0-preview.6> \
STEEL_GUARD=$PWD/kali/steel_guard.py \
  .venv/bin/python prototype/steel_pool_mcp/probe_two_agents.py
# {"ok": true, records: two-a.json, two-b.json}

PYTHONPATH="$PWD:$PWD/src" \
STEEL_CLI=<cli-0.5.0-preview.6> \
STEEL_GUARD=$PWD/kali/steel_guard.py \
  .venv/bin/python prototype/steel_pool_mcp/probe_hunter_binding.py
# {"ok": true, "record_mode": "0o600"}
```
