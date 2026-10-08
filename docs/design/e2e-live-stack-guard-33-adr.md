# ADR: the degraded-backend e2e is opt-in, pinned, disposable, and bounded (#33)

## Status
Accepted (2026-10-08).

## Context
- `tests/e2e/test_health_degraded.py::test_health_reports_and_diagnoses_degraded_backend` shelled `docker compose up -d --build` from CWD, waited up to 600s, stopped `neo4j`, asserted `/health` degraded, then restarted `neo4j`.
- It targeted whatever stack CWD resolved to, with no overlay.
  `docker-compose.yml` pins `name: polymerhus` at the top level, and that wins over a worktree's directory-derived project name, so a run from a worktree still resolved the operator's LIVE `polymerhus` project.
  It composed only `docker-compose.yml`, dropping `docker-compose.dev.yml`, so it RECREATED the live containers under a different configuration than the operator deployed.
- A worktree has no `.env` (gitignored, only in the main checkout).
  The recreated agent therefore booted without `LLM_MODEL_*`, hit `validate_llm_config`, and fail-fast exited (`Exited (3)`).
  Named volumes survived; availability did not.
- `--build` plus the 600s wait made a plain `pytest tests/` look HUNG: no `pytest-timeout` was installed and nothing bounded the `subprocess.run` calls.
  The documented unit command (`.venv/bin/python -m pytest tests/ -q`) reaches `tests/e2e/`, so a unit run could stall on live infra.

## Decision
1. **Opt-in gate.** The test skips at module level unless `PH_E2E_LIVE=1`.
   The gate uses `pytest.skip(..., allow_module_level=True)`, so a bare `pytest tests/` collects zero items from the module (clean exit 0) and a direct file run reports one clean skip.
   The file also carries `pytest.mark.e2e_live`, registered in `pyproject.toml` `[tool.pytest.ini_options] markers`, so the live-stack class has a selectable label.
2. **Pinned compose.** Every invocation is `docker compose -f docker-compose.yml -f docker-compose.dev.yml --project-directory <repo root> -p <disposable project>`.
   The repo root is resolved from the test file (`Path(__file__).resolve().parents[2]`), never CWD, and each `subprocess.run` also sets `cwd=REPO_ROOT`.
   Both overlays are always present, so a partial config can never be composed.
3. **Disposable project.** The test runs under `polymerhus-e2e-health` (overridable via `PH_E2E_HEALTH_PROJECT`), not `polymerhus`.
   `-p` overrides the compose file's top-level `name:` and `COMPOSE_PROJECT_NAME`, so the test can never recreate or degrade the operator's project; containers, network, and volumes are all project-scoped.
   Teardown is `down -v --remove-orphans`, which reclaims the throwaway volumes.
4. **Bounded.** Every `subprocess.run` carries an explicit `timeout` (900s for the `--build` bring-up, 120s for later commands), the health polls keep their `wait_for` bounds, and the test carries `pytest.mark.timeout(1200)` as a backstop.
   `pytest-timeout==2.4.0` is added to `requirements-dev.txt`.
5. **Honest unit command.** `loop-constraints.md`, `README.md`, and `docs/design/testing-strategy.md` now document the unit command as `.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/integration`, so the live tier is excluded explicitly instead of by a remembered deselect list.

## Consequences
- A bare unit run cannot collect or hang on this test, and cannot reach it to mutate any stack.
- An opted-in run degrades and then destroys a throwaway project; the operator's `polymerhus` stack is untouched by construction.
- The test needs the operator's stack DOWN to run.
  The base compose fixes the network subnet (`172.28.0.0/16`) and publishes the host ports (`8080`, `5432`, `7687`, `7474`, `8000`, `9621`), so a throwaway project cannot coexist with the live stack.
  When the live stack is up, the bring-up fails fast on the port or subnet conflict; it does not degrade the live stack.
  A throwaway run also rebuilds the shared `polymerhus-agent:latest` / `polymerhus-kali:latest` tags from the worktree source, which is the intended image content but does replace the local tag.
- This is a test-infrastructure and documentation change only; no production code changed.

## Alternatives considered
- **Keep the stack target but only pin the config.** Rejected: the test would still stop and recreate the operator's live `polymerhus` services.
  A disposable project removes that failure mode entirely.
- **Deselect via `addopts = -m "not e2e_live"`.** Rejected: running the file directly would then deselect its only test and exit 5 (`NO_TESTS_COLLECTED`), which is not a clean result.
  The module-level skip reports a clean skip (exit 0) while still collecting nothing on a bare run.
- **A fixed opt-in boolean in a conftest collection hook.** Rejected: per-file gates already exist in this repo (`test_eval_chain_full_live.py` gates on `EVAL_CHAIN_E2E=1`), so the file-local env gate reuses the existing convention.
- **Rely on the `--ignore` flags alone.** Rejected as the only defence: they are easy to forget in an ad-hoc invocation, so the in-file gate is the durable guard.

## Known adjacent gap (flagged, not fixed here)
- Several root-level unit-tree tests still bring up live services and are not covered by `--ignore=tests/e2e`: `tests/test_stack_smoke.py`, `tests/test_agent_health.py`, `tests/test_kali_mcp.py`, `tests/test_neo4j_schema.py`, `tests/test_postgres_schema.py`, `tests/test_steel_exec_live.py`.
  They are pre-existing and tracked in `STATE.md` (the five docker-down failures).
  Moving them into `tests/e2e/` (or the integration tier) so the path-based live tier covers them is a recommended follow-up, out of #33's single-test scope.

## References
- #33.
- `tests/e2e/test_eval_chain_full_live.py` (the existing opt-in live-e2e pattern).
- `tests/e2e/gateway_stack.py` (the canonical `-f docker-compose.yml -f docker-compose.dev.yml` shape).
- `docs/design/testing-strategy.md` §1 and §5.
