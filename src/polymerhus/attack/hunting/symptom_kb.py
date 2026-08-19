"""The typed retrieval seam into the external symptom-technique KB (#66, spec
section 7; the `symptom-technique KB` handle of `HuntConfig`).

The hunting agent queries the external, operator-built symptom-technique KB at
spec-writing time for the `symptom(s)` + `probing-technique(s)` of a
`(fault-class, unit technological-axis)` pair. THIS module does not author
those - it specs the typed contract only (FKB-5):

  * `SymptomTechniqueQuery` - the typed query: the join key is
    `(fault-class, unit technological-axis)`. The query carries the
    TECHNOLOGICAL axis (framework / runtime / middleware names); the fault-KB
    entry's `enum_kinds` tag carries the TECHNICAL-axis SYSTEM_KINDS - the two
    vocabularies never share a field (FKB-6, the non-conflation rule).
  * `SymptomTechniqueResult` - the typed response: symptoms + probing
    techniques + an optional source; the external KB's internal ontology stays
    an implementation detail behind this contract, so a swap is a seam change,
    never a hunting-agent rewrite.

Fail-open readiness: the external KB is a parallel operator build and may not
be ready. Selection / spec-writing degrades to the fault-KB's own
materialisation content when it is not ready and NEVER crashes the caller: a
not-ready or erroring external KB returns an empty `SymptomTechniqueResult`.

STATUS: the contract is typed and live here; the KB's live WIRING into a
running hunting agent is designed-not-built (the hunting agent itself is
#67/#82) - this module performs no I/O at import, imports no driver, and the
default query seam is an inert fail-open stub, never a fake implementation
(CODING_STANDARD section 12).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

# The external KB's lookup function shape: (query) -> result. A caller with a
# live external KB supplies this at the seam; the default is the fail-open
# stub below. Injectability keeps this module's unit tier DB/LLM-free.
SymptomTechniqueLookup = Callable[[object], "SymptomTechniqueResult"]


@dataclass(frozen=True)
class SymptomTechniqueQuery:
    """The typed query into the external symptom-technique KB (spec 7).

    `fault_id` is the CWE fault id; `technological_axis` names the unit's
    technological stack (framework / runtime / middleware), NEVER a SYSTEM_KIND
    - the technical axis lives only in the fault-KB entry's `enum_kinds` tag
    (FKB-6, the non-conflation rule).
    """

    fault_id: str
    technological_axis: tuple[str, ...] = ()


@dataclass(frozen=True)
class SymptomTechniqueResult:
    """The typed response (spec 7). An EMPTY result is the fail-open signal: a
    not-ready or erroring external KB returns `SymptomTechniqueResult()`, and
    the caller degrades to the fault-KB's own materialisation content."""

    symptoms: tuple[str, ...] = ()
    techniques: tuple[str, ...] = ()
    source: str | None = None


def _fail_open_stub(query: object) -> SymptomTechniqueResult:
    """The default (dormant) lookup: the external KB is a designed-not-built
    parallel build, so the seam is inert and fail-open - it never crashes and
    never fabricates content (CODING_STANDARD section 12)."""
    return SymptomTechniqueResult()


def query_symptom_technique(
        query: SymptomTechniqueQuery,
        lookup: SymptomTechniqueLookup | None = None) -> SymptomTechniqueResult:
    """The typed seam: query the external symptom-technique KB and NEVER crash
    the caller - a missing, not-ready, or erroring KB yields an empty
    `SymptomTechniqueResult` (spec 7 fail-open readiness).

    The caller (a hunting agent at spec-writing time) treats an empty result
    as "degrade to the fault-KB's own materialisation content" - the fallback
    is the KB's `load_materialisation`, not this seam."""
    try:
        if lookup is not None:
            return lookup(query)
        return _fail_open_stub(query)
    except Exception:  # noqa: BLE001 - fail-open is the contract
        return SymptomTechniqueResult()


def build_fault_kb_lookup(
    catalogue_path=None,
) -> SymptomTechniqueLookup:
    """The REAL symptom-technique lookup, wired to the packaged fault-KB
    materialisation facet (fault_kb.load_materialisation): symptoms come from
    the entry's description, probing techniques from its related attack
    patterns and alternate terms. Loading is lazy (first call) and the lookup
    is fail-open: an unknown fault id returns an empty `SymptomTechniqueResult`,
    never raising (CODING_STANDARD section 12 - no I/O at import)."""
    from polymerhus.attack.hunting.fault_kb import load_materialisation  # noqa: PLC0415

    cache: dict | None = None

    def lookup(query: object) -> SymptomTechniqueResult:
        nonlocal cache
        if cache is None:
            cache = load_materialisation(catalogue_path)
        entry = cache.get(getattr(query, "fault_id", ""))
        if entry is None:
            return SymptomTechniqueResult()
        techniques = tuple(dict.fromkeys(
            [*(entry.related_attack_patterns or ()), *(entry.alternate_terms or ())]
        ))
        symptoms = (entry.description,) if entry.description else ()
        return SymptomTechniqueResult(
            symptoms=symptoms,
            techniques=techniques,
            source="fault-kb",
        )

    return lookup


def build_gate_kb_retriever(catalogue_path=None):
    """The orchestrator gate's KB evidence retriever (D67-11): `fault_class ->
    dict` with the materialised symptoms/probing techniques, consumed by the
    gate prompt and the fault-targeting tool registry. Fail-open to an empty
    entry for an unknown fault."""
    lookup = build_fault_kb_lookup(catalogue_path)

    def retrieve(fault_class: str) -> dict:
        result = lookup(SymptomTechniqueQuery(fault_id=fault_class))
        return {
            "symptoms": list(result.symptoms),
            "probing_techniques": list(result.techniques),
            "source": result.source,
        }

    return retrieve
