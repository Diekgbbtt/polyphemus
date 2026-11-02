"""Load the checked-in fixtures into their typed records.

A loader never returns raw JSON: a malformed fixture must stop the test that
uses it, naming the file, rather than degrade into a downstream type error.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .records import CdpStream, CliEnvelope, DomSnapshot

FIXTURES_ROOT = Path(__file__).resolve().parent

ModelT = TypeVar("ModelT", bound=BaseModel)


class FixtureError(ValueError):
    """A fixture is missing, unparseable, or does not match its record."""


def _load_model(path: Path, model: type[ModelT]) -> ModelT:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FixtureError(f"fixture not found: {path}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FixtureError(f"fixture is not valid JSON: {path}: {exc}") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise FixtureError(f"fixture does not match {model.__name__}: {path}: {exc}") from exc


def load_cli(name: str, *, root: Path = FIXTURES_ROOT) -> CliEnvelope:
    """Load one CLI envelope by verb name, e.g. `load_cli("navigate")`."""
    return _load_model(root / "cli" / f"{name}.json", CliEnvelope)


def load_dom(name: str, *, root: Path = FIXTURES_ROOT) -> DomSnapshot:
    """Load one DOM snapshot by page name, e.g. `load_dom("home")`."""
    return _load_model(root / "dom" / f"{name}.json", DomSnapshot)


def load_cdp(name: str, *, root: Path = FIXTURES_ROOT) -> CdpStream:
    """Load one CDP event stream by name, e.g. `load_cdp("http_flow")`."""
    return _load_model(root / "cdp" / f"{name}.json", CdpStream)
