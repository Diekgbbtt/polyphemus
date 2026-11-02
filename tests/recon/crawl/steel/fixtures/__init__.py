"""The steel-crawl fixture pack.

Import the loaders and their records from here; the JSON files live in the
sibling `cli/`, `dom/`, `cdp/`, and `golden/` directories.
"""
from __future__ import annotations

from .loader import FIXTURES_ROOT, FixtureError, load_cdp, load_cli, load_dom
from .records import CdpEvent, CdpStream, CliEnvelope, DomNode, DomSnapshot

GOLDEN_ROOT = FIXTURES_ROOT / "golden"

__all__ = [
    "FIXTURES_ROOT",
    "GOLDEN_ROOT",
    "CdpEvent",
    "CdpStream",
    "CliEnvelope",
    "DomNode",
    "DomSnapshot",
    "FixtureError",
    "load_cdp",
    "load_cli",
    "load_dom",
]
