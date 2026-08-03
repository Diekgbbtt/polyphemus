"""E1-E6 e2e walkthrough - the #63 typed applies-if predicate over the live model.

Fires the FaultSource selection entry (fault_source.select) over REAL
writer-built L1 models (no LLM; canned deltas) against live Neo4j, with the LLM
match in pass-through COUNTING mode - the declared substitution of the spec's
Appendix A walkthrough predicates (the match's verdicts are #71/#64 scope, not
this spec's; only its invocation count is asserted). Asserts each walkthrough's
terminal quantities: the stage's evaluation log (the selection report's
outcomes), the match invocation counter, and the candidate set read back from
the minting seam. Expected values are taken from the spec, never recomputed.

The unit set of each walkthrough is the curated model's unit set (the units the
spec names). The System node a system-edge writer MERGEs as a by-product (e.g.
the RESTApi behind S3) is an edge endpoint, not a curated unit of the model,
and is not in the unit set - the spec's terminals (4 evaluations, 3 pass, 1
does-not-apply) are the ground truth.
"""
import subprocess
import uuid

import pytest
from neo4j import GraphDatabase

from db.neo4j.init_schema import init_schema
from db.neo4j.l1_schema import init_l1_schema
from polymerhus.analysis.l1_curator import enrich, l1_curate
from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    Provenance,
    ServiceDelta,
    SystemDelta,
    SystemEdgeDelta,
)
from polymerhus.attack.hunting.fault_source import FaultEntry, mint_candidates, select
from polymerhus.attack.hunting.predicate import Clause, ClauseForm, TypedPredicate
from tests.conftest import neo4j_target, wait_for

# Single source of truth (tests/conftest.py::neo4j_target): env-driven so this
# file works BOTH in-network (bolt://neo4j:7687) and from the host against the
# published port.
URI, AUTH = neo4j_target()

PROV = Provenance(job="hunting:walkthrough", model="m", prompt_id="p")

GQL_CLAUSE = Clause(form=ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA",
                    values=("GraphQLApi",))


def _driver():
    d = GraphDatabase.driver(URI, auth=AUTH)
    d.verify_connectivity()
    return d


@pytest.fixture(scope="module")
def session():
    try:
        subprocess.run(["docker", "compose", "up", "-d", "neo4j"], check=False)
    except Exception:  # noqa: BLE001
        pass
    try:
        driver = wait_for(_driver, timeout=60)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"neo4j not reachable for the #63 walkthrough: {exc}")
    with driver.session() as s:
        init_schema(s)
        init_l1_schema(s)
        yield s
    driver.close()


@pytest.fixture
def project(session):
    pid = "ht63_wt_" + uuid.uuid4().hex[:8]
    yield pid
    session.run("MATCH (n) WHERE n.project_id = $p DETACH DELETE n", p=pid)


def _read_fn(session):
    return lambda cy, p: [r.data() for r in session.run(cy, **p)]


def _curate_model(session, project, services, systems):
    mf = lambda cy, p: session.run(cy, **p).consume()
    l1_curate(services, systems, project, merge_fn=mf)


def _add_edges(session, project, edges):
    mf = lambda cy, p: session.run(cy, **p).consume()
    enrich(project, system_edges=edges, merge_fn=mf)


def _service(slug, **props):
    return ServiceDelta(business_function_slug=slug,
                        props={"label": slug, **props}, provenance=PROV)


def _system(kind, discriminator=L1_SINGLETON, **props):
    return SystemDelta(kind=kind, discriminator=discriminator, props=props,
                       provenance=PROV)


def _edge(service_slug, rel, kind):
    return SystemEdgeDelta(service_slug=service_slug, kind=kind, rel=rel,
                           provenance=PROV)


class _CountingMatch:
    """The declared substitution: the LLM match in pass-through COUNTING mode
    (its verdicts are #71/#64 scope, not this spec's - only the invocation
    count is asserted)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, unit_id, fault_id):
        self.calls += 1
        return True


def _s1_oracle(session, project, fault):
    """The Q8 S1 spine-existence reference set, reimplemented from the Q8
    semantics (#62) - NEVER the code's own filter, so the comparison is not a
    tautology: a Service is pruned iff it carries NO edge of the clause's
    family to a System of any listed kind (its required system is missing)."""
    if fault.predicate is None:
        return set()
    pruned = set()
    for clause in fault.predicate.clauses:
        if clause.form is not ClauseForm.REACHABLE_VIA:
            continue
        rows = _read_fn(session)(
            "MATCH (s:L1TestableUnit:L1Service {project_id: $p}) "
            "OPTIONAL MATCH (s)-[:" + clause.key + "]->(m:L1System) "
            "WITH s, collect(DISTINCT m.kind) AS kinds "
            "WHERE NOT any(k IN kinds WHERE k IN $kinds) "
            "RETURN s.business_function_slug AS slug",
            {"p": project, "kinds": list(clause.values)},
        )
        for row in rows:
            pruned.add(f"Service:{row['slug']}")
    return pruned


# --- E1: a hardened fault prunes only the structurally impossible ---

def test_E1_hardened_prune_and_match_survivors(session, project):
    _curate_model(session, project,
                  services=[_service("s1"), _service("s2"), _service("s3")],
                  systems=[_system("GraphQLApi")])
    _add_edges(session, project, [
        _edge("s1", "EXPOSED_VIA", "GraphQLApi"),
        _edge("s2", "EXPOSED_VIA", "GraphQLApi"),
        _edge("s3", "EXPOSED_VIA", "RESTApi"),
    ])
    fault = FaultEntry("graphql-introspection",
                       predicate=TypedPredicate(target="Both",
                                                clauses=(GQL_CLAUSE,)))
    units = ("Service:s1", "Service:s2", "Service:s3",
             "GraphQLApi:__singleton__")
    match = _CountingMatch()
    (report,) = select((fault,), units, project_id=project,
                       read_fn=_read_fn(session), match_fn=match)

    assert report.predicates_evaluated == 4
    outcomes = {o.unit_id: o for o in report.outcomes}
    assert outcomes["Service:s1"].verdict == "passed"
    assert outcomes["Service:s2"].verdict == "passed"
    assert outcomes["Service:s3"].verdict == "pruned-by-predicate"
    assert outcomes["Service:s3"].witness == \
        "reachable-via(EXPOSED_VIA, {GraphQLApi})"
    assert outcomes["GraphQLApi:__singleton__"].verdict == "passed"
    assert match.calls == 3  # once per passer (S1, S2, G)
    # the output set contains no insufficient-evidence (D-D)
    assert all(o.verdict in {"passed", "pruned-by-predicate", "pruned-by-tag"}
               for o in report.outcomes)


# --- E2: unknown-facet default-open in the live model ---

def test_E2_unknown_facet_default_open(session, project):
    _curate_model(session, project,
                  services=[_service("s4", exposure="public"), _service("s5")],
                  systems=[])
    fault = FaultEntry("exposed-service",
                       predicate=TypedPredicate(
                           target="Service",
                           clauses=(Clause(form=ClauseForm.SPINE_PRESENT,
                                           key="exposure"),)))
    units = ("Service:s4", "Service:s5")
    match = _CountingMatch()
    (report,) = select((fault,), units, project_id=project,
                       read_fn=_read_fn(session), match_fn=match)

    assert [o.verdict for o in report.outcomes] == ["passed", "passed"]
    assert all(o.witness is None for o in report.outcomes)
    assert report.predicates_evaluated == 2
    assert match.calls == 2


# --- E3: unhardened entry degrade in the live model ---

def test_E3_unhardened_entry_degrade(session, project):
    _curate_model(session, project,
                  services=[_service("s6"), _service("s7")],
                  systems=[_system("WAF")])
    _add_edges(session, project, [_edge("s6", "FRONTED_BY", "WAF")])
    fault = FaultEntry("waf-dependent", enum_kinds=frozenset({"WAF"}))
    units = ("Service:s6", "Service:s7")
    match = _CountingMatch()
    (report,) = select((fault,), units, project_id=project,
                       read_fn=_read_fn(session), match_fn=match)

    assert report.predicates_evaluated == 0  # the typed stage is inert
    outcomes = {o.unit_id: o for o in report.outcomes}
    assert outcomes["Service:s6"].verdict == "passed"
    assert outcomes["Service:s7"].verdict == "pruned-by-tag"
    assert match.calls == 1  # S6 only


# --- E4: system-strict faults mint no Service candidates ---

def test_E4_system_strict_mints_no_services(session, project):
    _curate_model(session, project,
                  services=[_service("s8"), _service("s9"),
                            _service("s10"), _service("s11")],
                  systems=[_system("WAF", discriminator="EdgeWAF"),
                           _system("WAF", discriminator="CloudWAF")])
    fault = FaultEntry("waf-bypass",
                       predicate=TypedPredicate(
                           target="System",
                           clauses=(Clause(form=ClauseForm.KIND_IS,
                                           values=("WAF",)),)))
    units = ("Service:s8", "Service:s9", "Service:s10", "Service:s11",
             "WAF:EdgeWAF", "WAF:CloudWAF")

    assert mint_candidates(fault, units) == ("WAF:EdgeWAF", "WAF:CloudWAF")

    match = _CountingMatch()
    (report,) = select((fault,), units, project_id=project,
                       read_fn=_read_fn(session), match_fn=match)
    assert [o.unit_id for o in report.outcomes] == \
        ["WAF:EdgeWAF", "WAF:CloudWAF"]
    assert all(o.verdict == "passed" for o in report.outcomes)
    assert match.calls == 2


# --- E5: S1-subsumption parity live ---

def test_E5_s1_subsumption_parity_live(session, project):
    _curate_model(session, project,
                  services=[_service("s1"), _service("s2"), _service("s3")],
                  systems=[_system("GraphQLApi")])
    _add_edges(session, project, [
        _edge("s1", "EXPOSED_VIA", "GraphQLApi"),
        _edge("s2", "EXPOSED_VIA", "GraphQLApi"),
        _edge("s3", "EXPOSED_VIA", "RESTApi"),
    ])
    fault = FaultEntry("graphql-introspection",
                       predicate=TypedPredicate(target="Both",
                                                clauses=(GQL_CLAUSE,)))
    units = ("Service:s1", "Service:s2", "Service:s3",
             "GraphQLApi:__singleton__")
    match = _CountingMatch()
    (report,) = select((fault,), units, project_id=project,
                       read_fn=_read_fn(session), match_fn=match)

    predicate_pruned = {o.unit_id for o in report.outcomes
                        if o.verdict == "pruned-by-predicate"}
    s1_pruned = _s1_oracle(session, project, fault)

    # the predicate's prune set is a superset of S1's; every S1 prune is
    # reproduced by a predicate clause (S1-only pruned count is exactly 0)
    assert predicate_pruned.issuperset(s1_pruned)
    assert s1_pruned - predicate_pruned == set()
    assert s1_pruned == {"Service:s3"}


# --- E6: FALSE dominates UNKNOWN in the live model ---

def test_E6_false_dominates_unknown_live(session, project):
    _curate_model(session, project,
                  services=[_service("s12")],
                  systems=[_system("WebPresentation")])
    _add_edges(session, project, [_edge("s12", "EXPOSED_VIA", "WebPresentation")])
    fault = FaultEntry("dom-xss",
                       predicate=TypedPredicate(
                           target="Service",
                           clauses=(
                               Clause(form=ClauseForm.SPINE_PRESENT,
                                      key="exposure"),
                               Clause(form=ClauseForm.REACHABLE_VIA,
                                      key="EXPOSED_VIA",
                                      values=("RESTApi",)),
                           )))
    units = ("Service:s12",)
    match = _CountingMatch()
    (report,) = select((fault,), units, project_id=project,
                       read_fn=_read_fn(session), match_fn=match)

    assert len(report.outcomes) == 1
    outcome = report.outcomes[0]
    assert outcome.verdict == "pruned-by-predicate"
    # clause 1 (spine-present(exposure)) is UNKNOWN - never the witness;
    # clause 2 is FALSE - it is the witness
    assert outcome.witness == "reachable-via(EXPOSED_VIA, {RESTApi})"
    assert match.calls == 0
