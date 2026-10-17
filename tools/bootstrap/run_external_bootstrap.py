#!/usr/bin/env python3
"""The external-bootstrap entry point: argv -> `runner.cli.main`.

Only sys.path wiring lives here (the architecture doc, section 2): `tools/bootstrap`
for the `runner` package itself, and `eval/` for the platform's
`orchestrator.commands`, which the harness adapter reuses for its command seam.
Everything else is the CLI:

    python3 tools/bootstrap/run_external_bootstrap.py plan   --config <run.yaml>
    python3 tools/bootstrap/run_external_bootstrap.py run    --config <run.yaml>
    python3 tools/bootstrap/run_external_bootstrap.py status --rundir <rundir>
    python3 tools/bootstrap/run_external_bootstrap.py resume --rundir <rundir>
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]

for _relative in ("tools/bootstrap", "eval"):
    _path = str(_REPO_ROOT / _relative)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from runner.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
