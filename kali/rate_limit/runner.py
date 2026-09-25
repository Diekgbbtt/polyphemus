"""`python -m kali.rate_limit.runner` - one Vegeta experiment, compacted (#238).

Invoked through Kali's EXISTING `execute_command` seam with the experiment spec
on PRIVATE STDIN (never argv - the spec carries the authenticated context) and
answered with ONE compact JSON object on stdout.

Sequence, all inside a temporary `0700` workdir that is removed in `finally`:

1. write the Vegeta target file `0600` (method/url/headers - never a body);
2. `vegeta attack` -> GOB result stream on disk;
3. `vegeta encode --to=json` -> JSONL of hits;
4. compact each hit: response bodies become SHA-256 + size, secret-valued
   response headers are redacted, everything else is preserved verbatim;
5. `vegeta report -type=json` -> secondary aggregate (best-effort);
6. publish the compressed JSONL + manifest atomically (Task 3 store);
7. print the compact result - aggregates, fingerprints, reference, hash.

No response body, credential or absolute path reaches stdout. A non-zero
Vegeta exit is a TYPED failure that publishes nothing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from pydantic import ValidationError

from kali.rate_limit.models import (
    KaliExperimentResult,
    KaliExperimentSpec,
    KaliExperimentSpecError,
)
from kali.rate_limit.store import (
    DEFAULT_MAX_BYTES,
    RateLimitArtifactStore,
    write_private_file,
)

#: Vegeta answers a limiter refusal with one of these (spec: "typically 429, or
#: an equivalent documented retry signal").
_LIMITER_STATUSES = frozenset({429, 503})
_LIMITER_HEADER_RE = re.compile(
    r"^(retry-after|x-ratelimit-.*|ratelimit-.*|x-rate-limit-.*)$", re.IGNORECASE
)
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key"}
)
_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")
_STDERR_TAIL = 400


@dataclass(frozen=True)
class RunOutcome:
    """The shaped subprocess result the injected `run` seam returns."""

    stdout: str
    stderr: str
    returncode: int


def sha256_hex(data: bytes) -> str:
    """The body fingerprint helper (hash, never the bytes)."""
    return hashlib.sha256(data).hexdigest()


def default_run(
    argv: Sequence[str], *, input_text: str | None = None, timeout_s: float = 60.0
) -> RunOutcome:
    """The production subprocess seam: loud, bounded, text-mode."""
    proc = subprocess.run(
        list(argv),
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    return RunOutcome(
        stdout=proc.stdout or "", stderr=proc.stderr or "", returncode=proc.returncode
    )


def default_store() -> RateLimitArtifactStore:
    """The production store, resolved lazily from the deployment knobs."""
    root = os.environ.get("KALI_HTTP_HISTORY_ROOT", "/data")
    retention = int(os.environ.get("RATE_LIMIT_ARTIFACT_RETENTION_S") or 0)
    max_bytes = int(os.environ.get("RATE_LIMIT_ARTIFACT_MAX_BYTES") or DEFAULT_MAX_BYTES)
    return RateLimitArtifactStore(root, retention_s=retention, max_bytes=max_bytes)


def _call(
    run: Callable[..., RunOutcome],
    argv: Sequence[str],
    *,
    timeout_s: float,
    input_text: str | None = None,
) -> RunOutcome:
    return run(list(argv), input_text=input_text, timeout_s=timeout_s)


def _vegeta_version(run: Callable[..., RunOutcome]) -> str:
    """The running binary's version, pinned into the manifest (best-effort)."""
    try:
        outcome = _call(run, ["vegeta", "-version"], timeout_s=15.0)
    except Exception:  # noqa: BLE001 - a version probe never fails an experiment
        return "unknown"
    match = _VERSION_RE.search(outcome.stdout or "")
    return match.group(1) if match else "unknown"


def _decode_body(raw: Any) -> bytes | None:
    if not raw:
        return b""
    if isinstance(raw, bytes):
        return raw
    try:
        return base64.b64decode(str(raw), validate=False)
    except Exception:  # noqa: BLE001 - an undecodable body is a missing body
        return None


def _compact_headers(headers: Any) -> dict[str, list[str]]:
    """Preserve the response header SHAPE; redact secret-valued headers."""
    compact: dict[str, list[str]] = {}
    if not isinstance(headers, Mapping):
        return compact
    for name, values in headers.items():
        items = values if isinstance(values, (list, tuple)) else [values]
        if str(name).lower() in _SENSITIVE_HEADERS:
            compact[str(name)] = ["[redacted]" for _ in items]
        else:
            compact[str(name)] = [str(item) for item in items]
    return compact


def _compact_hit(hit: Mapping) -> dict:
    body = _decode_body(hit.get("body"))
    return {
        "seq": int(hit.get("seq", 0) or 0),
        "attack": str(hit.get("attack", "") or ""),
        "code": int(hit.get("code", 0) or 0),
        "timestamp": str(hit.get("timestamp", "") or ""),
        "latency_ms": round(float(hit.get("latency", 0) or 0) / 1_000_000, 3),
        "bytes_out": int(hit.get("bytes_out", 0) or 0),
        "bytes_in": int(hit.get("bytes_in", 0) or 0),
        "error": str(hit.get("error", "") or ""),
        "headers": _compact_headers(hit.get("headers")),
        "body_sha256": sha256_hex(body) if body else None,
        "body_size": len(body) if body is not None else 0,
    }


def _is_rejection(hit: Mapping) -> bool:
    code = int(hit.get("code", 0) or 0)
    if code in _LIMITER_STATUSES:
        return True
    if code < 400:
        return False
    return any(
        _LIMITER_HEADER_RE.match(str(name))
        for name in (hit.get("headers") or {})
    )


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    """Nearest-rank percentile: deterministic, no interpolation guessing."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(percentile / 100.0 * len(ordered)))
    return ordered[rank - 1]


def _fingerprints(hits: Sequence[Mapping]) -> tuple[list[str], list[str]]:
    """Header names and body hashes of the dominant response class.

    The dominant class is the REFUSAL class when any hit was refused (that is
    the limiter's fingerprint) and the accepted class otherwise. The mapper
    only ever compares like with like, and `judge_bypass` uses the two classes
    to tell "the mutation reached the app" from "the limiter still said no".
    """
    refused = [hit for hit in hits if _is_rejection(hit)]
    source = refused or list(hits)
    header_names = sorted(
        {
            str(name).lower()
            for hit in source
            for name in (hit.get("headers") or {})
        }
    )
    body_hashes = sorted(
        {
            str(hit["body_sha256"])
            for hit in source
            if hit.get("body_sha256")
        }
    )
    return header_names, body_hashes


def _metrics(hits: Sequence[Mapping]) -> dict:
    total = len(hits)
    status_counts: dict[str, int] = {}
    transport_errors = 0
    for hit in hits:
        code = int(hit.get("code", 0) or 0)
        if 100 <= code <= 599:
            key = str(code)
            status_counts[key] = status_counts.get(key, 0) + 1
        else:
            # Vegeta writes `code=0` when no HTTP response was produced at all
            # (DNS/TLS/connect/timeout). Code 0 is NOT a status and must never
            # be counted as one: a probe with only transport errors answered
            # nothing, so it can never be accepted evidence (#238 P0).
            transport_errors += 1
    rejected = sum(1 for hit in hits if _is_rejection(hit))
    latencies = [float(hit.get("latency_ms") or 0.0) for hit in hits]
    leading_accepted = 0
    for hit in hits:
        if _is_rejection(hit):
            break
        leading_accepted += 1
    header_fingerprint, body_fingerprint = _fingerprints(hits)
    return {
        "status_counts": dict(sorted(status_counts.items())),
        "transport_errors": transport_errors,
        "rejection_ratio": (rejected / total) if total else 0.0,
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "burst_accepted": leading_accepted,
        "header_fingerprint": header_fingerprint,
        "body_fingerprint": body_fingerprint,
    }


def _parse_hits(jsonl: str) -> list[dict]:
    hits: list[dict] = []
    for line in (jsonl or "").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise KaliExperimentSpecError(f"vegeta encode emitted invalid JSON: {exc}") from exc
        hits.append(_compact_hit(payload))
    return hits


def _failure(parsed: KaliExperimentSpec, error: str) -> dict:
    result = KaliExperimentResult(
        experiment_id=parsed.experiment_id,
        phase=parsed.phase,
        offered_rate_per_s=parsed.rate_per_s,
        concurrent_workers=parsed.concurrency,
    ).failure(error)
    return result.model_dump(mode="json")


def vegeta_rate(rate_per_s: float) -> str:
    """Vegeta's `-rate` value for a requests-per-second rate.

    Vegeta parses the numerator with `strconv.Atoi`, so a DECIMAL numerator is
    rejected outright (`invalid value "1.0/s" for flag -rate`) - every integral
    rate the controller derives (`1.0`, `2.0`, `5.0`, ...) would fail. The rate
    is therefore re-expressed as an exact integer FRACTION per second:
    `1.5/s` -> `3/2s`, `20/s` -> `20/1s`.

    The denominator counts SECONDS (`3/2s` is three requests per two seconds).
    Scaling the numerator into a sub-second unit instead would multiply the
    offered rate by that unit's factor - the exact runaway the operator budget
    exists to prevent.
    """
    fraction = Fraction(float(rate_per_s)).limit_denominator(1_000_000)
    return f"{fraction.numerator}/{fraction.denominator}s"


def run_experiment(
    spec: Mapping,
    *,
    run: Callable[..., RunOutcome] = default_run,
    store: RateLimitArtifactStore | None = None,
    workdir_root: str | os.PathLike | None = None,
    experiment_timeout_s: float | None = None,
) -> dict:
    """Run one admitted experiment and return the compact result dict.

    Raises `KaliExperimentSpecError` for a malformed spec (nothing runs).
    Every other failure is a TYPED failure result, never an exception the pod
    layer would have to guess about.
    """
    try:
        parsed = KaliExperimentSpec.model_validate(dict(spec))
    except ValidationError as exc:
        raise KaliExperimentSpecError(f"invalid experiment spec: {exc}") from exc

    artifact_store = store or default_store()
    if workdir_root:
        os.makedirs(workdir_root, exist_ok=True)
    workdir = Path(
        tempfile.mkdtemp(
            prefix=f"rate-{parsed.experiment_id}-",
            dir=str(workdir_root) if workdir_root else None,
        )
    )
    target_file = workdir / "vegeta-target.json"
    gob_file = workdir / "results.gob"
    timeout = float(experiment_timeout_s or 0) or (parsed.timeout_s + parsed.duration_s + 30.0)
    try:
        # 0600 target file: credentials reach Vegeta through the filesystem, and
        # never through argv (which is visible in the process table).
        # The trailing newline is LOAD-BEARING: vegeta's reader is line-based
        # and drops a final line that is not newline-terminated ("no targets to
        # attack" otherwise).
        write_private_file(
            target_file, (json.dumps(parsed.vegeta_target()) + "\n").encode("utf-8")
        )
        version = _vegeta_version(run)
        attack = _call(
            run,
            [
                "vegeta", "attack",
                # The target file is one JSON object per line; vegeta's
                # `-format` defaults to "http" (plain `METHOD URL` lines), so
                # the JSON form has to be requested explicitly.
                "-format=json",
                f"-targets={target_file}",
                f"-rate={vegeta_rate(parsed.rate_per_s)}",
                f"-duration={parsed.duration_s}s",
                f"-workers={parsed.concurrency}",
                f"-timeout={parsed.timeout_s}s",
                f"-output={gob_file}",
            ],
            timeout_s=timeout,
        )
        if attack.returncode != 0:
            return _failure(
                parsed,
                f"vegeta attack exited {attack.returncode}: "
                f"{(attack.stderr or '').strip()[:_STDERR_TAIL]}",
            )

        encoded = _call(
            run, ["vegeta", "encode", "--to=json", str(gob_file)], timeout_s=timeout
        )
        if encoded.returncode != 0:
            return _failure(
                parsed,
                f"vegeta encode exited {encoded.returncode}: "
                f"{(encoded.stderr or '').strip()[:_STDERR_TAIL]}",
            )
        hits = _parse_hits(encoded.stdout)
        metrics = _metrics(hits)

        if not metrics["status_counts"]:
            # No HTTP response was produced by ANY hit: the probe never reached
            # the target. Publish nothing - a probe with no evidence is a typed
            # failure, never a "measured" result the mapper could read as an
            # accepted bound (#238 P0).
            return KaliExperimentResult(
                experiment_id=parsed.experiment_id,
                phase=parsed.phase,
                outcome="failed",
                offered_rate_per_s=parsed.rate_per_s,
                concurrent_workers=parsed.concurrency,
                count=len(hits),
                transport_errors=metrics["transport_errors"],
                duration_s=parsed.duration_s,
                vegeta_version=version,
                error="no valid HTTP response",
            ).model_dump(mode="json")

        aggregate: dict = {}
        try:
            report = _call(
                run, ["vegeta", "report", "-type=json", str(gob_file)], timeout_s=timeout
            )
            if report.returncode == 0 and report.stdout.strip():
                aggregate = json.loads(report.stdout)
        except Exception:  # noqa: BLE001 - the report is SECONDARY evidence
            aggregate = {}

        published = artifact_store.publish(
            project_id=parsed.project_id,
            run_id=parsed.run_id,
            experiment_id=parsed.experiment_id,
            hits=hits,
            spec=parsed.model_dump(mode="json"),
            vegeta_version=version,
            duration_s=parsed.duration_s,
            aggregate=aggregate,
        )
        # Retention runs AFTER a successful publication, never before: a trim
        # failure must never cost the experiment that just succeeded.
        try:
            artifact_store.enforce_limits()
        except Exception:  # noqa: BLE001 - housekeeping never fails a measurement
            pass
        return KaliExperimentResult(
            experiment_id=parsed.experiment_id,
            phase=parsed.phase,
            outcome="measured",
            artifact_ref=published.ref,
            manifest_sha256=published.sha256,
            count=published.count,
            duration_s=parsed.duration_s,
            offered_rate_per_s=parsed.rate_per_s,
            concurrent_workers=parsed.concurrency,
            vegeta_version=version,
            **metrics,
        ).model_dump(mode="json")
    except KaliExperimentSpecError:
        raise
    except Exception as exc:  # noqa: BLE001 - a runner fault is a typed failure
        return _failure(parsed, f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _emit(stdout, payload: Mapping) -> None:
    stdout.write(json.dumps(payload, separators=(",", ":")))
    stdout.write("\n")
    stdout.flush()


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin=None,
    stdout=None,
    run: Callable[..., RunOutcome] = default_run,
    store: RateLimitArtifactStore | None = None,
    workdir_root: str | os.PathLike | None = None,
) -> int:
    """The module entry point: private stdin in, one compact JSON object out.

    Exit codes tell the CALLER whether the runner could run, while the JSON
    `outcome` tells the CONTROLLER whether the target could be measured:
    `0` measured, `3` typed measurement failure, `2` invalid spec, `1`
    unexpected runner fault.
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        spec = json.loads(stdin.read())
        if not isinstance(spec, dict):
            raise KaliExperimentSpecError("the experiment spec must be a JSON object")
    except (ValueError, KaliExperimentSpecError) as exc:
        _emit(
            stdout,
            {
                "version": "rate-result/v1",
                "experiment_id": "",
                "phase": "",
                "outcome": "failed",
                "count": 0,
                "artifact_ref": None,
                "manifest_sha256": None,
                "error": f"invalid experiment spec: {exc}",
            },
        )
        return 2

    try:
        result = run_experiment(
            spec, run=run, store=store, workdir_root=workdir_root
        )
    except KaliExperimentSpecError as exc:
        _emit(
            stdout,
            {
                "version": "rate-result/v1",
                "experiment_id": str(spec.get("experiment_id", "")),
                "phase": str(spec.get("phase", "")),
                "outcome": "failed",
                "count": 0,
                "artifact_ref": None,
                "manifest_sha256": None,
                "error": str(exc),
            },
        )
        return 2
    except Exception as exc:  # noqa: BLE001 - never take the exec server down
        _emit(
            stdout,
            {
                "version": "rate-result/v1",
                "experiment_id": str(spec.get("experiment_id", "")),
                "phase": str(spec.get("phase", "")),
                "outcome": "failed",
                "count": 0,
                "artifact_ref": None,
                "manifest_sha256": None,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        return 1

    _emit(stdout, result)
    return 0 if result.get("outcome") == "measured" else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RunOutcome",
    "default_run",
    "default_store",
    "main",
    "run_experiment",
    "sha256_hex",
    "vegeta_rate",
]
