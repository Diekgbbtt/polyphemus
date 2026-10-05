"""Host-side preflight for the operator ground-truth overlay.

Run this on the host before the documented four-file Compose command:

    EVAL_WEB_DIR_HOST_PATH=/home/<operator>/WebExploitBench \
      python -m operator_api.preflight

It fails closed on a missing, relative, or nonexistent path and never creates
one. The diagnostics are stable codes and never echo the host path, so they are
safe to paste into a report.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ENV_VAR = "EVAL_WEB_DIR_HOST_PATH"

OK = "operator-preflight-ok"
CODE_MISSING = "operator-preflight-missing-benchmark-path"
CODE_RELATIVE = "operator-preflight-relative-benchmark-path"
CODE_NOT_A_DIRECTORY = "operator-preflight-benchmark-path-not-a-directory"


def check(raw: str | None) -> tuple[int, str]:
    """`(exit_code, message)` for the configured benchmark host path."""
    if raw is None or not raw.strip():
        return 1, f"{CODE_MISSING}: {ENV_VAR} is not set"
    path = Path(raw)
    if not path.is_absolute():
        return 1, f"{CODE_RELATIVE}: {ENV_VAR} must be an absolute path"
    if not path.is_dir():
        return 1, f"{CODE_NOT_A_DIRECTORY}: {ENV_VAR} is not an existing directory"
    return 0, OK


def main() -> int:
    """Print the outcome and return the exit code (0 when the path is usable)."""
    code, message = check(os.environ.get(ENV_VAR))
    stream = sys.stdout if code == 0 else sys.stderr
    print(f"operator ground truth preflight: {message}", file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
