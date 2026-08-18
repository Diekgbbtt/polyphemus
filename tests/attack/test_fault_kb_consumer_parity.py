"""Consumer-parity tier: the REAL fault-KB catalogue feeds the FaultSource
selection stage (#66, spec section 11, third bullet).

A walkthrough over `fault_source.select` with an injected fake reader - no
DB, no network, no LLM - asserting the KB-to-selection contract holds without
a grammar fork:

  * a HARDENED entry (typed predicate) prunes a unit through the
    deterministic stage (`pruned-by-predicate` with the violating clause as
    witness, and the stage is evaluated - `predicates_evaluated == 1`);
  * an UNHARDENED TAG entry degrades to the enum-of-system-kinds gate
    (`pruned-by-tag` when the unit links no presupposed kind, `passed` when
    it does - no predicate evaluation, `predicates_evaluated == 0`);
  * an NL-ONLY entry (no predicate, no tag) passes straight through to the
    match stage (fail-open).

The fake reader serves the projection read (`build_projection`): a Service
unit exposes its outgoing typed edges; the second read (data relationships)
returns nothing.
"""
import pytest

from polymerhus.attack.hunting.fault_kb import (
    load_fault_entries,
    load_materialisation,
)
from polymerhus.attack.hunting.fault_source import select


# --- the fake reader ------------------------------------------------------------

def _fake_read_fn(unit_edges):
    """A projection reader: one row for the unit query (given edges), empty
    rows for every other query (data relationships). The read_fn receives the
    SPLIT identity params (kind + key); the edges dict is keyed by the
    kind-qualified unit id."""
    def read(query, params):
        if "RETURN labels(u)" in query:
            unit_id = f"{params['kind']}:{params['key']}"
            edges = []
            for family, target_kind in unit_edges.get(unit_id, []):
                edges.append({
                    "family": family,
                    "tlabels": ["L1System", "L1TestableUnit"],
                    "tprops": {"kind": target_kind},
                    "rprops": {},
                })
            return [{
                "labels": ["L1Service", "L1TestableUnit"],
                "props": {"business_function_slug": unit_id},
                "edges": edges,
            }]
        return []
    return read


# --- the real catalogue ---------------------------------------------------------

@pytest.fixture(scope="module")
def catalogue():
    """The checked-in fault-KB artifact, loaded through its default lazy path."""
    entries = load_fault_entries()
    assert entries, "the real catalogue must load (fault-kb.yaml present)"
    by_id = {e.fault_id: e for e in entries}
    return by_id


# --- the two-tier shape holds on the real artifact -------------------------------

def test_selection_tier_excludes_every_folded_variant():
    """The selection tier must carry no folded entry, and every fold_parent
    must point at a live selection entry: the fold is a closed capture."""
    selection = load_fault_entries()
    materialisation = load_materialisation()
    selection_ids = {e.fault_id for e in selection}
    folded = [m for m in materialisation.values() if m.fold_parent]
    assert folded, "the real catalogue must carry folded recipes"
    assert all(m.fault_id not in selection_ids for m in folded)
    assert all(m.fold_parent in selection_ids for m in folded)
    # the fold demonstrably shrinks the matching loop (selection tier < the
    # full recipe set) - the phase-1 scaling premise of the fold
    assert len(selection_ids) < len(materialisation)


def _run(by_id, fault_ids, unit_edges):
    """One selection pass over the given faults with the given fake model."""
    faults = [by_id[fid] for fid in fault_ids]
    reports = select(faults, sorted(unit_edges),
                     project_id="parity-project", read_fn=_fake_read_fn(unit_edges))
    return {r.fault_id: r for r in reports}


# --- a hardened entry prunes (predicate stage) ----------------------------------

def test_hardened_entry_prunes_via_predicate(catalogue):
    # CWE-89 is hardened: REACHABLE_VIA EXPOSED_VIA (WebPresentation,
    # RESTApi, GraphQLApi) AND DATA_EDGE_EXISTS CONSUMES (catalogue file).
    # The unit exposes only a WAF edge - a validated kind outside the clause
    # values -> the family contradicts -> FALSE -> deterministic prune.
    report = _run(catalogue, ["CWE-89"],
                  {"Service:cart": [("EXPOSED_VIA", "WAF")]})["CWE-89"]
    outcome = report.outcomes[0]
    assert outcome.verdict == "pruned-by-predicate"
    assert outcome.witness is not None
    assert report.predicates_evaluated == 1


def test_hardened_entry_passes_on_matching_exposure(catalogue):
    report = _run(catalogue, ["CWE-89"],
                  {"Service:cart": [("EXPOSED_VIA", "RESTApi")]})["CWE-89"]
    assert report.outcomes[0].verdict == "passed"
    assert report.predicates_evaluated == 1


# --- an unhardened entry degrades to the enum gate ------------------------------

def test_tag_entry_prunes_by_tag_when_kind_absent(catalogue):
    # CWE-1021 (clickjacking) is unhardened: predicate null, enum_kinds
    # [WebPresentation]. The unit exposes only a WAF system -> no presupposed
    # kind linked -> pruned-by-tag, no predicate evaluation.
    report = _run(catalogue, ["CWE-1021"],
                  {"Service:session": [("EXPOSED_VIA", "WAF")]})["CWE-1021"]
    assert report.outcomes[0].verdict == "pruned-by-tag"
    assert report.predicates_evaluated == 0


def test_tag_entry_passes_when_kind_linked(catalogue):
    report = _run(catalogue, ["CWE-1021"],
                  {"Service:session": [("EXPOSED_VIA", "WebPresentation")]})["CWE-1021"]
    assert report.outcomes[0].verdict == "passed"
    assert report.predicates_evaluated == 0


# --- an NL-only entry passes straight through (fail-open) ------------------------

def test_nl_only_entry_passes_straight_through(catalogue):
    # an entry with neither predicate nor enum_kinds cannot prune: it passes
    # to the match stage with an empty evaluation log
    nl_only = [fid for fid, e in catalogue.items()
               if e.predicate is None and not e.enum_kinds]
    assert nl_only, "the real catalogue carries NL-only entries"
    fid = nl_only[0]
    report = _run(catalogue, [fid],
                  {"Service:unit": [("EXPOSED_VIA", "WebPresentation")]})[fid]
    assert report.outcomes[0].verdict == "passed"
    assert report.predicates_evaluated == 0
