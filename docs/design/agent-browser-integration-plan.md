# Agent browser integration plan

Status: S1-S6 complete, S7 in progress, 2026-11-07.
Branch: `feat/steel-crawl-agent-browser`, based on `feat/steel-crawl-convergence`.
Design inputs: the convergence record and the operator decisions of 2026-11-07.

## Fixed decisions

- The agent-facing surface is ONE tool: `browser(command, url, input, account, persist_context)`.
- The tool description carries the usage contract. Each agent's Tools paragraph gets one entry.
- The session name is never an agent parameter. The binding derives it from the execution unit.
- The auth context is a decoupled object in the pool store. The auth store holds a reference.
- `steel.state` is removed completely. No fallback and no compatibility read.
- Fail-open everywhere. The lease TTL is the backstop.
- Actor-lifetime binding. End the session when the browser is not needed anymore.
- Pool size stays two.
- Legacy crawler six-tool path is removed with an EOL record.

## In-scope agents

- `job_orchestrator` (the recon orchestrator's gateway stretch), full browser.
- `hunting_threat_modeller`, full browser.
- `hunting_hunter`, full browser.
- `pod_runner`, full browser.
- `pod_triager`, full browser (the old "never touches the target" invariant becomes "never mutates the target").
- `triager` (recon triager), full browser.
- `mechanism_typist`, full browser in the verify/falsify phase.

Out: `assigner`, `skill_evolver`, one-shot roles, `configurator`, `crawler` (removed).

## Slices

### S1 Shared browser tool and client (complete)

- Add `src/polymerhus/app/llm/browser_client.py`: the sync MCP client, generalised from the crawl client.
- Add `src/polymerhus/app/llm/browser_tools.py`: the unified `BrowserTool`, the contract description, the session/context key helpers, and the model-safe result projection (no CDP endpoint is exposed).
- Delete `src/polymerhus/attack/hunting/browser_tools.py`; there is no compatibility re-export (the old wrapper had no consumer after the binding swap).
- Gate: the new unit tier is green.

### S2 Pool store context reference (complete)

- `kali/steel_pool/lease.py`: `start(context_ref=...)`, `end(persist_context=...)`, context save under the ref.
- `kali/steel_pool/server.py`: the MCP tools pass the context ref and the persist flag.
- The session name stays the ephemeral key. The context ref is the durable auth-context key.
- Gate: `tests/kali` is green.

### S3 Auth store decoupling (complete)

- Replace `account.steel` with `account.browser_context = {ref}` in the auth records and the tool contract.
- Replace `project_steel_state` with `project_browser_context`.
- The pipeline passes `browser_context_ref` to the crawl.
- The crawl computes an ephemeral session name and mounts the context ref.
- Delete `app/steel_session_state.py` and its old session-state tests.
- Gate: the auth feed, pipeline, crawl, and auth-store tests are green.

### S4 Agent bindings and prompts (complete)

- Bind `BrowserTool` to every in-scope agent at its actor or turn boundary.
- Add the `browser` entry to every in-scope Tools paragraph.
- Add `steel-browser` to every in-scope role's bounded skill set.
- The shared auth seam forwards `project_id` and lets `with_write_skill` win over `with_readonly_auth_store`, so the gateway's bound skill role and its project-scoped auth store agree.
- The mechanism typist binds the browser on its turn; the prompt scopes its use to the verify/falsify phase.
- Gate: the agent tool-surface and prompt tests are green.

### S5 Pod evidence (complete)

- Record every browser call as a `RawObservation` with a command hash, status, returncode, and error code.
- Count the call against the pod cap and dedup repeats.
- Gate: the pod tool, harness, and ReAct seam tests are green.

### S6 Legacy crawler removal (complete)

- Delete `crawl_agent.py`, `crawl_agentic.py`, `steel_provider.py`, `steel_client.py`, and `prompts/steel-crawl.md`.
- Remove the `crawler` role and every comment/test/doc that wires it.
- Rename the `steel_crawl` job skill from `agentic_crawl` to `steel_crawl`.
- Point the analysis anatomy deep-probe availability check at `KALI_BROWSER_MCP_URL`.
- Add the EOL record with date 2026-11-07 and the rationale.
- Gate: the full targeted tier is green and no `crawler` reference remains outside the EOL record.

### S7 Review and verification (complete)

- Adversarial standards and spec review (two axes, parallel sub-agents). The
  final pass after the fix commits reports no hard standards violations and no
  missing spec requirement; the remaining judgement calls are accepted (the
  pool context is a session record under a context key, the six tool bindings
  share one constructor, and the app/crawl typed-error classes stay layer
  local).
- Full unit tier: 6821 passed, 44 skipped, 1 xfailed. The only failures are the
  six known local Node failures in `tests/ingestion/test_n8n_url_workflow.py`
  (`docs/tickets/local-node-missing-simdjson.md`).
- Targeted tiers: `tests/app tests/kali tests/eval` 1717 passed, 22 skipped;
  `tests/recon` 1722 passed, 14 skipped; `tests/attack tests/analysis` 1318
  passed.
- Integration tier: 324 passed, 44 skipped. The one failure is the live
  Postgres schema test, which needs a local Postgres the host does not run;
  production and CI point `POSTGRES_DSN` at the compose service.
- E2E tier: 161 tests collected; the live walkthroughs stay operator-gated.
- Environment note: the local Neo4j database had entered a critical
  no-space state; the Docker build cache was pruned (22 GB) and the container
  restarted before the integration run.
