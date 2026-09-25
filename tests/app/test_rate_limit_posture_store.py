"""The per-project, per-target rate-limit posture bucket (#238 follow-up).

The store's WRITE path: one YAML per `target_key`, atomic, recency-guarded.
"""
import yaml
import pytest

from polymerhus.app.rate_limit.store import (
    POSTURE_VERSION,
    PostureWriteError,
    RateLimitPostureStore,
)
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.domain.rate_limit import RateProfile


def _profile(target_key: str = "acme.com") -> RateProfile:
    return RateProfile.conservative(
        target_key, [target_key], rate_limit_safety_budget(), "test fixture",
    )


def test_write_creates_one_file_per_target(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)

    path = store.write("proj-1", _profile("api.acme.com"), "run-1")

    assert path == tmp_path / "proj-1" / "rate-limit" / "api.acme.com.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["version"] == POSTURE_VERSION
    assert payload["advisory"] is True
    assert payload["source_run_id"] == "run-1"
    assert payload["profile"]["target_key"] == "api.acme.com"


def test_write_rejects_an_unsafe_target_key(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)

    with pytest.raises(PostureWriteError):
        store.write("proj-1", _profile("../escape"), "run-1")


def test_write_keeps_the_newer_measurement(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    newer = _profile("acme.com")
    older = newer.model_copy(
        update={"measured_at": newer.measured_at.replace(year=newer.measured_at.year - 1)}
    )

    store.write("proj-1", newer, "run-new")
    store.write("proj-1", older, "run-old")

    stored = yaml.safe_load(
        (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert stored["source_run_id"] == "run-new"
