from polymerhus.lightrag.query_spec import (
    QuerySpecV1,
    R_A,
    R_B,
    build_q3,
    build_retrieval_payload,
    derive_keywords,
    sha256_hex,
)


def _spec() -> QuerySpecV1:
    return QuerySpecV1(
        scenario_id="SIM-01",
        attack_goal="Identify a bounded authorization-boundary comparison hypothesis",
        concern="GraphQL and REST object-level authorization",
        technology_stack=["HTTP JSON API", "GraphQL"],
        target_refs=["component:account-api", "surface:graphql"],
        input_vectors=["GraphQL object identifier", "REST path object identifier"],
        known_facts=[
            "GraphQL introspection is visible",
            "Object identifiers are client supplied",
        ],
        acceptable_technique_families=[
            "Object-level authorization comparison",
            "GraphQL authorization review",
        ],
    )


def test_build_q3_matches_phase6b_evidence_template():
    assert build_q3(_spec()) == (
        "Identify a bounded authorization-boundary comparison hypothesis "
        "Fields: target=component:account-api,surface:graphql | "
        "technology=HTTP JSON API,GraphQL | "
        "concern=GraphQL and REST object-level authorization | "
        "vectors=GraphQL object identifier,REST path object identifier"
    )


def test_derive_keywords_is_deterministic_and_bounded():
    keywords = derive_keywords(_spec())
    assert keywords == derive_keywords(_spec())
    assert len(keywords["hl"]) <= 8
    assert len(keywords["ll"]) <= 8
    assert "graphql" in keywords["hl"]


def test_r_a_payload_omits_graph_knobs():
    payload = build_retrieval_payload(_spec(), R_A)
    assert payload["mode"] == "naive"
    assert payload["chunk_top_k"] == 20
    assert payload["max_total_tokens"] == 8000
    assert "top_k" not in payload
    assert "hl_keywords" not in payload


def test_r_b_payload_includes_keywords_and_top_k():
    payload = build_retrieval_payload(_spec(), R_B)
    assert payload["mode"] == "mix"
    assert payload["top_k"] == 20
    assert payload["chunk_top_k"] == 10
    assert payload["max_total_tokens"] == 16000
    assert payload["hl_keywords"]
    assert payload["ll_keywords"]


def test_query_hash_is_stable():
    spec = _spec()
    first = sha256_hex({"scenario_id": spec.scenario_id, "query": build_q3(spec)})
    second = sha256_hex({"scenario_id": spec.scenario_id, "query": build_q3(spec)})
    assert first == second
    assert len(first) == 64
