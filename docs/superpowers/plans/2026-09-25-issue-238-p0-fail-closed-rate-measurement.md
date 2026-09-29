# Issue #238 P0 - Fail-Closed Rate Measurement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a rate-measurement that never reached the target fail closed, keep `no_limiter` an honest statement about the bounds actually tested, and stop persisting credentials or phantom target observations.

**Architecture:** The controller owns every traffic number; the Kali runner owns the raw Vegeta evidence and the classifier turns aggregates into hypotheses. This plan adds one honesty gate at each of the three seams - the wire payload (Kali), the controller boundary, and the classifier - plus two persistence correctors (command redaction, `target_observed`). Every uncertainty path ends in the existing 1 req/s conservative policy, which already excludes `arjun` and `ffuf` from admission.

**Tech Stack:** Python 3.12, Pydantic v2 (closed contracts, `extra="forbid"`), asyncio, pytest/pytest-asyncio, Vegeta 12.13.0, MCP/Kali exec seam.

**Spec:** `docs/superpowers/specs/2026-09-24-rate-limit-job-admission-e2e-design.md` (resolved decisions and the outcome/failure matrix) and `docs/design/rate-limit-system-mapping-238-spec.md` (failure posture, raw-artifact posture).

## Global Constraints

- Run every command from the worktree root `/home/alelxsalc03/Desktop/powerpoint/polyphemus/.worktrees/rate-limit-job-admission-e2e` with `.venv/bin/python -m pytest ... -q`.
- Branch `feat/rate-limit-job-admission-e2e`, base HEAD `7c443fb4`. One commit per task.
- Every contract in `src/polymerhus/recon/domain/` is CLOSED (`extra="forbid"`): a new field needs a default and a docstring.
- No new runtime dependency. Standard library only.
- Conservative default is unchanged and must stay reachable: rate `1.0` req/s, burst `1`, `max_concurrency 1`, `source="conservative-fallback"`.
- The unit and pipeline tiers must not need a live DB, a Kali host, a model or a Docker stack.
- Domain rule preserved: a `failed` experiment carries a typed error and publishes no artifact reference.
- Wire versions: `rate-result/v1` stays (the added field is additive with default `0`); `rate-profile/v2` and `traffic-policy/v2` are unchanged.
- `no_limiter` means "no transition within the tested bounds", never "no limiter exists".

## Review Focus

These are the inputs the spec implies but no current test exercises. Each one is pinned by a test in the task named next to it.

1. A probe where SOME hits fail at transport level and some return HTTP - it must not count as "accepted" evidence, so it can never lower the measured bound (Task 1, Task 3).
2. A producer that still claims `outcome="measured"` while every hit is a transport failure - the controller must fail closed regardless of the producer (Task 1).
3. A budget that stops the ladder after two accepted rates - inconclusive, never `no_limiter`, never a policy built on an untested bound (Task 3).
4. A tool command carrying a credential in a flag with no pattern-matchable key (`-b 'session=...'`) - value-level redaction from the run's own `auth_context` must catch it (Task 4).
5. A target-facing pod that ran, exited 0 and merged nothing (every connection refused) - `target_observed` must not be emitted (Task 5).

---

## Task 1: A probe with no HTTP response is a typed failure

**Files:**

- Modify: `src/polymerhus/recon/domain/rate_limit.py:340-368` (`ExperimentEvidence`)
- Modify: `src/polymerhus/recon/control/rate_limit_runner.py:146-176` (`evidence_from_kali_result`)
- Test: `tests/recon/test_rate_limit_runner.py` (append after `test_evidence_from_a_failed_kali_result_is_typed_and_unreferenced`)

**Interfaces:**

- Consumes: `ExperimentSpec`, `ExperimentEvidence` (existing).
- Produces: `ExperimentEvidence.transport_errors: int` (default `0`); `evidence_from_kali_result(spec, payload) -> ExperimentEvidence` returns `outcome="failed"` whenever the payload carries no valid HTTP status, even if the payload says `outcome="measured"`.

This is the controller-side defence: it protects the run against an unfixed or older Kali runner. Task 2 makes the producer itself honest.

- [ ] **Step 1: Write the failing test**

Append to `tests/recon/test_rate_limit_runner.py`:

```python
def test_transport_only_evidence_is_a_typed_failure_not_a_measurement():
    """Kills: "connection refused counts as an accepted probe".

    Zero valid HTTP responses is the ABSENCE of a measurement. If it reaches
    the classifier as `measured`, two accepted rates are enough for
    `no_limiter` - and a target the probe never reached gets a 20 req/s policy.
    """
    spec = ExperimentSpec(
        experiment_id="steady-0", phase="steady", url="https://t.example/",
        rate_per_s=5.0, duration_s=3.0, requests=15,
    )
    payload = {
        "experiment_id": "steady-0",
        "phase": "steady",
        "outcome": "measured",            # the producer's (unfixed) claim
        "count": 15,
        "duration_s": 3.0,
        "offered_rate_per_s": 5.0,
        "concurrent_workers": 1,
        "status_counts": {"0": 15},       # every hit is a transport failure
        "rejection_ratio": 0.0,
        "error": "dial tcp: connection refused",
    }

    evidence = evidence_from_kali_result(spec, payload)

    assert evidence.outcome == "failed"
    assert evidence.status_counts == {}
    assert evidence.transport_errors == 15
    assert evidence.error and "HTTP" in evidence.error


def test_partially_failed_transport_keeps_the_http_fraction_visible():
    """A probe that reached the target AND lost hits is measured, but the lost
    hits stay countable: the classifier refuses to call it an acceptance."""
    spec = ExperimentSpec(
        experiment_id="steady-1", phase="steady", url="https://t.example/",
        rate_per_s=2.0, duration_s=3.0, requests=6,
    )
    payload = {
        "experiment_id": "steady-1", "phase": "steady", "outcome": "measured",
        "count": 6, "duration_s": 3.0, "offered_rate_per_s": 2.0,
        "concurrent_workers": 1,
        "status_counts": {"200": 4, "0": 2},
        "rejection_ratio": 0.0,
    }

    evidence = evidence_from_kali_result(spec, payload)

    assert evidence.outcome == "measured"
    assert evidence.status_counts == {"200": 4}
    assert evidence.transport_errors == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/recon/test_rate_limit_runner.py::test_transport_only_evidence_is_a_typed_failure_not_a_measurement \
  tests/recon/test_rate_limit_runner.py::test_partially_failed_transport_keeps_the_http_fraction_visible -q
```

Expected: both FAIL. The first on `evidence.outcome == "measured"` (and a missing `transport_errors` attribute); the second on the missing attribute.

- [ ] **Step 3: Add the field to the domain contract**

In `src/polymerhus/recon/domain/rate_limit.py`, inside `ExperimentEvidence`, directly after `status_counts`:

```python
    transport_errors: int = Field(default=0, ge=0)
    """Hits that never produced an HTTP response (DNS/TLS/connect/timeout).

    These are NOT HTTP statuses. A probe whose every hit is a transport error
    is the ABSENCE of a measurement, never an acceptance, and a probe that lost
    some hits can never be read as "the target accepted this rate".
    """
```

- [ ] **Step 4: Implement the boundary rule**

In `src/polymerhus/recon/control/rate_limit_runner.py`, add this helper directly above `evidence_from_kali_result`:

```python
def _is_http_status(key: object) -> bool:
    """A real HTTP status code. Vegeta writes a synthetic `0` for a hit that
    never got a response; that is a transport failure, not a status."""
    text = str(key)
    return len(text) == 3 and text.isdigit() and text[0] != "0"


def _http_status_counts(raw: object) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in dict(raw or {}).items()
        if _is_http_status(key)
    }
```

Then replace the body of `evidence_from_kali_result` with:

```python
def evidence_from_kali_result(spec: ExperimentSpec, payload: Mapping) -> ExperimentEvidence:
    """Translate the Kali runner's compact result into domain evidence.

    Aggregates, fingerprints and references only: the raw hit stream stays on
    the Kali data root, addressed by `artifact_ref` and pinned by
    `manifest_sha256`.

    The payload is NOT trusted about what "measured" means. No valid HTTP
    response means no measurement: the probe is a typed failure, because
    "the target never answered" and "the target accepted everything" are two
    different facts and only one of them may feed a traffic policy.
    """
    failed = str(payload.get("outcome") or "measured") == "failed"
    status_counts = _http_status_counts(payload.get("status_counts"))
    transport_errors = int(payload.get("transport_errors") or 0)
    requests = int(payload.get("count") or 0)
    common = dict(
        experiment_id=str(payload.get("experiment_id") or spec.experiment_id),
        phase=spec.phase,
        offered_rate_per_s=float(payload.get("offered_rate_per_s") or spec.rate_per_s),
        requests=requests,
        concurrent_workers=int(payload.get("concurrent_workers") or spec.concurrency),
        duration_s=float(payload.get("duration_s") or spec.duration_s),
    )
    if failed:
        return ExperimentEvidence(
            **common,
            transport_errors=transport_errors,
            outcome="failed",
            error=payload.get("error") or None,
        )
    if not status_counts:
        return ExperimentEvidence(
            **common,
            status_counts={},
            transport_errors=transport_errors or requests,
            outcome="failed",
            error=(
                "no HTTP response: the probe produced only transport-level "
                f"failures ({payload.get('error') or 'no detail'})"
            ),
        )
    return ExperimentEvidence(
        **common,
        status_counts=status_counts,
        transport_errors=transport_errors,
        rejection_ratio=float(payload.get("rejection_ratio") or 0.0),
        latency_p50_ms=payload.get("latency_p50_ms"),
        latency_p95_ms=payload.get("latency_p95_ms"),
        burst_accepted=payload.get("burst_accepted"),
        header_fingerprint=[str(item) for item in payload.get("header_fingerprint") or []],
        body_fingerprint=[str(item) for item in payload.get("body_fingerprint") or []],
        artifact_ref=payload.get("artifact_ref") or None,
        manifest_sha256=payload.get("manifest_sha256") or None,
        outcome="measured",
        error=payload.get("error") or None,
    )
```

Note the deliberate asymmetry: a transport-only failure carries NO artifact
reference, matching the domain rule that a failed experiment publishes nothing.
The raw hits stay on the Kali data root; this profile simply does not advertise
them.

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/recon/test_rate_limit_runner.py -q
```

Expected: PASS, including the pre-existing
`test_evidence_from_kali_result_keeps_only_aggregates_and_references`.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/recon/domain/rate_limit.py \
        src/polymerhus/recon/control/rate_limit_runner.py \
        tests/recon/test_rate_limit_runner.py
git commit -m "fix(recon): a probe with no HTTP response is not a measurement"
```

---

## Task 2: The Kali runner reports transport errors instead of a synthetic status

**Files:**

- Modify: `kali/rate_limit/models.py:96-137` (`KaliExperimentResult`)
- Modify: `kali/rate_limit/runner.py:210-232` (`_metrics`)
- Modify: `kali/rate_limit/runner.py:251-258` (`_failure`)
- Modify: `kali/rate_limit/runner.py:349-395` (`run_experiment` publication guard)
- Test: `tests/kali/test_rate_limit_runner.py` (append after `test_runner_compacts_hits_and_publishes_an_artifact`)

**Interfaces:**

- Consumes: Task 1's `transport_errors` field name (same key on both sides of the wire).
- Produces: `KaliExperimentResult.transport_errors: int` (default `0`); `_metrics(hits)` returns `status_counts` with HTTP statuses only plus a separate `transport_errors`; `run_experiment(...)` returns a typed failure and publishes NO artifact when `status_counts` is empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/kali/test_rate_limit_runner.py`:

```python
def _transport_error_jsonl(count: int = 5) -> str:
    hits = [
        {
            "attack": "GET http://rate-matrix-no-limiter/",
            "seq": seq,
            "code": 0,
            "timestamp": "2025-01-01T00:00:00.000000000Z",
            "latency": 1_000_000,
            "bytes_out": 0,
            "bytes_in": 0,
            "error": "dial tcp: connection refused",
            "body": "",
            "headers": {},
        }
        for seq in range(count)
    ]
    return "\n".join(json.dumps(hit) for hit in hits)


def test_a_transport_only_probe_fails_and_publishes_nothing(tmp_path):
    """Kills: "status 0 is a status".

    An unreachable target produced no HTTP response at all. Reporting that as
    `measured` with `{"0": N}` is exactly what let the classifier read an
    unreachable target as `no_limiter`.
    """
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun(jsonl=_transport_error_jsonl(5))

    result = runner_module.run_experiment(
        _spec(requests=5), run=run, store=store, workdir_root=str(tmp_path / "work")
    )

    assert result["outcome"] == "failed"
    assert result["status_counts"] == {}
    assert result["transport_errors"] == 5
    assert result["artifact_ref"] is None
    assert "HTTP" in (result["error"] or "")


def test_a_mixed_probe_keeps_http_statuses_and_counts_the_lost_hits(tmp_path):
    hits = _hit_jsonl().splitlines() + _transport_error_jsonl(2).splitlines()
    store = RateLimitArtifactStore(tmp_path)
    run = _FakeRun(jsonl="\n".join(hits))

    result = runner_module.run_experiment(
        _spec(), run=run, store=store, workdir_root=str(tmp_path / "work")
    )

    assert result["outcome"] == "measured"
    assert result["status_counts"] == {"200": 1, "429": 1}
    assert result["transport_errors"] == 2
    assert "0" not in result["status_counts"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/kali/test_rate_limit_runner.py::test_a_transport_only_probe_fails_and_publishes_nothing \
  tests/kali/test_rate_limit_runner.py::test_a_mixed_probe_keeps_http_statuses_and_counts_the_lost_hits -q
```

Expected: both FAIL - `transport_errors` does not exist yet and `{"0": 5}` is
reported as `status_counts`.

- [ ] **Step 3: Add the field to the Kali wire contract**

In `kali/rate_limit/models.py`, inside `KaliExperimentResult`, directly after `status_counts`:

```python
    transport_errors: int = Field(default=0, ge=0)
    """Hits that never produced an HTTP response (DNS/TLS/connect/timeout).
    `status_counts` carries HTTP statuses only; a synthetic `0` is never a
    status. A result whose every hit is a transport error is a `failed`
    experiment, not a measurement."""
```

- [ ] **Step 4: Split the metrics**

In `kali/rate_limit/runner.py`, replace `_metrics` with:

```python
def _metrics(hits: Sequence[Mapping]) -> dict:
    total = len(hits)
    status_counts: dict[str, int] = {}
    transport_errors = 0
    for hit in hits:
        code = int(hit.get("code", 0) or 0)
        if code >= 100:
            key = str(code)
            status_counts[key] = status_counts.get(key, 0) + 1
        else:
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
```

- [ ] **Step 5: Let a failure carry the transport count**

In `kali/rate_limit/runner.py`, replace `_failure` with:

```python
def _failure(
    parsed: KaliExperimentSpec, error: str, *, transport_errors: int = 0
) -> dict:
    result = KaliExperimentResult(
        experiment_id=parsed.experiment_id,
        phase=parsed.phase,
        offered_rate_per_s=parsed.rate_per_s,
        concurrent_workers=parsed.concurrency,
    ).failure(error)
    if transport_errors:
        result = result.model_copy(update={"transport_errors": transport_errors})
    return result.model_dump(mode="json")
```

- [ ] **Step 6: Refuse to publish a probe that reached nothing**

In `kali/rate_limit/runner.py`, inside `run_experiment`, insert this guard directly
after `metrics = _metrics(hits)` and before the `aggregate` block:

```python
        if not metrics["status_counts"]:
            # No HTTP response at all: the target was never measured. Publishing
            # this as `measured` is what allowed an unreachable target to be
            # classified as "no limiter" and receive a 20 req/s policy.
            return _failure(
                parsed,
                "no HTTP response: "
                f"{metrics['transport_errors']} transport-level failures, "
                "zero valid HTTP statuses",
                transport_errors=metrics["transport_errors"],
            )
```

- [ ] **Step 7: Run the tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/kali/test_rate_limit_runner.py tests/kali/test_rate_limit_store.py -q
```

Expected: PASS. The pre-existing
`test_runner_compacts_hits_and_publishes_an_artifact` still passes because
`_hit_jsonl()` contains only real statuses.

- [ ] **Step 8: Commit**

```bash
git add kali/rate_limit/models.py kali/rate_limit/runner.py \
        tests/kali/test_rate_limit_runner.py
git commit -m "fix(kali): report transport failures separately and fail on zero HTTP responses"
```

---

## Task 3: `no_limiter` is reserved for a clean, fully walked ladder

**Files:**

- Modify: `src/polymerhus/recon/control/rate_limit_mapper.py:473-545` (`classify_mapping`)
- Modify: `src/polymerhus/recon/control/rate_limit_mapper.py` (new pure `ladder_exhausted`, above `classify_mapping`)
- Modify: `src/polymerhus/recon/control/rate_limit_runner.py:424-438` (`RateLimitHarness._finish`)
- Modify: `src/polymerhus/recon/control/rate_limit_runner.py:718-728` (`__all__`)
- Test: `tests/recon/test_rate_limit_mapper.py`, `tests/recon/test_rate_limit_runner.py`

**Interfaces:**

- Consumes: `ExperimentEvidence.transport_errors` (Task 1), `MappingState`, `RateLimitSafetyBudget`, `_ladder`.
- Produces: `ladder_exhausted(evidence, budget) -> bool` (pure, exported); `classify_mapping` never returns `no_limiter` when any measured probe lost hits at transport level; `RateLimitHarness._finish` downgrades `no_limiter` to `inconclusive` when the rate ladder was not fully walked, which routes the policy through `RateProfile.conservative`.

- [ ] **Step 1: Write the failing mapper test**

Append to `tests/recon/test_rate_limit_mapper.py`:

```python
def test_a_transport_degraded_ladder_is_inconclusive_not_no_limiter():
    """Kills: "a probe that lost half its hits proves the target accepted it".

    Two rates were offered, nothing was refused, and every probe dropped hits
    on the floor. The honest reading is "unknown", not "no limiter".
    """
    evidence = [
        _ev("steady-0", "steady", 1.0, requests=10, codes={"200": 8, "0": 2}),
        _ev("steady-1", "steady", 2.0, requests=10, codes={"200": 7, "0": 3}),
    ]
    for item in evidence:
        item.transport_errors = sum(
            count for key, count in item.status_counts.items() if key == "0"
        )

    control = classify_mapping(evidence)

    assert control.outcome == "inconclusive"
    assert control.signals == []
```

Note: `_ev` builds `status_counts` directly. Adding a `transport_errors: int = 0`
parameter to the `_ev` helper and passing it is an equally good shape; either
way the evidence must carry a nonzero `transport_errors` when it reaches
`classify_mapping`.

- [ ] **Step 2: Write the failing runner tests**

Append to `tests/recon/test_rate_limit_runner.py`:

```python
def test_a_partial_ladder_is_never_no_limiter_however_many_rates_it_tested():
    """Kills: "two accepted rates are enough to call it no_limiter".

    The ladder is 1/2/5/10/20 req/s. This budget fits the baseline and the two
    cheapest steady steps and then runs out: the evidence says "accepted at 1
    and 2", NOT "no limiter up to 20". The profile must be inconclusive under
    the conservative policy, so no intensive runner is admitted from an
    untested bound.
    """
    executor = RecordingExecutor()
    harness = _harness(
        executor,
        budget=RateLimitSafetyBudget(
            max_requests=11, max_duration_s=8, max_concurrency=1
        ),
    )

    control = _run(harness.map())

    assert control.outcome == "inconclusive"
    assert control.traffic_policy is not None
    assert control.traffic_policy.source == "conservative-fallback"
    assert control.traffic_policy.rate_per_s <= 1.0


def test_a_fully_walked_ladder_still_earns_no_limiter():
    """The positive control: the guard must not make `no_limiter`
    unreachable. With the default budget the whole 1/2/5/10/20 ladder is
    walked, so the outcome and the tested-max policy stand."""
    executor = RecordingExecutor()
    harness = _harness(executor)

    control = _run(harness.map())

    assert control.outcome == "no_limiter"
    assert control.tested_max_rate_per_s == 20.0
    assert control.traffic_policy is not None
    assert control.traffic_policy.source == "measured-no-limiter"
    assert control.traffic_policy.rate_per_s == 20.0
```

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/recon/test_rate_limit_mapper.py::test_a_transport_degraded_ladder_is_inconclusive_not_no_limiter \
  tests/recon/test_rate_limit_runner.py::test_a_partial_ladder_is_never_no_limiter_however_many_rates_it_tested -q
```

Expected: both FAIL (`no_limiter` today). The positive control
`test_a_fully_walked_ladder_still_earns_no_limiter` PASSES already; it exists to
prove the fix does not break the happy path.

- [ ] **Step 4: Make the classifier refuse degraded acceptance**

In `src/polymerhus/recon/control/rate_limit_mapper.py`, inside `classify_mapping`, replace the `accepted` computation with:

```python
    accepted = [
        item
        for item in ladder
        if item.rejection_ratio <= _EPSILON and item.transport_errors == 0
    ]
    degraded_transport = any(item.transport_errors > 0 for item in measured)
```

and change the outcome branch to:

```python
    if inconsistent:
        outcome = "inconclusive"
    elif refused or concurrency_limited:
        outcome = "mapped"
    elif len(distinct_rates) >= 2 and not degraded_transport:
        outcome = "no_limiter"
    else:
        outcome = "inconclusive"
```

A refusal is still positive evidence (it comes from the target), so a `mapped`
transition with some transport noise stays `mapped`.

- [ ] **Step 5: Add the ladder-exhaustion predicate**

In `src/polymerhus/recon/control/rate_limit_mapper.py`, directly above `classify_mapping`:

```python
def ladder_exhausted(
    evidence: Sequence[ExperimentEvidence], budget: RateLimitSafetyBudget
) -> bool:
    """True iff every rate the operator's budget permits was actually offered
    and measured at steady state.

    `no_limiter` means "no transition within the TESTED bounds". A ladder that
    stopped at 2 req/s because the request budget ran out supports no claim
    about 5, 10 or 20 req/s, and the derived policy would be built on a bound
    nobody exercised.
    """
    tested = {
        round(item.offered_rate_per_s, 4)
        for item in evidence
        if item.phase == "steady" and item.outcome == "measured"
    }
    return all(round(rate, 4) in tested for rate in _ladder(budget))
```

Add `"ladder_exhausted"` to the module's `__all__`.

- [ ] **Step 6: Enforce it in the harness**

In `src/polymerhus/recon/control/rate_limit_runner.py`, add `ladder_exhausted` to
the existing named import block:

```python
from polymerhus.recon.control.rate_limit_mapper import (
    STEADY_DURATION_S,
    BudgetLedger,
    MappingState,
    ScopeProbe,
    classify_mapping,
    derive_policy,
    derive_scope,
    judge_bypass,
    ladder_exhausted,
    next_experiment,
)
```

then replace `_finish` with:

```python
    def _finish(self, state: MappingState) -> MappedControl:
        control = classify_mapping(state.evidence)
        if (
            control.outcome == "no_limiter"
            and not ladder_exhausted(state.evidence, self.budget)
        ):
            # The docstring promise, now enforced: a `no_limiter` that did not
            # walk the whole ladder is evidence about the rates tested, not
            # about the target's capacity. Downgrade BEFORE the policy is
            # derived, so the conservative fallback is what governs traffic.
            control = control.model_copy(
                update={"outcome": "inconclusive", "confidence": 0.2}
            )
            self._failure_reason = (
                self._failure_reason or "rate ladder not exhausted by the budget"
            )
        control = control.model_copy(
            update={"scope": derive_scope(state.evidence, state.scope_probes)}
        )
        control = control.model_copy(
            update={
                "traffic_policy": derive_policy(
                    control,
                    self.budget,
                    target_key=self.target_key,
                    host_patterns=self.host_patterns,
                )
            }
        )
        self._control = control
        return control
```

- [ ] **Step 7: Run the tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest \
  tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py -q
```

Expected: PASS, including the pre-existing
`test_a_truncated_ladder_is_inconclusive_not_no_limiter` and
`test_no_transition_through_the_tested_maximum_is_no_limiter`.

- [ ] **Step 8: Commit**

```bash
git add src/polymerhus/recon/control/rate_limit_mapper.py \
        src/polymerhus/recon/control/rate_limit_runner.py \
        tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py
git commit -m "fix(recon): no_limiter requires a clean, fully walked rate ladder"
```

---

## Task 4: Redact credentials before they are persisted

**Files:**

- Create: `src/polymerhus/recon/domain/redaction.py`
- Modify: `src/polymerhus/recon/control/pipeline.py` (domain import block, currently lines 52-61)
- Modify: `src/polymerhus/recon/control/pipeline.py:981-987` (the `commands` fold into `job_stats`)
- Test: `tests/recon/test_redaction.py` (new)
- Test: `tests/recon/test_pipeline.py:683-711` (extend `test_job_stats_include_per_pod_commands`)

**Interfaces:**

- Produces: `redact_command(command: str, *, secrets: Sequence[str] = ()) -> str`; `secret_values_from_auth_context(context: Mapping | None) -> tuple[str, ...]`; `REDACTED = "[redacted]"`.
- Consumes: `extra["auth_context"]` in both shapes the pipeline builds - the flat request projection (`{"cookies": [{"name", "value"}, ...], "<Header-Name>": "<value>", ...}`) and the browser path (`{"cookies": [...]}`).

- [ ] **Step 1: Write the failing redaction tests**

Create `tests/recon/test_redaction.py`:

```python
"""#238 P0 - persisted run state never carries a credential.

`recon_jobs.stats` is durable, versioned state. Redacting logs is not enough:
a command stored there is a leak whether or not a log line also had it.
"""
from __future__ import annotations

from polymerhus.recon.domain.redaction import (
    REDACTED,
    redact_command,
    secret_values_from_auth_context,
)


def test_a_known_secret_is_replaced_wherever_it_appears():
    """The `-b` cookie flag carries no key to pattern-match, so the run's own
    auth context is the only thing that makes it safe to persist."""
    command = "httpx -u http://t.example -b 'session=sentinel-cookie' -silent"

    redacted = redact_command(command, secrets=("sentinel-cookie",))

    assert "sentinel-cookie" not in redacted
    assert REDACTED in redacted


def test_sensitive_keys_are_scrubbed_even_without_a_known_value():
    command = (
        "arjun -u http://t.example -H 'Authorization: Bearer unknown-token' "
        "-H 'X-Api-Key: unknown-key' --headers 'Cookie: sid=unknown-sid'"
    )

    redacted = redact_command(command)

    for leaked in ("unknown-token", "unknown-key", "unknown-sid"):
        assert leaked not in redacted


def test_a_benign_command_survives_redaction_unchanged():
    command = "subfinder -d example.com -all -json -silent"

    assert redact_command(command) == command


def test_secret_values_are_read_from_the_flat_auth_projection_and_cookies():
    context = {
        "Authorization": "Bearer sentinel-header",
        "cookies": [
            {"name": "session", "value": "sentinel-cookie"},
            {"name": "other", "value": ""},
        ],
    }

    values = secret_values_from_auth_context(context)

    assert "sentinel-header" in values
    assert "sentinel-cookie" in values


def test_a_malformed_auth_context_yields_no_secrets_instead_of_raising():
    assert secret_values_from_auth_context(None) == ()
    assert secret_values_from_auth_context({"cookies": "not-a-list"}) == ()
```

- [ ] **Step 2: Write the failing pipeline test**

In `tests/recon/test_pipeline.py`, extend `test_job_stats_include_per_pod_commands`.
Keep its `FakeRegistry`, but make the fake command credential-bearing:

```python
    async def fake_run_job(job, input_assets, *, run_id, phase, extra, prepared_pod_inputs=None):
        return [
            PodExport(
                input_asset=input_assets[0], verdict="success",
                stats={
                    "command": (
                        "httpx -d example.com -b 'session=e2e-session-sentinel' "
                        "-H 'Authorization: Bearer e2e-rate-sentinel' -silent"
                    )
                },
            ),
        ]
```

and add these assertions:

```python
    command = captured["subfinder"]["commands"][0]
    assert "e2e-session-sentinel" not in command
    assert "e2e-rate-sentinel" not in command
    assert command.startswith("httpx -d example.com")
    assert "[redacted]" in command
```

Both sentinels sit behind a pattern-matchable key (`-b` on a session cookie,
`Authorization:` on a bearer header), so the test holds with or without an
`auth_context`. Do not weaken the assertions if the fake job resolves no account.

- [ ] **Step 3: Run the tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/recon/test_redaction.py \
  tests/recon/test_pipeline.py::test_job_stats_include_per_pod_commands -q
```

Expected: `test_redaction.py` errors on import (module missing);
`test_job_stats_include_per_pod_commands` FAILS because the credential is stored
verbatim.

- [ ] **Step 4: Create the redaction module**

Create `src/polymerhus/recon/domain/redaction.py`:

```python
"""Secret redaction for PERSISTED run state.

`recon_jobs.stats` is durable, versioned state: a credential that reaches it is
a leak whether or not a log line also carried it. This module is the single
place where a tool command is made safe to persist.

Two layers, both needed:

* VALUE replacement - the run knows the exact credential values it handed the
  pod (`auth_context`), so those are replaced verbatim, wherever they appear.
  This is the only layer that can catch a cookie value behind `-b 'session=...'`
  when the flag name is not in the pattern table.
* PATTERN scrubbing - a command may carry a credential this run never saw (a
  tool's own token argument), so `key: value` and `key=value` shapes with a
  credential-shaped key are scrubbed too.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

REDACTED = "[redacted]"

_SENSITIVE_KEY = (
    r"authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[-_]?key|"
    r"x-auth-token|access[-_]?token|refresh[-_]?token|id[-_]?token|token|"
    r"password|passwd|secret"
)
_KV_RE = re.compile(
    rf"(?i)(\b(?:{_SENSITIVE_KEY})\b\s*[:=]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s;&|'\"]+)"
)


def secret_values_from_auth_context(context: Mapping | None) -> tuple[str, ...]:
    """The credential VALUES the pipeline handed this job's pod.

    Key-directed on purpose: `auth_context` is a flat header projection (every
    top-level string is a header value, hence credential-bearing) plus a
    `cookies` list whose `value` entries are opaque. Nothing else is treated as
    a secret, so a benign value cannot mangle an unrelated command.
    """
    if not isinstance(context, Mapping):
        return ()
    values: list[str] = []
    for key, item in context.items():
        if str(key).lower() == "cookies":
            if isinstance(item, (list, tuple)):
                values.extend(
                    str(cookie["value"])
                    for cookie in item
                    if isinstance(cookie, Mapping) and cookie.get("value")
                )
            continue
        if isinstance(item, str) and item:
            values.append(item)
    return tuple(dict.fromkeys(values))


def redact_command(command: str, *, secrets: Sequence[str] = ()) -> str:
    """A command string safe to persist in `recon_jobs.stats`."""
    text = str(command or "")
    for secret in secrets:
        if secret:
            text = text.replace(str(secret), REDACTED)
    return _KV_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", text)


__all__ = ["REDACTED", "redact_command", "secret_values_from_auth_context"]
```

- [ ] **Step 5: Redact at the persistence seam**

In `src/polymerhus/recon/control/pipeline.py`, add to the domain import block:

```python
from polymerhus.recon.domain.redaction import (
    redact_command,
    secret_values_from_auth_context,
)
```

and replace the `commands` fold in `_run_one` with:

```python
                # The command is durable run state and carries the credential
                # flags the pod was given. Redact BEFORE persistence: logs being
                # clean does not make stored stats clean.
                auth_secrets = secret_values_from_auth_context(
                    (extra or {}).get("auth_context")
                )
                commands = [
                    redact_command(e.stats.get("command"), secrets=auth_secrets)
                    for e in pod_exports
                    if e.stats and e.stats.get("command")
                ]
                if commands:
                    job_stats["commands"] = commands
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/recon/test_redaction.py tests/recon/test_pipeline.py -q
```

Expected: PASS. A benign command with no sensitive key and no auth context is
persisted unchanged, so the pre-existing exact-value assertion elsewhere in the
file stays valid.

- [ ] **Step 7: Commit**

```bash
git add src/polymerhus/recon/domain/redaction.py \
        src/polymerhus/recon/control/pipeline.py \
        tests/recon/test_redaction.py tests/recon/test_pipeline.py
git commit -m "fix(recon): redact credentials before persisting job commands"
```

---

## Task 5: `target_observed` requires target-derived output

**Files:**

- Modify: `src/polymerhus/recon/control/pipeline.py` (new `_pod_observed_target` helper, after `_exec_window`)
- Modify: `src/polymerhus/recon/control/pipeline.py:937-945` (the `target_observed` emission)
- Test: `tests/recon/test_rate_limit_pipeline.py:594-612` (update the positive helper)
- Test: `tests/recon/test_rate_limit_pipeline.py` (new negative test)

**Interfaces:**

- Consumes: `PodExport` (`verdict`, `assets_merged`, `observations_merged`).
- Produces: `_pod_observed_target(export) -> bool`; `target_observed` is emitted only when a target-facing pod's export proves it obtained target-derived output.

- [ ] **Step 1: Write the failing negative test**

Append to `tests/recon/test_rate_limit_pipeline.py`, next to
`test_the_envelope_records_the_full_run_trajectory`:

```python
def test_a_target_facing_pod_that_merged_nothing_never_claims_target_observed():
    """Kills: "a pod started, therefore the target was observed".

    A target-facing tool whose every connection was refused still returns an
    export and merges nothing. `pod_started` already says it was scheduled;
    `target_observed` must stay a verifiable fact about the TARGET.
    """
    events: list = []
    from polymerhus.recon.domain.traffic_admission import TrafficCostClass
    from polymerhus.recon.domain.types import PodExport

    def _exports_for(job, inputs):
        if job.traffic_cost.cost_class is TrafficCostClass.NON_TARGET:
            return []
        # Ran, exited 0, obtained nothing from the target.
        return [PodExport(input_asset={"name": "app.t.com"}, verdict="success")]

    registry, _ = _run(events, _orchestrator(events), pod_exports_for=_exports_for)

    order = registry.run_stats["traffic_admission"]["event_order"]
    assert "pod_started" in order, order
    assert "target_observed" not in order, order
```

- [ ] **Step 2: Update the positive test so it proves the positive case**

In `test_the_envelope_records_the_full_run_trajectory`, the `_exports_for` helper
returns a bare successful export with zero merges. Change its return value to:

```python
        return [
            PodExport(
                input_asset={"name": "app.t.com"},
                verdict="success",
                assets_merged=1,
            )
        ]
```

Without this, the positive test would stop proving that a real observation IS
recorded - it would either pass for the wrong reason or fail.

- [ ] **Step 3: Run the tests to verify the new one fails**

Run:

```bash
.venv/bin/python -m pytest \
  tests/recon/test_rate_limit_pipeline.py::test_a_target_facing_pod_that_merged_nothing_never_claims_target_observed \
  tests/recon/test_rate_limit_pipeline.py::test_the_envelope_records_the_full_run_trajectory -q
```

Expected: the negative test FAILS (`target_observed` is present today); the
updated positive test PASSES.

- [ ] **Step 4: Implement the predicate and use it**

In `src/polymerhus/recon/control/pipeline.py`, add directly after `_exec_window`:

```python
def _pod_observed_target(export) -> bool:
    """True only when a pod's export proves it obtained TARGET-derived output.

    A pod that ran and merged nothing (a tool whose every connection failed)
    proved nothing about the target. `pod_started` already records the
    scheduling; `target_observed` must stay a verifiable fact about the target,
    not a by-product of the pod's existence.
    """
    return (
        getattr(export, "verdict", "") == "success"
        and (
            int(getattr(export, "assets_merged", 0) or 0)
            + int(getattr(export, "observations_merged", 0) or 0)
        )
        > 0
    )
```

and replace the emission with:

```python
                total = len(pod_exports)
                if (target_facing
                        and any(_pod_observed_target(e) for e in pod_exports)
                        and "target_observed" not in admission_events):
                    # The run's first TARGET-FACING pod returned TARGET-DERIVED
                    # output: the trajectory has observed the target's own
                    # responses. A non-target job proves nothing about the
                    # target, and neither does a target-facing pod that merged
                    # nothing - it never got an answer.
                    admission_events.append("target_observed")
                    await _record_trajectory()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:

```bash
.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py -q
```

Expected: PASS, including `test_a_fully_pruned_run_records_no_pod_start`.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/recon/control/pipeline.py \
        tests/recon/test_rate_limit_pipeline.py
git commit -m "fix(recon): target_observed requires target-derived output"
```

---

## Verification and expected results

### Per-area suites (fast, no stack)

| Command | Expected |
| --- | --- |
| `.venv/bin/python -m pytest tests/kali/test_rate_limit_runner.py tests/kali/test_rate_limit_store.py -q` | green: transport split, zero-HTTP failure, no publication |
| `.venv/bin/python -m pytest tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py tests/recon/test_rate_limit_types.py -q` | green: classification, ladder exhaustion, conservative policy |
| `.venv/bin/python -m pytest tests/recon/test_redaction.py tests/recon/test_pipeline.py tests/recon/test_rate_limit_pipeline.py -q` | green: redaction, trajectory, `target_observed` |

### Whole-feature offline regression

```bash
.venv/bin/python -m pytest tests/recon tests/kali -q
```

Expected: green, with the same skip count as before this plan. The six
pre-existing `tests/integration` failures are unchanged and are NOT part of this
plan's exit criteria; do not "fix" them here.

### What each fix must be observably true about

1. **Transport failure never becomes `no_limiter`.** An unreachable target (DNS,
   TLS, connection refused, blanket timeout) ends as `failed` or `inconclusive`
   with `traffic_policy.source == "conservative-fallback"` and
   `rate_per_s <= 1.0`, so `arjun` and `ffuf` are excluded from admission.
2. **`no_limiter` is bounded.** It can appear only after the whole 1/2/5/10/20
   ladder was measured at steady state with no refusals and no
   transport-degraded probes. Every other combination is `inconclusive`.
3. **No credential is persisted.** `recon_jobs.stats["commands"]` contains no
   known secret value and no credential-shaped `key: value` payload.
4. **`target_observed` is a fact.** It appears only when a target-facing pod
   merged at least one asset or observation; `pod_started` remains the
   scheduling event.

### Live gate dependency (explicit, out of P0 scope)

The functional E2E gate (`tests/e2e/test_rate_limit_admission_e2e.py`) CANNOT be
the evidence for these four items yet: it fails on `PUT /projects/{id}/auth`
with `auth_invalid: overview.target is not a known overview field` before it
reaches rate mapping, admission, pod or target (P1 harness item). P0 is
certified at the unit, contract and pipeline tiers above.

Two honest options, in order of preference:

1. Land the P1 harness fix (auth payload against the public schema, `job`
   instead of `job_name`, `artifact_refs`/`evidence`) and re-run the live matrix,
   where the transport-failure row must show `failed`/`inconclusive` with zero
   intensive traffic.
2. If a live proof is needed before the harness fix, run the same unreachable
   target through an UNAUTHENTICATED project (no `store_auth` call), so only
   `_rate_request_headers` returns `{}`. The same four observations must hold;
   record explicitly that the authenticated phase was not exercised.

Never certify P0 from a mocked Kali seam alone.
