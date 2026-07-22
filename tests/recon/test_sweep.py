"""FR-SWEEP unit tier — the derived sweep queries with an injected read_fn
(no live DB). Store-level correctness is the integration tier
(tests/integration/test_sweep_merge.py).
"""
import pytest

from agent.recon.analysis import sweep


def test_stale_pool_query_shape_and_label_filter():
    captured = {}

    def fake_read(cy, params):
        captured["cy"] = cy
        captured["params"] = params
        return [{"props": {"path": "/healthz", "method": "GET"}}]

    rows = sweep.stale_pool("proj-1", read_fn=fake_read)
    assert "MATCH (n:Endpoint)" in captured["cy"]
    assert "NOT ( (:L1Service)-[:AGGREGATES]->(n) )" in captured["cy"]
    assert captured["params"] == {"project_id": "proj-1"}
    assert rows == [{"path": "/healthz", "method": "GET", "_label": "Endpoint"}]


def test_stale_pool_widened_labels():
    seen_labels = []

    def fake_read(cy, params):
        # record which label each query targeted
        for lbl in ("Endpoint", "Parameter"):
            if f"MATCH (n:{lbl})" in cy:
                seen_labels.append(lbl)
        return []

    sweep.stale_pool("proj-1", labels=("Endpoint", "Parameter"), read_fn=fake_read)
    assert seen_labels == ["Endpoint", "Parameter"]


def test_stale_pool_rejects_unsafe_label():
    with pytest.raises(ValueError):
        sweep.stale_pool("proj-1", labels=("Endpoint) DETACH DELETE n //",), read_fn=lambda cy, p: [])
    # a trailing newline must NOT slip past the guard (\Z, not $)
    with pytest.raises(ValueError):
        sweep.stale_pool("proj-1", labels=("Endpoint\n",), read_fn=lambda cy, p: [])


def test_stale_pool_count_sums_labels():
    def fake_read(cy, params):
        return [{"c": 7}]

    assert sweep.stale_pool_count("proj-1", labels=("Endpoint", "Parameter"), read_fn=fake_read) == 14


def test_default_assignable_labels_is_endpoint():
    assert sweep.DEFAULT_ASSIGNABLE_LABELS == ("Endpoint",)
