"""Task 5 (#238 follow-up): the typed mutation materialization and its lossless
transport across the controller -> Kali seam.

The gap this pins: `ExperimentSpec.variant` used to be DROPPED by
`kali_spec_payload`, so a production variant probe silently replayed the
canonical request while the evidence claimed a mutation. These tests fail if the
variant is discarded again.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from kali.rate_limit.models import KaliExperimentSpec
from polymerhus.recon.control.rate_limit_runner import kali_spec_payload
from polymerhus.recon.control.request_mutation import (
    CanonicalRequest,
    apply_mutation,
)
from polymerhus.recon.domain.rate_limit import (
    BodyMutation,
    ExperimentSpec,
    HeaderMutation,
    MutationSpec,
    PathMutation,
    QueryMutation,
)

CANONICAL_URL = "https://app.test/search?q=base"


# --- pure materialization ----------------------------------------------------


def test_no_mutation_is_the_identity_and_leaves_the_canonical_untouched():
    canonical = CanonicalRequest(
        method="GET", url=CANONICAL_URL, headers=(("Accept", "application/json"),)
    )
    effective = apply_mutation(canonical, None)
    assert effective.url == CANONICAL_URL
    assert effective.headers == {"Accept": "application/json"}
    assert effective.mutation_id == "canonical"
    assert canonical.url.endswith("q=base")


def test_query_variant_changes_the_effective_url_without_mutating_canonical():
    canonical = CanonicalRequest(method="GET", url=CANONICAL_URL, headers=())
    effective = apply_mutation(
        canonical, QueryMutation(name="q", value="a b", mutation_id="m1")
    )
    assert effective.url == "https://app.test/search?q=a+b"
    assert canonical.url.endswith("q=base")
    assert effective.mutation_id == "m1"


def test_query_add_keeps_the_canonical_parameter():
    canonical = CanonicalRequest(method="GET", url=CANONICAL_URL, headers=())
    effective = apply_mutation(
        canonical, QueryMutation(name="q", value="extra", replace=False, mutation_id="m2")
    )
    assert effective.url == "https://app.test/search?q=base&q=extra"


def test_path_variant_preserves_the_origin():
    canonical = CanonicalRequest(method="GET", url="https://app.test/api/search", headers=())
    effective = apply_mutation(canonical, PathMutation(suffix="/", mutation_id="m3"))
    assert effective.url == "https://app.test/api/search/"


def test_header_replace_and_add():
    canonical = CanonicalRequest(
        method="GET", url=CANONICAL_URL, headers=(("Accept", "application/json"),)
    )
    replaced = apply_mutation(
        canonical, HeaderMutation(name="Accept", value="text/html", mutation_id="h1")
    )
    assert replaced.headers["Accept"] == "text/html"
    added = apply_mutation(
        canonical,
        HeaderMutation(
            name="Accept", value="text/plain", replace=False, mutation_id="h2"
        ),
    )
    assert added.headers["Accept"] == "application/json, text/plain"
    # The canonical request is immutable.
    assert canonical.headers == (("Accept", "application/json"),)


def test_body_variant_replaces_the_body_reference_only():
    canonical = CanonicalRequest(
        method="POST", url=CANONICAL_URL, headers=(), body_ref="rate-artifact/v1:p/r/old"
    )
    effective = apply_mutation(
        canonical, BodyMutation(body_ref="rate-artifact/v1:p/r/new", mutation_id="b1")
    )
    assert effective.body_ref == "rate-artifact/v1:p/r/new"
    assert canonical.body_ref == "rate-artifact/v1:p/r/old"


def test_a_mutation_cannot_change_the_origin():
    canonical = CanonicalRequest(method="GET", url=CANONICAL_URL, headers=())
    with pytest.raises((ValidationError, ValueError)):
        apply_mutation(canonical, PathMutation(suffix="/../..", mutation_id="x"))
    with pytest.raises(ValueError):
        apply_mutation(canonical, HeaderMutation(name="Host", value="evil.test", mutation_id="h"))


def test_a_path_suffix_cannot_carry_a_scheme():
    with pytest.raises(ValidationError):
        PathMutation(suffix="://evil.test/", mutation_id="x")


# --- cross-boundary transport -------------------------------------------------


@pytest.mark.parametrize(
    "mutation,expected_url,expected_mutation_id",
    [
        (None, CANONICAL_URL, "canonical"),
        (QueryMutation(name="q", value="a b", mutation_id="v1"), "https://app.test/search?q=a+b", "v1"),
        (PathMutation(suffix="/", mutation_id="v2"), "https://app.test/search/?q=base", "v2"),
    ],
)
def test_the_effective_request_crosses_the_seam_verbatim(
    mutation, expected_url, expected_mutation_id
):
    spec = ExperimentSpec(
        experiment_id="exp-1",
        phase="steady",
        url=CANONICAL_URL,
        method="GET",
        headers={"Accept": "application/json"},
        rate_per_s=5.0,
        duration_s=2.0,
        requests=10,
        variant=(
            MutationSpec(
                variant_id=expected_mutation_id,
                family="endpoint-shape",
                payload=mutation,
            )
            if mutation is not None
            else None
        ),
    )

    payload = kali_spec_payload(spec, project_id="p", run_id="r")
    kali_spec = KaliExperimentSpec.model_validate(payload)

    assert kali_spec.effective_request.url == expected_url
    assert kali_spec.effective_request.mutation_id == expected_mutation_id
    target = kali_spec.vegeta_target()
    assert target["url"] == expected_url

    # Adversarial: a payload that drops `effective_request` is refused.
    without = {k: v for k, v in payload.items() if k != "effective_request"}
    with pytest.raises(ValidationError):
        KaliExperimentSpec.model_validate(without)

    # Adversarial: the canonical request is NOT what reaches the target when a
    # mutation was admitted.
    if mutation is not None:
        assert kali_spec.effective_request.url != spec.url


def test_a_header_variant_reaches_the_target_as_a_list_valued_header():
    spec = ExperimentSpec(
        experiment_id="exp-h", phase="steady", url=CANONICAL_URL,
        headers={"Accept": "application/json"}, rate_per_s=5.0, duration_s=2.0,
        requests=10,
        variant=MutationSpec(
            variant_id="hdr", family="parameter-carrier",
            payload=HeaderMutation(name="Accept", value="text/html", mutation_id="hdr"),
        ),
    )
    payload = kali_spec_payload(spec, project_id="p", run_id="r")
    kali_spec = KaliExperimentSpec.model_validate(payload)
    assert kali_spec.vegeta_target()["header"] == {"Accept": ["text/html"]}


def test_the_model_facing_mutation_cannot_carry_traffic_numbers():
    for field in ("rate_per_s", "max_concurrency", "budget", "requests"):
        with pytest.raises(ValidationError):
            QueryMutation(name="q", value="v", mutation_id="m", **{field: 1})


# --- the adversarial regression gate (#238 Task 11) -------------------------------


def test_variant_reaches_target_request():
    """Kills: "serialize the canonical request instead of the `variant`".

    The regression is subtle and was real: the payload still carried the
    experiment, the manifest still named the variant, and the evidence still
    claimed a bypass - while the request that reached the target was the
    canonical one. The assertion is therefore on the TARGET-BOUND request
    (`vegeta_target()`), not on the spec that described it.
    """
    variant = MutationSpec(
        variant_id="e2e-endpoint-shape-1",
        family="endpoint-shape",
        payload=PathMutation(mutation_id="e2e-path-1", suffix="/alt"),
    )
    spec = ExperimentSpec(
        experiment_id="exp-variant", phase="steady", url=CANONICAL_URL,
        method="GET", headers={"Accept": "application/json"},
        rate_per_s=5.0, duration_s=2.0, requests=10, variant=variant,
    )

    payload = kali_spec_payload(spec, project_id="p", run_id="r")
    kali_spec = KaliExperimentSpec.model_validate(payload)
    target = kali_spec.vegeta_target()

    # The EFFECTIVE request names the transported mutation (the payload's own
    # id), not merely the variant that motivated it.
    assert kali_spec.effective_request.mutation_id == "e2e-path-1"
    assert target["url"] != CANONICAL_URL, (
        "the canonical request reached the target even though a variant was "
        "admitted: the evidence would have certified a bypass that never happened"
    )
    assert target["url"] == kali_spec.effective_request.url
