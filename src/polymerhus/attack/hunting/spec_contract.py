"""The hunter -> pod spec contract types shared by both roles (S3 8.6, S5 8.6).

The hunter authors the spec set; the pod's triager reads it. Three types are
shared.

`Discriminator` is one instance of a discrimination variable: the `axis` the
hunter named in `phase:discriminate` and the `value` the slot takes on that
axis. The ordered tuple of discriminator values is the spec identity, so the
identity is the same argument the hunter used to separate the slot from its
nearest alternative.

`SkillConcretisedProcedure` is the target-specific concretisation of the loaded
abstract procedure. It replaces the old copied seven-field class excerpt: the
hunter writes what the procedure becomes on this target, and the triager diffs
the executed probe against that concretisation.

`SpecProvenance` is the dispatch provenance. It no longer carries the copied
class excerpt; the concretised procedure is a first-class spec field.

This module is pure (pydantic models + constants); it imports no driver and
performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# --- the discrimination axes and the derived identity -------------------------

DISCRIMINATOR_AXIS_PATTERN = r"^[a-z][a-z0-9-]{0,40}$"
"""The axis token: the variable name the hunter declared in DISCRIMINATE."""

DISCRIMINATOR_VALUE_PATTERN = r"^[a-z0-9][a-z0-9.-]{0,59}$"
"""The instance value token. `_` is deliberately absent: the identity join is
`__`, so a value can never contain the separator. A single `-` and `.` are
allowed for readable words such as `signed-url` and `v1.2`."""

MIN_DISCRIMINATORS = 2
"""A spec is separated on at least two dimensions (DISCRIMINATE)."""

MAX_DISCRIMINATORS = 4
"""More than four dimensions is a slice, not a spec: split the slice or merge
the axes instead of producing an unreadable identity."""

SPEC_IDENTIFIER_MAX_CHARS = 120
"""The file-name stem bound; a longer identity is a slice-level name."""

_SAFE_COMPONENT_RE = re.compile(r"[^a-z0-9.-]+")
_SAFE_VALUE_RE = re.compile(DISCRIMINATOR_VALUE_PATTERN)
_SAFE_AXIS_RE = re.compile(DISCRIMINATOR_AXIS_PATTERN)


class Discriminator(BaseModel):
    """One instance of one discrimination variable.

    The `axis` names the variable (for example `delivery-route`); the `value`
    names the instance the slot takes (for example `signed-url`). The ordered
    list of discriminators is the spec's separation argument.
    """

    axis: str = Field(
        pattern=DISCRIMINATOR_AXIS_PATTERN,
        description="The discrimination variable name, lowercase kebab-case.",
    )
    value: str = Field(
        pattern=DISCRIMINATOR_VALUE_PATTERN,
        description="The instance value on that axis, lowercase. It cannot "
                    "contain `__` (the identity separator).",
    )

    model_config = ConfigDict(extra="forbid")


# --- the concretised skill procedure ------------------------------------------

SKILL_CONCRETISED_PROCEDURE_FIELDS: tuple[str, ...] = (
    "recon_action",
    "bypass_technique",
    "advanced_technique",
    "preliminary_chaining",
    "payload_vector",
    "technology_misconfiguration",
    "technology_grounding",
    "pro_tips",
    "interpretation_pitfalls",
)
"""The nine concretisation fields, in the triager's procedure-gap order.

The first five are the dimensions the hunter uses to describe the instance
values that discriminated the spec. The last four keep the grounding, the
practical tips, and the interpretation pitfall. A field the target does not
exercise stays an empty string, which the triager treats as a recorded gap."""

SKILL_CONCRETISED_PROCEDURE_MAX_CHARS = 6000
"""The bounded concretisation. It is larger than the old copied excerpt because
it now carries the target-specific instance description, not a class excerpt."""


class SkillConcretisedProcedure(BaseModel):
    """The abstract procedure, concretised on the target for this spec.

    The hunter reads the class skill and writes what the procedure becomes on
    this target. The pod triager diffs the executed probe against this object;
    the pod runner may load the declared skills for a wider view but follows
    this concretisation.
    """

    recon_action: str = Field(
        default="",
        description="The concrete reconnaissance action on this target.")
    bypass_technique: str = Field(
        default="",
        description="The technique that bypasses the target's control.")
    advanced_technique: str = Field(
        default="",
        description="The advanced technique the slot exercises, or empty.")
    preliminary_chaining: str = Field(
        default="",
        description="The prior vulnerability the slot chains with, or empty.")
    payload_vector: str = Field(
        default="",
        description="The concrete payload vector: the effective request item, "
                    "its content, and its encoding.")
    technology_misconfiguration: str = Field(
        default="",
        description="The protocol or technology misconfiguration the slot "
                    "relies on.")
    technology_grounding: str = Field(
        default="",
        description="How the target technology is grounded on this target.")
    pro_tips: str = Field(
        default="",
        description="The practical tip that separates the slot from its "
                    "nearest alternative.")
    interpretation_pitfalls: str = Field(
        default="",
        description="The observation that would be misread as confirmation.")

    model_config = ConfigDict(extra="forbid")

    def excerpt_length(self) -> int:
        """The total concretisation length over the nine fields."""
        return sum(
            len(getattr(self, name)) for name in SKILL_CONCRETISED_PROCEDURE_FIELDS
        )


# --- the provenance and target identity ---------------------------------------

SPEC_PROVENANCE_FIELDS: tuple[str, ...] = (
    "run_id",
    "loop_id",
    "unit_id",
    "canonical_class",
    "web_vulnerability_class",
    "baseline_ref",
    "source_recon_refs",
    "assumption_ref",
    "playbook",
)
"""The provenance fields the hunter writes into every spec (S3 8.6/8.9).

`loop_id`, `unit_id`, the two classes and the loop's provenance ride the
dispatch payload; `baseline_ref` is optional; `source_recon_refs`,
`assumption_ref` and `playbook` record the grounding the hunter used. The
copied `skill_procedure` is retired: the concretised procedure is a top-level
spec field.""" 


class TargetIdentity(BaseModel):
    """The D4 target identity (#197): the probe base `url` plus the L1
    service/system `unit_id`.

    This is the ONE home for the shape the hunter writes and the pod reads.
    The harness binds it at the `hunts_store` tool from the dispatch context, so
    the hunter never authors it on the normal path. The fields default lenient
    so the pod's INIT rejection can collect every violation instead of raising
    at parse time.
    """

    url: str = Field(
        default="",
        description="The base URL the pod probes. Bound by the symbolic layer "
                    "from the project's canonical origin and the loop's "
                    "evidence; a spec without a url is INIT-rejected.")
    unit_id: str = Field(
        default="",
        description="The kind-qualified L1 service/system identity that surfaces "
                    "alongside the URL (for provenance).")

    model_config = ConfigDict(extra="forbid")


class SpecProvenance(BaseModel):
    """The typed provenance mapping every hunter spec carries (S3 8.6/8.9).

    The field set is the `SPEC_PROVENANCE_FIELDS` contract, so the tool schema
    and the pod/triager read cannot drift.
    """

    run_id: str = Field(
        default="",
        description="The hunting run id the spec was authored under; bound by "
                    "the hunts_store tool, never authored by the model.")
    loop_id: str = Field(default="", description="The dispatching loop id.")
    unit_id: str = Field(default="", description="The L1 unit identity.")
    canonical_class: str = Field(
        default="", description="The freely named taxonomy class.")
    web_vulnerability_class: str = Field(
        default="",
        description="The suite directory name; empty for a suite_gap.")
    baseline_ref: str = Field(
        default="",
        description="The optional recorded-baseline artifact id.")
    source_recon_refs: list[str] = Field(
        default_factory=list,
        description="The recon observations/probes this spec is grounded on.")
    assumption_ref: str = Field(
        default="", description="The assumption this spec tests, when one applies.")
    playbook: str = Field(
        default="", description="The short procedure the pod should follow.")

    model_config = ConfigDict(extra="forbid")


# --- the derived identity ------------------------------------------------------


def _safe_value(value: Any) -> str:
    """One identity value, validated against the value alphabet.

    A mapping/object is coerced through `Discriminator` first, so the tool
    schema and the store agree. A raw string is checked directly. An unsafe
    value raises `ValueError` (the store turns it into a coded rejection)."""
    if isinstance(value, Discriminator):
        return value.value
    if isinstance(value, Mapping):
        try:
            return Discriminator.model_validate(value).value
        except Exception as exc:  # noqa: BLE001 - a coded store rejection
            raise ValueError(
                f"identity value {value!r} is not a safe value token "
                f"({DISCRIMINATOR_VALUE_PATTERN}); it cannot contain the `__` "
                "separator") from exc
    if not isinstance(value, str):
        raise ValueError(f"identity value {value!r} is not a string")
    if not _SAFE_VALUE_RE.fullmatch(value):
        raise ValueError(
            f"identity value {value!r} is not a safe value token "
            f"({DISCRIMINATOR_VALUE_PATTERN}); it cannot contain the `__` "
            "separator")
    return value


def _safe_axis(discriminator: Any) -> str:
    if isinstance(discriminator, Discriminator):
        return discriminator.axis
    if isinstance(discriminator, Mapping):
        axis = discriminator.get("axis")
    else:
        raise ValueError(f"discriminator {discriminator!r} is not a mapping")
    if not isinstance(axis, str) or not _SAFE_AXIS_RE.fullmatch(axis):
        raise ValueError(
            f"discrimination axis {axis!r} is not a safe axis token "
            f"({DISCRIMINATOR_AXIS_PATTERN})")
    return axis


def _safe_class(value: str) -> str:
    """The class segment: lowercase, safe, never empty."""
    out = _SAFE_COMPONENT_RE.sub("-", str(value or "").strip().lower())
    out = re.sub(r"-{2,}", "-", out).strip("-.")
    return out or "spec"


def spec_identifier(
    class_name: str,
    discriminators: Sequence[Discriminator | Mapping[str, Any]],
    *,
    fallback_class: str = "",
) -> str:
    """The DERIVED spec identity: `<class>__<value>__<value>[__...]`.

    The class is the spec's `web_vulnerability_class` (or `canonical_class`,
    then `fallback_class`, then the literal `spec`). The values are the ordered
    discriminator instances: the same order the hunter wrote in DISCRIMINATE.
    The `__` join is unambiguous because a value can never contain `__`.

    Raises `ValueError` for fewer than two or more than four discriminators, a
    duplicate axis, an unsafe token, or an over-long identity. The store turns
    the error into a coded teaching rejection.
    """
    items = list(discriminators or ())
    if len(items) < MIN_DISCRIMINATORS:
        raise ValueError(
            f"a spec identity needs at least two discriminator values "
            f"(got {len(items)}); one value is not a discrimination")
    if len(items) > MAX_DISCRIMINATORS:
        raise ValueError(
            f"a spec identity takes at most four discriminator values "
            f"(got {len(items)}); more is a slice, not a spec")
    axes = [_safe_axis(item) for item in items]
    if len(set(axes)) != len(axes):
        raise ValueError(
            f"duplicate discrimination axis in {axes!r}; each axis names one "
            "separation dimension")
    values = [_safe_value(item) for item in items]
    ident = "__".join([_safe_class(class_name or fallback_class), *values])
    if len(ident) > SPEC_IDENTIFIER_MAX_CHARS:
        raise ValueError(
            f"the spec identity is {len(ident)} characters, over the "
            f"{SPEC_IDENTIFIER_MAX_CHARS}-character bound; shorten the class or "
            "the discriminator values")
    return ident


def skill_concretised_procedure_from(
        spec: object) -> SkillConcretisedProcedure | None:
    """The typed `SkillConcretisedProcedure` carried by a spec, or None.

    Accepts a stored mapping (or an already-built model). A malformed value is
    None: the reader (the triager) records the gap and no variant basis is
    derivable, never a raise."""
    if isinstance(spec, SkillConcretisedProcedure):
        return spec
    if not isinstance(spec, Mapping):
        return None
    raw = spec.get("skill_concretised_procedure")
    if raw is None:
        return None
    try:
        return SkillConcretisedProcedure.model_validate(raw)
    except Exception:  # noqa: BLE001 - a malformed concretisation is a gap
        return None


__all__ = [
    "DISCRIMINATOR_AXIS_PATTERN",
    "DISCRIMINATOR_VALUE_PATTERN",
    "Discriminator",
    "MAX_DISCRIMINATORS",
    "MIN_DISCRIMINATORS",
    "SKILL_CONCRETISED_PROCEDURE_FIELDS",
    "SKILL_CONCRETISED_PROCEDURE_MAX_CHARS",
    "SPEC_IDENTIFIER_MAX_CHARS",
    "SPEC_PROVENANCE_FIELDS",
    "SkillConcretisedProcedure",
    "SpecProvenance",
    "TargetIdentity",
    "skill_concretised_procedure_from",
    "spec_identifier",
]
