"""The per-project, per-target rate-limit posture bucket (#238 follow-up).

The store's WRITE path: one YAML per `target_key`, atomic, recency-guarded.
"""
import os
import threading
from datetime import timedelta

import yaml
import pytest

from polymerhus.app.rate_limit.store import (
    POSTURE_VERSION,
    PostureRecord,
    PostureUnreadableError,
    PostureWriteError,
    RateLimitPostureStore,
    host_matches,
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


def test_read_is_none_only_when_the_file_is_absent(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    assert store.read("proj-1", "acme.com") is None


def test_read_reports_freshness(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")

    record = store.read("proj-1", "acme.com")

    assert isinstance(record, PostureRecord)
    assert record.fresh is True
    assert record.profile.target_key == "acme.com"
    assert record.source_run_id == "run-1"


def test_list_targets_is_empty_without_a_bucket(tmp_path):
    assert RateLimitPostureStore(root=tmp_path).list_targets("nope") == []


def test_list_targets_lists_every_written_target(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")
    store.write("proj-1", _profile("api.acme.com"), "run-1")

    assert store.list_targets("proj-1") == ["acme.com", "api.acme.com"]


def test_resolve_matches_exact_and_wildcard_hosts():
    assert host_matches("api.acme.com", ["api.acme.com"]) is True
    assert host_matches("API.ACME.COM", ["api.acme.com"]) is True
    assert host_matches("api.acme.com", ["*.acme.com"]) is True
    assert host_matches("other.example.com", ["acme.com"]) is False
    assert host_matches(None, ["acme.com"]) is False
    assert host_matches("anything", []) is True


def test_resolve_returns_none_for_an_uncovered_host(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")

    assert store.resolve("proj-1", "api.acme.com") is None
    assert store.resolve("proj-1", "acme.com").target_key == "acme.com"


def test_a_corrupt_file_is_unreadable_never_absent(tmp_path):
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")
    (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").write_text(
        "::: not yaml :::", encoding="utf-8"
    )

    with pytest.raises(PostureUnreadableError):
        store.read("proj-1", "acme.com")


def test_a_failed_write_keeps_the_previous_file_and_leaves_no_temp(
    tmp_path, monkeypatch
):
    """Atomic by construction: a mid-write failure must leave the PREVIOUS
    posture exactly as it was, and must not leak a half-written temp file."""
    store = RateLimitPostureStore(root=tmp_path)
    store.write("proj-1", _profile("acme.com"), "run-1")
    bucket = tmp_path / "proj-1" / "rate-limit"
    before = (bucket / "acme.com.yaml").read_text(encoding="utf-8")

    def _no_space(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", _no_space)

    with pytest.raises(PostureWriteError):
        store.write("proj-1", _profile("acme.com"), "run-2")

    assert (bucket / "acme.com.yaml").read_text(encoding="utf-8") == before
    assert [path.name for path in bucket.iterdir()] == ["acme.com.yaml"]


def test_concurrent_writes_never_lose_the_newest_measurement(tmp_path):
    """The per-project lock covers the whole check-then-write section, so
    concurrent measurements of ONE target converge on the newest one."""
    store = RateLimitPostureStore(root=tmp_path)
    base = _profile("acme.com").measured_at
    profiles = [
        _profile("acme.com").model_copy(
            update={"measured_at": base + timedelta(seconds=index)}
        )
        for index in range(1, 9)
    ]

    def _write(profile, run_id):
        store.write("proj-1", profile, run_id)

    threads = [
        threading.Thread(target=_write, args=(profile, f"run-{index}"))
        for index, profile in enumerate(profiles)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = yaml.safe_load(
        (tmp_path / "proj-1" / "rate-limit" / "acme.com.yaml").read_text(
            encoding="utf-8"
        )
    )
    # The file and `stats.rate_limit` carry the SAME serialisation of the
    # instant (the envelope dumps the profile in JSON mode).
    assert (
        stored["profile"]["measured_at"]
        == profiles[-1].model_dump(mode="json")["measured_at"]
    )
    assert stored["source_run_id"] == f"run-{len(profiles) - 1}"
