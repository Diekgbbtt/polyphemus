# Rate-Limit Job Admission and QA E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authenticated rate-limit posture deterministically admit or prune request-intensive recon jobs before materialization, enforce the resulting rate and concurrency fail-closed in Kali, and prove the full production trajectory with deterministic functional E2E tests.

**Architecture:** The controller owns a typed job-cost catalogue, derives each job's canonical consumption set once, and persists an immutable admission decision before any runner starts. Kali receives only a versioned, validated policy and an already materialized request; its shared governor enforces both token rate and in-flight concurrency, while an OpenAI-compatible local fixture drives the real actor loop in E2E without giving the model policy authority.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, LangGraph, FastAPI, PostgreSQL JSONB, MCP, mitmproxy, Docker Compose, pytest/pytest-asyncio, Vegeta 12.13.0.

**Spec:** `docs/superpowers/specs/2026-09-24-rate-limit-job-admission-e2e-design.md`

## Global Constraints

- No new actor and no new LLM node may decide rate, concurrency, budgets, or phase composition.
- A bypass is evidence only: it never changes admission, policy limits, or the materialized phase list.
- `TrafficCostClass` is mandatory on every canonical `JobSpec`; `arjun` and `ffuf` are `request_intensive`.
- Admission uses both `safe_rate_per_s` and `projected_duration_s = estimated_requests / safe_rate_per_s`.
- `RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S` defaults to `2.0`; `RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S` defaults to `300`; both must be finite and greater than zero or startup fails.
- A request-intensive job is admitted only when `safe_rate_per_s >= 2.0` and `projected_duration_s <= 300` using the effective validated configuration.
- `failed`, `inconclusive`, stale, missing-policy, and invalid-cost states prune request-intensive jobs; bounded work continues only with the conservative policy.
- Pruning occurs after canonical consumption derivation and before `job_configs`, pod creation, runner invocation, or target traffic.
- With an armed policy, governor failure or unavailability produces a loud local refusal and no target egress.
- `KALI_HTTP_CAPTURE_ENABLED=false` disables storage only; it never disables governance.
- Governor sharing is keyed by `(project_id, target_key)` and must not depend on `source_ip`.
- Raw results and credentials never enter profiles, stats, logs, prompts, or versioned documents.
- Issue #238 evidence remains capped and secret-safe and is referenced only by relative path plus SHA-256.
- Wire contracts advance together to `rate-profile/v2` and `traffic-policy/v2`; mixed unsupported versions are refused.
- The functional E2E must use the real API, actor/tool loop, pipeline, pod, MCP/Kali proxy, governor, target, PostgreSQL stats, and output path; direct MCP-only and fake-runner tests do not satisfy this gate.

## Review Focus

- Empty canonical consumption sets must produce a stable zero-request admission record without dividing by zero or starting an intensive runner; Task 2 pins this.
- Boundary values (`safe_rate_per_s == minimum` and `projected_duration_s == maximum`) must be admitted, while the next representable failing values are pruned; Task 2 pins this.
- A cancellation or exception after acquiring a concurrency permit must release exactly once and never leak capacity; Task 6 pins this.
- A profile that expires between mapping and phase materialization must be treated as stale at admission time, not accepted because it was fresh when first read; Tasks 3 and 4 pin this.
- A missing or cardinality-mismatched ffuf wordlist must fail readiness and prune/refuse execution rather than silently underestimating cost; Task 7 pins this.

---

## File Structure

New focused modules:

- `src/polymerhus/recon/domain/traffic_admission.py`: closed admission contracts, reason codes, configuration, and pure decision function.
- `src/polymerhus/recon/control/traffic_admission.py`: canonical input preparation, cost estimation, phase pruning, envelope assembly, and persistence adapter.
- `src/polymerhus/recon/control/request_mutation.py`: typed mutation union and pure `EffectiveRequest` materialization.
- `tests/e2e/rate_limit_matrix_target.py`: one deterministic target application parameterized into isolated posture instances.
- `tests/e2e/deterministic_llm_provider.py`: local OpenAI-compatible provider that returns deterministic production tool calls and triage results.
- `tests/e2e/failing_governor_addon_entry.py`: E2E-only addon composition that injects a throwing governor without a production fault switch.
- `tests/e2e/test_rate_limit_admission_e2e.py`: black-box API trajectory, posture matrix, admission, enforcement, persistence, and secret-safety assertions.

Existing ownership points to modify:

- `src/polymerhus/recon/domain/types.py` and `src/polymerhus/recon/control/jobs.py`: canonical job cost declarations.
- `src/polymerhus/recon/domain/rate_limit.py`, `rate_limit_mapper.py`, and `rate_limit_runner.py`: v2 profile/policy/evidence and typed request variants.
- `src/polymerhus/recon/control/job_agent.py` and `pipeline.py`: single canonical preprocessing pass and pre-run pruning.
- `src/polymerhus/recon/domain/pod.py`: unchanged authority boundary but strengthened mandatory policy forwarding tests.
- `kali/rate_limit/models.py` and `runner.py`: receive the effective request rather than rediscovering mutations.
- `kali/http_history/governor.py`, `addon.py`, `addon_entry.py`, `service.py`, and `kali/mcp_server.py`: shared concurrency permits, fail-closed refusal, and runtime capability reporting.
- `Dockerfile.kali`, `docker-compose.yml`, and `docker-compose.e2e.yml`: reproducible binary metadata, validated configuration, and isolated fixtures.
- Existing unit, contract, and integration tests named in each task remain fast gates; the new functional suite is a separate live gate.

## Dependency Order

Tasks 1–4 establish controller admission. Task 5 completes request mutation before Task 6 hardens the governor. Task 7 makes the runtime reproducible. Tasks 8–9 build the deterministic E2E environment. Tasks 10–11 prove the complete behavior. Task 12 converges documentation and runs the full release gate. Do not start Tasks 10–11 before Tasks 1–9 are green.

### Task 1: Typed Job Cost Catalogue and Validated Admission Configuration

**Files:**
- Create: `src/polymerhus/recon/domain/traffic_admission.py`
- Modify: `src/polymerhus/recon/domain/types.py:124-158`
- Modify: `src/polymerhus/recon/control/jobs.py:18-384`
- Modify: `src/polymerhus/recon/config.py`
- Test: `tests/recon/test_jobs.py`
- Create: `tests/recon/test_traffic_admission_config.py`

**Interfaces:**
- Produces: `TrafficCostClass(StrEnum)` with `NON_TARGET`, `BOUNDED_HTTP`, `REQUEST_INTENSIVE`.
- Produces: `JobTrafficCost(BaseModel)` with `cost_class`, `estimated_requests_per_input`, `estimation_basis`, and optional `cardinality_source`.
- Produces: mandatory `JobSpec.traffic_cost: JobTrafficCost`.
- Produces: `TrafficAdmissionSettings.from_env(env: Mapping[str, str] | None = None) -> TrafficAdmissionSettings` with `min_safe_rate_per_s: float = 2.0` and `max_projected_duration_s: float = 300.0`.
- Consumers: Task 2 uses these types without job-name checks; Task 7 resolves `cardinality_source` for ffuf.

- [ ] **Step 1: Write failing catalogue and configuration tests**

Add table-driven assertions that every `JOBS` entry has an explicit class, `arjun` and `ffuf` are intensive, the remaining current jobs match the approved classification, and invalid values (`0`, negatives, `nan`, `inf`, non-numeric strings) raise `ValueError` naming the variable. Pin exact defaults and env overrides:

```python
def test_every_job_declares_a_typed_cost_class():
    assert set(JOBS) == set(EXPECTED_COST_CLASS)
    assert {name: spec.traffic_cost.cost_class for name, spec in JOBS.items()} == EXPECTED_COST_CLASS

@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "not-a-number"])
def test_invalid_min_rate_fails_startup(value):
    with pytest.raises(ValueError, match="RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S"):
        TrafficAdmissionSettings.from_env({"RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S": value})
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/recon/test_jobs.py tests/recon/test_traffic_admission_config.py -q`

Expected: collection/import failure because `TrafficCostClass`, `JobTrafficCost`, and `TrafficAdmissionSettings` do not exist.

- [ ] **Step 3: Add the closed types and strict environment parser**

Implement finite-positive parsing with `math.isfinite`, forbid extra fields, and make `traffic_cost` required with no default. Wire `TrafficAdmissionSettings.from_env()` into the existing startup configuration construction in `src/polymerhus/recon/config.py` so invalid process configuration fails before a run can start.

Use these exact declarations:

```python
class TrafficCostClass(StrEnum):
    NON_TARGET = "non_target"
    BOUNDED_HTTP = "bounded_http"
    REQUEST_INTENSIVE = "request_intensive"

class JobTrafficCost(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cost_class: TrafficCostClass
    estimated_requests_per_input: PositiveInt
    estimation_basis: Literal["fixed", "wordlist_cardinality"]
    cardinality_source: str | None = None
```

- [ ] **Step 4: Classify every canonical job explicitly**

Set `arjun` to `estimated_requests_per_input=260` with `estimation_basis="fixed"`. Set `ffuf` to `request_intensive`, `estimation_basis="wordlist_cardinality"`, and `cardinality_source="/usr/share/seclists/Discovery/Web-Content/common.txt"`. During the image-backed contract step, compute the exact constant with `python3 -c 'from pathlib import Path; print(sum(bool(line) for line in Path("/usr/share/seclists/Discovery/Web-Content/common.txt").read_text().splitlines()))'` inside the built image, then commit that integer as `estimated_requests_per_input`; the contract must rerun the same non-empty-line rule. Mark `httpx`, `httpx_services`, `httpx_reprofile`, `katana`, `kiterunner`, `jsluice`, `graphql-cop`, and `steel_crawl` as `bounded_http`; mark the remaining current jobs as `non_target`. Remove the obsolete ffuf “unthrottled” description.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/recon/test_jobs.py tests/recon/test_traffic_admission_config.py -q`

Expected: PASS, including startup rejection for every invalid environment value.

- [ ] **Step 6: Commit the slice**

```bash
git add src/polymerhus/recon/config.py src/polymerhus/recon/domain/traffic_admission.py src/polymerhus/recon/domain/types.py src/polymerhus/recon/control/jobs.py tests/recon/test_jobs.py tests/recon/test_traffic_admission_config.py
git commit -m "feat(recon): type job traffic costs"
```

**Acceptance:** No canonical job can be constructed without a typed cost. No sparse list of intensive or HTTP job names remains. Effective threshold values are deterministic and startup-validated.

### Task 2: Pure Admission Decision and Persistent Envelope Contracts

**Files:**
- Modify: `src/polymerhus/recon/domain/traffic_admission.py`
- Create: `src/polymerhus/recon/control/traffic_admission.py`
- Create: `tests/recon/test_traffic_admission.py`

**Interfaces:**
- Consumes: `JobSpec.traffic_cost` and `TrafficAdmissionSettings` from Task 1.
- Produces: `AdmissionReason(StrEnum)` values `admitted`, `profile_inconclusive`, `profile_failed`, `profile_stale`, `below_min_safe_rate`, `projected_duration_exceeded`, `cost_model_invalid`, `policy_missing`, `governor_refused`.
- Produces: `AdmissionContext(profile_status, safe_rate_per_s, profile_fresh, policy_present, evaluated_at)`.
- Produces: `AdmissionDisposition(StrEnum)` values `included` and `excluded`.
- Produces: `JobAdmissionDecision(phase, job_name, cost_class, input_count, estimated_requests, safe_rate_per_s, projected_duration_s, decision, reason_code)`.
- Produces: `decide_job_admission(phase: int, job: JobSpec, input_count: int, context: AdmissionContext, settings: TrafficAdmissionSettings, estimated_requests: int | None = None) -> JobAdmissionDecision`.
- Produces: `TrafficAdmissionEnvelope(version="traffic-admission/v1", profile_version, profile_outcome, measured_at, expires_at, effective_policy, candidate_phases, materialized_phases, decisions, effective_config, event_order, warnings, refusals)`.

- [ ] **Step 1: Write the complete decision-table tests**

Cover fresh mapped high/low rates, fresh `no_limiter` using the highest tested rate, `inconclusive`, `failed`, stale, missing policy, zero inputs, exact inclusive boundaries, just-below rate, just-over duration, and invalid estimates. Assert bounded jobs remain included when uncertain outcomes supply a valid conservative policy, bounded jobs are excluded with `policy_missing` when no policy exists, non-target jobs remain included without a policy, and intensive jobs are excluded for every uncertain outcome. Construct otherwise identical profiles with `no_bypass`, false, inconclusive, and confirmed bypass findings and assert identical admission decisions.

```python
def test_intensive_boundaries_are_inclusive(intensive_job, settings):
    decision = decide_job_admission(
        phase=4,
        job=intensive_job,
        input_count=1,
        estimated_requests=600,
        context=fresh_context(safe_rate_per_s=2.0),
        settings=settings.model_copy(update={"max_projected_duration_s": 300.0}),
    )
    assert decision.decision == "included"
    assert decision.projected_duration_s == 300.0

def test_empty_intensive_consumption_is_recorded_but_not_started(intensive_job, settings):
    decision = decide_job_admission(4, intensive_job, 0, fresh_context(10.0), settings)
    assert decision == JobAdmissionDecision(
        phase=4,
        job_name=intensive_job.name,
        cost_class="request_intensive",
        input_count=0,
        estimated_requests=0,
        safe_rate_per_s=10.0,
        projected_duration_s=0.0,
        decision="excluded",
        reason_code="no_inputs",
    )
```

Add `no_inputs` to `AdmissionReason` because an empty consumption set is an execution reason, not a rate failure.

- [ ] **Step 2: Run the decision suite and confirm RED**

Run: `.venv/bin/python -m pytest tests/recon/test_traffic_admission.py -q`

Expected: FAIL because admission contracts and decision function are incomplete.

- [ ] **Step 3: Implement the pure function with no external reads**

Order checks deterministically: validate count/estimate; record zero inputs; allow non-intensive classes; reject stale/status uncertainty/missing policy for intensive jobs; calculate duration; apply inclusive rate and duration thresholds. Ensure bypass fields are absent from every input type and branch.

```python
def decide_job_admission(...):
    if input_count == 0:
        return decision(False, AdmissionReason.NO_INPUTS, estimated_requests=0, duration=0.0)
    if job.traffic_cost.cost_class is not TrafficCostClass.REQUEST_INTENSIVE:
        return decision(True, AdmissionReason.ADMITTED, ...)
    # deterministic conservative checks, then numeric gates
```

- [ ] **Step 4: Build and round-trip the closed envelope**

Test `model_dump(mode="json")` and `model_validate()` equality, forbid unknown fields, preserve candidate/materialized phase order, and require all exclusion reasons to be structured enum values rather than prose.

- [ ] **Step 5: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/recon/test_traffic_admission.py tests/recon/test_traffic_admission_config.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the slice**

```bash
git add src/polymerhus/recon/domain/traffic_admission.py src/polymerhus/recon/control/traffic_admission.py tests/recon/test_traffic_admission.py
git commit -m "feat(recon): decide deterministic job admission"
```

**Acceptance:** The decision function is pure, total over all supported profile outcomes, boundary-tested, and cannot observe bypass findings or model output.

### Task 3: Rate Profile v2, Evidence References, and Freshness

**Files:**
- Modify: `src/polymerhus/recon/domain/rate_limit.py:82-382`
- Modify: `src/polymerhus/recon/control/rate_limit_mapper.py`
- Modify: `src/polymerhus/recon/control/rate_limit_runner.py:266-607`
- Modify: `tests/recon/test_rate_limit_types.py`
- Modify: `tests/recon/test_rate_limit_mapper.py`
- Modify: `tests/recon/test_rate_limit_runner.py`
- Modify: `tests/recon/test_orchestrator_actor.py`

**Interfaces:**
- Produces: `RATE_PROFILE_VERSION = "rate-profile/v2"` and `TRAFFIC_POLICY_VERSION = "traffic-policy/v2"`.
- Produces: `EvidenceReference(ref: str, sha256: str, experiment_id: str, count: NonNegativeInt)`.
- Produces: `RateProfile.evidence: tuple[EvidenceReference, ...]`, `safe_rate_per_s: PositiveFloat`, `measured_at`, `expires_at`, and explicit outcome.
- Produces: `RateProfile.is_fresh(at: datetime) -> bool` using timezone-aware timestamps.
- Consumes: effective `RATE_LIMIT_PROFILE_TTL_S` supplied to `RateLimitHarness`; it must not silently fall back to `PROFILE_TTL_DEFAULT_S`.

- [ ] **Step 1: Write failing v2 contract tests**

Assert v1 inputs are either migrated by the explicit compatibility adapter or rejected at the wire boundary, evidence refs reject absolute paths, bad SHA-256 values, raw payload keys, and sensitive headers, and freshness changes exactly at `expires_at`. Add a harness test proving an env/configured TTL appears in the profile.

```python
def test_profile_is_stale_at_expiry(profile):
    assert profile.is_fresh(profile.expires_at - timedelta(microseconds=1))
    assert not profile.is_fresh(profile.expires_at)

def test_evidence_reference_rejects_absolute_path():
    with pytest.raises(ValidationError):
        EvidenceReference(ref="/tmp/raw.json", sha256="a" * 64, experiment_id="e1", count=1)
```

- [ ] **Step 2: Run the rate contract suites and confirm RED**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py tests/recon/test_orchestrator_actor.py -q`

Expected: FAIL on v1 constants, unstructured artifact refs, and non-configurable TTL behavior.

- [ ] **Step 3: Implement the v2 closed contracts and compatibility boundary**

Keep one named `upgrade_rate_profile_v1(payload: Mapping) -> RateProfile` adapter only at persisted-data ingress. Emit v2 everywhere. Derive `safe_rate_per_s` from controller evidence: mapped posture uses the safe tested control; `no_limiter` uses the maximum actually tested rate; uncertain/error outcomes use the conservative fallback. Never derive it from LLM prose or bypass status.

- [ ] **Step 4: Thread the effective TTL into profile construction**

Change `RateLimitHarness.__init__` to accept `profile_ttl_s: float`, validate it finite-positive alongside settings, and compute `expires_at = measured_at + timedelta(seconds=profile_ttl_s)`. Update its production construction site and focused fixtures.

- [ ] **Step 5: Prove artifact caps and secret safety**

Extend the mapper/runner tests with oversized evidence, authorization/cookie inputs, and raw result objects. Assert stored profile JSON contains only capped `EvidenceReference` entries and no credential values, headers, response bodies, or raw command output.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py tests/recon/test_orchestrator_actor.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the slice**

```bash
git add src/polymerhus/recon/domain/rate_limit.py src/polymerhus/recon/control/rate_limit_mapper.py src/polymerhus/recon/control/rate_limit_runner.py tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py tests/recon/test_orchestrator_actor.py
git commit -m "feat(recon): version rate profiles and evidence"
```

**Acceptance:** Every new run emits v2, configured TTL is honored, `no_limiter` is bounded by actual experiments, and persisted evidence is relative, hashed, capped, and secret-safe.

### Task 4: Pre-Materialization Pruning and Immutable Pipeline Configuration

**Files:**
- Modify: `src/polymerhus/recon/control/traffic_admission.py`
- Modify: `src/polymerhus/recon/control/job_agent.py:72-329`
- Modify: `src/polymerhus/recon/control/pipeline.py:75-920`
- Modify: `src/polymerhus/app/clients/pg.py:116-130`
- Modify: `tests/recon/test_job_agent.py`
- Modify: `tests/recon/test_pipeline.py`
- Modify: `tests/recon/test_rate_limit_pipeline.py`
- Modify: `tests/recon/test_pipeline_e2e.py`

**Interfaces:**
- Produces: `prepare_job_inputs(input_assets: list[dict], job: JobSpec, extra: dict, asset_context: str) -> list[dict]` as the single canonical consumption derivation function.
- Changes: `run_job(..., prepared_pod_inputs: list[dict] | None = None)`; supplied inputs bypass re-derivation but not execution validation.
- Produces: `estimate_job_requests(job: JobSpec, prepared_pod_inputs: Sequence[dict], *, cardinalities: Mapping[str, int]) -> int`.
- Produces: `materialize_admitted_phase(phase: int, candidate_names: Sequence[str], prepared_by_job: Mapping[str, Sequence[dict]], profile: RateProfile, settings: TrafficAdmissionSettings, now: datetime) -> tuple[list[str], tuple[JobAdmissionDecision, ...]]`.
- Persists: `recon_runs.stats["traffic_admission"]` independently of `stats["rate_limit"]` via existing additive `set_run_stats`.

- [ ] **Step 1: Write failing single-derivation and pruning tests**

Instrument `prepare_job_inputs` and `run_job` so the test proves each candidate is derived once, `arjun`/`ffuf` are absent from final materialized phases below threshold, their runners are never invoked, and bounded jobs receive policy v2. Add a missing-policy case proving bounded and intensive runners are both refused while non-target work continues. Assert persistence occurs before the first admitted runner event.

```python
assert events.index("set_run_stats:traffic_admission") < events.index("run:httpx")
assert "run:arjun" not in events
assert "run:ffuf" not in events
assert stored["candidate_phases"] != stored["materialized_phases"]
assert {d["reason_code"] for d in stored["decisions"] if d["decision"] == "excluded"} >= {"below_min_safe_rate"}
```

Add an adversarial actor verdict containing extra `rate_per_s`, `max_concurrency`, `budget`, `candidate_jobs`, and `materialized_phases` fields. Assert closed model validation rejects those fields; if the actor emits ordinary candidate prose naming `arjun`/`ffuf`, assert the controller still computes only the intersection of the static candidate plan and admitted decisions and never unions model output into the plan.

Add a clock-controlled test where the profile is fresh during mapping but stale at materialization; expect `profile_stale` and no intensive runner.

- [ ] **Step 2: Run the pipeline suites and confirm RED**

Run: `.venv/bin/python -m pytest tests/recon/test_job_agent.py tests/recon/test_pipeline.py tests/recon/test_rate_limit_pipeline.py tests/recon/test_pipeline_e2e.py -q`

Expected: FAIL because the pipeline still uses `_HTTP_TRAFFIC_JOBS`, derives inside the job graph, and materializes all planned jobs.

- [ ] **Step 3: Extract canonical preparation without changing outputs**

Move the body of `default_preprocess_fn` into `prepare_job_inputs`; retain `default_preprocess_fn` as a thin compatibility wrapper. Add `prepared_pod_inputs` to `JobState` and `run_job`; when supplied, pass the immutable prepared list into the graph rather than calling the derivation again.

- [ ] **Step 4: Replace name-based policy wiring with cost metadata**

Delete `_HTTP_TRAFFIC_JOBS`. Attach `traffic_policy` when `job.traffic_cost.cost_class` is `bounded_http` or `request_intensive`, plus existing agent-mode HTTP execution. Assert the LLM-visible state contains neither settings nor an API that can edit decisions.

- [ ] **Step 5: Materialize and persist admission before runners**

For each candidate phase, derive inputs, estimate requests, make decisions, form the final phase list, and persist one `TrafficAdmissionEnvelope` before constructing `job_configs`. Pass the already prepared inputs to `run_job`. If persistence fails, fail the run before launching a runner so the executed configuration is never unobservable.

- [ ] **Step 6: Preserve test-double compatibility explicitly**

Update repository test doubles to accept `prepared_pod_inputs=None`. Do not add introspection that silently omits the production argument; production and tests must share the same signature.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/recon/test_job_agent.py tests/recon/test_pipeline.py tests/recon/test_rate_limit_pipeline.py tests/recon/test_pipeline_e2e.py -q`

Expected: PASS with structured admission stats and negative runner assertions.

- [ ] **Step 8: Commit the slice**

```bash
git add src/polymerhus/recon/control/traffic_admission.py src/polymerhus/recon/control/job_agent.py src/polymerhus/recon/control/pipeline.py src/polymerhus/app/clients/pg.py tests/recon/test_job_agent.py tests/recon/test_pipeline.py tests/recon/test_rate_limit_pipeline.py tests/recon/test_pipeline_e2e.py
git commit -m "feat(recon): prune intensive jobs before materialization"
```

**Acceptance:** The persisted materialized list exactly matches jobs eligible to run; excluded runners cannot be called; policy transport derives from typed metadata; stale is evaluated at the admission chokepoint.

### Task 5: Typed Mutation Materialization and Lossless Kali Transport

**Files:**
- Create: `src/polymerhus/recon/control/request_mutation.py`
- Modify: `src/polymerhus/recon/domain/rate_limit.py:165-239`
- Modify: `src/polymerhus/recon/control/rate_limit_runner.py:79-160`
- Modify: `kali/rate_limit/models.py`
- Modify: `kali/rate_limit/runner.py`
- Modify: `tests/recon/test_rate_limit_types.py`
- Modify: `tests/recon/test_rate_limit_runner.py`
- Modify: `tests/kali/test_rate_limit_runner.py`
- Create: `tests/integration/test_rate_limit_mutation_transport.py`

**Interfaces:**
- Replaces: generic mutation params with a discriminated union `HeaderMutation | QueryMutation | PathMutation | BodyMutation`, discriminated by `kind`.
- Produces: `CanonicalRequest(method, url, headers, body_ref)` and `EffectiveRequest(method, url, headers, body_ref, mutation_id)` closed models.
- Produces: `apply_mutation(request: CanonicalRequest, mutation: Mutation | None) -> EffectiveRequest`.
- Changes: `KaliExperimentSpec` contains `effective_request: EffectiveRequest`; it does not reinterpret `ExperimentSpec.variant`.
- Produces: `kali_spec_payload()` serializes the exact effective method, URL, headers, body reference, and mutation identity.

- [ ] **Step 1: Write failing pure mutation tests**

Pin header replace/add, query replace/add with correct percent encoding, path mutation preserving origin, body-reference replacement, no-mutation identity, duplicate header behavior, and rejection of host/scheme changes outside target scope. Verify inputs remain unchanged.

```python
def test_query_variant_changes_the_effective_url_without_mutating_canonical():
    canonical = CanonicalRequest(method="GET", url="https://app.test/search?q=base", headers=())
    effective = apply_mutation(canonical, QueryMutation(name="q", value="a b", mutation_id="m1"))
    assert effective.url == "https://app.test/search?q=a+b"
    assert canonical.url.endswith("q=base")
```

- [ ] **Step 2: Write the failing cross-boundary transport test**

Construct an `ExperimentSpec` with each union variant, call `kali_spec_payload`, validate as `KaliExperimentSpec`, build the runner command/request, and assert the target-visible request equals `EffectiveRequest` rather than the canonical URL. Include an adversarial assertion that deleting `effective_request` or serializing the canonical request fails the test.

- [ ] **Step 3: Run mutation suites and confirm RED**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_runner.py tests/kali/test_rate_limit_runner.py tests/integration/test_rate_limit_mutation_transport.py -q`

Expected: FAIL because `variant` is currently discarded and `KaliExperimentSpec` cannot carry it.

- [ ] **Step 4: Implement controller-side materialization**

Validate the discriminated union in the domain layer, apply it once in the controller, enforce same-origin/scope rules, and pass only `EffectiveRequest` across MCP. Do not log header values or body content; diagnostic output may contain mutation kind and ID only.

- [ ] **Step 5: Make Kali a dumb executor**

Update the Kali model and runner to consume `effective_request` exactly. Remove any opportunity for Kali or the LLM to choose a different mutation. Preserve evidence correlation through `mutation_id` and experiment ID.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_runner.py tests/kali/test_rate_limit_runner.py tests/integration/test_rate_limit_mutation_transport.py -q`

Expected: PASS; the transport test fails if the variant is discarded.

- [ ] **Step 7: Commit the slice**

```bash
git add src/polymerhus/recon/control/request_mutation.py src/polymerhus/recon/domain/rate_limit.py src/polymerhus/recon/control/rate_limit_runner.py kali/rate_limit/models.py kali/rate_limit/runner.py tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_runner.py tests/kali/test_rate_limit_runner.py tests/integration/test_rate_limit_mutation_transport.py
git commit -m "fix(rate-limit): transport effective mutations"
```

**Acceptance:** Every tested mutation reaches the target exactly, the canonical request remains immutable, and mutation data cannot broaden target scope or leak secrets.

### Task 6: Shared Rate/Concurrency Governor and Fail-Closed Proxy

**Files:**
- Modify: `kali/http_history/governor.py:33-245`
- Modify: `kali/http_history/addon.py:70-145`
- Modify: `kali/http_history/addon_entry.py`
- Modify: `kali/http_history/registry.py:53-140`
- Modify: `src/polymerhus/recon/domain/pod.py`
- Modify: `src/polymerhus/recon/control/pipeline.py`
- Modify: `tests/kali/test_rate_limit_governor.py`
- Modify: `tests/kali/test_http_history_addon.py`
- Modify: `tests/kali/test_http_history_registry.py`
- Modify: `tests/kali/test_http_history_deployment.py`
- Modify: `tests/recon/test_pod_capture_context.py`
- Modify: `tests/recon/test_rate_limit_pipeline.py`

**Interfaces:**
- Produces: `GovernorPermit(key: tuple[str, str], permit_id: str)`.
- Changes: `GovernorDecision` carries a non-null permit only when traffic may proceed.
- Produces: `TargetGovernor.acquire(...) -> GovernorDecision` enforcing rate and `max_concurrency` on the same `(project_id, target_key)` key.
- Produces: `TargetGovernor.release(permit: GovernorPermit) -> None`, idempotent for a completed flow and observable on duplicate release.
- Produces: `refuse_flow(flow, *, reason_code: str, detail: str) -> None` injected into `HttpHistoryAddon`; production adapter creates a local HTTP 503 with `X-Polymerhus-Traffic-Refusal` and no upstream request.
- Changes: `build_addons(governor_factory: Callable[[], TargetGovernor] = TargetGovernor, refusal_factory: Callable = mitmproxy_refuse_flow) -> list`, allowing the E2E-only addon entry to inject a fault without production environment switches.
- Produces: a secret-safe `TrafficRefusal(reason_code, target_key, policy_version)` propagated through pod output; the pipeline appends it to `traffic_admission.refusals` and the ordered event list without rewriting the original admission decision.

- [ ] **Step 1: Write failing concurrency and keying tests**

Use an injected monotonic clock and controllable tasks. Assert the second same-project/same-target acquire blocks at concurrency 1 until release, different projects acquire immediately, different source IPs in the same project still share capacity, rate spacing remains enforced, and dynamic policies cannot inflate an existing stricter bucket.

```python
first = await governor.acquire(project_id="p1", context=ctx("10.0.0.2"), traffic_policy=policy(1))
second = asyncio.create_task(governor.acquire(project_id="p1", context=ctx("10.0.0.3"), traffic_policy=policy(1)))
await asyncio.sleep(0)
assert not second.done()
await governor.release(first.permit)
assert (await second).allowed
```

- [ ] **Step 2: Write failing lifecycle and cancellation tests**

Cover response release, error release, cancellation while waiting, cancellation after acquisition, double response/error hooks, and a raised governor exception. Assert every acquired permit is released exactly once and waiters resume without exceeding the limit. Add pod/pipeline tests proving return code 78 or the refusal response becomes `TrafficRefusal`, is persisted with reason `governor_refused`, and retains no URL query, headers, body, or credential values.

- [ ] **Step 3: Write the fail-closed addon regression**

Inject a governor whose `acquire` raises. Call `HttpHistoryAddon.request(flow)` and assert a local 503 response, refusal header/reason metric, zero sender/upstream calls, and no credential-bearing exception text. Repeat with capture enabled and disabled; outcomes must match.

- [ ] **Step 4: Run governor/addon suites and confirm RED**

Run: `.venv/bin/python -m pytest tests/kali/test_rate_limit_governor.py tests/kali/test_http_history_addon.py tests/kali/test_http_history_registry.py tests/kali/test_http_history_deployment.py tests/recon/test_pod_capture_context.py tests/recon/test_rate_limit_pipeline.py -q`

Expected: FAIL because `max_concurrency` is currently validation-only and governor exceptions return from the hook without stopping egress.

- [ ] **Step 5: Implement shared permit state**

Maintain one condition-protected state object per `(project_id, target_key)` with token bucket, in-flight count, and active permit IDs. Never include source IP in the key. Reserve the concurrency slot and rate token atomically; release in `finally`-safe response/error paths and notify waiters.

- [ ] **Step 6: Make addon failures locally terminal**

Store the permit ID in `flow.metadata`. Make `response` and `error` awaitable so they can release. In `request`, catch validation/unavailability/runtime exceptions, emit the structured refusal metric, and call injected `refuse_flow`; do not merely return. Construct the mitmproxy response adapter in `addon_entry.py` so unit imports remain mitmproxy-independent.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/kali/test_rate_limit_governor.py tests/kali/test_http_history_addon.py tests/kali/test_http_history_registry.py tests/kali/test_http_history_deployment.py tests/recon/test_pod_capture_context.py tests/recon/test_rate_limit_pipeline.py -q`

Expected: PASS, including the source-IP adversarial test, exact concurrency ceiling, no permit leaks, and fail-closed capture-off behavior.

- [ ] **Step 8: Commit the slice**

```bash
git add kali/http_history/governor.py kali/http_history/addon.py kali/http_history/addon_entry.py kali/http_history/registry.py src/polymerhus/recon/domain/pod.py src/polymerhus/recon/control/pipeline.py tests/kali/test_rate_limit_governor.py tests/kali/test_http_history_addon.py tests/kali/test_http_history_registry.py tests/kali/test_http_history_deployment.py tests/recon/test_pod_capture_context.py tests/recon/test_rate_limit_pipeline.py
git commit -m "fix(kali): enforce traffic policy fail closed"
```

**Acceptance:** Measured in-flight traffic never exceeds `max_concurrency`; source IP cannot partition the bucket; every fault blocks egress; capture state is irrelevant to enforcement.

### Task 7: Runtime Capability Negotiation and Reproducible Kali Image

**Files:**
- Modify: `kali/http_history/service.py:477-510`
- Modify: `kali/mcp_server.py:206-220`
- Modify: `Dockerfile.kali`
- Modify: `docker-compose.yml`
- Modify: `tests/kali/test_http_history_service.py`
- Modify: `tests/kali/test_http_history_mcp_tools.py`
- Modify: `tests/kali/test_http_history_deployment.py`
- Modify: `tests/recon/test_traffic_admission_config.py`

**Interfaces:**
- Produces: `proxy_status()["traffic_governor"]` with `supported_policy_versions`, `capture_enabled`, `governor_enabled`, and refusal counters.
- Produces: `proxy_status()["build"]` with image revision and Vegeta module/version derived from build metadata.
- Produces: readiness refusal when controller requires `traffic-policy/v2` but Kali does not advertise it.
- Produces: verified ffuf wordlist cardinality used by `estimate_job_requests`.

- [ ] **Step 1: Write failing readiness/capability tests**

Assert v2 is advertised, capture and governor flags are separate, a controller/Kali version mismatch refuses before target traffic, build provenance is present, and the ffuf cardinality exactly equals the catalogue value. Assert a missing or changed wordlist causes startup/readiness failure naming the file and expected/actual count.

- [ ] **Step 2: Replace the unreliable Vegeta smoke**

In `Dockerfile.kali`, keep the pinned `vegeta@v12.13.0` install but replace `vegeta -version | grep 12.13.0` with a build step that runs:

```bash
go version -m "$(command -v vegeta)" | grep 'github.com/tsenart/vegeta/v12' | grep 'v12.13.0'
```

Record the same module metadata in a small image label/file read by `proxy_status`, along with the source revision build arg.

- [ ] **Step 3: Run non-container contract tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_service.py tests/kali/test_http_history_mcp_tools.py tests/kali/test_http_history_deployment.py tests/recon/test_traffic_admission_config.py -q`

Expected: FAIL because health lacks version/build metadata and the current smoke relies on unsupported CLI output.

- [ ] **Step 4: Implement capability negotiation and cost provenance**

Expose immutable runtime capabilities from service through MCP. Check them once before the authenticated rate stage and again before the first governed pod. Validate wordlist existence and non-empty-line cardinality at startup, and feed that verified count to Task 4's estimator; do not trust a stale hard-coded estimate alone.

- [ ] **Step 5: Run contract tests and build the image**

Run: `.venv/bin/python -m pytest tests/kali/test_http_history_service.py tests/kali/test_http_history_mcp_tools.py tests/kali/test_http_history_deployment.py tests/recon/test_traffic_admission_config.py -q`

Expected: PASS.

Run: `docker build --build-arg SOURCE_REVISION=$(git rev-parse HEAD) -f Dockerfile.kali -t polyphemus-kali:rate-admission .`

Expected: image build PASS and the module metadata smoke identifies Vegeta 12.13.0. This command is a future implementation action; it is not run during plan authoring.

- [ ] **Step 6: Commit the slice**

```bash
git add kali/http_history/service.py kali/mcp_server.py Dockerfile.kali docker-compose.yml tests/kali/test_http_history_service.py tests/kali/test_http_history_mcp_tools.py tests/kali/test_http_history_deployment.py tests/recon/test_traffic_admission_config.py
git commit -m "build(kali): verify traffic runtime capabilities"
```

**Acceptance:** The controller refuses stale/unsupported Kali before egress, Vegeta identity is obtained from Go module metadata, and the traffic estimate is tied to the wordlist actually present in the image.

### Task 8: Deterministic Multi-Posture Target Fixture

**Files:**
- Create: `tests/e2e/rate_limit_matrix_target.py`
- Modify: `docker-compose.e2e.yml`
- Create: `tests/e2e/test_rate_limit_matrix_target.py`
- Remove after migration: `tests/e2e/rate_limit_e2e_target.py`

**Interfaces:**
- Produces: one target app configured by `RATE_FIXTURE_POSTURE` as `no_limiter`, `high_limit`, `low_limit`, `false_bypass`, or `burst_inconclusive`.
- Produces: `GET /health`, `POST /reset`, `GET /counters`, `GET /events`, and ordinary target routes used by auth, probes, arjun, and ffuf.
- `GET /counters` returns request totals, timestamps, current/max in-flight, route counts, headers-by-name with sensitive values redacted, and an ordered event sequence.
- Compose exposes isolated service aliases and state for each posture; instances never share counters.

- [ ] **Step 1: Write failing fixture API tests**

Test reset isolation, deterministic 429 patterns and headers per posture, exact high/low sustainable limits, false bypass behavior, burst ambiguity, monotonic timestamp order, max-in-flight tracking, `/events` ordering, and automatic redaction of `authorization`, `cookie`, `proxy-authorization`, and configured secret values.

- [ ] **Step 2: Run fixture unit tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/e2e/test_rate_limit_matrix_target.py -q`

Expected: FAIL because the parameterized fixture application does not exist.

- [ ] **Step 3: Implement one deterministic application**

Use a monotonic clock for recorded intervals and a lock around counters. Keep posture behavior data-driven so route logic is shared. Make `/reset` return a generation ID; require tests to include it when reading counters so stale events cannot be mistaken for the current scenario.

- [ ] **Step 4: Define isolated Compose services**

Instantiate the same image/module five times with separate aliases, posture env values, and healthchecks. Do not publish host ports unless the existing E2E harness requires them; reach services by Compose DNS from agent/Kali.

- [ ] **Step 5: Run fixture unit tests and isolated Compose checks**

Run: `.venv/bin/python -m pytest tests/e2e/test_rate_limit_matrix_target.py -q`

Expected: PASS.

Run: `docker compose -f docker-compose.yml -f docker-compose.e2e.yml config --quiet`

Expected: PASS with five target services and distinct aliases.

- [ ] **Step 6: Commit the slice**

```bash
git add tests/e2e/rate_limit_matrix_target.py tests/e2e/test_rate_limit_matrix_target.py tests/e2e/rate_limit_e2e_target.py docker-compose.e2e.yml
git commit -m "test(e2e): add deterministic rate posture matrix"
```

**Acceptance:** Every required target posture is deterministic, resettable, isolated, timestamped, concurrency-aware, and secret-safe through a uniform inspection API.

### Task 9: Deterministic Local LLM Provider and Real Control-Plane Harness

**Files:**
- Create: `tests/e2e/deterministic_llm_provider.py`
- Modify: `docker-compose.e2e.yml`
- Modify: `tests/e2e/gateway_stack.py`
- Modify: `tests/e2e/harness/driver.py`
- Create: `tests/e2e/test_deterministic_llm_provider.py`

**Interfaces:**
- Produces: an OpenAI-compatible `POST /v1/chat/completions` fixture and `GET /health`.
- Produces: deterministic responses for the existing orchestrator and triager roles, selected from conversation/tool-result state rather than test-side direct calls.
- Produces: harness methods `create_project`, `configure_project`, `store_auth`, `start_recon`, `wait_for_run`, `read_run_stats`, `reset_target`, and `read_target_counters` that use public HTTP APIs and PostgreSQL only for persisted-output verification.
- Configures: agent role endpoints to the local provider using existing provider selection and API-key variables; no production code imports the fixture.

- [ ] **Step 1: Write failing provider protocol tests**

Feed representative production message histories and assert exact valid tool-call envelopes for: auth-store read and `GatewayVerdict`; skill load and rate mapping; optional typed mutation experiment; `RateLoopVerdict`; and triager output. Repeat identical inputs and assert byte-equivalent semantic JSON after ignoring generated request IDs.

- [ ] **Step 2: Run provider tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/e2e/test_deterministic_llm_provider.py -q`

Expected: FAIL because the local provider does not exist.

- [ ] **Step 3: Implement the protocol state machine**

Parse only the OpenAI-compatible request shape already emitted by the production client. Select the next response from tool names and structured tool results in the message history. Return schema-valid arguments and no policy, rate, concurrency, budget, admission, or phase-list fields. Fail unknown states with a diagnostic 422 that includes message roles and tool names but no message content.

- [ ] **Step 4: Connect all required model roles through Compose**

Add the provider service and set `LLM_GATEWAY_URL=http://rate-limit-llm:8080/v1`, `LLM_JOB_ORCHESTRATOR=openai:rate-admission-fixture`, `LLM_TRIAGER=openai:rate-admission-fixture`, and `API_KEY_OPENAI=e2e-inert-key` in the E2E-only agent service. The fixture accepts the registered model identifier emitted in gateway mode. Add a health dependency so the agent cannot begin a run before the fixture is ready.

- [ ] **Step 5: Add a public-API smoke trajectory**

Start a run through `POST /projects`, settings/auth endpoints, and `POST /projects/{project_id}/recon`; poll `GET /projects/{project_id}/recon/{run_id}`. Assert provider request counters prove the real gateway and rate actor called the fixture, and assert no `_ScriptedOrchestrator`, direct MCP call, or `fake_run_job` is imported by the functional test module.

- [ ] **Step 6: Run provider and Compose validation**

Run: `.venv/bin/python -m pytest tests/e2e/test_deterministic_llm_provider.py -q`

Expected: PASS.

Run: `docker compose -f docker-compose.yml -f docker-compose.e2e.yml config --quiet`

Expected: PASS with the local provider healthy and both production roles routed to it.

- [ ] **Step 7: Commit the slice**

```bash
git add tests/e2e/deterministic_llm_provider.py tests/e2e/test_deterministic_llm_provider.py tests/e2e/gateway_stack.py tests/e2e/harness/driver.py docker-compose.e2e.yml
git commit -m "test(e2e): drive rate mapping through local model"
```

**Acceptance:** The E2E actor loop is real and reproducible, the test never scripts the orchestrator directly, and the fixture has no authority to alter controller policy or admission.

### Task 10: Functional E2E Admission and Posture Matrix

**Files:**
- Create: `tests/e2e/test_rate_limit_admission_e2e.py`
- Modify: `tests/e2e/test_rate_limit_mapping_e2e.py`
- Modify: `tests/e2e/harness/driver.py`
- Modify: `docker-compose.e2e.yml`

**Interfaces:**
- Consumes: public control-plane harness from Task 9 and target API from Task 8.
- Verifies: auth → rate mapping → v2 profile/policy persistence → deterministic admission → materialized phases → real pod/Kali/governor → target → stats/output.
- Produces: parameterized scenario records with expected posture, reason codes, final phase membership, runner evidence, and target count/timing bounds.

- [ ] **Step 1: Write the failing no-limiter and high-limit scenarios**

For each target, reset state, create a distinct project, store auth, launch a real run whose requested subset reaches `arjun` and `ffuf`, and wait for completion. Assert trajectory event order, fresh posture, policy v2, relative evidence refs with valid hashes, admitted decisions, both names in materialized phases, real runner/job records, and target route counters attributable to both tools.

- [ ] **Step 2: Write the failing low-limit and every-bypass-outcome scenario**

Assert low-limit/no-bypass and low-limit/false-bypass runs produce a low safe rate, `arjun` and `ffuf` are absent from materialized phases, have structured pruning reasons, create no runner/job invocation, and generate no tool-specific target traffic. Reuse the isolated low-limit target with deterministic-provider modes for inconclusive and fully confirmed four-gate bypass findings; assert each finding is persisted but policy, admission, and materialized phases are byte-equivalent to low-limit/no-bypass after removing evidence IDs. No scenario waits for operator input.

- [ ] **Step 3: Write the failing inconclusive, stage-error, and stale scenarios**

Use burst fixture behavior for `inconclusive`. For stage error, have the E2E provider return HTTP 503 only when the message history reaches the rate turn for the `rate-stage-error` target alias; this exercises the production actor failure path without a production fault flag. For stale, use a short valid TTL plus a target-controlled phase gate that delays the next public observation until expiry. Assert conservative warning/refusal, intensive pruning, bounded work continuity where policy is available, and no intensive traffic.

- [ ] **Step 4: Assert persisted output and secret safety in every case**

For each row, verify:

```python
assert_event_order(stats, ["auth", "rate_mapping", "rate_profile_persisted", "admission_persisted", "pod_started", "target_observed", "run_finalized"])
assert stats["rate_limit"]["version"] == "rate-profile/v2"
assert stats["traffic_admission"]["version"] == "traffic-admission/v1"
assert_no_secrets(json.dumps(stats), auth_secret, cookie_secret)
assert_all_evidence_refs_relative_and_hashed(stats["rate_limit"])
```

- [ ] **Step 5: Run the new functional suite and confirm RED**

Run: `.venv/bin/python -m pytest tests/e2e/test_rate_limit_admission_e2e.py -vv -rs -p no:cacheprovider`

Expected: FAIL before the completed feature because intensive phases still materialize and the old E2E bypasses production seams.

- [ ] **Step 6: Complete only harness assertions needed by the scenarios**

Add polling diagnostics that print run ID, last status, provider state, and capped target events on timeout. Migrate useful assertions from `test_rate_limit_mapping_e2e.py`; retain fast direct-MCP coverage as integration tests but rename/comment it so it cannot be mistaken for the functional gate.

- [ ] **Step 7: Run the functional suite twice and confirm GREEN**

Run: `.venv/bin/python -m pytest tests/e2e/test_rate_limit_admission_e2e.py -vv -rs -p no:cacheprovider`

Expected: PASS.

Run the same command a second time after fixture reset.

Expected: PASS with no order dependence, stale counters, or leaked state.

- [ ] **Step 8: Commit the slice**

```bash
git add tests/e2e/test_rate_limit_admission_e2e.py tests/e2e/test_rate_limit_mapping_e2e.py tests/e2e/harness/driver.py docker-compose.e2e.yml
git commit -m "test(e2e): prove rate-aware job admission"
```

**Acceptance:** All five target postures plus stage error and stale profile traverse the production trajectory; final phases, runner invocation, target traffic, persistence, warnings, and secret safety agree.

### Task 11: Functional E2E Enforcement and Adversarial Regression Gate

**Files:**
- Modify: `tests/e2e/test_rate_limit_admission_e2e.py`
- Create: `tests/e2e/failing_governor_addon_entry.py`
- Modify: `docker-compose.e2e.yml`
- Modify: `tests/recon/test_pod_capture_context.py`
- Modify: `tests/kali/test_rate_limit_governor.py`
- Modify: `tests/integration/test_rate_limit_mutation_transport.py`

**Interfaces:**
- Adds: live same-project/different-pod and different-project bucket experiments.
- Adds: live max-concurrency measurement from target `current_in_flight`/`max_in_flight` and request timestamps.
- Adds: E2E-only failing-governor addon composition; production modules contain no test fault switch.
- Adds: capture-off service configuration with governor still armed.

- [ ] **Step 1: Write failing live rate and bucket-sharing tests**

Launch two real pods for the same project/target and assert target timestamps across both are spaced according to one shared bucket. Repeat with different projects and assert their first requests can overlap. Compare project and target keys from persisted policy; do not infer sharing from source IP.

- [ ] **Step 2: Write failing live concurrency test**

Use a target route with deterministic response delay and policy `max_concurrency=2`. Generate enough overlapping requests from multiple pods; assert target `max_in_flight == 2`, never 3, while all admitted requests complete. Confirm rate intervals separately so concurrency and rate are both measured.

- [ ] **Step 3: Write failing governor-fault and capture-off tests**

Compose one Kali service with `tests/e2e/failing_governor_addon_entry.py`, which imports the production addon and injects an `ExplodingGovernor`. Assert local refusal/warning, run failure or conservative terminal state, and zero target calls. Run the normal service with `KALI_HTTP_CAPTURE_ENABLED=false`; assert governed traffic is still paced/concurrency-limited while no capture artifacts are stored.

- [ ] **Step 4: Pin every adversarial mutation to a test**

Ensure the named tests fail under each deliberate one-line mutation:

| Deliberate regression | Owning test |
|---|---|
| Remove `traffic_policy` from pod MCP args | `test_pod_forwards_mandatory_policy_v2` |
| Add `source_ip` to governor bucket key | `test_same_project_different_source_ips_share_live_bucket` |
| Ignore `max_concurrency` | `test_live_target_never_exceeds_policy_concurrency` |
| Start `arjun` or `ffuf` below threshold | `test_low_rate_prunes_intensive_runners_and_traffic` |
| Serialize canonical request instead of `variant` | `test_variant_reaches_target_request` |
| Return from addon after governor exception | `test_governor_exception_has_zero_target_egress` |
| Couple governor enablement to capture flag | `test_capture_off_keeps_live_governance` |

- [ ] **Step 5: Run enforcement tests and confirm RED**

Run: `.venv/bin/python -m pytest tests/recon/test_pod_capture_context.py tests/kali/test_rate_limit_governor.py tests/integration/test_rate_limit_mutation_transport.py tests/e2e/test_rate_limit_admission_e2e.py -vv -rs -p no:cacheprovider`

Expected: FAIL until live services and assertions expose all enforcement paths.

- [ ] **Step 6: Complete E2E-only wiring and confirm GREEN twice**

Run the command from Step 5 twice, resetting all target generations between runs.

Expected: PASS twice; timing assertions use bounded tolerances declared beside the fixture rates, never unbounded sleeps.

- [ ] **Step 7: Commit the slice**

```bash
git add tests/e2e/test_rate_limit_admission_e2e.py tests/e2e/failing_governor_addon_entry.py docker-compose.e2e.yml tests/recon/test_pod_capture_context.py tests/kali/test_rate_limit_governor.py tests/integration/test_rate_limit_mutation_transport.py
git commit -m "test(e2e): gate live traffic enforcement"
```

**Acceptance:** The seven specified regressions each have a named test that demonstrably kills the mutation; rate, shared isolation, concurrency, mutation transport, fail-closed, and capture independence are observed at the target.

### Task 12: Documentation Convergence, Migration, and Release Verification

**Files:**
- Modify: `CLAUDE.md`
- Modify: `CONTEXT-MAP.md`
- Modify: `src/polymerhus/recon/CONTEXT.md`
- Modify: `docs/design/technical-architecture.md`
- Modify: `docs/design/after-mvp-work-items.md`
- Create: `docs/design/rate-limit-job-admission-operations.md`; leave the pre-existing operator-owned untracked mapping spec untouched.
- Modify: targeted READMEs/comments found by the stale-claim search below.
- Test: all suites and validation commands listed below.

**Interfaces:**
- Documents: v2 contracts, typed cost ownership, threshold units/defaults/ranges, outcome matrix, no-auto-bypass rule, event order, stats schema, health negotiation, target fixture APIs, and operational refusal behavior.
- Documents: compatibility adapter scope and rollback boundaries.

- [ ] **Step 1: Find obsolete claims and record the exact edit list**

Run:

```bash
rg -n 'unthrottled|_RATE_FLAGS|traffic-policy/v1|rate-profile/v1|fake_run_job|ScriptedOrchestrator|capture.*govern|bypass.*enable|bypass.*re.?enable' CLAUDE.md CONTEXT-MAP.md src docs tests kali
```

Expected: every hit is classified as a deliberate historical assertion/test fixture or queued for an exact documentation/comment update in this task.

- [ ] **Step 2: Update operator-facing documentation**

Describe the actual automatic flow: no human pause is required, but bypass findings never authorize increased traffic. Include both threshold environment variables, finite-positive validation, inclusive boundary semantics, typed classes, freshness rule, structured reason codes, and where to inspect `rate_limit` and `traffic_admission` stats.

- [ ] **Step 3: Document migration and rollback**

State that readers may ingest stored `rate-profile/v1` only through `upgrade_rate_profile_v1`, all new writes are v2, Kali rejects unsupported policy versions with return code 78/no target calls, and rolling back requires controller and Kali together. Preserve `traffic_admission` as additive JSONB so rollback does not require a destructive database migration.

- [ ] **Step 4: Run static and focused verification**

Run:

```bash
.venv/bin/python -m pytest tests/recon/test_jobs.py tests/recon/test_traffic_admission_config.py tests/recon/test_traffic_admission.py tests/recon/test_rate_limit_types.py tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py tests/recon/test_rate_limit_pipeline.py tests/recon/test_pod_capture_context.py tests/integration/test_rate_limit_mutation_transport.py -q
.venv/bin/python -m pytest tests/kali/test_rate_limit_governor.py tests/kali/test_rate_limit_runner.py tests/kali/test_http_history_addon.py tests/kali/test_http_history_service.py tests/kali/test_http_history_mcp_tools.py tests/kali/test_http_history_deployment.py -q
```

Expected: both commands PASS.

- [ ] **Step 5: Run subsystem regression suites**

Run:

```bash
.venv/bin/python -m pytest tests/recon -q
.venv/bin/python -m pytest tests/kali -q
```

Expected: PASS with only reviewed, pre-existing skips; compare totals with the historical baseline (recon 1069 passed/21 skipped, Kali 194 passed) and explain all count changes by new/removed tests.

- [ ] **Step 6: Build and verify the live image and full E2E twice**

Run:

```bash
docker build --build-arg SOURCE_REVISION=$(git rev-parse HEAD) -f Dockerfile.kali -t polyphemus-kali:rate-admission .
docker compose -f docker-compose.yml -f docker-compose.e2e.yml config --quiet
.venv/bin/python -m pytest tests/e2e/test_rate_limit_admission_e2e.py -vv -rs -p no:cacheprovider
.venv/bin/python -m pytest tests/e2e/test_rate_limit_admission_e2e.py -vv -rs -p no:cacheprovider
```

Expected: image metadata identifies Vegeta 12.13.0; Compose validates; both E2E runs PASS independently. If Docker, network namespaces, or required credentials are unavailable, report these exact commands as not run and do not substitute unit evidence for the live gate.

- [ ] **Step 7: Run final hygiene checks**

Run:

```bash
git diff --check
git status --short
rg -n 'traffic-policy/v1|rate-profile/v1|_HTTP_TRAFFIC_JOBS|unthrottled' src kali docs tests
```

Expected: no whitespace errors; only intended files changed; remaining v1 references are compatibility tests/adapter; `_HTTP_TRAFFIC_JOBS` and obsolete “unthrottled” claims are absent.

- [ ] **Step 8: Commit the documentation and release gate**

```bash
git add CLAUDE.md CONTEXT-MAP.md src/polymerhus/recon/CONTEXT.md docs/design/technical-architecture.md docs/design/after-mvp-work-items.md docs/design/rate-limit-job-admission-operations.md
git commit -m "docs(recon): explain rate-aware admission operations"
```

**Acceptance:** Documentation matches runtime behavior, version migration and rollback are explicit, focused and subsystem suites pass, and the real E2E passes twice or is reported as an unfulfilled release gate with exact environmental cause.

## Historical Baseline for Comparison

The issue #238 ledger records 112 passed in the focused suite, 194 passed in the Kali suite, 1069 passed and 21 skipped in recon, and 8 passed twice in about 64 seconds in the current rate-limit E2E. It also records same-project bucket pacing, immediate progress for a different project, invalid-policy refusal with return code 78 and zero target calls, budget refusal before executor invocation, and a valid redacted artifact hash. Preserve these as regression evidence and explain count changes; none substitutes for Tasks 10–11 because the old E2E uses direct MCP calls and a fake runner.

## Rulings That Supersede the 2026-09-23 Plan

1. **Real actor trajectory replaces scripted orchestration.** The previous `_ScriptedOrchestrator`/`fake_run_job` E2E remains useful below the functional tier but cannot certify production behavior. Cost of retaining it as the release gate: model-provider, actor loop, materialization, and pod wiring regressions can ship unseen.
2. **Typed `JobSpec` cost replaces `_HTTP_TRAFFIC_JOBS`.** Cost/admission metadata lives with the canonical job definition. Cost of a parallel name list: a renamed or newly added intensive job can escape governance silently.
3. **Governor faults are fail-closed.** The earlier fail-open handling is explicitly reversed for armed policy. Cost of fail-open: target traffic can exceed an authorized policy exactly when enforcement is unhealthy.
4. **Mutation transport is in scope.** `ExperimentSpec.variant` becomes a typed controller-materialized request rather than a deferred finding. Cost of deferral: evidence can claim a bypass experiment that never reached the target.
5. **Rate and concurrency are one enforceable v2 contract.** `max_concurrency` is not validation-only. Cost of retaining v1 semantics: average rate may look compliant while bursts exceed simultaneous-load limits.
6. **Image identity is runtime-verifiable.** Vegeta verification uses Go module metadata and source provenance. Cost of the old smoke: a stale or differently built binary can pass/fail for CLI-format reasons unrelated to its actual version.
7. **Admission gets a separate stats envelope.** `traffic_admission` is not folded into `rate_limit`. Cost of conflation: detected posture cannot be distinguished from the downstream decision that used it.

## Risk and Rollback Plan

- **Timing flakiness:** target timestamps use monotonic time, fixed delays, bounded tolerances, reset generations, and two consecutive executions. Roll back only fixture tolerance changes independently; never weaken production limits to make tests pass.
- **Deadlock/permit leak:** cancellation, response/error double hooks, and waiter wake-up tests precede live rollout. The governor commit is independently revertible together with `traffic-policy/v2`; controller and Kali must remain version-aligned.
- **Estimate drift:** image readiness compares ffuf's actual wordlist count with the catalogue and refuses mismatch. Updating a wordlist requires one reviewed cost update and boundary-test adjustment in the same commit.
- **Stored v1 rows:** additive read compatibility is isolated to `upgrade_rate_profile_v1`; no v1 emission remains. If rollback is needed, roll back controller and Kali together and leave additive stats data intact.
- **LLM fixture drift:** the provider speaks the public OpenAI-compatible protocol and fails unknown states loudly. Update fixture protocol tests when production message shape changes; do not bypass the actor in response.
- **Environment unavailable:** absence of Docker, Compose networking, or image-build access leaves Tasks 10–12 incomplete. Record exact unavailable commands and do not mark the feature accepted from mocks.
- **Performance:** request estimation and input derivation are linear in the already-required consumption set and occur once. If memory pressure appears, preserve the same immutable decision contract while introducing bounded iterators in a separately reviewed change.

## Final Definition of Done

- Every approved design invariant maps to a passing unit, contract, integration, or functional E2E assertion.
- `arjun` and `ffuf` are absent from materialized configuration, runner records, and target traffic whenever intensive admission fails.
- High/no-limiter postures admit them only from measured safe capacity and projected duration.
- Bypass evidence never changes effective policy or admission.
- Policy reaches every HTTP pod and is enforced for rate plus concurrency with capture on or off.
- Governor errors and policy/version errors are loud, locally terminal, and produce zero target calls.
- Stats preserve posture, policy, evidence references/hashes, candidate/materialized phases, decisions, reasons, warnings, and event order without secrets.
- The deterministic functional suite traverses the real API-to-target path and passes twice from reset state.
- All documentation is converged and `git status --short` contains only intentional implementation changes before the final commit sequence.
