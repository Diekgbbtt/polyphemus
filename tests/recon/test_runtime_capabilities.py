"""#238 A9 - the controller-side Kali runtime-capability negotiation."""
from __future__ import annotations

from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.runtime_capabilities import (
    EXPECTED_FFUF_WORDLIST_COUNT,
    EXPECTED_VEGETA_VERSION,
    FFUF_WORDLIST_PATH,
    RuntimeCapabilities,
)


def _compatible() -> RuntimeCapabilities:
    return RuntimeCapabilities(
        governor_enabled=True,
        supported_policy_versions=("traffic-policy/v2",),
        vegeta_version=EXPECTED_VEGETA_VERSION,
        ffuf_wordlist_count=EXPECTED_FFUF_WORDLIST_COUNT,
        build_revision="abc123",
    )


def test_a_compatible_runtime_has_no_error():
    assert _compatible().compatibility_error() is None


def test_each_missing_capability_is_incompatible():
    assert _compatible().model_copy(
        update={"governor_enabled": False}).compatibility_error() == "governor_disabled"
    assert _compatible().model_copy(
        update={"supported_policy_versions": ("traffic-policy/v1",)}
    ).compatibility_error() == "policy_version"
    assert _compatible().model_copy(
        update={"vegeta_version": "v12.12.0"}).compatibility_error() == "vegeta_version"
    assert _compatible().model_copy(
        update={"vegeta_version": None}).compatibility_error() == "vegeta_version"
    assert _compatible().model_copy(
        update={"ffuf_wordlist_count": 4752}
    ).compatibility_error() == "ffuf_wordlist_cardinality"


def test_from_proxy_status_parses_the_live_shape():
    payload = {
        "ok": True,
        "traffic_governor": {
            "governor_enabled": True,
            "capture_enabled": True,
            "supported_policy_versions": ["traffic-policy/v2"],
        },
        "build": {"revision": "deadbeef", "vegeta_version": EXPECTED_VEGETA_VERSION},
        "wordlists": {FFUF_WORDLIST_PATH: EXPECTED_FFUF_WORDLIST_COUNT},
    }
    caps = RuntimeCapabilities.from_proxy_status(payload)
    assert caps.compatibility_error() is None
    assert caps.build_revision == "deadbeef"


def test_a_malformed_payload_degrades_to_incompatible():
    assert RuntimeCapabilities.from_proxy_status(None).compatibility_error() is not None
    assert RuntimeCapabilities.from_proxy_status({}).compatibility_error() is not None


def test_the_expected_wordlist_count_matches_the_ffuf_job_cost():
    """The readiness constant the controller verifies must equal the ffuf
    JobSpec's declared per-input request cost, or the admission arithmetic
    disagrees with the image."""
    assert JOBS["ffuf"].traffic_cost.estimated_requests_per_input == (
        EXPECTED_FFUF_WORDLIST_COUNT
    )


def test_controller_capability_constants_mirror_the_kali_side():
    """The controller mirrors the Kali constants deliberately; they must not
    drift, or the negotiation would refuse a compatible image (or accept an
    incompatible one)."""
    from kali.http_history import capabilities as kali_caps

    assert EXPECTED_VEGETA_VERSION == kali_caps.EXPECTED_VEGETA_VERSION
    assert FFUF_WORDLIST_PATH == kali_caps.FFUF_WORDLIST_PATH
