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

import re
from pathlib import Path

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

KB_SECTIONS = ("Services", "Systems", "Roles")


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


def scaffold_project(project_id: str, operator_kb: str, *, curate_fn=None) -> tuple[int, int]:
    """Deterministically project `operator_kb` into the L1 skeleton for
    `project_id` through the SAME projection the LLM bootstrap uses.

    Returns `(services_written, systems_written)`. Raises `ScaffoldError` when
    the KB parses zero Services: a broken KB is a blocked scaffold, never an
    empty success (mirrors the bootstrap fail-closed rule). `curate_fn` is the
    injectable sole-writer seam (tests pass a recorder); it defaults to
    `l1_curator.l1_curate`, resolved lazily so importing this module constructs
    no driver.
    """
    from polymerhus.analysis.analyser_types import proposals_to_deltas
    from polymerhus.analysis.bootstrap import shells_to_batch
    from polymerhus.analysis.l1_types import Provenance

    service_shells, system_shells, _dispositions = build_shells(operator_kb)
    if not service_shells:
        raise ScaffoldError(
            "zero services parsed - a broken KB is a blocked scaffold"
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
    "scaffold_project",
    "system_kinds",
]
