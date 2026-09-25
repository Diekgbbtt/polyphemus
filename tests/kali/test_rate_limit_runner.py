"""#238 Task 3 - the in-Kali Vegeta experiment runner.

The runner is where raw load evidence is produced and compacted. Its contract
is deliberately narrow: private stdin in, one compact JSON object on stdout,
the raw per-hit stream only ever on disk under the artifact root.

Nothing secret and no raw body may cross the stdout/exec envelope - response
bodies are replaced by hash and size, the authenticated context travels only
on private stdin and is redacted in the manifest.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import stat

import pytest

from kali.rate_limit import runner as runner_module
from kali.rate_limit.store import RateLimitArtifactStore

BODY = b"<html>welcome back</html>"


def _spec(**overrides) -> dict:
    spec = {
        "experiment_id": "exp-1",
        "phase": "steady",
        "project_id": "proj-1",
        "run_id": "run-1",
        # #238 follow-up (Task 5): the controller materializes the effective
        # request and Kali executes it verbatim.
        "effective_request": {
            "mutation_id": "canonical",
            "method": "POST",
            "url": "https://target.example/login",
            "headers": {
                "Authorization": "Bearer supersecret-token",
                "Cookie": "session=supersecret-cookie",
                "Accept": "application/json",
            },
        },
        "rate_per_s": 5.0,
        "duration_s": 2.0,
        "requests": 10,
        "concurrency": 2,
        "timeout_s": 15.0,
    }
    spec.update(overrides)
    return spec


def test_vegeta_rate_never_emits_a_decimal_numerator():
    """#238 Task 8 (found live): vegeta parses the rate numerator with
    `strconv.Atoi`, so `-rate=1.0/s` is REJECTED ("invalid value \\"1.0/s\\" for
    flag -rate") - and every integral rate the controller derives renders as
    `1.0`, `2.0`, `5.0`, ... The rate has to be an integer FRACTION per second,
    and the denominator must count SECONDS: `1500/1000ms` is 1500 rps, not
    1.5 rps - a 1000x runaway of the operator's budget (measured live)."""
    assert runner_module.vegeta_rate(1.0) == "1/1s"
    assert runner_module.vegeta_rate(20.0) == "20/1s"
    assert runner_module.vegeta_rate(1.5) == "3/2s"
    assert runner_module.vegeta_rate(0.25) == "1/4s"
    for rate in (0.5, 1.0, 1.5, 2.0, 5.0, 12.5):
        numerator, denominator = runner_module.vegeta_rate(rate).rstrip("s").split("/")
        assert int(numerator) / int(denominator) == rate


def test_the_vegeta_attack_argv_carries_a_parseable_rate(monkeypatch, tmp_path):
    run = _FakeRun()
    store = RateLimitArtifactStore(tmp_path)
    result = runner_module.run_experiment(
        _spec(rate_per_s=1.0, duration_s=1.0, requests=1), run=run, store=store
    )
    assert result["outcome"] == "measured"
    attack = next(argv for argv in run.calls if argv[1] == "attack")
    rate = next(arg for arg in attack if arg.startswith("-rate="))
    assert rate == "-rate=1/1s"
    assert not rate.endswith(".0/s")
    # The target file is JSONL: vegeta's `-format` defaults to the plain
    # `METHOD URL` form, which rejects it with "bad target".
    assert "-format=json" in attack


def _hit_jsonl() -> str:
    hits = [
        {
            "attack": "POST https://target.example/login",
            "seq": 0,
            "code": 200,
            "timestamp": "2025-01-01T00:00:00.000000000Z",
            "latency": 12_000_000,
            "bytes_out": 128,
            "bytes_in": 4096,
            "error": "",
            "body": base64.b64encode(BODY).decode(),
            "headers": {"Content-Type": ["text/html"], "Set-Cookie": ["sid=raw-secret"]},
        },
        {
            "attack": "POST https://target.example/login",
            "seq": 1,
            "code": 429,
            "timestamp": "2025-01-01T00:00:00.100000000Z",
            "latency": 4_000_000,
            "bytes_out": 128,
            "bytes_in": 96,
            "error": "",
            "body": base64.b64encode(b"slow down").decode(),
            "headers": {"Retry-After": ["30"]},
        },
    ]
    return "\n".join(json.dumps(hit) for hit in hits)


class _FakeRun:
    """The injected subprocess seam: records argv, replays synthetic Vegeta."""

    def __init__(self, *, attack_rc: int = 0, jsonl: str = "", version="12.13.0"):
        self.calls: list[list[str]] = []
        self.attack_rc = attack_rc
        self.jsonl = jsonl or _hit_jsonl()
        self.version = version
        self.target_mode: int | None = None
        self.target_headers: dict | None = None
        self.target_existed = False

    def __call__(self, argv, *, input_text=None, timeout_s=None):
        self.calls.append(list(argv))
        verb = argv[1] if len(argv) > 1 else ""
        if verb in ("-version", "--version"):
            return runner_module.RunOutcome(
                stdout=f"Version: {self.version}\nCommit: abc\nRuntime: go1.x\n",
                stderr="",
                returncode=0,
            )
        if verb == "attack":
            target = next(a.split("=", 1)[1] for a in argv if a.startswith("-targets="))
            self.target_existed = os.path.exists(target)
            self.target_mode = stat.S_IMODE(os.stat(target).st_mode)
            self.target_headers = json.loads(open(target, encoding="utf-8").read())["header"]
            return runner_module.RunOutcome(stdout="", stderr="", returncode=self.attack_rc)
        if verb == "encode":
            return runner_module.RunOutcome(
                stdout=self.jsonl + "\n", stderr="", returncode=0
            )
        if verb == "report":
            return runner_module.RunOutcome(
                stdout=json.dumps({"latencies": {"95th": 20_000_000}, "requests": 2}),
                stderr="",
                returncode=0,
            )
        return runner_module.RunOutcome(stdout="", stderr="", returncode=2)


def test_runner_compacts_hits_and_publishes_an_artifact(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun()

    result = runner_module.run_experiment(
        _spec(), run=run, store=store, workdir_root=str(tmp_path / "work")
    )

    assert result["outcome"] == "measured"
    assert result["experiment_id"] == "exp-1"
    assert result["artifact_ref"] == "rate-artifact/v1:proj-1/run-1/exp-1"
    assert result["count"] == 2
    assert result["status_counts"] == {"200": 1, "429": 1}
    assert result["rejection_ratio"] == 0.5
    assert result["latency_p50_ms"] == 4.0
    assert result["latency_p95_ms"] == 12.0
    assert result["vegeta_version"] == "12.13.0"
    assert result["duration_s"] == 2.0
    assert result["error"] is None

    # The manifest sha is the compressed stream's hash, and that stream is the
    # compacted hit stream - not the raw Vegeta payload.
    artifact_dir = tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1"
    blob = (artifact_dir / "results.jsonl.gz").read_bytes()
    assert result["manifest_sha256"] == hashlib.sha256(blob).hexdigest()
    records = [json.loads(line) for line in gzip.decompress(blob).decode().splitlines()]
    assert records[0] == {
        "seq": 0,
        "attack": "POST https://target.example/login",
        "code": 200,
        "timestamp": "2025-01-01T00:00:00.000000000Z",
        "latency_ms": 12.0,
        "bytes_out": 128,
        "bytes_in": 4096,
        "error": "",
        # The header SHAPE is preserved; a secret-valued header is redacted even
        # in the durable raw store (the credential never lands on disk).
        "headers": {"Content-Type": ["text/html"], "Set-Cookie": ["[redacted]"]},
        "body_sha256": runner_module.sha256_hex(BODY),
        "body_size": len(BODY),
    }
    assert b"sid=raw-secret" not in blob
    # A limiter signal keeps its VALUE: the fingerprint is the measured evidence.
    assert records[1]["headers"] == {"Retry-After": ["30"]}


def _transport_only_jsonl(count: int = 5) -> str:
    """Every hit failed before any HTTP response: Vegeta records code 0."""
    hits = [
        {
            "attack": "GET https://target.example/",
            "seq": index,
            "code": 0,
            "timestamp": "2025-01-01T00:00:00.000000000Z",
            "latency": 1_000_000,
            "bytes_out": 0,
            "bytes_in": 0,
            "error": "dial tcp: lookup target.example: no such host",
            "body": "",
            "headers": {},
        }
        for index in range(count)
    ]
    return "\n".join(json.dumps(hit) for hit in hits)


def test_transport_only_probe_publishes_nothing_and_fails(tmp_path):
    """#238 P0: zero valid HTTP responses is a TYPED failure, not a measurement.

    The old runner claimed `outcome="measured"` with `status_counts={"0": 5}`
    and published an artifact; the controller read that as a valid probe and
    could conclude `no_limiter` from a target it never reached.
    """
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun(jsonl=_transport_only_jsonl(5))

    result = runner_module.run_experiment(
        _spec(duration_s=1.0, requests=5, concurrency=1), run=run, store=store
    )

    assert result["outcome"] == "failed"
    assert result["status_counts"] == {}
    assert result["transport_errors"] == 5
    assert result["artifact_ref"] is None
    assert result["manifest_sha256"] is None
    assert result["error"]
    # Nothing was published for a probe that produced no evidence.
    assert not (tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1").exists()


def test_a_partially_transported_probe_keeps_the_real_statuses(tmp_path):
    """A mixed probe keeps its HTTP evidence but records the transport loss."""
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun(jsonl=_hit_jsonl() + "\n" + _transport_only_jsonl(1))

    result = runner_module.run_experiment(
        _spec(duration_s=1.0, requests=3, concurrency=1), run=run, store=store
    )

    assert result["outcome"] == "measured"
    assert result["transport_errors"] == 1
    assert "0" not in result["status_counts"]
    assert result["status_counts"] == {"200": 1, "429": 1}


def test_runner_publishes_metrics_but_never_raw_bodies(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun()

    result = runner_module.run_experiment(_spec(), run=run, store=store)

    assert BODY.decode() not in json.dumps(result)
    artifact_dir = tmp_path / "proj-1" / "rate-limit" / "run-1" / "exp-1"
    assert BODY not in (artifact_dir / "results.jsonl.gz").read_bytes()
    assert BODY.decode() not in (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    # The secret-bearing request spec is redacted in the manifest.
    manifest_text = (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    assert "supersecret-token" not in manifest_text
    assert "supersecret-cookie" not in manifest_text


def test_runner_uses_a_private_target_file_and_removes_every_scratch_file(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    workdir_root = tmp_path / "work"
    run = _FakeRun()

    runner_module.run_experiment(
        _spec(), run=run, store=store, workdir_root=str(workdir_root)
    )

    assert run.target_existed and run.target_mode == 0o600
    # Credentials were handed to Vegeta through that private target file.
    # Vegeta decodes `header` into http.Header (map[string][]string): a bare
    # string value is a parse error at the wire, so the list shape is pinned.
    assert run.target_headers["Authorization"] == ["Bearer supersecret-token"]
    # No target/GOB file survives the experiment.
    leftovers = [p for p in workdir_root.rglob("*") if p.is_file()]
    assert leftovers == []


def test_runner_returns_a_typed_failure_and_publishes_nothing_on_nonzero_exit(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun(attack_rc=1)

    result = runner_module.run_experiment(_spec(), run=run, store=store)

    assert result["outcome"] == "failed"
    assert result["error"]
    assert result["artifact_ref"] is None
    assert result["manifest_sha256"] is None
    assert result["count"] == 0
    assert store.status()["experiments"] == 0


def test_runner_refuses_an_invalid_spec_without_touching_the_target(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun()
    with pytest.raises(runner_module.KaliExperimentSpecError):
        runner_module.run_experiment({"experiment_id": "exp-1"}, run=run, store=store)
    assert run.calls == []


def test_main_reads_the_spec_from_stdin_and_prints_one_compact_object(tmp_path):
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun()
    stdout = io.StringIO()

    code = runner_module.main(
        stdin=io.StringIO(json.dumps(_spec())),
        stdout=stdout,
        run=run,
        store=store,
        workdir_root=str(tmp_path / "work"),
    )

    assert code == 0
    payload = json.loads(stdout.getvalue())
    assert payload["artifact_ref"] == "rate-artifact/v1:proj-1/run-1/exp-1"
    assert "\n" not in stdout.getvalue().strip()


def test_main_reports_a_typed_failure_on_invalid_stdin(tmp_path):
    stdout = io.StringIO()
    code = runner_module.main(
        stdin=io.StringIO("not json"),
        stdout=stdout,
        run=_FakeRun(),
        store=RateLimitArtifactStore(tmp_path),
    )
    assert code != 0
    payload = json.loads(stdout.getvalue())
    assert payload["outcome"] == "failed"
    assert payload["error"]


def test_default_run_forwards_private_stdin_without_echoing_it(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        import subprocess

        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(runner_module.subprocess, "run", fake_run)
    outcome = runner_module.default_run(
        ["vegeta", "encode"], input_text='{"Authorization":"Bearer x"}', timeout_s=5
    )
    assert outcome.stdout == "ok"
    assert seen["kwargs"]["input"] == '{"Authorization":"Bearer x"}'
    assert seen["argv"] == ["vegeta", "encode"]


def test_runner_enforces_the_cap_only_after_publishing(tmp_path):
    """The trim runs AFTER the new artifact lands: the experiment that just
    succeeded is never the one sacrificed to make room for itself."""
    run = _FakeRun()
    runner_module.run_experiment(
        _spec(experiment_id="exp-old"), run=run, store=RateLimitArtifactStore(tmp_path)
    )
    one = RateLimitArtifactStore(tmp_path).status()["bytes"]
    capped = RateLimitArtifactStore(tmp_path, max_bytes=int(one * 1.5))

    # Something has to be published before anything can be evicted: enforcement
    # happens post-publication, and the newest experiment survives it.
    second = runner_module.run_experiment(
        _spec(experiment_id="exp-new"), run=run, store=capped
    )

    run_dir = tmp_path / "proj-1" / "rate-limit" / "run-1"
    assert second["outcome"] == "measured"
    assert second["artifact_ref"] == "rate-artifact/v1:proj-1/run-1/exp-new"
    assert (run_dir / "exp-new").is_dir()
    assert not (run_dir / "exp-old").exists()
