"""Unit tier: the deterministic stage `evaluate` + the FaultSource selection
entry (#63, spec 2.4/2.5/2.6, C2/C3/C9/C10/C11/C12 at the unit tier).

The stage is the pure function `evaluate(predicate, unit_projection) ->
{pass, does-not-apply, witness}`: three-valued clause semantics (TRUE / FALSE /
UNKNOWN), FALSE iff at least one clause is FALSE (AND of necessary
conditions), UNKNOWN never prunes, no LLM, deterministic. `evaluate_unit` adds
the fail-open wrapper over the reader; `select` is the entry that mints by
target declaration, evaluates per unit, degrades per-entry (predicate -> tag ->
default-open), and passes survivors to the LLM `match_fn` (counting mode in
these tests - the real match is #71/#64 scope).

Expected values are taken from the spec, never recomputed the way the code
computes them.
"""
from typing import Any, cast


from polymerhus.attack.hunting.fault_source import (
    FaultEntry,
    delivered_candidates,
    evaluate,
    evaluate_unit,
    materialize_candidates,
    mint_candidates,
    select,
)
from polymerhus.attack.hunting.predicate import (
    Clause,
    ClauseForm,
    TypedPredicate,
)
from polymerhus.attack.hunting.unit_projection import (
    EdgeInfo,
    UnitProjection,
)

P_EXPOSURE = TypedPredicate(target="Service", clauses=(
    Clause(ClauseForm.SPINE_PRESENT, key="exposure"),))


def proj(unit_id: str = "Service:checkout", kind: str = "Service",
         spine: dict[str, str] | None = None,
         edges: dict[str, tuple[EdgeInfo, ...]] | None = None,
         data_edges: dict[str, int] | None = None,
         data_rel_kinds: frozenset[str] | None = None) -> UnitProjection:
    """A valid projection with the given facets overridden."""
    return UnitProjection(
        unit_id=unit_id,
        kind=kind,
        spine=spine or {},
        edges=edges or {},
        data_edges=data_edges or {},
        data_rel_kinds=data_rel_kinds if data_rel_kinds is not None else frozenset(),
    )


# --- C1: determinism and purity -----------------------------------------------

def test_evaluate_is_deterministic_and_pure():
    projection = proj(spine={"exposure": "public"})
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),
        Clause(ClauseForm.KIND_IS, values=("WAF",)),
    ))
    first = evaluate(predicate, projection)
    second = evaluate(predicate, projection)
    assert first == second
    assert first.verdict == "pass"  # exposure TRUE, kind-is UNKNOWN -> pass


def test_evaluate_never_calls_an_llm():
    # the stage takes no invoke_fn at all - the pure function has no I/O to inject
    projection = proj(spine={"exposure": "public"})
    assert evaluate(P_EXPOSURE, projection).verdict == "pass"


# --- C2: necessary-only FALSE -------------------------------------------------

def test_single_false_clause_yields_does_not_apply_with_that_witness():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),
        Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF",)),
    ))
    # exposure TRUE; kind present-and-contradicting (RESTApi != WAF) -> FALSE
    projection = proj(spine={"exposure": "public"}, kind="RESTApi")
    result = evaluate(predicate, projection)
    assert result.verdict == "does-not-apply"
    assert result.witness == 'spine-equals(kind, "WAF")'


# --- C3: default-open on unknown ----------------------------------------------

def test_absent_facet_passes_never_prunes():
    predicate = TypedPredicate(target="Service", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),))
    assert evaluate(predicate, proj(spine={})).verdict == "pass"


def test_unvalidated_kind_value_passes():
    # a Service's kind ("Service") is not a validated System kind -> UNKNOWN
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.KIND_IS, values=("WAF",)),))
    assert evaluate(predicate, proj(kind="Service")).verdict == "pass"


# --- C9/C11: composition - FALSE dominates, first-violator witness -------------

def test_false_dominates_unknown():
    predicate = TypedPredicate(target="Service", clauses=(
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),      # UNKNOWN
        Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF",)),  # FALSE
    ))
    result = evaluate(predicate, proj(kind="RESTApi"))
    assert result.verdict == "does-not-apply"
    assert result.witness == 'spine-equals(kind, "WAF")'  # the FALSE clause


def test_multi_false_witness_is_first_violating_clause_in_authoring_order():
    predicate = TypedPredicate(target="Service", clauses=(
        Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF",)),   # FALSE
        Clause(ClauseForm.SPINE_PRESENT, key="exposure"),               # TRUE
        Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("CDN",)),   # FALSE
    ))
    projection = proj(spine={"exposure": "public"}, kind="RESTApi")
    first = evaluate(predicate, projection)
    second = evaluate(predicate, projection)
    assert first.verdict == "does-not-apply"
    assert first.witness == 'spine-equals(kind, "WAF")'   # clause 1, never 3
    assert second == first                                # identical re-run


# --- C10: output domain is the binary prune signal -----------------------------

def test_output_domain_is_pass_or_does_not_apply_never_yellow():
    predicates = [
        (TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_PRESENT, key="exposure"),
            Clause(ClauseForm.KIND_IS, values=("WAF",)),)),      # TRUE + UNKNOWN
         proj(spine={"exposure": "public"}, kind="WAF")),        # -> pass
        (TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF",)),)),
         proj(kind="RESTApi")),                                  # FALSE -> pruned
        (TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.KIND_IS, values=("WAF",)),)),      # UNKNOWN
         proj(kind="Service")),                                  # -> pass
        (TypedPredicate(target="Both", clauses=(
            Clause(ClauseForm.SPINE_EQUALS, key="kind", values=("WAF",)),
            Clause(ClauseForm.SPINE_PRESENT, key="exposure"),)), # FALSE + TRUE
         proj(kind="RESTApi")),                                  # -> pruned
    ]
    for predicate, projection in predicates:
        result = evaluate(predicate, projection)
        assert result.verdict in ("pass", "does-not-apply")
        assert result.verdict != "insufficient-evidence"


# --- C12: family present vs absent ---------------------------------------------

def test_family_present_with_wrong_kind_is_false():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA", values=("GraphQLApi",)),))
    projection = proj(edges={"EXPOSED_VIA": (EdgeInfo("EXPOSED_VIA", "RESTApi"),)})
    result = evaluate(predicate, projection)
    assert result.verdict == "does-not-apply"
    assert result.witness == "reachable-via(EXPOSED_VIA, {GraphQLApi})"


def test_family_absent_is_unknown():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA", values=("GraphQLApi",)),))
    assert evaluate(predicate, proj(edges={})).verdict == "pass"


def test_family_present_with_matching_kind_is_true():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA", values=("GraphQLApi",)),))
    projection = proj(edges={"EXPOSED_VIA": (
        EdgeInfo("EXPOSED_VIA", "RESTApi"), EdgeInfo("EXPOSED_VIA", "GraphQLApi"))})
    assert evaluate(predicate, projection).verdict == "pass"


def test_role_constraint_is_presence_only():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.REACHABLE_VIA, key="AUTHORIZED_BY",
               values=("AuthorizationSystem",), role="admin"),))
    # edge present with the kind but NO role attribute -> role facet absent
    # family-wide -> UNKNOWN, never FALSE
    no_role = proj(edges={"AUTHORIZED_BY": (EdgeInfo("AUTHORIZED_BY", "AuthorizationSystem"),)})
    assert evaluate(predicate, no_role).verdict == "pass"
    # edge present with the kind AND the role attribute -> TRUE
    with_role = proj(edges={"AUTHORIZED_BY": (
        EdgeInfo("AUTHORIZED_BY", "AuthorizationSystem", role="admin"),)})
    assert evaluate(predicate, with_role).verdict == "pass"
    # family present, kind mismatch -> FALSE
    wrong_kind = proj(edges={"AUTHORIZED_BY": (
        EdgeInfo("AUTHORIZED_BY", "RESTApi", role="admin"),)})
    assert evaluate(predicate, wrong_kind).verdict == "does-not-apply"


# --- data axis -----------------------------------------------------------------

def test_data_edge_exist_present_true_absent_unknown():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.DATA_EDGE_EXISTS, key="CONSUMES"),))
    assert evaluate(predicate, proj(data_edges={"CONSUMES": 2})).verdict == "pass"
    assert evaluate(predicate, proj(data_edges={})).verdict == "pass"


def test_data_relationship_kind_semantics():
    predicate = TypedPredicate(target="Both", clauses=(
        Clause(ClauseForm.DATA_RELATIONSHIP_KIND, values=("derived_from",)),))
    # matching kind -> TRUE
    assert evaluate(predicate, proj(
        data_rel_kinds=frozenset({"DERIVED_FROM"}))).verdict == "pass"
    # validated kind present and contradicting -> FALSE
    result = evaluate(predicate, proj(data_rel_kinds=frozenset({"SUBSET_OF"})))
    assert result.verdict == "does-not-apply"
    assert result.witness == "data-relationship-kind({derived_from})"
    # no relationships at all -> UNKNOWN
    assert evaluate(predicate, proj(data_rel_kinds=frozenset())).verdict == "pass"


# --- C6: fail-open --------------------------------------------------------------

def test_malformed_projection_passes_with_diagnostic():
    malformed = cast(Any, UnitProjection)(unit_id="Service:x", kind=None, spine={},
                                          edges={}, data_edges={},
                                          data_rel_kinds=frozenset())
    result = evaluate(P_EXPOSURE, malformed)
    assert result.verdict == "pass"
    assert result.diagnostic


def test_none_projection_passes_with_diagnostic():
    result = evaluate(P_EXPOSURE, None)
    assert result.verdict == "pass"
    assert result.diagnostic


def test_evaluate_unit_reader_failure_passes_with_diagnostic():
    def boom(cypher, params):
        raise RuntimeError("neo4j is down")

    result = evaluate_unit(P_EXPOSURE, "Service:checkout", project_id="p",
                           read_fn=boom)
    assert result.verdict == "pass"
    assert result.diagnostic is not None
    assert "projection read failed" in result.diagnostic


def test_serves_units_with_is_inert_defensive_unknown():
    # unreachable through the validator (D3-unlanded); evaluate stays total
    predicate = TypedPredicate(target="System", clauses=(
        Clause(ClauseForm.SERVES_UNITS_WITH, key="exposure"),))
    assert evaluate(predicate, proj()).verdict == "pass"


# --- the selection entry -------------------------------------------------------

class FakeL1:
    """In-memory L1 model behind the read_fn seam (mirrors the projection tier)."""

    def __init__(self, units):
        self.units = units

    def __call__(self, cypher, params):
        if "type(dr) AS family" in cypher:
            unit = self.units.get(f"{params['kind']}:{params['key']}")
            return [{"family": f} for f in (unit or {}).get("data_rel_families", [])]
        unit = self.units.get(f"{params['kind']}:{params['key']}")
        if unit is None:
            return []
        return [{"labels": unit["labels"], "props": unit["props"],
                 "edges": unit.get("edges", [])}]


class CountingMatch:
    """The declared substitution for the LLM match (E1/E2/E3): pass-through
    counting mode - asserts only the invocation count, never verdicts."""

    def __init__(self):
        self.calls = []

    def __call__(self, unit_id, fault_id):
        self.calls.append((unit_id, fault_id))
        return True


def _model():
    return FakeL1({
        "Service:s1": {"labels": ["L1Service"],
                       "props": {"business_function_slug": "s1", "exposure": "public"},
                       "edges": [{"family": "EXPOSED_VIA", "tlabels": ["L1System"],
                                  "tprops": {"kind": "GraphQLApi"}, "rprops": {}}]},
        "Service:s3": {"labels": ["L1Service"],
                       "props": {"business_function_slug": "s3"},
                       "edges": [{"family": "EXPOSED_VIA", "tlabels": ["L1System"],
                                  "tprops": {"kind": "RESTApi"}, "rprops": {}}]},
        "GraphQLApi:__singleton__": {"labels": ["L1System"],
                                     "props": {"kind": "GraphQLApi",
                                               "discriminator": "__singleton__"},
                                     "edges": []},
        "Service:w6": {"labels": ["L1Service"],
                       "props": {"business_function_slug": "w6"},
                       "edges": [{"family": "EXPOSED_VIA", "tlabels": ["L1System"],
                                  "tprops": {"kind": "WAF"}, "rprops": {}}]},
        "WAF:__singleton__": {"labels": ["L1System"],
                              "props": {"kind": "WAF", "discriminator": "__singleton__"},
                              "edges": []},
    })


def _graphql_fault():
    return FaultEntry(fault_id="graphql-introspection",
                      predicate=TypedPredicate(target="Both", clauses=(
                          Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA",
                                 values=("GraphQLApi",)),)))


def test_mint_candidates_reads_only_the_target_declaration():
    units = ("Service:s1", "Service:s3", "GraphQLApi:__singleton__", "WAF:__singleton__")
    assert mint_candidates(_graphql_fault(), units) == units  # target Both
    assert mint_candidates(FaultEntry(fault_id="f",
                                      predicate=TypedPredicate(target="Service", clauses=(
                                          Clause(ClauseForm.SPINE_PRESENT, key="exposure"),))),
                           units) == ("Service:s1", "Service:s3")
    assert mint_candidates(FaultEntry(fault_id="f",
                                      predicate=TypedPredicate(target="System", clauses=(
                                          Clause(ClauseForm.KIND_IS, values=("WAF",)),))),
                           units) == ("GraphQLApi:__singleton__", "WAF:__singleton__")
    # an unhardened entry declares no direction -> both kinds, fail-open
    assert mint_candidates(FaultEntry(fault_id="f"), units) == units


def test_select_prunes_structurally_impossible_and_matches_only_passers():
    match = CountingMatch()
    reports = select((_graphql_fault(),), ("Service:s1", "Service:s3",
                                           "GraphQLApi:__singleton__"),
                     project_id="p", read_fn=_model(), match_fn=match)
    report = reports[0]
    assert report.fault_id == "graphql-introspection"
    assert report.predicates_evaluated == 3
    assert {o.unit_id: o.verdict for o in report.outcomes} == {
        "Service:s1": "passed",                     # TRUE
        "Service:s3": "pruned-by-predicate",        # FALSE
        "GraphQLApi:__singleton__": "passed",       # UNKNOWN (no outgoing edge)
    }
    s3 = [o for o in report.outcomes if o.unit_id == "Service:s3"][0]
    assert s3.witness == "reachable-via(EXPOSED_VIA, {GraphQLApi})"
    assert match.calls == [("Service:s1", "graphql-introspection"),
                           ("GraphQLApi:__singleton__", "graphql-introspection")]


def test_unhardened_entry_degrades_to_tag_then_default_open():
    tag_fault = FaultEntry(fault_id="waf-bypass", enum_kinds=frozenset({"WAF"}))
    match = CountingMatch()
    reports = select((tag_fault, FaultEntry(fault_id="untagged")),
                     ("Service:s1", "Service:s3", "Service:w6", "WAF:__singleton__"),
                     project_id="p", read_fn=_model(), match_fn=match)
    tag_report, open_report = reports
    assert {o.unit_id: o.verdict for o in tag_report.outcomes} == {
        "Service:s1": "pruned-by-tag",       # GraphQLApi-fronted, not WAF
        "Service:s3": "pruned-by-tag",       # not linked to a WAF System
        "Service:w6": "passed",              # WAF-fronted via EXPOSED_VIA
        "WAF:__singleton__": "passed",       # IS the presupposed System
    }
    assert tag_report.predicates_evaluated == 0  # the typed stage is inert
    assert all(o.verdict == "passed" for o in open_report.outcomes)
    assert match.calls == [("Service:w6", "waf-bypass"),
                           ("WAF:__singleton__", "waf-bypass"),
                           ("Service:s1", "untagged"), ("Service:s3", "untagged"),
                           ("Service:w6", "untagged"),
                           ("WAF:__singleton__", "untagged")]


def test_hardened_entry_never_consults_its_tag():
    # a hardened predicate that passes a unit the tag would prune: the tag is
    # retired for the entry (R-c)
    hardened = FaultEntry(fault_id="graphql",
                          enum_kinds=frozenset({"WAF"}),  # would prune s1
                          predicate=TypedPredicate(target="Both", clauses=(
                              Clause(ClauseForm.REACHABLE_VIA, key="EXPOSED_VIA",
                                     values=("GraphQLApi",)),)))
    report = select((hardened,), ("Service:s1",), project_id="p",
                    read_fn=_model(), match_fn=CountingMatch())[0]
    assert report.outcomes[0].verdict == "passed"


def test_select_is_fail_open_on_reader_failure():
    def boom(cypher, params):
        raise RuntimeError("down")

    match = CountingMatch()
    report = select((_graphql_fault(),), ("Service:s1",), project_id="p",
                    read_fn=boom, match_fn=match)[0]
    outcome = report.outcomes[0]
    assert outcome.verdict == "passed"      # never pruned on a bug
    assert outcome.diagnostic
    assert match.calls == [("Service:s1", "graphql-introspection")]


def test_select_outputs_are_deterministic():
    match = CountingMatch()
    first = select((_graphql_fault(),), ("Service:s3", "Service:s1"),
                   project_id="p", read_fn=_model(), match_fn=match)
    second = select((_graphql_fault(),), ("Service:s3", "Service:s1"),
                    project_id="p", read_fn=_model(), match_fn=CountingMatch())
    assert first == second
    assert first[0].outcomes[0].unit_id == "Service:s3"  # authoring order kept


# --- the production wiring seam (#200): the pure mapper -------------------------

def test_delivered_candidates_maps_passed_matched_to_applies():
    """The pure mapper (spec 4.1): a `passed` + `matched` outcome becomes one
    `DeliveredCandidate` with `match_verdict="applies"` and the deterministic
    witness, and its llm half stays None (a deterministic-only witness is a
    valid delivered candidate)."""
    from polymerhus.attack.hunting.fault_source import (
        FaultSelectionReport,
        UnitOutcome,
    )

    reports = (
        FaultSelectionReport(
            fault_id="graphql-introspection",
            outcomes=(
                UnitOutcome("Service:s1", "passed", matched=True),
                UnitOutcome("Service:s3", "passed", matched=True),
            ),
        ),
    )
    candidates = delivered_candidates(reports)
    assert [c.unit_id for c in candidates] == ["Service:s1", "Service:s3"]
    assert all(c.fault_class == "graphql-introspection" for c in candidates)
    assert all(c.match_verdict == "applies" for c in candidates)
    assert all(c.applies_witnesses.llm is None for c in candidates)
    assert all(c.applies_witnesses.deterministic for c in candidates)


def test_delivered_candidates_drops_pruned_and_unmatched_outcomes():
    """`pruned-by-predicate` / `pruned-by-tag` and a `passed` but NOT matched
    outcome produce no candidate (the prune signal is preserved)."""
    from polymerhus.attack.hunting.fault_source import (
        FaultSelectionReport,
        UnitOutcome,
    )

    reports = (
        FaultSelectionReport(
            fault_id="fault-x",
            outcomes=(
                UnitOutcome("Service:a", "pruned-by-predicate",
                            witness="reachable-via(EXPOSED_VIA, {GraphQLApi})"),
                UnitOutcome("Service:b", "pruned-by-tag"),
                UnitOutcome("Service:c", "passed", matched=False),
                UnitOutcome("Service:d", "passed", matched=True),
            ),
        ),
    )
    candidates = delivered_candidates(reports)
    assert [c.unit_id for c in candidates] == ["Service:d"]


def test_delivered_candidates_survivors_carry_the_deterministic_witness():
    """A passed outcome's deterministic half carries the outcome's diagnostic
    when present (the fail-open pass surfaces its diagnostic), else the pass
    marker - never a blank witness that the intake would drop as malformed."""
    from polymerhus.attack.hunting.fault_source import (
        FaultSelectionReport,
        UnitOutcome,
    )

    reports = (
        FaultSelectionReport(
            fault_id="fault-x",
            outcomes=(
                UnitOutcome("Service:a", "passed", matched=True,
                            diagnostic="projection read failed for Service:a"),
                UnitOutcome("Service:b", "passed", matched=True),
            ),
        ),
    )
    candidates = delivered_candidates(reports)
    by_unit = {c.unit_id: c for c in candidates}
    assert by_unit["Service:a"].applies_witnesses.deterministic == \
        "projection read failed for Service:a"
    assert by_unit["Service:b"].applies_witnesses.deterministic  # the pass marker


class InventoryL1(FakeL1):
    """Serves the L1 INVENTORY read (the `read_l1_inventory` cyphers) AND the
    per-unit projection reads (FakeL1's unit lookup)."""

    def __init__(self, units, *, services=(), systems=()):
        super().__init__(units)
        self.services = list(services)
        self.systems = list(systems)

    def __call__(self, cypher, params):
        if "L1TestableUnit" in cypher:
            return super().__call__(cypher, params)
        if "L1Service" in cypher:
            return [{"slug": s["slug"], "contract": s.get("contract")}
                    for s in self.services]
        if "L1System" in cypher:
            return [{"kind": s["kind"], "disc": s.get("disc", "__singleton__"),
                     "description": s.get("description")}
                    for s in self.systems]
        return []


def _inventory_model():
    """A fixture L1 with a linked Service+System (s1 fronted by a GraphQLApi
    System) plus an unlinked System and an unlinked Service."""
    return InventoryL1(
        {
            "Service:s1": {"labels": ["L1Service"],
                           "props": {"business_function_slug": "s1",
                                     "exposure": "public"},
                           "edges": [{"family": "EXPOSED_VIA",
                                      "tlabels": ["L1System"],
                                      "tprops": {"kind": "GraphQLApi"},
                                      "rprops": {}}]},
            "Service:s3": {"labels": ["L1Service"],
                           "props": {"business_function_slug": "s3"},
                           "edges": [{"family": "EXPOSED_VIA",
                                      "tlabels": ["L1System"],
                                      "tprops": {"kind": "RESTApi"},
                                      "rprops": {}}]},
            "GraphQLApi:__singleton__": {"labels": ["L1System"],
                                         "props": {"kind": "GraphQLApi",
                                                   "discriminator": "__singleton__"},
                                         "edges": []},
            "RESTApi:__singleton__": {"labels": ["L1System"],
                                      "props": {"kind": "RESTApi",
                                                "discriminator": "__singleton__"},
                                      "edges": []},
        },
        services=[{"slug": "s1"}, {"slug": "s3"}],
        systems=[{"kind": "GraphQLApi", "disc": "__singleton__"},
                 {"kind": "RESTApi", "disc": "__singleton__"}],
    )


def test_materialize_candidates_empty_batch_selects_over_the_live_l1():
    """#200: an empty caller batch triggers the platform's OWN selection: the
    project's units are enumerated from the L1 inventory, the matching fault
    is selected over them (the deterministic predicate prunes the unlinked
    Service), and the survivors map to the intake - never a vacuous set."""
    candidates, summary = materialize_candidates(
        "p", (), fault_entries=(_graphql_fault(),), read_fn=_inventory_model())
    assert [c.unit_id for c in candidates] == [
        "Service:s1",                      # GraphQLApi-fronted -> passed+matched
        "GraphQLApi:__singleton__",        # IS the presupposed System (UNKNOWN -> pass)
        "RESTApi:__singleton__",           # no outgoing edge (UNKNOWN -> pass)
    ]
    assert all(c.match_verdict == "applies" for c in candidates)
    assert all(c.fault_class == "graphql-introspection" for c in candidates)
    assert summary.caller_supplied is False
    assert summary.faults_evaluated == 1
    assert summary.units_minted == 4
    assert summary.pruned_by_predicate == 1
    assert summary.pruned_by_tag == 0
    assert summary.passed == 3


def test_materialize_candidates_enum_kinds_fault_prunes_unlinked_units():
    """The phase-1 enum-of-system-kinds tag prunes deterministically: a fault
    presupposing WAF Systems yields NO candidate when no unit is WAF-linked -
    the meaningful all-pruned empty selection."""
    waf_fault = FaultEntry(fault_id="waf-bypass", enum_kinds=frozenset({"WAF"}))
    candidates, summary = materialize_candidates(
        "p", (), fault_entries=(waf_fault,), read_fn=_inventory_model())
    assert candidates == ()
    assert summary.faults_evaluated == 1
    assert summary.units_minted == 4
    assert summary.pruned_by_tag == 4
    assert summary.passed == 0


def test_materialize_candidates_caller_batch_is_the_override():
    """A non-empty caller batch is returned unchanged - never re-selected (the
    harness / integration / eval seams still drive selection externally)."""
    from polymerhus.attack.hunting.hunt_orchestrator import (
        DeliveredCandidate,
        Witness,
    )
    caller = (
        DeliveredCandidate(
            unit_id="Service:caller", fault_class="caller-fault",
            applies_witnesses=Witness(deterministic="w", llm="w"),
            match_verdict="applies",
        ),
    )
    candidates, summary = materialize_candidates(
        "p", caller, fault_entries=(_graphql_fault(),), read_fn=_inventory_model())
    assert candidates == caller
    assert summary.caller_supplied is True
    assert summary.faults_evaluated == 0


def test_materialize_candidates_fails_open_to_an_empty_set():
    """A raising L1 read degrades to the empty candidate set - the selection
    seam never raises into the pass (fail-open). The inventory's own
    fail-open yields the empty enumeration, so the selection loop ran over the
    fault entries with zero units minted (the honest zeroed counts)."""
    def boom(cypher, params):
        raise RuntimeError("neo4j is down")

    candidates, summary = materialize_candidates(
        "p", (), fault_entries=(_graphql_fault(),), read_fn=boom)
    assert candidates == ()
    assert summary.faults_evaluated == 1  # the loop ran over the fault entry
    assert summary.units_minted == 0
    assert summary.passed == 0
