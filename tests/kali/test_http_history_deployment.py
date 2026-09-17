"""#196 deployment shape: compose service, env config, healthcheck."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml


def _compose() -> dict:
    proc = subprocess.run(
        ["docker", "compose", "config"], capture_output=True, text=True, cwd=".", check=False
    )
    if proc.returncode != 0:
        pytest.skip(f"docker compose config unavailable: {proc.stderr.strip()[:200]}")
    return yaml.safe_load(proc.stdout)


def test_kali_mounts_the_kali_tree_and_the_history_volume():
    kali = _compose()["services"]["kali"]
    mounts = {
        v["target"]: v["source"] for v in kali.get("volumes", []) if isinstance(v, dict)
    }
    assert mounts["/opt/kali"].endswith("/kali")
    assert mounts["/data"] == "http-history"
    assert "http-history" in _compose()["volumes"]


def test_kali_environment_exposes_the_capture_knobs():
    env = _compose()["services"]["kali"]["environment"]
    assert env["KALI_HTTP_HISTORY_ROOT"] == "/data"
    assert env["PYTHONPATH"] == "/opt"
    for key in (
        "KALI_HTTP_CAPTURE_ENABLED",
        "KALI_HTTP_MAX_BODY_BYTES",
        "KALI_HTTP_NAMESPACE_POOL",
        "KALI_HTTP_LEASE_TTL_S",
        "KALI_HTTP_PROXY_PORT",
        "KALI_HTTP_RETENTION_S",
        "KALI_HTTP_PROJECT_MAX_BYTES",
        "KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S",
        "KALI_HTTP_UPSTREAM_CA",
    ):
        assert key in env


def test_postrun_installs_the_operator_upstream_ca():
    """The knob alone does nothing: the bootstrap must install the file into the
    trust store the proxy verifies against (C.13, self-signed lab targets)."""
    script = (Path(__file__).resolve().parents[2] / "kali" / "postrun.sh").read_text(
        encoding="utf-8"
    )
    assert "KALI_HTTP_UPSTREAM_CA" in script
    assert "kali.http_history.trust" in script, "the CA file must actually be installed"


def test_entrypoint_hands_the_proxy_the_upstream_bundle():
    """mitmproxy verifies the upstream against its own CA source (certifi), not
    the system store: without this flag the operator CA is trusted by curl and
    ignored by the recorder (measured live, C.13)."""
    script = (Path(__file__).resolve().parents[2] / "kali" / "entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "ssl_verify_upstream_trusted_ca" in script
    assert "upstream-ca-bundle.pem" in script
    # The bundle persists on the volume: it must only be honoured while the
    # operator's knob is set, or the trust decision would outlive its removal.
    flag_line = next(
        line for line in script.splitlines() if "ssl_verify_upstream_trusted_ca=" in line
    )
    guard = script.splitlines()[: script.splitlines().index(flag_line)]
    assert any("KALI_HTTP_UPSTREAM_CA" in line for line in guard[-4:]), guard[-4:]


def test_e2e_overlay_offers_the_waf_and_challenge_fixtures():
    """The WAF test needs a target that DEFENDS itself, in two shapes: an engine
    that blocks (ModSecurity CRS) and a vendor-shaped challenge. Both must be
    reachable on port 80, the only web port the lease's REDIRECT covers."""
    root = Path(__file__).resolve().parents[2]
    overlay = (root / "docker-compose.e2e.yml").read_text(encoding="utf-8")
    for service in ("waf-e2e-target", "waf-e2e-front", "challenge-e2e-target"):
        assert service in overlay, service
    assert "owasp/modsecurity-crs" in overlay
    assert 'LISTEN_PORT: "80"' in overlay, "the WAF front must be on the captured port"
    assert (root / "tests/e2e/tcp_forwarder.py").is_file()
    assert (root / "tests/e2e/http_challenge_target.py").is_file()


def test_kali_defaults_bound_the_store_without_age_based_deletion():
    """The byte cap is ON by default (capture is on for every recon pod) and
    retention stays 0: age-based deletion would drop evidence with no disk
    pressure to justify it (deliberate deviation, decision record Parte C)."""
    env = _compose()["services"]["kali"]["environment"]
    assert int(env["KALI_HTTP_PROJECT_MAX_BYTES"]) > 0
    assert int(env["KALI_HTTP_RETENTION_S"]) == 0
    assert int(env["KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S"]) > 0


def test_kali_healthcheck_distinguishes_components():
    healthcheck = _compose()["services"]["kali"]["healthcheck"]
    assert "healthcheck.py" in " ".join(healthcheck["test"])
