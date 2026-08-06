#!/usr/bin/env python3
"""Out-of-band curation of the phase-1 fault-KB catalogue (#66, spec section 5).

Standalone OFFLINE transform, run by a curator (never at runtime):

    local cwec_v4.20.xml + the reviewed OWASP Top 10 2025 seed mapping
        -> the deterministic YAML fault catalogue

CWE is NEVER a runtime dependency: the runtime reads the emitted catalogue
artifact only (`polymerhus.attack.hunting.fault_kb`). This script exists purely
to produce the artifact out-of-band (FKB-4).

The mechanical algorithm (spec section 5, steps 1-5 and 7):

    1. Seed.  For each of the 10 OWASP Top 10 2025 risks (A01..A10), take the
       mapped CWE ids from the reviewed seed file.
    2. Walk.  For each seed CWE, walk its descendants in the XML ChildOf tree
       (View 1000, the research view) to the concrete web-relevant leaves -
       not only the ids OWASP directly references (mitigates R-a).
    3. Filter.  Drop deprecated ids; drop ids explicitly irrelevant to web
       applications (hardware / embedded / mobile / ICS-OT technology entries
       with no web signal).  Missing platform data keeps (fail-open recall).
    4. Abstract -> concrete.  Replace a retained Pillar / Class with its
       smallest-id Base / Variant descendant already in the collected set,
       then deduplicate (a descendant is one entry regardless of how many
       seeds reached it).
    5. Extract content.  Per surviving CWE: description, extended description,
       alternate terms, related attack patterns (CAPEC), likelihood, common
       consequences, abstraction + OWASP provenance.
    7. Emit.  The deterministic, sorted YAML catalogue.

Step 6 (author the matching facet - the NL `applies_if`, the optional
typed-SHAPED predicate, the enum-of-system-kinds tag) is the CURATOR'S
knowledge pass over the emitted artifact, not script logic: the script emits
`applies_if.nl: ""`, `predicate: null`, `enum_kinds: []` for every entry and
the authoring edits land in the committed artifact, reviewed in the PR.

The script is pure and deterministic: same inputs -> byte-identical output.
Depends on PyYAML (present in the dev venv and in the runtime base image via
langchain-core); the runtime loader documents the same dependency.

Usage:
    python tools/hunting/curate_fault_kb.py \
        --xml /path/to/cwec_v4.20.xml \
        --seed tools/hunting/owasp-top10-2025-seed.yaml \
        --out src/polymerhus/attack/hunting/data/fault-kb.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

_NS = "{http://cwe.mitre.org/cwe-7}"

# The web-relevance vocabulary (spec section 5.3). Single place; edit here only.
_WEB_TECH_CLASSES = frozenset({"Web Based"})
_WEB_TECH_NAMES = frozenset({"Web Server"})
_NON_WEB_TECH_CLASSES = frozenset({"ICS/OT", "System on Chip", "Mobile"})
_HARDWARE_TECH_NAMES = frozenset({
    "Processor Hardware", "Memory Hardware", "Microcontroller Hardware",
    "Security Hardware", "Power Management Hardware", "Bus/Interface Hardware",
    "Sensor Hardware", "Test/Debug Hardware", "Clock/Counter Hardware",
    "Storage Hardware", "Network on Chip Hardware",
})

# Abstraction ladder (the ticket's pillar -> class -> base -> variant -> compound).
_ABSTRACT_ORDER = ("Pillar", "Class", "Base", "Variant", "Compound")


def _collapse(node: ET.Element) -> str:
    """The element's text with whitespace collapsed (single-line, diff-friendly)."""
    return re.sub(r"\s+", " ", " ".join(node.itertext())).strip()


@dataclass(frozen=True)
class Weakness:
    """One CWE entry as the curation script sees it."""

    cwe_id: int
    name: str
    abstraction: str
    status: str
    description: str
    extended_description: str
    alternate_terms: tuple[str, ...]
    attack_patterns: tuple[str, ...]  # "CAPEC-<id>" strings, sorted
    likelihood: str | None
    common_consequences: tuple[str, ...]
    potential_mitigations: tuple[str, ...]
    functional_areas: tuple[str, ...]
    parents_view1000: frozenset[int]  # ChildOf parents in View 1000
    tech_classes: frozenset[str]      # Applicable_Platforms Technology classes
    tech_names: frozenset[str]        # Applicable_Platforms Technology names
    has_lang_not_specific: bool

    @property
    def is_deprecated(self) -> bool:
        return self.status == "Deprecated"

    def is_web_relevant(self) -> bool:
        """Explicitly web keeps; explicitly non-web (hardware / embedded /
        mobile / ICS-OT technologies) drops; anything ambiguous (neutral
        platforms, missing platforms) keeps - fail-open recall. The
        Not-Language-Specific language class is NOT a web signal: hardware
        CWEs carry it too (the curator-sidecar `omit` markers handle the
        residual neutral-platform hardware entries, spec 5.6)."""
        if not self.tech_classes and not self.tech_names:
            return True  # no platform data: keep (undetermined, not non-web)
        if self.tech_classes & _WEB_TECH_CLASSES or self.tech_names & _WEB_TECH_NAMES:
            return True  # explicit web signal
        # Every technology entry is explicitly non-web -> not web relevant.
        non_web_only = (self.tech_classes <= _NON_WEB_TECH_CLASSES) \
            and (self.tech_names <= _HARDWARE_TECH_NAMES)
        return not non_web_only


def load_seed(path: Path) -> dict[str, tuple[int, ...]]:
    """The reviewed OWASP Top 10 2025 seed mapping: risk -> sorted CWE ids."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    mapped = data.get("mapped_cwes")
    if not isinstance(mapped, Mapping):
        raise ValueError(f"seed file {path}: missing 'mapped_cwes' mapping")
    risks: dict[str, tuple[int, ...]] = {}
    for risk, ids in sorted(mapped.items()):
        risks[risk] = tuple(sorted(int(i) for i in ids))
    return risks


def parse_catalogue(xml_path: Path) -> dict[int, Weakness]:
    """Parse the CWE catalogue XML into the Weakness index (id -> Weakness)."""
    root = ET.parse(str(xml_path)).getroot()
    index: dict[int, Weakness] = {}
    for w in root.iter(f"{_NS}Weakness"):
        raw_id = w.get("ID") or ""
        if not raw_id.isdigit():
            continue  # catalogues always carry a numeric ID; stay total
        cwe_id = int(raw_id)
        abstraction = w.get("Abstraction") or ""
        status = w.get("Status") or ""

        description = ""
        ext = next(iter(w.iter(f"{_NS}Description")), None)
        if ext is not None:
            description = _collapse(ext)

        extended = ""
        ext_node = next(iter(w.iter(f"{_NS}Extended_Description")), None)
        if ext_node is not None:
            paragraphs = [
                _collapse(child) for child in ext_node
                if _collapse(child)
            ]
            extended = "\n\n".join(paragraphs)

        alternate_terms = tuple(sorted({
            _collapse(t) for t in w.iter(f"{_NS}Alternate_Term")
            if _collapse(t)
        }))

        attack_patterns = tuple(sorted({
            f"CAPEC-{p.get('CAPEC_ID')}"
            for p in w.iter(f"{_NS}Related_Attack_Pattern")
            if p.get("CAPEC_ID")
        }))

        likelihood = None
        like = next(iter(w.iter(f"{_NS}Likelihood_Of_Exploit")), None)
        if like is not None and like.text and like.text.strip():
            likelihood = like.text.strip()

        consequences: list[str] = []
        for cc in w.iter(f"{_NS}Common_Consequences"):
            scopes = [s.text.strip() for s in cc.iter(f"{_NS}Scope")
                      if s.text and s.text.strip()]
            impacts = [i.text.strip() for i in cc.iter(f"{_NS}Impact")
                       if i.text and i.text.strip()]
            parts = []
            if scopes:
                parts.append(f"scope: {', '.join(scopes)}")
            if impacts:
                parts.append(f"impact: {'; '.join(impacts)}")
            if parts:
                consequences.append(" - ".join(parts))

        mitigations: list[str] = []
        for mit in w.iter(f"{_NS}Potential_Mitigations"):
            phases = [p.text.strip() for p in mit.iter(f"{_NS}Phase")
                      if p.text and p.text.strip()]
            strategies = [s.text.strip() for s in mit.iter(f"{_NS}Strategy")
                          if s.text and s.text.strip()]
            parts = []
            if phases:
                parts.append(f"phase: {', '.join(phases)}")
            if strategies:
                parts.append(f"strategy: {'; '.join(strategies)}")
            if parts:
                mitigations.append(" - ".join(parts))

        functional_areas: set[str] = set()
        for fa in w.iter(f"{_NS}Functional_Areas"):
            for area in fa.iter(f"{_NS}Functional_Area"):
                if area.text and area.text.strip():
                    functional_areas.add(area.text.strip())
        functional_areas = tuple(sorted(functional_areas))

        parents: set[int] = set()
        for rw in w.iter(f"{_NS}Related_Weakness"):
            parent_id = rw.get("CWE_ID") or ""
            if (rw.get("Nature") == "ChildOf" and rw.get("View_ID") == "1000"
                    and parent_id.isdigit()):
                parents.add(int(parent_id))

        tech_classes: set[str] = set()
        tech_names: set[str] = set()
        has_lang_not_specific = False
        for ap in w.iter(f"{_NS}Applicable_Platforms"):
            for t in ap.iter(f"{_NS}Technology"):
                tech_class = t.get("Class")
                if tech_class:
                    tech_classes.add(tech_class)
                tech_name = t.get("Name")
                if tech_name:
                    tech_names.add(tech_name)
            for lang in ap.iter(f"{_NS}Language"):
                if lang.get("Class") == "Not Language-Specific":
                    has_lang_not_specific = True

        index[cwe_id] = Weakness(
            cwe_id=cwe_id,
            name=w.get("Name") or "",
            abstraction=abstraction,
            status=status,
            description=description,
            extended_description=extended,
            alternate_terms=alternate_terms,
            attack_patterns=attack_patterns,
            likelihood=likelihood,
            common_consequences=tuple(consequences),
            potential_mitigations=tuple(mitigations),
            functional_areas=functional_areas,
            parents_view1000=frozenset(parents),
            tech_classes=frozenset(tech_classes),
            tech_names=frozenset(tech_names),
            has_lang_not_specific=has_lang_not_specific,
        )
    return index


def _children_map(index: Mapping[int, Weakness]) -> dict[int, frozenset[int]]:
    """parent -> children over the View 1000 ChildOf edges."""
    children: dict[int, set[int]] = {}
    for weakness in index.values():
        for parent in weakness.parents_view1000:
            children.setdefault(parent, set()).add(weakness.cwe_id)
    return {p: frozenset(c) for p, c in children.items()}


def walk_descendants(seed_ids: Iterable[int],
                     children: Mapping[int, frozenset[int]]) -> frozenset[int]:
    """The FULL View-1000 descendant set of the seeds (spec 5.2): every
    descendant at any depth, not hand-picked children - the R-a mitigation."""
    collected: set[int] = set()
    frontier = list(seed_ids)
    while frontier:
        current = frontier.pop()
        if current in collected:
            continue
        collected.add(current)
        frontier.extend(children.get(current, ()))
    return frozenset(collected)


def _abstract_to_concrete(collected: set[int], index: Mapping[int, Weakness],
                          children: Mapping[int, frozenset[int]]) -> set[int]:
    """Replace a retained Pillar/Class with its smallest-id unclaimed Base/
    Variant descendant already in the collected set (spec 5.4); dedupe again.

    Each abstract claims its OWN smallest candidate (a later abstract cannot
    steal one an earlier abstract already emitted); an abstract with no
    unclaimed concrete descendant stays (fail-open recall). Deterministic:
    sorted iteration, smallest-id choice."""
    result: set[int] = set()
    claimed: set[int] = set()
    for cwe_id in sorted(collected):
        weakness = index[cwe_id]
        if weakness.abstraction not in ("Pillar", "Class"):
            result.add(cwe_id)
            continue
        descendants = walk_descendants((cwe_id,), children)
        candidates = sorted(
            d for d in descendants
            if d in collected and d != cwe_id
            and index[d].abstraction in ("Base", "Variant")
            and d not in claimed
        )
        if not candidates:
            result.add(cwe_id)  # no concrete descendant in set: keep, fail-open
            continue
        chosen = candidates[0]
        claimed.add(chosen)
        result.add(chosen)
    return result


def _risk_of(seed: Mapping[str, tuple[int, ...]], cwe_id: int) -> tuple[str, ...]:
    return tuple(sorted(r for r, ids in seed.items() if cwe_id in ids))


def promote_captures(entries: list[dict], index: Mapping[int, Weakness],
                     authoring: dict[str, dict]) -> list[dict]:
    """The promotion stage: add `promote: true` authoring entries to the
    catalogue as selection captures (the overlap-critic's PROMOTE-AND-FOLD
    verdicts). A promoted id is either (a) ALREADY in the curated set - its
    promotion is the web-relevance-omit REVERSAL (the omit entry is removed
    from 10-web-relevance-omit.yaml, this marker stays as the record), or
    (b) genuinely absent from the catalogue - a CWE in the XML that the walk
    never reached (it is an ancestor of an orphan, not a descendant of a
    seed); it is extracted like any other entry and gets its matching facet
    from the same authoring dict via fold_authoring afterwards. Pure +
    deterministic (sorted insertion)."""
    existing = {e["fault_id"] for e in entries}
    added = []
    for fault_id, spec in sorted(authoring.items()):
        if not spec.get("promote"):
            continue
        if fault_id in existing:
            continue
        cwe_id = int(fault_id.split("-")[1])
        if cwe_id not in index:
            raise ValueError(
                f"promote names {fault_id}, absent from the XML")
        entries.append(_extract_entry(index[cwe_id], ()))
        added.append(fault_id)
    if added:
        print(f"note: promoted captures added: {', '.join(sorted(added))}",
              file=sys.stderr)
    return sorted(entries, key=lambda e: e["fault_id"])


def _fold_target(cwe_id: int, *, in_catalogue: frozenset[int],
                 index: Mapping[int, Weakness]) -> int | None:
    """The deterministic fold target of one entry: the NEAREST in-catalogue
    Base/Class ancestor along the View-1000 ChildOf chains (BFS, multi-parent
    aware, cycle-guarded). Variant/Compound waypoints are skipped so a chain
    lands on the narrowest retained capture ("taxed as base, not class"): a
    Variant whose parent is a folded Variant folds to the same Base. `None`
    for an orphan (no retained Base/Class ancestor) - the entry STAYS in the
    selection tier (fail-open recall)."""
    seen: set[int] = set()
    frontier = list(index[cwe_id].parents_view1000)
    while frontier:
        current = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        if current in in_catalogue \
                and index[current].abstraction in ("Base", "Class"):
            return current
        frontier.extend(index[current].parents_view1000)
    return None


def fold_variants(entries: list[dict],
                  index: Mapping[int, Weakness],
                  keep_separate: frozenset[int] = frozenset()) -> list[dict]:
    """The fold stage: compute each entry's `fold_parent` (the deterministic
    nearest retained Base/Class ancestor, `null` for selection-tier entries).
    Variants/Compounds fold into their capture; Bases/Classes are captures;
    orphans keep `null` and stay selectable; `keep_separate` ids (the
    overlap-critic's SPLIT verdicts) are forced to `null` - they are
    genuinely distinct fault classes even though a View-1000 capture exists.
    Pure + deterministic (sorted iteration, BFS order)."""
    in_catalogue = frozenset(
        int(e["fault_id"].split("-")[1]) for e in entries)
    for entry in sorted(entries, key=lambda e: e["fault_id"]):
        cwe_id = int(entry["fault_id"].split("-")[1])
        if entry["abstraction"] not in ("Variant", "Compound"):
            entry["fold_parent"] = None
            continue
        if cwe_id in keep_separate:
            entry["fold_parent"] = None
            continue
        target = _fold_target(cwe_id, in_catalogue=in_catalogue, index=index)
        entry["fold_parent"] = f"CWE-{target}" if target is not None else None
    return entries


def _extract_entry(weakness: Weakness, risks: tuple[str, ...]) -> dict:
    """One entry in the schema of spec section 4, matching facet un-authored."""
    return {
        "fault_id": f"CWE-{weakness.cwe_id}",
        "name": weakness.name,
        "abstraction": weakness.abstraction,
        "owasp_2025": list(risks),
        "applies_if": {
            "nl": "",
            "predicate": None,
        },
        "enum_kinds": [],
        "fold_parent": None,
        "materialisation": {
            "description": weakness.description,
            "extended_description": weakness.extended_description or None,
            "alternate_terms": list(weakness.alternate_terms),
            "related_attack_patterns": list(weakness.attack_patterns),
            "likelihood": weakness.likelihood,
            "common_consequences": list(weakness.common_consequences),
            "potential_mitigations": list(weakness.potential_mitigations),
            "functional_areas": list(weakness.functional_areas),
        },
    }


class _Dumper(yaml.SafeDumper):
    """Deterministic emitter: multi-line strings as | block scalars."""


def _represent_str(dumper: _Dumper, data: str) -> yaml.Node:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _represent_predicate(dumper: _Dumper, predicate: Any) -> yaml.Node:
    """Emit a TypedPredicate in the plain-mapping shape of spec section 4
    (target + clauses) so the catalogue stays a pure data artifact."""
    clauses = [
        {"form": clause.form.value,
         "key": clause.key,
         "values": list(clause.values),
         "role": clause.role}
        for clause in predicate.clauses
    ]
    return dumper.represent_mapping(
        "tag:yaml.org,2002:map",
        {"target": predicate.target, "clauses": clauses},
    )


# NOTE: the TypedPredicate representer is registered lazily inside
# _ensure_runtime_constants() once the class is imported (the class is a
# curation-time-only import, never a module-level dependency).

# --- the authoring fold (spec section 5.6) -------------------------------------
#
# The matching facet is authored by the CURATOR over the emitted catalogue, in
# a checked-in sidecar (the one authoring seat, FKB-3). The fold below merges
# the sidecar into the emitted entries and VALIDATES against the runtime
# single-sources at curation time (spec section 3, Option A): enum_kinds must
# be a subset of SYSTEM_KINDS, a predicate must pass the #63 validator. A
# malformed authoring is a hard curation-time error - never silently dropped,
# never reaching runtime.
#
# Sidecar shape (one YAML file per range under tools/hunting/authoring/):
#   entries:
#     CWE-89:
#       nl: "The unit accepts user-controlled input that is incorporated into
#           an SQL query without proper neutralisation."
#       enum_kinds: [RESTApi, GraphQLApi, WebPresentation]
#       predicate:
#         target: Both
#         clauses:
#           - form: reachable-via
#             key: EXPOSED_VIA
#             values: [RESTApi, GraphQLApi, WebPresentation]
#     CWE-1189:
#       omit: true
#       omit_reason: "hardware SoC weakness: not web-application relevant"

_SYSTEM_KIND_IDS: frozenset[str] = frozenset()
_CLAUSE_FORMS: dict[str, Any] = {}
_Clause: Any = None
_TypedPredicate: Any = None
_validate_predicate: Any = None
_PREDICATE_REPRESENTER_REGISTERED = False


def _ensure_runtime_constants() -> None:
    """Import the runtime single-sources (SYSTEM_KINDS, the #63 validator)
    from the repo's src/ tree - the curation-time validation seat."""
    global _SYSTEM_KIND_IDS, _CLAUSE_FORMS, _Clause, _TypedPredicate
    global _validate_predicate
    if _SYSTEM_KIND_IDS:
        return
    repo_src = Path(__file__).resolve().parents[2] / "src"
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS  # noqa: PLC0415
    from polymerhus.attack.hunting.predicate import (  # noqa: PLC0415
        Clause,
        ClauseForm,
        TypedPredicate,
        validate_predicate,
    )
    _SYSTEM_KIND_IDS = frozenset(kind for kind, _desc in SYSTEM_KINDS)
    _CLAUSE_FORMS = {form.value: form for form in ClauseForm}
    _Clause = Clause
    _TypedPredicate = TypedPredicate
    _validate_predicate = validate_predicate
    global _PREDICATE_REPRESENTER_REGISTERED
    if not _PREDICATE_REPRESENTER_REGISTERED:
        _Dumper.add_representer(TypedPredicate, _represent_predicate)
        _PREDICATE_REPRESENTER_REGISTERED = True


def load_authoring(dir_path: Path) -> dict[str, dict]:
    """Load + validate the authoring sidecar files (sorted by name, one file
    per range). Returns fault_id -> authoring dict. Duplicate authoring of the
    same fault across files is a hard error, EXCEPT for three documented
    override layers (files apply in sorted-name order, later wins):
      * an OMIT marker (10-web-relevance-omit.yaml) overrides a prior entry:
        the fault is dropped from the catalogue, keeping its prior nl in the
        source only;
      * a SPLIT marker (70-fold-amendments.yaml) MERGES into the prior entry
        ({split: true} only): the fault stays selection-tier with its prior
        matching facet;
      * a PROMOTE spec (70-fold-amendments.yaml) REVERSES an omit (the
        overlap-critic's PROMOTE-AND-FOLD verdict supersedes a web-relevance
        omission) or MERGES into a prior entry: later keys win per-key, the
        promoted capture keeps the amendment's nl/enum_kinds/predicate.
    Deterministic: sorted-name file order."""
    authoring: dict[str, dict] = {}
    for path in sorted(dir_path.glob("*.yaml")):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            raise ValueError(f"authoring file {path}: missing 'entries' mapping")
        for fault_id, spec in entries.items():
            if not isinstance(spec, dict):
                raise ValueError(f"authoring file {path}: entry {fault_id} is "
                                 f"{type(spec).__name__}, expected a mapping")
            prior = authoring.get(fault_id)
            if "promote" in spec or "split" in spec:
                if prior is None:
                    authoring[fault_id] = spec
                    continue
                if prior.get("omit"):
                    if "promote" in spec:
                        authoring[fault_id] = spec
                        continue
                    raise ValueError(
                        f"authoring file {path}: split marker for OMITTED "
                        f"{fault_id} is contradictory")
                authoring[fault_id] = {**prior, **spec}
                continue
            if prior is not None:
                if spec.get("omit") and prior.get("omit"):
                    raise ValueError(
                        f"authoring file {path}: duplicate OMIT for {fault_id}")
                if spec.get("omit"):
                    authoring[fault_id] = spec
                    continue
                raise ValueError(
                    f"authoring file {path}: duplicate authoring for {fault_id}")
            authoring[fault_id] = spec
    return authoring


def _parse_predicate(raw: Any, fault_id: str) -> Any:
    """The sidecar predicate dict -> TypedPredicate, validated (#63 grammar)."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"{fault_id}: predicate must be a mapping or null")
    target = raw.get("target")
    if target not in ("Service", "System", "Both"):
        raise ValueError(f"{fault_id}: predicate.target must be one of "
                         "Service/System/Both, got {target!r}")
    raw_clauses = raw.get("clauses")
    if not isinstance(raw_clauses, list) or not raw_clauses:
        raise ValueError(f"{fault_id}: predicate needs a non-empty 'clauses' list")
    clauses = []
    for raw_clause in raw_clauses:
        form = raw_clause.get("form")
        form_enum = _CLAUSE_FORMS.get(form)
        if form_enum is None:
            raise ValueError(
                f"{fault_id}: unsupported clause form {form!r}; the #63 "
                f"grammar is {sorted(_CLAUSE_FORMS)}")
        key = raw_clause.get("key")
        values = tuple(raw_clause.get("values") or ())
        clauses.append(_Clause(form_enum, key=key, values=values,
                               role=raw_clause.get("role")))
    predicate = _TypedPredicate(target=target, clauses=tuple(clauses))
    try:
        _validate_predicate(predicate)
    except ValueError as exc:
        raise ValueError(f"{fault_id}: invalid predicate: {exc}") from exc
    return predicate


def fold_authoring(entries: list[dict], authoring: dict[str, dict]) -> list[dict]:
    """Merge the authoring sidecar into the emitted entries: omit markers
    remove entries, nl/enum_kinds/predicate overrides land in the matching
    facet (validated). Returns the final catalogue, sorted by fault_id."""
    _ensure_runtime_constants()
    by_id = {e["fault_id"]: e for e in entries}
    for fault_id, spec in authoring.items():
        entry = by_id.get(fault_id)
        if entry is None:
            raise ValueError(
                f"authoring names {fault_id}, but the curated catalogue does "
                f"not contain it (id absent or filtered)")
        if spec.get("omit"):
            by_id.pop(fault_id)
            continue
        nl = spec.get("nl")
        if nl is None or not str(nl).strip():
            raise ValueError(f"{fault_id}: a kept entry needs a non-empty "
                             "applies_if.nl (authoring is per-entry)")
        entry["applies_if"]["nl"] = str(nl).strip()
        enum_kinds = spec.get("enum_kinds", [])
        unknown = [k for k in enum_kinds if k not in _SYSTEM_KIND_IDS]
        if unknown:
            raise ValueError(
                f"{fault_id}: enum_kinds {unknown} not in SYSTEM_KINDS")
        entry["enum_kinds"] = list(enum_kinds)
        predicate = spec.get("predicate")
        if "predicate" in spec:
            entry["applies_if"]["predicate"] = _parse_predicate(
                predicate, fault_id)
    return sorted(by_id.values(), key=lambda e: e["fault_id"])

_HEADER = """\
# The phase-1 web-app fault knowledge base (CWE via OWASP Top 10 2025), #66.
#
# Out-of-band curation output: `tools/hunting/curate_fault_kb.py` over
# cwec_v4.20.xml (2026-04-30) entered through the reviewed OWASP Top 10 2025
# seed mapping (`tools/hunting/owasp-top10-2025-seed.yaml`, commit
# 11a618cfa7a707d3b03137dd00b3c2bad461922a of OWASP/Top10).
#
# Mechanical content (fault_id, name, abstraction, owasp_2025, the
# materialisation facet) is script-generated and deterministic. The MATCHING
# facet (applies_if.nl, applies_if.predicate, enum_kinds) is authored by the
# curator over the emitted artifact (spec section 5.6) and reviewed in the PR.
# The typed predicate grammar is #63's; enum_kinds is a subset of SYSTEM_KINDS
# (the technical axis; the technological axis never appears here, #66 FKB-6).
#
# Spec: docs/design/hunting-66-fault-kb-spec.md. Loader:
# src/polymerhus/attack/hunting/fault_kb.py.
"""


def emit_catalogue(entries: list[dict]) -> str:
    """Deterministic YAML for the catalogue (sorted entries, sorted keys)."""
    body = yaml.dump(
        entries,
        Dumper=_Dumper,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
        width=10**6,
    )
    return _HEADER + body


def curate(xml_path: Path, seed_path: Path) -> list[dict]:
    """Run the full algorithm (spec 5.1-5.5 + 5.7): seed -> walk -> filter ->
    replace -> extract -> ordered entries (matching facet un-authored)."""
    seed = load_seed(seed_path)
    index = parse_catalogue(xml_path)
    children = _children_map(index)

    seed_ids = {cwe_id for ids in seed.values() for cwe_id in ids}
    absent = sorted(cwe_id for cwe_id in seed_ids if cwe_id not in index)
    if absent:
        print(f"note: seed ids absent from the XML (skipped): {absent}",
              file=sys.stderr)
    seed_ids = {cwe_id for cwe_id in seed_ids if cwe_id in index}

    collected = walk_descendants(seed_ids, children)
    filtered = {
        cwe_id for cwe_id in collected
        if not index[cwe_id].is_deprecated and index[cwe_id].is_web_relevant()
    }
    replaced = _abstract_to_concrete(filtered, index, children)

    entries = []
    for cwe_id in sorted(replaced):
        entries.append(_extract_entry(
            index[cwe_id], _risk_of(seed, cwe_id)))
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Produce the phase-1 fault-KB catalogue (offline, deterministic).")
    parser.add_argument("--xml", required=True, help="the local cwec_v4.20.xml path")
    parser.add_argument("--seed", required=True,
                        help="the reviewed OWASP Top 10 2025 seed mapping (YAML)")
    parser.add_argument("--out", required=True,
                        help="the catalogue YAML file to write")
    parser.add_argument("--authoring", required=True,
                        help="the directory of authoring sidecar YAML files "
                             "(the curator matching-facet seat, spec 5.6)")
    args = parser.parse_args(argv)

    authoring = load_authoring(Path(args.authoring))
    index = parse_catalogue(Path(args.xml))
    entries = curate(Path(args.xml), Path(args.seed))
    entries = promote_captures(entries, index, authoring)
    entries = fold_authoring(entries, authoring)
    keep_separate = frozenset(
        int(fid.split("-")[1]) for fid, spec in authoring.items()
        if spec.get("split"))
    entries = fold_variants(entries, index, keep_separate)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(emit_catalogue(entries), encoding="utf-8")
    print(f"wrote {len(entries)} entries to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
