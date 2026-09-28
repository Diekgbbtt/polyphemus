"""data_root.py - the eval harness's shared #234 data-root resolver.

One behaviour, one implementation: every eval script resolves the app-owned
data root through this module. `HUNT_DATA_ROOT` overrides; otherwise the repo
root beside `eval/`, then the CWD. Resolution runs on call, never at import.
"""
from __future__ import annotations

import os
from pathlib import Path


def resolve() -> Path:
    """The app-owned data root: the `HUNT_DATA_ROOT` override, else `<repo>/data`."""
    env = os.environ.get("HUNT_DATA_ROOT")
    if env:
        return Path(env)
    candidates = [Path(__file__).resolve().parents[1] / "data", Path.cwd() / "data"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
