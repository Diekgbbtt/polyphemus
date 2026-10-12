"""The ONE seam that selects an analysis proposer's role prompt FILE (T0 of the
batched L1-unit-first change).

The `service_sourced` mode keeps its value but gains a new default behaviour behind
`ANALYSIS_PROMPT_VARIANT`:

  - `batched_l1unit_first` (DEFAULT) loads `prompts/<base>-batched-l1unit-first.md`.
  - `legacy` loads the original `prompts/<base>.md` (the rollback).

Three roles share the seam: `assigner -> assigner`, `mechanism_typist ->
technical-system`, `data_modeller -> data-plane`.

Importing this module performs NO I/O and reads NO env var (CODING_STANDARD
section 6): the variant is resolved ON CALL, so a same-process test can flip it. It
deliberately imports none of the three role modules - it only builds paths under
`analysis/prompts/` - so the role modules can import it without a cycle.

The decision is the ADR `docs/design/batched-l1unit-first-adr.md`.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

BATCHED_L1UNIT_FIRST = "batched_l1unit_first"
LEGACY = "legacy"
KNOWN_VARIANTS = (BATCHED_L1UNIT_FIRST, LEGACY)
DEFAULT_VARIANT = BATCHED_L1UNIT_FIRST

# role_id -> the base name of the role's prompt file. `batched_l1unit_first` appends
# a suffix; `legacy` is the bare name. Kept here, not in the role modules, so the
# map has ONE owner and the seam stays leaf.
_ROLE_BASE_FILES = {
    "assigner": "assigner",
    "mechanism_typist": "technical-system",
    "data_modeller": "data-plane",
}


def _coerce(variant: str | None) -> str:
    """Coerce a raw variant to a known one, warning on an unknown value.
    Mirrors `assigner._assigner_prompt_config`: an ABSENT value is the default and
    does not warn; an UNKNOWN value does, naming the known values, then coerces."""
    cfg = (variant or DEFAULT_VARIANT).strip()
    if cfg not in KNOWN_VARIANTS:
        logger.warning(
            "ANALYSIS_PROMPT_VARIANT=%r is unknown (known: %s); using %r",
            cfg, ", ".join(KNOWN_VARIANTS), DEFAULT_VARIANT,
        )
        return DEFAULT_VARIANT
    return cfg


def resolve_prompt_variant() -> str:
    """The active prompt variant, read from `ANALYSIS_PROMPT_VARIANT` ON CALL."""
    return _coerce(os.environ.get("ANALYSIS_PROMPT_VARIANT"))


def prompt_path(role_id: str, variant: str | None = None) -> Path:
    """The prompt file for `role_id` under `variant` (resolving the env when None).

    An explicit `variant` overrides the env read; an unknown value coerces to the
    default with a warning, exactly like the env path. An unknown `role_id` raises
    (a programming error, never a silent miss). The path is built under this
    module's `prompts/` dir."""
    base = _ROLE_BASE_FILES.get(role_id)
    if base is None:
        raise KeyError(
            f"no prompt file registered for {role_id!r}; the analysis proposers "
            f"are {', '.join(sorted(_ROLE_BASE_FILES))}"
        )
    resolved = resolve_prompt_variant() if variant is None else _coerce(variant)
    suffix = "-batched-l1unit-first" if resolved == BATCHED_L1UNIT_FIRST else ""
    return Path(__file__).resolve().parent / "prompts" / f"{base}{suffix}.md"
