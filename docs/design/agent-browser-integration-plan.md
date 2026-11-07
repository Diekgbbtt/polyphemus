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
- Add `src/polymerhus/app/llm/browser_tools.py`: the unified `BrowserTool`, the contract description, the session/context key helpers, and the CDP-field stripper.
- Keep `src/polymerhus/attack/hunting/browser_tools.py` as a compatibility re-export.
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
- Gate: the agent tool-surface and prompt tests are green.

### S5 Pod evidence (complete)

- Record every browser call as a `RawObservation` with a command hash, status, returncode, and error code.
- Count the call against the pod cap and dedup repeats.
- Gate: the pod tool, harness, and ReAct seam tests are green.

### S6 Legacy crawler removal (complete)

- Delete `crawl_agent.py`, `crawl_agentic.py`, `steel_provider.py`, `steel_client.py`, and `prompts/steel-crawl.md`.
- Remove the `crawler` role and every comment/test/doc that wires it.
- Rename the `steel_crawl` job skill from `agentic_crawl` to `steel_crawl`.
- Add the EOL record with date 2026-11-07 and the rationale.
- Gate: the full targeted tier is green and no `crawler` reference remains outside the EOL record.

### S7 Review and verification (in progress)

- Adversarial standards and spec review.
- Full unit tier and the targeted integration tier.
- Evidence record.
