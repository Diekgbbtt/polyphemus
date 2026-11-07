# Ticket: the local Node install aborts, reddening the n8n URL-workflow tests

- **Severity:** low (environment; production and CI use their own Node).
- **Area:** `tests/ingestion/test_n8n_url_workflow.py` (6 tests), local `/opt/homebrew/bin/node`.
- **Status:** open (found 2026-11-07 while running the full unit tier).
- **Filed from:** the steel-crawl pool convergence verification.

## Summary

The six n8n URL-workflow tests run a Node one-liner to validate the workflow's
native boolean expressions. On this workstation every `node -e` invocation
aborts before it evaluates the expression:

```text
dyld[58276]: Library not loaded: /opt/homebrew/opt/simdjson/lib/libsimdjson.33.dylib
  Referenced from: .../node/26.7.0/bin/node
  Reason: tried: '/opt/homebrew/opt/simdjson/lib/libsimdjson.33.dylib' (no such file)
```

`node --version` exits `134` (SIGABRT).
The failure is independent of the convergence diff; the tests do not import
any changed module.

## Evidence

```text
$ node --version
dyld[...]: Library not loaded: /opt/homebrew/opt/simdjson/lib/libsimdjson.33.dylib
zsh: abort node --version

$ .venv/bin/pytest -q tests/ingestion/test_n8n_url_workflow.py
6 failed
  subprocess.CalledProcessError: Command '['/opt/homebrew/bin/node', '-e', ...]'
  died with <Signals.SIGABRT: 6>.
```

## Proposed fix

Repair the local Node installation, then rerun the file:

```bash
brew reinstall simdjson node
.venv/bin/python -m pytest -q tests/ingestion/test_n8n_url_workflow.py
```

No repository change is expected; the workflow expressions are not under test
here.

## Acceptance criteria

- `node --version` prints a version.
- `tests/ingestion/test_n8n_url_workflow.py` passes.
- The full unit tier has no environment-only failures.
