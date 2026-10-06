# ADR: configuration is read through the module, never bound by value at import

## Status
Accepted (2026-10-06).

## Context
- `tests/ingestion/test_lightrag_wait_budget.py::test_from_config_wires_configured_deadline` passed alone and failed after `tests/lightrag` with `assert 1800.0 == 3600.5`.
- `tests/lightrag/test_client.py` called `importlib.reload(polymerhus.app.config)`.
  A reload rebinds `polymerhus.app.config.config` to a fresh object.
- `src/polymerhus/ingestion/service.py` bound the old object at import with `from polymerhus.app.config import config`.
  `IngestionService.__init__` and `from_config` then read that stale module-global, so the victim's `monkeypatch.setattr(config_module.config, ...)` mutated the reloaded object while the service read the pre-reload one.
- The leak is not unique to that test file.
  `tests/test_app_config.py` and several e2e tests also reload `polymerhus.app.config`, and any module that binds `config` by value at import (20 modules today) desyncs the same way.
- This is a test-pollution defect, not a product bug: production imports the config module once and never reloads it.

## Decision
- `src/polymerhus/ingestion/service.py` reads config through the module: `from polymerhus.app import config as config_module`, then `config_module.config.<NAME>` at each use site.
  The module attribute resolves at call time, so a reload or an attribute replacement is always observed.
- `tests/lightrag/test_client.py` no longer reloads the config module.
  It patches `config_module.config` attributes through `monkeypatch` (the seam), which removes the named global-state mutation without weakening the assertion.
- The new regression test `tests/ingestion/test_lightrag_wait_budget.py::test_from_config_reads_config_through_the_module` pins the invariant by replacing the module attribute with a stub (no reload).
  It is red against the import-time binding and green against the module read, in default collection order.
- Scope is the observed victim plus the named polluter.
  The remaining import-time `config` bindings are a tracked follow-up of the same class; hardening all 20 now would widen an otherwise local fix.

## Consequences
- The order-dependent flake is removed.
  `.venv/bin/python -m pytest tests/lightrag tests/ingestion/test_lightrag_wait_budget.py::test_from_config_wires_configured_deadline -q` passes, and the victim is now immune to any test that reloads the config module.
- `tests/ingestion/test_service.py::test_default_storage_reader_uses_configured_storage_dir` patches the canonical `polymerhus.app.config.config` object instead of the former `service.config` alias, matching where the service now reads.
- A unit test that reloads the config module no longer poisons the ingestion service; it must still restore the module to its prior values before the session continues.
- `tests/lightrag/test_client.py` keeps its contract: `build_lightrag_clients` still reads distinct base/writeup URLs and the shared key and timeout from config, now proven by patching config values directly.

## References
- #333 (this bug), #324 (where it was found), #335 (recent config-adjacent change).
- `docs/design/testing-strategy.md`; `src/polymerhus/app/CONTEXT.md`; `src/polymerhus/ingestion/service.py`; `polymerhus/app/config.py`; `lightrag/client.py`.
