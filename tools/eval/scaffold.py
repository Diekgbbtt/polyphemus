#!/usr/bin/env python3
"""scaffold.py - the deterministic L1 skeleton scaffold (the eval's primary
bootstrapping path).

The LLM bootstrap (`POST /bootstrap`) is non-deterministic: two LLM calls per
trial, run-to-run skeleton drift (AMV-12/13), cost and latency. This utility
replaces it for the eval: it parses the PRECOMPUTED per-target operator_kb.md
(services, systems, roles) into the platform's OWN `ServiceShell`/`SystemShell`
shapes and writes the skeleton through the SAME projection and sole-writer the
LLM bootstrap uses (`shells_to_batch` + `l1_curate`) - deterministically,
without an LLM call.

The system kinds in the KB are free-form mechanism names; they are mapped onto
the controlled `SYSTEM_KINDS` vocabulary by `KIND_MAP` (keyword match after an
exact vocabulary hit). Unmappable mechanisms are DROPPED with a warning,
mirroring the platform's own out-of-vocabulary gate - a mechanism the L1
vocabulary does not speak is context, never a skeleton node.

Usage:
  scaffold.py <project_id> --kb <operator_kb.md> [--dry-run]

Run host-side from the repo root with PYTHONPATH=src and the .env in-network
view (NEO4J_URI=bolt://localhost:7687), mirroring tools/eval_bootstrapper.sh.
`--dry-run` parses the KB and prints the shells and dispositions WITHOUT
writing anything (stack-free verification).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# The free-form KB mechanism kind -> SYSTEM_KINDS vocabulary map.
# Keyword matching on the lowercased kind token, applied after an exact
# vocabulary hit. Order matters: more specific keywords first.
# ---------------------------------------------------------------------------
SYSTEM_KINDS = (
    "WAF", "CDN", "ReverseProxy", "APIGateway", "RESTApi", "GraphQLApi",
    "IdentificationSystem", "IntegrationSystem", "AuthenticationMechanism",
    "AuthorizationSystem", "WebPresentation", "Sitemap",
)

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


def map_system_kind(kind: str) -> str | None:
    """Map a KB mechanism kind token onto the vocabulary, or None (drop)."""
    token = kind.strip().lower()
    for vocab in SYSTEM_KINDS:
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


def build_shells(kb_path: Path):
    """Parse the KB and return (service_shells, system_shells, dispositions)."""
    from polymerhus.analysis.bootstrap import ServiceShell, SystemShell

    services, systems, roles = parse_kb(kb_path.read_text())
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_id")
    ap.add_argument("--kb", required=True, help="the operator_kb.md path")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and print the shells without writing")
    args = ap.parse_args()

    kb_path = Path(args.kb)
    if not kb_path.exists():
        sys.exit(f"scaffold.py: no KB at {kb_path}")

    service_shells, system_shells, dispositions = build_shells(kb_path)

    for kind, name, outcome, note in dispositions:
        print(f"scaffold.py: {kind} {name}: {outcome} - {note}")

    print(f"scaffold.py: parsed {len(service_shells)} services, "
          f"{len(system_shells)} systems, from {kb_path}")

    if not service_shells:
        sys.exit("scaffold.py: zero services parsed - a broken KB is a blocked "
                 "scaffold, the trial must not proceed (mirrors the bootstrap "
                 "fail-closed rule)")

    if args.dry_run:
        for s in service_shells:
            print(f"  service {s.business_function_slug} exposure={s.exposure}")
        for s in system_shells:
            extra = f" roles={s.roles}" if s.roles else ""
            print(f"  system  {s.kind} <{s.discriminator}>{extra}")
        return 0

    from polymerhus.analysis.bootstrap import shells_to_batch
    from polymerhus.analysis.analyser_types import proposals_to_deltas
    from polymerhus.analysis.l1_types import Provenance
    from polymerhus.analysis import l1_curator

    batch = shells_to_batch(service_shells, system_shells)
    provenance = Provenance(job="scaffold", model=None, prompt_id=None)
    services, systems, _aggregates_dropped = proposals_to_deltas(batch, provenance)
    merged_services, merged_systems = l1_curator.l1_curate(
        services, systems, args.project_id)
    print(f"scaffold.py: wrote {merged_services} services, {merged_systems} "
          f"systems to project {args.project_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())