"""The deterministic L1 skeleton scaffold (the eval's primary bootstrapping path).

The LLM bootstrap (`POST /projects/{id}/bootstrap`) is non-deterministic: two LLM
calls per trial, run-to-run skeleton drift (AMV-12/13), cost and latency. This
module replaces it for the eval: it parses the PRECOMPUTED per-target
`operator_kb.md` (services, systems, roles) into the platform's OWN
`ServiceShell`/`SystemShell` shapes and writes the skeleton through the SAME
projection and sole-writer the LLM bootstrap uses (`shells_to_batch` +
`l1_curate`) - deterministically, without an LLM call.

The system kinds in the KB are free-form mechanism names; they are mapped onto
the controlled `SYSTEM_KINDS` vocabulary by `KIND_MAP` (keyword match after an
exact vocabulary hit). Unmappable mechanisms are DROPPED with a warning,
mirroring the platform's own out-of-vocabulary gate - a mechanism the L1
vocabulary does not speak is context, never a skeleton node.

This module was extracted from `eval/scaffold.py` so the app API can place an
L1 surface (the four eval data-dependency endpoints) through the SAME
deterministic path the eval CLI runs. The parsing and shell-building are pure
(text in, shells out); only `scaffold_project` performs I/O, and it resolves the
sole-writer lazily so importing this module constructs no driver
(CODING_STANDARD section 6).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from polymerhus.analysis.overview import (
    empty_overview,
    normalize_overview,
    overview_is_empty,
)

# ---------------------------------------------------------------------------
# The free-form KB mechanism kind -> SYSTEM_KINDS vocabulary map.
# Keyword matching on the lowercased kind token, applied after an exact
# vocabulary hit. Order matters: more specific keywords first.
# ---------------------------------------------------------------------------

KIND_MAP: tuple[tuple[str, str], ...] = (
    ("reactive rest", "RESTApi"),
    ("rest framework", "RESTApi"),
    ("graphql", "GraphQLApi"),
    ("web storefront", "WebPresentation"),
    ("presentation", "WebPresentation"),
    ("rendering", "WebPresentation"),
    ("template", "WebPresentation"),
    ("authentication", "AuthenticationMechanism"),
    ("shiro", "AuthenticationMechanism"),
    ("session", "IdentificationSystem"),
    ("identification", "IdentificationSystem"),
    ("cookie", "IdentificationSystem"),
    ("authorization", "AuthorizationSystem"),
    ("permission", "AuthorizationSystem"),
    ("integration", "IntegrationSystem"),
    ("cross-origin", "IntegrationSystem"),
    ("waf", "WAF"),
    ("cdn", "CDN"),
    ("reverse proxy", "ReverseProxy"),
    ("api gateway", "APIGateway"),
    ("sitemap", "Sitemap"),
)


class ScaffoldError(ValueError):
    """The denoted blocked-scaffold signal: the KB parsed zero Services, so the
    L1 surface is empty and the caller must not proceed (mirrors the
    bootstrap fail-closed rule)."""


def system_kinds() -> tuple[str, ...]:
    """The controlled System-kind vocabulary, single-sourced from the L1
    sole-writer so this seam's validation can never drift from it."""
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS

    return tuple(kind for kind, _desc in SYSTEM_KINDS)


def map_system_kind(kind: str) -> str | None:
    """Map a KB mechanism kind token onto the vocabulary, or None (drop)."""
    token = kind.strip().lower()
    for vocab in system_kinds():
        if token == vocab.lower():
            return vocab
    for keyword, vocab in KIND_MAP:
        if keyword in token:
            return vocab
    return None


# ---------------------------------------------------------------------------
# KB parsing (pure, deterministic)
# ---------------------------------------------------------------------------
SECTION_RE = re.compile(r"^##\s+(.*)$")
HEADING_RE = re.compile(r"^###\s+(.*)$")
BULLET_RE = re.compile(r"^-\s+(.*)$")

# The structured Overview fence: opened by ```yaml and closed by ```.
OVERVIEW_FENCE_RE = re.compile(r"^\s*```yaml\s*$", re.IGNORECASE)
FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")

KB_SECTIONS = ("Services", "Systems", "Roles")

logger = logging.getLogger(__name__)


def _overview_section_lines(text: str) -> list[str]:
    """The raw lines of the `## Overview` section, up to the next `##` header."""
    lines: list[str] = []
    in_overview = False
    for raw in text.splitlines():
        m = SECTION_RE.match(raw)
        if m:
            in_overview = m.group(1).strip().lower() == "overview"
            continue
        if in_overview:
            lines.append(raw.rstrip())
    return lines


def _extract_yaml_block(lines: list[str]) -> str | None:
    """The first ```yaml block's body in the section, or None (no fence).

    An unclosed fence takes the remainder of the section (the YAML parse then
    decides: valid content still lands, invalid content fails open)."""
    start = None
    for i, line in enumerate(lines):
        if OVERVIEW_FENCE_RE.match(line):
            start = i + 1
            break
    if start is None:
        return None
    for j in range(start, len(lines)):
        if FENCE_CLOSE_RE.match(lines[j]):
            return "\n".join(lines[start:j])
    return "\n".join(lines[start:])


def parse_overview(text: str) -> dict:
    """Parse the operator_kb `## Overview` section into the structured entity.

    The structured form is a fenced ```yaml mapping with `domain`,
    `description`, and `journeys` (the normalized shape lives in
    `polymerhus.analysis.overview`). Legacy prose (no fence) stays accepted and
    maps to `description`. Malformed YAML, a non-mapping document, or an absent
    section fails open to the empty shape: the platform never breaks the
    skeleton over framing (the validator is the strict build gate)."""
    section = _overview_section_lines(text)
    block = _extract_yaml_block(section)
    if block is not None:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            logger.warning(
                "parse_overview: malformed YAML in the Overview block; fail-open to empty"
            )
            return empty_overview()
        if not isinstance(data, dict):
            logger.warning(
                "parse_overview: the Overview block is not a mapping; fail-open to empty"
            )
            return empty_overview()
        return normalize_overview(data)
    prose = " ".join(line.strip() for line in section if line.strip())
    return normalize_overview(prose)


def parse_kb(text: str) -> tuple[list[dict], list[dict], list[str]]:
    """Parse the structured operator_kb.md. Returns (services, systems, roles).

    Services: {slug, contract, exposure}
    Systems:  {kind, name, description}
    Roles:    [role, ...]
    Continuation lines (indented prose) join the preceding bullet. Anything
    outside the three sections is ignored (Overview, Service-system mapping).
    """
    services: list[dict] = []
    systems: list[dict] = []
    roles: list[str] = []
    section = ""
    current: dict | None = None
    field = ""

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m = SECTION_RE.match(line)
        if m:
            section = m.group(1).strip()
            current = None
            field = ""
            continue
        if section not in KB_SECTIONS:
            continue
        m = HEADING_RE.match(line)
        if m:
            current = None
            field = ""
            if section == "Services":
                slug = m.group(1).strip()
                current = {"slug": slug, "contract": "", "exposure": None}
                services.append(current)
            elif section == "Systems":
                head = m.group(1).strip()
                kind, _, name = head.partition(" - ")
                current = {"kind": kind.strip(), "name": (name or kind).strip(),
                           "description": ""}
                systems.append(current)
            continue
        m = BULLET_RE.match(line)
        if m:
            bullet = m.group(1).strip()
            key, _, value = bullet.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if current is not None and section == "Services":
                if key == "contract":
                    field = "contract"
                    current["contract"] = value
                elif key == "exposure":
                    field = ""
                    current["exposure"] = value or None
                else:
                    field = ""
            elif current is not None and section == "Systems":
                if key == "description":
                    field = "description"
                    current["description"] = value
                else:
                    field = ""
            elif section == "Roles":
                roles.append(key)
            continue
        if current is not None and field:
            current[field] = f"{current[field]} {line.strip()}"

    return services, systems, roles


# ---------------------------------------------------------------------------
# The scaffold
# ---------------------------------------------------------------------------
def _normalize_exposure(value: str | None) -> str | None:
    """Normalize a KB exposure onto the platform's {public, authenticated}
    allowlist. A compound value (e.g. 'public (login), authenticated (current
    user)') resolves to 'public' - the looser, permissive value, so a partially
    public service is never over-restricted; the assigner sees the real surface
    and judges it."""
    if not value:
        return None
    lowered = value.lower()
    if "public" in lowered:
        return "public"
    if "authenticated" in lowered:
        return "authenticated"
    return None


def build_shells(text: str):
    """Parse the KB text and return (service_shells, system_shells, dispositions)."""
    from polymerhus.analysis.bootstrap import ServiceShell, SystemShell

    services, systems, roles = parse_kb(text)
    dispositions = []

    service_shells = []
    for s in services:
        exposure = _normalize_exposure(s["exposure"])
        if exposure is not None and exposure not in ("public", "authenticated"):
            dispositions.append(("service", s["slug"], "exposure-dropped",
                                 f"exposure {exposure!r} not in {{public, authenticated}}"))
            continue
        if not s["contract"].strip():
            dispositions.append(("service", s["slug"], "contract-dropped",
                                 "empty contract"))
            continue
        service_shells.append(ServiceShell(
            business_function_slug=s["slug"],
            exposure=exposure,
            service_contract=s["contract"].strip(),
        ))

    system_shells = []
    for s in systems:
        vocab_kind = map_system_kind(s["kind"])
        if vocab_kind is None:
            dispositions.append(("system", f"{s['kind']} - {s['name']}",
                                 "kind-dropped",
                                 f"{s['kind']!r} has no SYSTEM_KINDS home"))
            continue
        system_shells.append(SystemShell(
            kind=vocab_kind,
            discriminator=s["name"],
            claim=s["description"].strip() or None,
        ))

    # The KB's Roles section lands on the AuthorizationSystem shell(s).
    if roles:
        for shell in system_shells:
            if shell.kind == "AuthorizationSystem":
                shell.roles = roles

    return service_shells, system_shells, dispositions


def build_shells_from_path(kb_path: str | Path):
    """The path-reading wrapper the eval CLI keeps (reads, then `build_shells`)."""
    return build_shells(Path(kb_path).read_text(encoding="utf-8"))


def scaffold_project(project_id: str, operator_kb: str, *, curate_fn=None,
                     save_settings_fn=None) -> tuple[int, int]:
    """Deterministically project `operator_kb` into the L1 skeleton for
    `project_id` through the SAME projection the LLM bootstrap uses.

    Returns `(services_written, systems_written)`. Raises `ScaffoldError` when
    the KB parses zero Services: a broken KB is a blocked scaffold, never an
    empty success (mirrors the bootstrap fail-closed rule). `curate_fn` is the
    injectable sole-writer seam (tests pass a recorder); it defaults to
    `l1_curator.l1_curate`, resolved lazily so importing this module constructs
    no driver.

    The KB's `## Overview` is carried as the structured skeleton attribute
    `settings.application_overview` (W-d, structured 2026-10-17): the normalized
    `{domain, description, journeys}` value is persisted with ALL THREE keys on
    every write, so the settings store's JSONB deep merge can never let an older
    value survive under a missing key. It is the framing the four item-consuming
    agents receive as a dedicated message downstream. `save_settings_fn` is the
    injectable settings seam (default `app.clients.pg.save_settings`); a write
    failure is fail-open - the skeleton still persists, only the framing is
    dropped."""
    import logging

    from polymerhus.analysis.analyser_types import proposals_to_deltas
    from polymerhus.analysis.bootstrap import shells_to_batch
    from polymerhus.analysis.l1_types import Provenance

    service_shells, system_shells, _dispositions = build_shells(operator_kb)
    if not service_shells:
        raise ScaffoldError(
            "zero services parsed - a broken KB is a blocked scaffold"
        )

    overview = parse_overview(operator_kb)
    if not overview_is_empty(overview):
        if save_settings_fn is None:
            from polymerhus.app.clients import pg

            save_settings_fn = pg.save_settings
        try:
            save_settings_fn(project_id, {"application_overview": overview})
        except Exception:  # noqa: BLE001 - framing is fail-open, the skeleton is not
            logging.getLogger(__name__).warning(
                "scaffold: could not persist application_overview for %s",
                project_id, exc_info=True,
            )

    batch = shells_to_batch(service_shells, system_shells)
    provenance = Provenance(job="data-dependency-scaffold", model=None, prompt_id=None)
    services, systems, _aggregates_dropped = proposals_to_deltas(batch, provenance)

    if curate_fn is None:
        from polymerhus.analysis import l1_curator

        curate_fn = l1_curator.l1_curate
    return curate_fn(services, systems, project_id)


__all__ = [
    "KIND_MAP",
    "KB_SECTIONS",
    "ScaffoldError",
    "build_shells",
    "build_shells_from_path",
    "map_system_kind",
    "parse_kb",
    "parse_overview",
    "scaffold_project",
    "system_kinds",
]
