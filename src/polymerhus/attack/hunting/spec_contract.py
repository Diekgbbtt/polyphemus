"""The hunter -> pod spec contract types shared by both roles (S3 8.6, S5 8.6).

The hunter authors the spec set; the pod's triager reads it. The one type both
sides must agree on is the typed `SkillProcedure` carried in
`spec["provenance"]["skill_procedure"]`: a seven-field excerpt of the loaded
web-vulnerability class skill, one field per procedure-gap class the triager
tests (S5 8.6). The type lives HERE, in one home, so the hunter writes the same
shape the triager reads (T6 #379 carry-forward; the plan's "single home"
disposition).

`SKILL_PROCEDURE_MAX_CHARS` is the bounded excerpt (S3 8.6): the total excerpt
is capped at 4000 characters, and the hunter-store write rejects an over-long
one with a coded teaching rejection instead of silently truncating authored
content.

This module is pure (pydantic models + constants); it imports no driver and
performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

SKILL_PROCEDURE_FIELDS: tuple[str, ...] = (
    "recon_action",
    "bypass_technique",
    "technology_grounding",
    "pro_tips",
    "advanced_technique",
    "preliminary_chaining",
    "interpretation_pitfalls",
)
"""The seven procedure-gap fields, in the S5 8.6 table order: the triager maps
each field to its gap class one-to-one, so the order is part of the contract."""

SKILL_PROCEDURE_MAX_CHARS = 4000
"""The bounded skill-procedure excerpt (S3 8.6): the total of the seven fields."""

SPEC_PROVENANCE_FIELDS: tuple[str, ...] = (
    "loop_id",
    "unit_id",
    "canonical_class",
    "web_vulnerability_class",
    "baseline_ref",
    "source_recon_refs",
    "assumption_ref",
    "playbook",
    "skill_procedure",
)
"""The provenance fields the hunter writes into every spec (S3 8.6/8.9).

`loop_id`, `unit_id`, the two classes and the loop's provenance ride the
dispatch payload; `baseline_ref` is optional; `source_recon_refs`,
`assumption_ref` and `playbook` record the grounding the hunter used; the
`skill_procedure` is the typed excerpt above."""


class SkillProcedure(BaseModel):
    """The typed seven-field skill-procedure excerpt (S3 8.6, S5 8.6).

    Each field carries the loaded class skill's text for that procedure
    section. Fields default to the empty string so a partial skill still
    round-trips; the triager treats an empty field as an uncovered gap."""

    recon_action: str = ""
    bypass_technique: str = ""
    technology_grounding: str = ""
    pro_tips: str = ""
    advanced_technique: str = ""
    preliminary_chaining: str = ""
    interpretation_pitfalls: str = ""

    model_config = ConfigDict(extra="forbid")

    def excerpt_length(self) -> int:
        """The total excerpt length over the seven fields."""
        return sum(len(getattr(self, name)) for name in SKILL_PROCEDURE_FIELDS)


def skill_procedure_from(provenance: object) -> SkillProcedure | None:
    """The typed `SkillProcedure` carried by `provenance`, or None.

    Accepts the stored mapping (or an already-built model); a malformed value
    is None - the reader (the triager) records the gap and uses the
    failure-mode fallback, never a raise."""
    if not isinstance(provenance, dict):
        return None
    raw = provenance.get("skill_procedure")
    if raw is None:
        return None
    try:
        return SkillProcedure.model_validate(raw)
    except Exception:  # noqa: BLE001 - a malformed excerpt is a recorded gap
        return None


__all__ = [
    "SkillProcedure",
    "SKILL_PROCEDURE_FIELDS",
    "SKILL_PROCEDURE_MAX_CHARS",
    "SPEC_PROVENANCE_FIELDS",
    "skill_procedure_from",
]
