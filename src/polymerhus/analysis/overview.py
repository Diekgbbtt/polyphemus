"""The structured Application Overview skeleton attribute.

The Overview is the macro framing of the deployed application: its stable
canonical domain, a generalised description of the offered features, and the
canonical end-user navigation journeys. The deterministic scaffold parses it
from the operator_kb `## Overview` block (a fenced YAML mapping), persists it to
`settings.application_overview`, and the four item-consuming agents (assigner,
mechanism typist, hunt orchestrator, hunter) each receive it as a dedicated
HumanMessage (the Q4 model; see `docs/design/overview-entity-impact-map.md`).

The normalized value shape is exactly::

    {"domain": str, "description": str,
     "journeys": [{"name": str, "steps": [str, ...]}, ...]}

Normalization is fail-open and lenient by design: a legacy prose string maps to
`description`, malformed journey entries are dropped, and no input ever raises.
The strict gate is the data-dependency validator, never the runtime read path.
"""
from __future__ import annotations


def empty_overview() -> dict:
    """A fresh empty Overview value (never a shared mutable)."""
    return {"domain": "", "description": "", "journeys": []}


def is_overview(value) -> bool:
    """True when `value` is a normalized Overview mapping shape."""
    return isinstance(value, dict) and set(value) == {"domain", "description", "journeys"}


def normalize_overview(value) -> dict:
    """Coerce any stored/parsed Overview value into the normalized shape.

    - a mapping: strings for `domain`/`description` (non-strings degrade to ""),
      a list of `{name, steps}` journeys (non-mapping entries are dropped,
      non-string steps are dropped, an entry with neither name nor steps is
      dropped);
    - a string (legacy prose): `description` only;
    - anything else (None, list, number): the empty shape.
    """
    if isinstance(value, str):
        out = empty_overview()
        out["description"] = value.strip()
        return out
    if not isinstance(value, dict):
        return empty_overview()
    out = empty_overview()
    out["domain"] = _text(value.get("domain"))
    out["description"] = _text(value.get("description"))
    journeys = value.get("journeys")
    if isinstance(journeys, list):
        for entry in journeys:
            if not isinstance(entry, dict):
                continue
            name = _text(entry.get("name"))
            raw_steps = entry.get("steps")
            steps = (
                [s.strip() for s in raw_steps if isinstance(s, str) and s.strip()]
                if isinstance(raw_steps, list)
                else []
            )
            if name or steps:
                out["journeys"].append({"name": name, "steps": steps})
    return out


def overview_is_empty(overview: dict) -> bool:
    """True when the normalized Overview carries no content at all."""
    return not (
        overview.get("domain") or overview.get("description") or overview.get("journeys")
    )


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


# The operator budget (Q3, grilled 2026-10-16): the whole Overview - domain,
# description, journey names, journey steps - stays under 250 words of rendered
# plain text. The creator self-checks with this, the critic judges with it, and
# the deterministic validator hard-counts with it: ONE rule, three sites.
OVERVIEW_WORD_BUDGET = 250


def overview_word_count(value) -> int:
    """The Overview's word count over its RENDERED PLAIN TEXT: the domain, the
    description, and each journey's name and steps, whitespace-tokenised. The
    count never touches YAML/markdown artifacts, so it measures what the agents
    actually read."""
    overview = normalize_overview(value)
    parts = [overview["domain"], overview["description"]]
    for journey in overview["journeys"]:
        parts.append(journey["name"])
        parts.extend(journey["steps"])
    return len(" ".join(parts).split())


_STRUCTURED_INTRO = (
    "APPLICATION OVERVIEW (the deployed application the following items belong to):"
)


def overview_message(value) -> str:
    """The dedicated Overview HumanMessage content (the Q4 model).

    A structured value renders as clean deterministic prose: the intro line,
    the domain, the offered features, and the numbered canonical journeys with
    indented steps - no YAML or markdown artifacts, no blank-line runs. A
    description-only value (legacy prose) keeps the historical one-line render.
    An empty Overview renders "" so the caller keeps its single-message shape
    and sends no chaining verbatim."""
    overview = normalize_overview(value)
    if overview_is_empty(overview):
        return ""
    if not overview["domain"] and not overview["journeys"]:
        return f"APPLICATION OVERVIEW: {overview['description']}"
    lines = [_STRUCTURED_INTRO]
    if overview["domain"]:
        lines.append(f"Domain: {overview['domain']}")
    if overview["description"]:
        lines.append(f"Offered features: {overview['description']}")
    if overview["journeys"]:
        lines.append("Canonical journeys:")
        for i, journey in enumerate(overview["journeys"], start=1):
            lines.append(f"{i}. {journey['name']}".rstrip())
            for step in journey["steps"]:
                lines.append(f"   - {step}")
    return "\n".join(lines)
