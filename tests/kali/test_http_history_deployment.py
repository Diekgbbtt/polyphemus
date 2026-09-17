"""#196 deployment shape: compose service, env config, healthcheck."""
from __future__ import annotations

import subprocess

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
    ):
        assert key in env


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
