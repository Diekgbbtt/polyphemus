"""#238 Task 3 - the durable, bounded Vegeta artifact store.

Raw per-hit evidence is the run's ground truth, so its store carries three
non-negotiable properties:

* an experiment directory is PUBLISHED atomically or not at all - a partial
  write is never advertised as a reference the profile can point at;
* the manifest pins the compressed stream (SHA-256, count, duration, Vegeta
  version) and REDACTES the secret-bearing parts of the experiment spec, so a
  stored artifact can never leak the authenticated context;
* retention and the per-project byte cap are explicit operator knobs which
  default OFF (age) / 256 MiB (bytes), and eviction only ever removes
  COMPLETE, oldest-first experiment directories.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os

import pytest

from kali.rate_limit import store as store_module
from kali.rate_limit.store import (
    DEFAULT_MAX_BYTES,
    RATE_ARTIFACT_SCHEME,
    REDACTED,
    ArtifactIdentifierError,
    RateLimitArtifactStore,
)


def _hits() -> list[dict]:
    return [
        {"seq": 0, "code": 200, "latency_ms": 12.0, "bytes_in": 512, "bytes_out": 0},
        {"seq": 1, "code": 429, "latency_ms": 8.0, "bytes_in": 96, "bytes_out": 0},
    ]


def _spec() -> dict:
    return {
        "experiment_id": "exp-1",
        "phase": "steady",
        "url": "https://target.example/login",
        "method": "POST",
        "headers": {
            "Authorization": "Bearer supersecret-token",
            "Cookie": "session=supersecret-cookie",
            "Accept": "application/json",
        },
        "rate_per_s": 5.0,
        "duration_s": 2.0,
    }


def test_defaults_keep_every_artifact_and_cap_at_256_mib(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    assert store.retention_s == 0  # age retention is OFF by default
    assert store.max_bytes == 256 * 1024 * 1024 == DEFAULT_MAX_BYTES
    # A retention of zero means "keep everything": nothing is evicted by age.
    store.publish(
        project_id="p", run_id="r", experiment_id="e",
        hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
        created_at=1.0,
    )
    assert store.enforce_limits(now=10**9)["removed"] == 0


def test_artifact_ref_refuses_identifier_traversal(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    for bad in ("..", ".", "", "a/b", "../evil", "a\\b", ".hidden"):
        with pytest.raises(ArtifactIdentifierError):
            RateLimitArtifactStore.artifact_ref(bad, "run", "exp")
    for bad in ("..", "a/b"):
        with pytest.raises(ArtifactIdentifierError):
            store.publish(
                project_id="proj", run_id=bad, experiment_id="exp",
                hits=[], spec=_spec(), vegeta_version="12.13.0", duration_s=0.0,
            )


def test_published_ref_has_the_wire_shape_and_directory_layout(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    published = store.publish(
        project_id="proj-1", run_id="run-1", experiment_id="exp-1",
        hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
    )
    assert published.ref == f"{RATE_ARTIFACT_SCHEME}:proj-1/run-1/exp-1"
    assert published.count == 2
    directory = tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1"
    assert (directory / "results.jsonl.gz").is_file()
    assert (directory / "manifest.json").is_file()
    # The reference is a RELATIVE, immutable coordinate: no absolute path leaks
    # into a stored profile or a run-stats row.
    assert str(tmp_path) not in published.ref


def test_manifest_pins_the_compressed_stream_count_duration_and_version(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    published = store.publish(
        project_id="proj-1", run_id="run-1", experiment_id="exp-1",
        hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
    )
    directory = tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1"
    blob = (directory / "results.jsonl.gz").read_bytes()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["sha256"] == hashlib.sha256(blob).hexdigest() == published.sha256
    assert manifest["count"] == 2
    assert manifest["duration_s"] == 2.0
    assert manifest["vegeta_version"] == "12.13.0"
    assert manifest["version"] == RATE_ARTIFACT_SCHEME
    assert manifest["project_id"] == "proj-1"
    assert manifest["run_id"] == "run-1"
    assert manifest["experiment_id"] == "exp-1"
    # The hashed stream IS the compacted hit stream, one JSON object per line.
    lines = gzip.decompress(blob).decode("utf-8").splitlines()
    assert [json.loads(line) for line in lines] == _hits()


def test_manifest_redacts_secret_spec_values(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    store.publish(
        project_id="proj-1", run_id="run-1", experiment_id="exp-1",
        hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
    )
    manifest_text = (
        tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1" / "manifest.json"
    ).read_text(encoding="utf-8")

    assert "supersecret-token" not in manifest_text
    assert "supersecret-cookie" not in manifest_text
    assert REDACTED in manifest_text
    # Non-secret transport shape is preserved so the manifest stays auditable.
    spec = json.loads(manifest_text)["spec"]
    assert spec["url"] == "https://target.example/login"
    assert spec["rate_per_s"] == 5.0


def test_interrupted_publication_cleans_up_and_returns_no_reference(tmp_path, monkeypatch):
    store = RateLimitArtifactStore(tmp_path)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(store_module.os, "replace", boom)
    with pytest.raises(OSError):
        store.publish(
            project_id="proj-1", run_id="run-1", experiment_id="exp-1",
            hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
        )

    run_dir = tmp_path / "proj-1" / "rate-limit" / "run-1"
    assert not (run_dir / "exp-1").exists()
    # No partial/temporary directory survives to be mistaken for an artifact.
    assert list(run_dir.iterdir()) == []
    assert store.status()["experiments"] == 0


def test_a_partial_directory_is_never_counted_or_advertised(tmp_path):
    store = RateLimitArtifactStore(tmp_path, max_bytes=1)
    store.publish(
        project_id="proj-1", run_id="run-1", experiment_id="exp-1",
        hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
    )
    run_dir = tmp_path / "proj-1" / "rate-limit" / "run-1"
    partial = run_dir / ".exp-2.tmp"
    partial.mkdir()
    (partial / "results.jsonl.gz").write_bytes(b"half a stream")

    status = store.status()
    assert status["experiments"] == 1
    assert status["bytes"] < 1024  # the partial blob is excluded from the total
    assert store.enforce_limits()["removed"] == 1
    assert not (run_dir / "exp-1").exists()
    assert partial.is_dir()  # a temp dir is not ours to delete while a writer owns it


def test_byte_cap_evicts_the_oldest_complete_experiments(tmp_path):
    # Poorly-compressible content so the byte total is dominated by real payload
    # and the cap is a meaningful constraint rather than a compression artifact.
    noisy = "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(64))
    hits = [{"seq": i, "code": 200, "body_sha256": noisy} for i in range(4)]
    store = RateLimitArtifactStore(tmp_path)
    for index in range(3):
        store.publish(
            project_id="proj-1", run_id="run-1", experiment_id=f"exp-{index}",
            hits=hits, spec=_spec(), vegeta_version="12.13.0", duration_s=1.0,
            created_at=100.0 + index,
        )

    total = store.status()["bytes"]
    assert total > 4096
    capped = RateLimitArtifactStore(tmp_path, max_bytes=total // 2)
    result = capped.enforce_limits()
    run_dir = tmp_path / "proj-1" / "rate-limit" / "run-1"

    assert result["removed"] >= 1
    assert not (run_dir / "exp-0").exists()  # oldest evicted first
    assert (run_dir / "exp-2").exists()
    assert capped.status()["bytes"] <= total // 2


def test_age_retention_removes_only_older_complete_experiments(tmp_path):
    store = RateLimitArtifactStore(tmp_path, retention_s=60)
    for index, created in enumerate((100.0, 200.0)):
        store.publish(
            project_id="proj-1", run_id="run-1", experiment_id=f"exp-{index}",
            hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=1.0,
            created_at=created,
        )
    removed = store.enforce_limits(now=250.0)["removed"]
    run_dir = tmp_path / "proj-1" / "rate-limit" / "run-1"

    assert removed == 1
    assert not (run_dir / "exp-0").exists()  # created 100 < 250 - 60
    assert (run_dir / "exp-1").exists()  # created 200 is inside the window


def test_artifact_files_are_written_owner_only(tmp_path):
    """The compressed stream is raw target evidence: never group/world-readable."""
    store = RateLimitArtifactStore(tmp_path)
    store.publish(
        project_id="proj-1", run_id="run-1", experiment_id="exp-1",
        hits=_hits(), spec=_spec(), vegeta_version="12.13.0", duration_s=2.0,
    )
    directory = tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1"
    for name in ("results.jsonl.gz", "manifest.json"):
        mode = os.stat(directory / name).st_mode & 0o777
        assert mode & 0o077 == 0, f"{name} is {oct(mode)}"
