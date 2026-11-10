"""The checkpoint serde allow-list carries every persisted structured envelope.

Under `LANGGRAPH_STRICT_MSGPACK=true` an unlisted type is BLOCKED at load and
silently degrades to a plain `dict` - the pydantic entity loses its type on a
resumed turn. The arm L white-jotter trials surfaced the gap in production for
every envelope below (each logged `Blocked deserialization ...`), so each must
round-trip through the ONE serde (`app.llm.checkpoints.checkpoint_serde`).

Unit tier: no model, no database - the real classes and the real serde.
"""
from __future__ import annotations

import importlib

import pytest

from polymerhus.app.llm import checkpoints as C

# The envelopes observed blocked in the arm L white-jotter trials (2026-10-19),
# as `(module, name)` exactly as the loader names them.
ENVELOPES = (
    ("polymerhus.analysis.analyser_types", "L1DeltaBatch"),
    ("polymerhus.recon.control.authn_loop", "GatewayVerdict"),
    ("polymerhus.recon.domain.pod", "_ObservationBatch"),
    ("polymerhus.attack.hunting.pod.agents", "TriagerDecision"),
)


def test_every_observed_envelope_is_listed() -> None:
    listed = set(C._ALLOWED_MSGPACK_MODULES)
    missing = [entry for entry in ENVELOPES if entry not in listed]
    assert missing == [], f"not allow-listed: {missing}"


def test_the_component_envelopes_round_trip() -> None:
    from polymerhus.analysis.analyser_types import (
        Aggregation,
        AssignerDelta,
        BaseURLWitness,
        CertificateWitness,
        EndpointRef,
        EndpointWitness,
        HeaderWitness,
        SystemAttributes,
        SystemDefinition,
        SystemExtraction,
        SystemLink,
        SystemLinking,
        TechnologyWitness,
    )

    objects = [
        Aggregation(
            service="checkout",
            endpoints=[EndpointRef(method="GET", path="/x", baseurl="https://a")],
            evidence="path segment /x",
        ),
        AssignerDelta(aggregations=[]),
        SystemAttributes(description="a mechanism"),
        SystemDefinition(
            kind="ReverseProxy",
            attributes=SystemAttributes(description="nginx"),
            evidence=[
                EndpointWitness(method="GET", path="/", baseurl="https://a"),
                HeaderWitness(name="Server", endpoint="/", baseurl="https://a"),
                TechnologyWitness(name="nginx", version="1.31.6"),
                CertificateWitness(subject_cn="a.example"),
                BaseURLWitness(url="https://a"),
            ],
        ),
        SystemExtraction(systems=[]),
        SystemLink(service="checkout", kind="ReverseProxy", relation="FRONTED_BY"),
        SystemLinking(links=[]),
    ]
    serde = C.checkpoint_serde()
    for obj in objects:
        loaded = serde.loads_typed(serde.dumps_typed(obj))
        assert isinstance(loaded, type(obj)), (
            f"{type(obj).__name__} loaded as {type(loaded).__name__}; "
            f"the allow-list is missing it"
        )


@pytest.mark.parametrize("module,name", ENVELOPES)
def test_each_envelope_round_trips_through_the_one_serde(module: str, name: str) -> None:
    cls = getattr(importlib.import_module(module), name)
    serde = C.checkpoint_serde()
    loaded = serde.loads_typed(serde.dumps_typed(cls()))
    assert isinstance(loaded, cls), (
        f"{module}.{name} loaded as {type(loaded).__name__}; "
        f"the allow-list is missing it"
    )
