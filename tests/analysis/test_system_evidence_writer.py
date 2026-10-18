"""The system-evidence writer (ticket #354): the pure `build_system_evidence_cypher`
builder, the `enrich` write seam, and the proposal -> delta mapping.

The mechanism-typist grounds every System in observed evidence but never wrote the
cross-layer edge; before this the only `EVIDENCED_BY` producer was the reconcile
relabel remap. These are the pure-builder / fail-open-loop assertions (no driver);
the store-level MERGE behaviour is the integration tier.

Decisions the assertions encode: `docs/design/system-evidenced-by-decisions.md`.
"""
import pytest

from polymerhus.analysis import l1_curator
from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    SystemProposal,
    enrichment_proposals_to_deltas,
)
from polymerhus.analysis.l1_types import (
    L1_SINGLETON,
    L0Ref,
    Provenance,
    SystemEvidenceDelta,
)

PROV = Provenance(job="analyser:run-1", model="m", prompt_id="p")


def _header(name="sid", endpoint="/login", baseurl="https://a"):
    return L0Ref(label="Header", identity={"name": name, "endpoint": endpoint, "baseurl": baseurl})


def _evidence(kind="IdentificationSystem", *, discriminator=L1_SINGLETON, l0=None):
    return SystemEvidenceDelta(kind=kind, discriminator=discriminator,
                               l0=l0 or _header(), provenance=PROV)


def _recorder():
    """A `merge_fn` capture: the (cypher, params) pairs the writer dispatched."""
    calls: list[tuple[str, dict]] = []

    def merge_fn(cypher, params):
        calls.append((cypher, params))

    return calls, merge_fn


# --- AC1: a System carries one EVIDENCED_BY edge per witness -------------------

def test_one_evidenced_by_edge_per_witness():
    calls, merge_fn = _recorder()
    deltas = [
        _evidence(l0=_header("sid", "/login", "https://a")),
        _evidence(l0=L0Ref(label="Technology", identity={"name": "express-session", "version": ""})),
        _evidence(l0=L0Ref(label="Certificate", identity={"subject_cn": "a"})),
    ]
    counts = l1_curator.enrich("proj-1", system_evidence=deltas, merge_fn=merge_fn)

    assert counts["system_evidence"] == 3
    assert len(calls) == 3  # one statement per witness
    cy, params = calls[0]
    # the L0 target is MATCHed on its OWN key (L1D-2) and scoped to the project
    assert "MATCH (l0:Header {baseurl: $l0_baseurl, endpoint: $l0_endpoint, name: $l0_name, project_id: $project_id})" in cy
    # the System endpoint is MERGEd by identity, minting provenance ON CREATE only
    assert "MERGE (sy:L1TestableUnit:L1System {kind: $kind, discriminator: $discriminator, project_id: $project_id})" in cy
    assert "ON CREATE SET sy.prov_job = $prov_job, sy.first_seen = datetime()" in cy
    # the cross-layer edge itself, idempotent, provenance + timestamps only (no envelope)
    assert "MERGE (sy)-[r:EVIDENCED_BY]->(l0)" in cy
    assert "ON CREATE SET r.first_seen = datetime()" in cy
    assert "SET r.last_seen = datetime()" in cy
    assert "SET r.prov_job = $prov_job, r.prov_model = $prov_model, r.prov_prompt_id = $prov_prompt_id" in cy
    assert "status" not in params and "evidence_refs" not in params  # no judgment envelope
    assert params["project_id"] == "proj-1"          # the pending placeholder is overwritten
    assert params["l0_name"] == "sid" and params["l0_endpoint"] == "/login"
    assert params["l0_baseurl"] == "https://a"
    assert params["kind"] == "IdentificationSystem"
    assert params["discriminator"] == L1_SINGLETON
    assert params["prov_job"] == "analyser:run-1"
    # the other two witnesses hit their OWN labels
    assert "MATCH (l0:Technology {" in calls[1][0]
    assert "MATCH (l0:Certificate {" in calls[2][0]


def test_evidence_builder_is_deterministic_and_identity_order_independent():
    a = _evidence(l0=L0Ref(label="Header", identity={"name": "sid", "endpoint": "/login", "baseurl": "https://a"}))
    b = _evidence(l0=L0Ref(label="Header", identity={"baseurl": "https://a", "endpoint": "/login", "name": "sid"}))
    cy_a, _ = l1_curator.build_system_evidence_cypher(a)
    cy_b, _ = l1_curator.build_system_evidence_cypher(b)
    assert cy_a == cy_b  # sorted identity keys -> map order never changes the query


def test_discriminated_system_carries_its_own_witnesses():
    """A per-cluster WebPresentation (`<service>::<cluster>`) is not special-cased:
    its witnesses hang off the exact discriminated node."""
    cy, params = l1_curator.build_system_evidence_cypher(_evidence(
        kind="WebPresentation", discriminator="catalogue::home",
        l0=L0Ref(label="Endpoint", identity={"path": "/", "baseurl": "https://a"})))
    assert params["discriminator"] == "catalogue::home"
    assert "MATCH (l0:Endpoint {baseurl: $l0_baseurl, path: $l0_path, project_id: $project_id})" in cy


# --- AC2: a witness absent from L0 produces no edge and never a crash ----------

def test_an_absent_witness_is_a_no_op_never_a_fabricated_l0_node():
    """The L0 target is MATCH-only, so a witness the graph does not hold yields no
    row - hence no edge - and the statement can never mint an L0 node."""
    cy, _ = l1_curator.build_system_evidence_cypher(_evidence())
    assert "MATCH (l0:Header {" in cy
    assert "MERGE (l0" not in cy
    assert "CREATE (l0" not in cy


def test_an_unwritable_witness_is_skipped_and_the_batch_continues(caplog):
    """A witness label outside the allowlist (here an L0 label that is not evidence:
    a connectivity/fingerprint-but-not-surface record) is dropped item-wise; the
    batch keeps writing the witnesses that ARE valid, and nothing raises."""
    calls, merge_fn = _recorder()
    counts = l1_curator.enrich("p", system_evidence=[
        _evidence(l0=L0Ref(label="DNSRecord", identity={"name": "a"})),
        _evidence(l0=_header("cf-ray", "/", "https://a")),
    ], merge_fn=merge_fn)

    assert counts["system_evidence"] == 1
    assert len(calls) == 1 and "MATCH (l0:Header {" in calls[0][0]


def test_an_unsafe_or_unknown_witness_raises_in_the_builder():
    with pytest.raises(ValueError):  # Cypher-injection guard on the interpolated label
        l1_curator.build_system_evidence_cypher(_evidence(
            l0=L0Ref(label="Header) DETACH DELETE n //", identity={"name": "x"})))
    with pytest.raises(ValueError):  # empty identity map
        l1_curator.build_system_evidence_cypher(_evidence(l0=L0Ref(label="Header", identity={})))
    with pytest.raises(ValueError):  # null identity value
        l1_curator.build_system_evidence_cypher(_evidence(
            l0=L0Ref(label="Header", identity={"name": "x", "baseurl": None})))
    with pytest.raises(ValueError):  # unknown System kind (typo guard, as every writer)
        l1_curator.build_system_evidence_cypher(_evidence(kind="NotAKind"))


def test_a_blank_discriminator_is_coerced_to_the_singleton_sentinel():
    cy, params = l1_curator.build_system_evidence_cypher(
        _evidence(discriminator="   "))
    assert params["discriminator"] == L1_SINGLETON


def test_a_merge_failure_degrades_fail_open(caplog):
    def boom(cypher, params):
        raise RuntimeError("neo4j down")

    counts = l1_curator.enrich("p", system_evidence=[_evidence()], merge_fn=boom)
    assert counts["system_evidence"] == 0  # degraded, never raised


# --- AC2 (proposal side): a no-witness claim stays edgeless --------------------

def test_a_system_with_no_witness_produces_no_evidence_statement():
    batch = L1DeltaBatch(systems=[SystemProposal(kind="RESTApi", props={"description": "a REST surface"})])
    deltas = enrichment_proposals_to_deltas(batch, PROV)
    assert deltas["system_evidence"] == []

    calls, merge_fn = _recorder()
    l1_curator.enrich("p", **deltas, merge_fn=merge_fn)
    assert calls == []  # the System is still written by the core path; no edge is attempted


def test_evidence_proposals_map_to_deltas_with_system_provenance():
    """The LLM names the witness; the curate boundary stamps provenance, exactly as
    the edge mapping does - the proposer can never set it."""
    batch = L1DeltaBatch(systems=[SystemProposal(
        kind="CDN", evidence=[_header("cf-ray", "/", "https://a")])])
    (delta,) = enrichment_proposals_to_deltas(batch, PROV)["system_evidence"]
    assert (delta.kind, delta.discriminator) == ("CDN", L1_SINGLETON)
    assert delta.l0.label == "Header" and delta.l0.identity["name"] == "cf-ray"
    assert delta.provenance is PROV
    assert "provenance" not in SystemProposal.model_fields


def test_every_witness_of_a_multi_witness_system_is_mapped():
    batch = L1DeltaBatch(systems=[SystemProposal(kind="AuthenticationMechanism", evidence=[
        _header("www-authenticate", "/api", "https://a"),
        L0Ref(label="Technology", identity={"name": "Keycloak", "version": ""}),
    ])])
    deltas = enrichment_proposals_to_deltas(batch, PROV)["system_evidence"]
    assert [d.l0.label for d in deltas] == ["Header", "Technology"]


# --- AC3: the relabel remap path is unchanged ---------------------------------

def test_the_relabel_remap_path_still_produces_evidenced_by():
    assert l1_curator._RELABEL_EDGE_REMAP == {("L1Service", "L1System"): {"AGGREGATES": "EVIDENCED_BY"}}
    assert "EVIDENCED_BY" in l1_curator._REPOINT_REL_TYPES
    cy, _ = l1_curator.build_relabel_unit_cypher(
        "L1Service", "L1System", {"business_function_slug": "s"}, {"kind": "RESTApi"}, PROV)
    assert "MATCH (n)-[r:AGGREGATES]->(x) MERGE (n)-[nr:EVIDENCED_BY]->(x)" in cy


# --- the witness-label allowlist ----------------------------------------------

def test_the_witness_label_allowlist_is_the_surfaced_fingerprint_family():
    """Single source of truth: the kinds a mechanism fingerprint can be observed ON.
    The connectivity types are deliberately absent (the chunk FILTER drops them), as
    are Parameter and Secret."""
    assert l1_curator.EVIDENCE_L0_LABELS == (
        "Endpoint", "BaseURL", "Header", "Technology", "Certificate")
