"""The CVSS 4.0 risk module: the ONE place the repository talks to `cvss`.

`risk` is the CVSS 4.0 base score of one impact assessment, a float in
`0.0 .. 10.0` rounded to two decimals.  It is the only severity number; the
qualitative `SeverityBand` is derived from it on read.  The model never authors
either value: it authors the eight base factors, and this module compiles the
vector, computes the score, and validates the factor set (ADR 7).

The authored factors are the eight base metrics `AV`, `AC`, `AT`, `PR`, `UI`,
`VC`, `VI`, and `VA`.  The subsequent-system impact is derived, not elicited:
`SC = VC`, `SI = VI`, and `SA = VA`.  The vector is a derived serialization for
audit and for the FIRST requirement that a published CVSS score carries its
vector.

The factor semantics are the domain mapping, not the standard's wording: `PR` is
the role and permission the chain's application primitives need, `AC` is the
defence that must be circumnavigated, `AT` is a further attacker capability that
adds a phase, and `UI` is passive for a routine flow and active for a specific
victim action.  A score from this module is a CVSS 4.0 base score over
domain-mapped factors, never a certified CVSS assessment.

This module is pure and imports nothing from the hunting schema.  The local
`_Record` base mirrors `threat_model._Record` rather than importing it, because
the schema imports `RiskMetrics` from here in the other direction (schema v5):
one import direction, no cycle.  No other module imports `cvss`.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from cvss import CVSS4
from pydantic import BaseModel, ConfigDict, Field

# The disposition of an assessment row, duplicated from the schema's
# `ImpactDisposition` as a structural type so this module never imports the
# schema.  The schema's `StrEnum` members compare equal to these strings.
RiskDisposition = Literal["threat", "precursor"]

# The vector prefix of the CVSS 4.0 base metric group.
VECTOR_PREFIX = "CVSS:4.0"


class _Record(BaseModel):
    """The shared shape rule: unknown fields are forbidden at every level."""

    model_config = ConfigDict(extra="forbid")


class AttackVector(StrEnum):
    """`AV`: the position from which the attack is launched."""

    NETWORK = "network"
    ADJACENT = "adjacent"
    LOCAL = "local"
    PHYSICAL = "physical"


class AttackComplexity(StrEnum):
    """`AC`: the defence that must be circumnavigated, not the step count."""

    LOW = "low"
    HIGH = "high"


class AttackRequirements(StrEnum):
    """`AT`: an attacker capability that adds a phase to the chain."""

    NONE = "none"
    PRESENT = "present"


class PrivilegesRequired(StrEnum):
    """`PR`: the role and permissions the chain's primitives need."""

    NONE = "none"
    LOW = "low"
    HIGH = "high"


class UserInteraction(StrEnum):
    """`UI`: passive for a routine flow, active for a specific victim action."""

    NONE = "none"
    PASSIVE = "passive"
    ACTIVE = "active"


class ImpactLevel(StrEnum):
    """The CVSS 4.0 impact value of one impact property (no `medium`)."""

    NONE = "none"
    LOW = "low"
    HIGH = "high"


class SeverityBand(StrEnum):
    """The standard CVSS qualitative band of a score."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# The ONE source of the factor descriptions the `assess_impact` tool contract
# and the modeller prompt render, so the two cannot drift (spec 1).  Every entry
# is "<one-line semantic>. Example: <one brief example>", keyed by the
# `RiskMetrics` field and then by the enum value.  `RiskMetrics` renders it into
# the tool schema's factor descriptions.
FACTOR_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "attack_vector": {
        "network": (
            "The attack reaches the target from any network position. "
            "Example: a hostile HTTP request to the public front."
        ),
        "adjacent": (
            "The attack needs the same local network segment or broadcast "
            "domain as the target. "
            "Example: a spoofed request from another host on the office LAN."
        ),
        "local": (
            "The attack needs a local account or shell on the target host. "
            "Example: a shell on the application server running the target."
        ),
        "physical": (
            "The attack needs physical contact with the target hardware. "
            "Example: a device plugged into an exposed port."
        ),
    },
    "attack_complexity": {
        "low": (
            "No defence has to be beaten; the chain works on the first "
            "attempt. "
            "Example: an object reference read with no token or rate check."
        ),
        "high": (
            "A defence must be circumnavigated for the chain to work. "
            "Example: escaping a context-aware HTML sanitizer."
        ),
    },
    "attack_requirements": {
        "none": (
            "No further attacker capability is needed beyond the chain "
            "itself. "
            "Example: one request that returns another user's record."
        ),
        "present": (
            "One further attacker capability adds a phase to the chain. "
            "Example: a planted XSS payload for exfiltration."
        ),
    },
    "privileges_required": {
        "none": (
            "The chain needs no account and no permission. "
            "Example: an anonymous request to a public route."
        ),
        "low": (
            "The chain needs a basic authenticated role. "
            "Example: a self-registered user calling the API with its own "
            "session."
        ),
        "high": (
            "The chain needs an administrative role or a high-privilege "
            "permission. "
            "Example: an admin-only management route called with an admin "
            "session."
        ),
    },
    "user_interaction": {
        "none": (
            "The attack needs no victim action; a routine or automatic flow is "
            "enough. "
            "Example: a page that fires the request as soon as it loads."
        ),
        "passive": (
            "The attack rides a routine flow or common application state the "
            "victim already uses. "
            "Example: a stored XSS that runs when a reader opens the article "
            "they came to read."
        ),
        "active": (
            "The attack needs a specific non-routine action by the victim. "
            "Example: the victim drags a crafted string into a form field."
        ),
    },
    "confidentiality": {
        "none": (
            "No data is disclosed. "
            "Example: the injected request returns only its own status."
        ),
        "low": (
            "The disclosure is partial or bounded. "
            "Example: username enumeration that confirms one account exists."
        ),
        "high": (
            "The disclosure is direct and serious. "
            "Example: the full record set of every user is returned."
        ),
    },
    "integrity": {
        "none": (
            "No data can be modified. "
            "Example: a read-only route that ignores the mutated body."
        ),
        "low": (
            "The damage to data is partial or bounded. "
            "Example: one non-load-bearing profile field of the attacker's own "
            "account is changed."
        ),
        "high": (
            "The damage to data is direct and serious. "
            "Example: another user's session state is rewritten."
        ),
    },
    "availability": {
        "none": (
            "No service is lost. "
            "Example: the injected request completes and leaves the pool "
            "healthy."
        ),
        "low": (
            "The loss of service is partial or bounded. "
            "Example: one request is delayed by a per-account timeout."
        ),
        "high": (
            "The loss of service is direct and serious. "
            "Example: the whole worker pool is exhausted by one request."
        ),
    },
}


def _factor_description(name: str) -> str:
    """One factor's schema description: every value, its semantic and example.

    Rendered from `FACTOR_DESCRIPTIONS` with the same sentence-space joiner the
    modeller prompt uses, so the tool schema the model reads and the prompt it
    reads carry the same text.
    """
    return " ".join(
        f"`{value}`: {text}" for value, text in FACTOR_DESCRIPTIONS[name].items()
    )


class RiskMetrics(_Record):
    """The eight authored CVSS 4.0 base factors of one impact assessment."""

    attack_vector: AttackVector = Field(
        description=_factor_description("attack_vector"))
    attack_complexity: AttackComplexity = Field(
        description=_factor_description("attack_complexity"))
    attack_requirements: AttackRequirements = Field(
        description=_factor_description("attack_requirements"))
    privileges_required: PrivilegesRequired = Field(
        description=_factor_description("privileges_required"))
    user_interaction: UserInteraction = Field(
        description=_factor_description("user_interaction"))
    confidentiality: ImpactLevel = Field(
        description=_factor_description("confidentiality"))
    integrity: ImpactLevel = Field(
        description=_factor_description("integrity"))
    availability: ImpactLevel = Field(
        description=_factor_description("availability"))


class RiskResult(_Record):
    """The derived risk of one factor set: the vector, the score, and the band."""

    vector: str
    score: float
    band: SeverityBand


# The serialization token of each authored value, in the standard's letter set.
_ATTACK_VECTOR_TOKENS: dict[AttackVector, str] = {
    AttackVector.NETWORK: "N",
    AttackVector.ADJACENT: "A",
    AttackVector.LOCAL: "L",
    AttackVector.PHYSICAL: "P",
}
_ATTACK_COMPLEXITY_TOKENS: dict[AttackComplexity, str] = {
    AttackComplexity.LOW: "L",
    AttackComplexity.HIGH: "H",
}
_ATTACK_REQUIREMENTS_TOKENS: dict[AttackRequirements, str] = {
    AttackRequirements.NONE: "N",
    AttackRequirements.PRESENT: "P",
}
_PRIVILEGES_REQUIRED_TOKENS: dict[PrivilegesRequired, str] = {
    PrivilegesRequired.NONE: "N",
    PrivilegesRequired.LOW: "L",
    PrivilegesRequired.HIGH: "H",
}
_USER_INTERACTION_TOKENS: dict[UserInteraction, str] = {
    UserInteraction.NONE: "N",
    UserInteraction.PASSIVE: "P",
    UserInteraction.ACTIVE: "A",
}
_IMPACT_TOKENS: dict[ImpactLevel, str] = {
    ImpactLevel.NONE: "N",
    ImpactLevel.LOW: "L",
    ImpactLevel.HIGH: "H",
}

# The inclusive upper bound of each band below `critical`, over the standard
# CVSS table: 0.1..3.9 low, 4.0..6.9 medium, 7.0..8.9 high, 9.0..10.0 critical.
# Zero is the only score in the `none` band.
_BAND_UPPER_BOUNDS: tuple[tuple[float, SeverityBand], ...] = (
    (3.9, SeverityBand.LOW),
    (6.9, SeverityBand.MEDIUM),
    (8.9, SeverityBand.HIGH),
)


def build_vector(metrics: RiskMetrics) -> str:
    """The CVSS 4.0 base vector: the eight authored factors plus the mirrors.

    `SC = VC`, `SI = VI`, and `SA = VA`, because the domain elicits one impact
    reading per property and the subsequent system carries the same damage.
    """
    metrics_part = "/".join((
        f"AV:{_ATTACK_VECTOR_TOKENS[metrics.attack_vector]}",
        f"AC:{_ATTACK_COMPLEXITY_TOKENS[metrics.attack_complexity]}",
        f"AT:{_ATTACK_REQUIREMENTS_TOKENS[metrics.attack_requirements]}",
        f"PR:{_PRIVILEGES_REQUIRED_TOKENS[metrics.privileges_required]}",
        f"UI:{_USER_INTERACTION_TOKENS[metrics.user_interaction]}",
        f"VC:{_IMPACT_TOKENS[metrics.confidentiality]}",
        f"VI:{_IMPACT_TOKENS[metrics.integrity]}",
        f"VA:{_IMPACT_TOKENS[metrics.availability]}",
        f"SC:{_IMPACT_TOKENS[metrics.confidentiality]}",
        f"SI:{_IMPACT_TOKENS[metrics.integrity]}",
        f"SA:{_IMPACT_TOKENS[metrics.availability]}",
    ))
    return f"{VECTOR_PREFIX}/{metrics_part}"


def severity_band(score: float) -> SeverityBand:
    """The standard CVSS band of a score in `0.0 .. 10.0`."""
    if score <= 0:
        return SeverityBand.NONE
    for upper_bound, band in _BAND_UPPER_BOUNDS:
        if score <= upper_bound:
            return band
    return SeverityBand.CRITICAL


def compute_risk(metrics: RiskMetrics) -> RiskResult:
    """The derived risk of one factor set: the base score rounded to 2 decimals.

    The score comes from the `cvss` library's CVSS 4.0 macrovector lookup, so it
    is the reference implementation's value and never a first-party formula.
    """
    vector = build_vector(metrics)
    score = round(CVSS4(vector).base_score, 2)
    return RiskResult(vector=vector, score=score, band=severity_band(score))


def validate_metrics(
    metrics: RiskMetrics,
    *,
    disposition: RiskDisposition,
) -> list[str]:
    """The coded findings of one factor set against its row disposition.

    A `precursor` row reaches a capability and no end damage, so all three
    impact values must be `none`.  A `threat` row carries an end damage, so at
    least one impact value must be above `none`.  The typed model already
    enforces the presence of every factor, so this checks values only.  The
    findings are dotted paths in the completion checker's style; an empty list
    is a valid row.
    """
    impact = {
        "confidentiality": metrics.confidentiality,
        "integrity": metrics.integrity,
        "availability": metrics.availability,
    }
    findings: list[str] = []
    if disposition == "precursor":
        for name, level in impact.items():
            if level is not ImpactLevel.NONE:
                findings.append(
                    f"factors.{name}={level.value} on a precursor row "
                    "(a precursor row must have all three impact values none)")
        return findings
    if all(level is ImpactLevel.NONE for level in impact.values()):
        findings.append(
            "factors.confidentiality/integrity/availability=all none on a "
            "threat row (a threat row must carry at least one impact value "
            "above none)")
    return findings
