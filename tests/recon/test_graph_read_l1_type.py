"""WI-1 (viz): the graph formatter must distinguish L1 nodes.

L1 units are multi-label (`:L1TestableUnit:L1Service`) and Neo4j returns labels
in an unspecified order, so the old `labels[0]` type-resolution could surface the
generic supertype - making every L1 node read as one type (and one grey colour)
in the frontend. `primary_label` fixes this by preferring the specific subtype,
and `node_name` names L1 units by their identity slug instead of a bare label.
"""
from agent.recon.graph_read import node_name, primary_label


def test_primary_label_prefers_l1_subtype_over_supertype():
    # order-independent: the subtype wins regardless of Neo4j's label ordering
    assert primary_label(["L1TestableUnit", "L1Service"]) == "L1Service"
    assert primary_label(["L1Service", "L1TestableUnit"]) == "L1Service"
    assert primary_label(["L1TestableUnit", "L1System"]) == "L1System"
    assert primary_label(["L1DataItem", "L1TestableUnit"]) == "L1DataItem"


def test_primary_label_l0_single_label_and_empty():
    assert primary_label(["Endpoint"]) == "Endpoint"
    assert primary_label([]) == "Unknown"
    assert primary_label(None) == "Unknown"


def test_node_name_service_uses_business_slug():
    assert node_name(["L1TestableUnit", "L1Service"], {"business_function_slug": "sign-in"}) == "sign-in"


def test_node_name_system_shows_kind_and_only_nonsingleton_discriminator():
    assert node_name(["L1System", "L1TestableUnit"], {"kind": "CDN", "discriminator": "Datadome"}) == "CDN:Datadome"
    # a singleton system shows just its kind (the sentinel is not display noise)
    assert node_name(["L1System"], {"kind": "RESTApi", "discriminator": "__singleton__"}) == "RESTApi"
    assert node_name(["L1System"], {"kind": "AuthorizationSystem"}) == "AuthorizationSystem"


def test_node_name_dataitem_uses_item_key():
    assert node_name(["L1DataItem"], {"item_key": "shopping_basket"}) == "shopping_basket"


def test_node_name_l0_endpoint_unchanged():
    assert node_name(["Endpoint"], {"path": "/api/Cards", "method": "GET"}) == "/api/Cards"
