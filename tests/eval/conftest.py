"""Test setup for the eval harness modules.

`eval/` is a flat directory of scripts with no package `__init__`; the newer
`eval/advance/` package is imported by putting `eval/` on `sys.path`, so the
tests load it the same way the daemon's entry point does.
"""
from __future__ import annotations

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))
