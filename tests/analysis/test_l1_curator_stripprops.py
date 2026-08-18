"""FR-TYPESEP-b prop-strip tier: the L1 sole-writer's `build_strip_props_cypher`
pure builder + the impure `strip_props` fail-open loop (no driver, no live Neo4j).

The prop-strip is the second leg of the re-homing backstop (FR-TYPESEP-b): once a
spine fact wrongly set on a Service is re-homed to the correct System edge, the
stale Service prop is removed. Because a prop removal is an `:L1*` write, the
sole-writer discipline forces it to live here in `l1_curator`, not in curation.py.

Each test names the assertion it encodes (docs/design/
post-recon-curation-and-l1-remediation-plan.md §5 FR-TYPESEP-b).
"""
import pytest

from polymerhus.analysis import l1_curator
from polymerhus.analysis.l1_types import Provenance, StripPropsOp

PROV = Provenance(job="curation", model="m", prompt_id="p")


# --- AST-TYPE-02 (builder): strip removes the named non-identity props + stamps prov ---

def test_build_strip_props_cypher_removes_keys_and_stamps_prov():
    cy, params = l1_curator.build_strip_props_cypher(
        "L1Service", {"business_function_slug": "checkout"},
        ["rendering_model", "api_paradigm"], PROV,
    )
    # MATCH by identity: key interpolated, VALUE parameterised
    assert "MATCH (n:L1Service {business_function_slug: $id_business_function_slug, project_id: $project_id})" in cy
    # REMOVE each prop, sorted + deduped
    assert "REMOVE n.api_paradigm, n.rendering_model" in cy
    # provenance + last_seen stamped
    assert "SET n.last_seen = datetime()" in cy
    assert "SET n.prov_job = $prov_job, n.prov_model = $prov_model, n.prov_prompt_id = $prov_prompt_id" in cy
    assert params["id_business_function_slug"] == "checkout"
    assert params["prov_job"] == "curation"
    # pure + deterministic
    cy2, _ = l1_curator.build_strip_props_cypher(
        "L1Service", {"business_function_slug": "checkout"}, ["rendering_model", "api_paradigm"], PROV
    )
    assert cy == cy2


def test_build_strip_props_dedups_keys():
    cy, _ = l1_curator.build_strip_props_cypher(
        "L1System", {"kind": "WAF", "discriminator": "__singleton__"},
        ["exposure", "exposure"], PROV,
    )
    assert cy.count("n.exposure") == 1  # deduped, not removed twice


# --- AST-TYPE-02 (guard): never strip an identity/reserved key or an unsafe key ---

def test_build_strip_props_rejects_reserved_identity_and_unsafe_keys():
    # identity + curator-managed keys must never be stripped (they would orphan/spoof)
    for reserved in ("business_function_slug", "project_id", "kind",
                     "discriminator", "prov_job", "first_seen", "last_seen"):
        with pytest.raises(ValueError):
            l1_curator.build_strip_props_cypher(
                "L1Service", {"business_function_slug": "s"}, [reserved], PROV
            )
    # a Cypher-injection attempt in the prop key is rejected
    with pytest.raises(ValueError):
        l1_curator.build_strip_props_cypher(
            "L1Service", {"business_function_slug": "s"}, ["x REMOVE n //"], PROV
        )
    # empty prop-key set is rejected (nothing to strip)
    with pytest.raises(ValueError):
        l1_curator.build_strip_props_cypher("L1Service", {"business_function_slug": "s"}, [], PROV)


def test_build_strip_props_rejects_non_l1_label():
    # the label guard is what keeps a strip from ever touching an L0 node
    for l0_label in ("Endpoint", "Parameter", "Header", "Service"):
        with pytest.raises(ValueError):
            l1_curator.build_strip_props_cypher(l0_label, {"path": "/x"}, ["rendering_model"], PROV)
    # L1DataItem is not an operative unit label for a spine-prop strip either
    with pytest.raises(ValueError):
        l1_curator.build_strip_props_cypher("L1DataItem", {"item_key": "k"}, ["x"], PROV)


# --- AST-TYPE-02 (behavior): strip_props is fail-open per op + project-scoped ---

def test_strip_props_fail_open_and_project_scoped():
    calls = []
    ops = [
        StripPropsOp(label="L1Service", identity={"business_function_slug": "a"},
                     prop_keys=["rendering_model"], provenance=PROV),
        StripPropsOp(label="Endpoint", identity={"path": "/x"},
                     prop_keys=["rendering_model"], provenance=PROV),  # non-L1 -> skipped at build
        StripPropsOp(label="L1Service", identity={"business_function_slug": "b"},
                     prop_keys=["project_id"], provenance=PROV),  # reserved key -> skipped at build
    ]
    n = l1_curator.strip_props("proj1", ops, merge_fn=lambda cy, p: calls.append(p))
    assert n == 1  # only the one valid op executed
    assert len(calls) == 1
    assert calls[0]["project_id"] == "proj1"


def test_strip_props_merge_fn_exception_does_not_abort_batch():
    seen = []

    def flaky(cy, p):
        seen.append(p)
        if p.get("id_business_function_slug") == "boom":
            raise RuntimeError("db blip")

    ops = [
        StripPropsOp(label="L1Service", identity={"business_function_slug": "boom"},
                     prop_keys=["rendering_model"], provenance=PROV),  # merge_fn raises
        StripPropsOp(label="L1Service", identity={"business_function_slug": "ok"},
                     prop_keys=["rendering_model"], provenance=PROV),  # succeeds
    ]
    n = l1_curator.strip_props("proj1", ops, merge_fn=flaky)
    assert n == 1
    assert len(seen) == 2  # both attempted; one failed without aborting the batch
