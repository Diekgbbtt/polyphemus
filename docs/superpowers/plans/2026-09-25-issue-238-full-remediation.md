# Issue #238 Full Rate-Limit Job Admission Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve every A1-A10 and B1-B7 item for #238 and prove the result twice from independently reset live stacks, through the real public API-to-target trajectory.

**Architecture:** The controller remains authoritative for measurement, policy and admission. Transport uncertainty fails closed before policy derivation; runtime capabilities are negotiated before measurement and before target-facing dispatch; a project-isolated Compose harness uses the real actor, pods, Kali, governor, binaries, PostgreSQL, and deterministic targets.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, pytest, PostgreSQL JSONB, MCP, mitmproxy 12.2.3, Docker Compose, Vegeta v12.13.0, arjun, ffuf; no new dependency.

**Spec:** docs/superpowers/specs/2026-09-24-rate-limit-job-admission-e2e-design.md (binding). docs/design/rate-limit-system-mapping-238-spec.md is operator-owned and read-only.

## Pre-flight evidence

Read-only pre-flight produced exactly:

~~~text
worktree: feat/rate-limit-job-admission-e2e @ 7c443fb4b314e32d3d7781c14a8baaaa97cba53d
?? docs/superpowers/plans/2026-09-25-issue-238-p0-fail-closed-rate-measurement.md
main: dev @ 7a474a55e6c611a2df9f2e6127a215af44be5592
 D PROMPT-continue-hunting-agent-wiring.md
?? docs/design/eval-harness-summary-slide-prompt.md
?? docs/design/rate-limit-system-mapping-238-spec.md
?? docs/superpowers/plans/2026-09-23-issue-238-rate-limit-mapping.md
~~~

This matches the brief. Never clean/reset/stash/merge/push/tag or touch main-tree changes. This plan supersedes and absorbs the P0 plan; leave that untracked file untouched and never execute it in parallel.

## Global Constraints

- Python 3.12; closed Pydantic v2 contracts; no dependency addition.
- Writes stay rate-profile/v2, traffic-policy/v2, traffic-admission/v1; rate-result/v1 changes are additive/defaulted.
- Missing, stale, incompatible or uncertain state fails closed; never ungoverned HTTP.
- Conservative fallback is exactly 1.0 req/s, burst 1, max_concurrency 1.
- Inclusive gates: rate >= 2.0; projected duration <= 300.0 seconds.
- arjun cost 260; ffuf cost 4750; non_target inert positive sentinel 1.
- no_limiter requires a clean, complete 1/2/5/10/20 ladder and remains reachable under the 400-request default.
- Any transport loss disqualifies that probe as accepted evidence; real HTTP refusal remains evidence.
- Bypasses never affect policy/admission.
- Excluded jobs have a decision, but no recon_jobs row, pod, runner or traffic.
- Runtime incompatibility prunes only bounded_http/request_intensive jobs with runtime_capability_incompatible; non_target continues.
- target_scheme is configurable; host mode is scope, not an HTTP workaround.
- Live certification forbids mocks, scripted orchestrators, fake_run_job and direct MCP calls.
- No uncommitted behavior override; no secret/sentinel in state, target data, logs, manifests or fixtures.
- One file-changing task, one commit; no amend/squash during execution.

## Review Focus

1. DNS target over HTTP must not become HTTPS: Task 7.
2. Mixed refusal plus transport loss preserves refusal but not an accepted bound: Task 4.
3. Empty target-facing output emits no target_observed, but an observed duplicate does: Task 9.
4. Policy v2 plus wordlist mismatch prunes target-facing work only: Task 14.
5. Run B must reject every Run A run ID and fixture generation: Task 18.

## Dependency order

B3/B6 -> A3 -> B4 -> A1/A2/B5 -> A4/A5/A6 -> A7/B2/A8/A9 -> B1 -> seven-posture matrix -> A10 enforcement -> B7. Do not run containers before Task 12 approval; do not run enforcement before the matrix is green.

## Binding design decisions

1. Make `settings.target_scheme` configurable and set it to `http` in every committed #238 E2E project. `host` mode denotes a bare-IP scope and cannot be used to coerce an ordinary DNS production target onto HTTP.
2. The partial-transport tolerance is zero: one transport error removes that probe from the accepted set. An explicit HTTP refusal (for example 429/503) remains refusal evidence, so a clean lower probe plus a partially transported refusing probe may map only the clean lower bound; partial transport alone can never prove `no_limiter`.
3. An excluded job has a persisted `JobAdmissionDecision` and no `recon_jobs` row. The spec permits this choice because the admission envelope is the audit record and explicitly forbids runner/pod/traffic materialization for excluded jobs.
4. Runtime incompatibility does not fail the entire run. It yields a failed conservative profile/warning and prunes only `bounded_http` and `request_intensive` work with reason code `runtime_capability_incompatible`; `non_target` work proceeds with its required sentinel cost 1.

## File Structure and Verified Exact Anchors

All line numbers below were re-read at HEAD 7c443fb4 before this plan was written. New files are identified as such in their owning task.

| Concern | Existing intervention/test anchors |
|---|---|
| A1 auth | `tests/e2e/harness/driver.py:269,424-438`; `src/polymerhus/app/auth/records.py:35-68,198-306` |
| A2 JSON contract | `src/polymerhus/recon/domain/traffic_admission.py:161-181,204-276`; `src/polymerhus/recon/domain/rate_limit.py:495-541`; `src/polymerhus/app/clients/pg.py:381-399`; `tests/e2e/test_rate_limit_admission_e2e.py:123-155` |
| A3/B4 measurement | `src/polymerhus/recon/domain/rate_limit.py:340-368`; `src/polymerhus/recon/control/rate_limit_runner.py:146-176,425-438`; `src/polymerhus/recon/control/rate_limit_mapper.py:473-545`; `kali/rate_limit/models.py:96-137`; `kali/rate_limit/runner.py:212-267,349-395`; tests at `tests/recon/test_rate_limit_runner.py:138`, `tests/recon/test_rate_limit_mapper.py:83`, `tests/kali/test_rate_limit_runner.py:159` |
| B5 scheme | `src/polymerhus/recon/control/pipeline.py:87-101`; `tests/recon/test_rate_limit_pipeline.py:238-290` |
| A4 rows | `src/polymerhus/recon/control/pipeline.py:800-925` (current early insert at 834); `tests/recon/test_rate_limit_pipeline.py:33-60,547-583` |
| A5 observation | `src/polymerhus/recon/domain/types.py:170`; `src/polymerhus/recon/control/pipeline.py:937-945`; `tests/recon/test_rate_limit_pipeline.py:585-632` |
| A6 redaction | `src/polymerhus/recon/control/pipeline.py:981-987`; `tests/recon/test_pipeline.py:680-711` |
| A7 roles | `docker-compose.e2e.yml:21-43` |
| A8 image | `docker-compose.yml:95-110`; `kali/Dockerfile:1-38`; `Dockerfile.kali:16-117`; `tests/kali/test_http_history_deployment.py:106-145` |
| A9 capabilities | `kali/http_history/capabilities.py:48-58,115-141`; `kali/http_history/service.py:486-527`; `kali/mcp_server.py:206-229`; `src/polymerhus/recon/control/pipeline.py:125-178,620-925`; `tests/kali/test_http_history_service.py:31-55` |
| Matrix/enforcement/reset | `tests/e2e/test_rate_limit_admission_e2e.py:34-294`; `tests/e2e/harness/driver.py:230-470`; `tests/e2e/rate_limit_matrix_target.py:35-337`; `docker-compose.e2e.yml:157-284` |

---

### Task 1 [B3]: One Authoritative Plan

**Files:** Track this file; leave the untracked P0 file untouched.

**Interfaces:** Consumes the pre-flight state above. Produces this tracked file as the sole implementation plan and leaves `2026-09-25-issue-238-p0-fail-closed-rate-measurement.md` untracked and inert.

- [ ] **RED:** git ls-files --error-unmatch docs/superpowers/plans/2026-09-25-issue-238-full-remediation.md

Expected: exit 1.

- [ ] **Implement and commit:**

~~~bash
git add docs/superpowers/plans/2026-09-25-issue-238-full-remediation.md
git commit -m "docs(plan): supersede issue 238 p0 plan"
~~~

- [ ] **GREEN:** repeat ls-files; git status --short must show only the untracked P0 plan.

### Task 2 [B6]: Auditable Commit Policy

**Files:** Create scripts/check_issue_238_commit_series.py; tests/recon/test_issue_238_commit_series.py.

**Interfaces:** Consumes Git subjects after `7c443fb4`. Produces `missing_subjects(actual: list[str], expected: list[str]) -> list[str]` and a zero/non-zero CLI used by final verification.

- [ ] **Failing test:**

~~~python
from scripts.check_issue_238_commit_series import missing_subjects
def test_order():
    assert missing_subjects(["one", "three"], ["one", "two", "three"]) == ["two"]
~~~

- [ ] **RED:** .venv/bin/python -m pytest tests/recon/test_issue_238_commit_series.py -q

Expected: ModuleNotFoundError.

- [ ] **Minimal implementation:**

~~~python
def missing_subjects(actual, expected):
    pos, missing = 0, []
    for subject in expected:
        try: pos = actual.index(subject, pos) + 1
        except ValueError: missing.append(subject)
    return missing

EXPECTED_SUBJECTS = [
    "docs(plan): supersede issue 238 p0 plan",
    "test(issue-238): audit task commit sequence",
    "fix(rate-limit): fail closed without HTTP evidence",
    "fix(rate-limit): require clean exhausted ladder",
    "fix(e2e): use valid public auth fixture",
    "fix(issue-238): align persisted public shapes",
    "fix(recon): make target transport scheme explicit",
    "fix(recon): avoid rows for pruned jobs",
    "fix(recon): ground target observation in responses",
    "fix(recon): redact durable job commands",
    "fix(e2e): configure every required model role",
    "test(e2e): isolate issue 238 container scope",
    "build(kali): make issue 238 image self contained",
    "fix(recon): negotiate Kali runtime capabilities",
    "ops(issue-238): version live stack lifecycle",
    "test(e2e): prove seven rate postures live",
    "test(e2e): certify four live enforcement paths",
    "ops(issue-238): prove independent reset gates",
]
~~~

The CLI runs `git log --format=%s --reverse 7c443fb4..HEAD`, passes its lines to `missing_subjects`, prints only missing subjects, and exits 1 when the returned list is non-empty; otherwise it prints `18 ordered task commits present` and exits 0.

- [ ] **GREEN/commit:**

~~~bash
.venv/bin/python -m pytest tests/recon/test_issue_238_commit_series.py -q
git add scripts/check_issue_238_commit_series.py tests/recon/test_issue_238_commit_series.py
git commit -m "test(issue-238): audit task commit sequence"
~~~

### Task 3 [A3]: Zero HTTP Responses Are Failure

**Files:** Modify src/polymerhus/recon/domain/rate_limit.py:340-368; src/polymerhus/recon/control/rate_limit_runner.py:146-176; kali/rate_limit/models.py:96-137; kali/rate_limit/runner.py:212-267,349-395. Test both runner suites.

**Interfaces:** Consumes Kali probe hits and the existing `RateLimitEvidence` wire shape. Produces additive `transport_errors: int` and controller evidence whose `outcome` is `failed` when no 100..599 response exists.

- [ ] **Failing tests:**

~~~python
e = evidence_from_kali_result(spec, {"outcome":"measured","count":5,
                                    "status_counts":{"0":5},"transport_errors":5})
assert e.outcome == "failed" and e.status_counts == {}
assert e.transport_errors == 5 and e.artifact_ref is None
~~~

Kali twin feeds five code=0 hits and asserts failed, empty status_counts, transport_errors=5, no artifact. A pipeline test feeds that evidence into the mapper and asserts policy `(1.0, 1, 1)`, arjun/ffuf exclusion, and persisted warning `measurement_failed`.

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_runner.py::test_transport_only_evidence_is_failed_not_measured tests/kali/test_rate_limit_runner.py::test_kali_transport_only_probe_publishes_nothing tests/recon/test_rate_limit_pipeline.py::test_transport_only_measurement_falls_back_and_prunes_intensive_jobs -q`

Expected: all three FAIL; status 0 is retained, the field is absent, and current policy/admission incorrectly permits the request-intensive jobs.

- [ ] **Implement:** add `transport_errors: int = Field(default=0, ge=0)` to both contracts and apply these exact guards before publication and again at the controller boundary:

~~~python
valid_status_counts = {
    str(code): count for code, count in raw_status_counts.items()
    if 100 <= int(code) <= 599
}
transport_errors = sum(
    count for code, count in raw_status_counts.items()
    if not 100 <= int(code) <= 599
)
failed = producer_failed or not valid_status_counts
outcome = "failed" if failed else "measured"
artifact_ref = None if failed else payload.get("artifact_ref")
manifest_sha256 = None if failed else payload.get("manifest_sha256")
~~~

On Kali, compute the same split from hits and return the object below before `artifact_store.publish` when no valid status remains; code 0 never enters `status_counts`. The controller recomputes rather than trusting producer `outcome`.

~~~python
return KaliExperimentResult(
    experiment_id=parsed.experiment_id,
    phase=parsed.phase,
    outcome="failed",
    offered_rate_per_s=parsed.rate_per_s,
    concurrent_workers=parsed.concurrency,
    count=len(hits),
    transport_errors=transport_errors,
    error="no valid HTTP response",
).model_dump(mode="json")
~~~

- [ ] **GREEN:** pytest tests/recon/test_rate_limit_runner.py tests/kali/test_rate_limit_runner.py tests/kali/test_rate_limit_store.py -q; expected PASS.

- [ ] **Commit:**

~~~bash
git add src/polymerhus/recon/domain/rate_limit.py src/polymerhus/recon/control/rate_limit_runner.py kali/rate_limit/models.py kali/rate_limit/runner.py tests/recon/test_rate_limit_runner.py tests/kali/test_rate_limit_runner.py
git commit -m "fix(rate-limit): fail closed without HTTP evidence"
~~~

### Task 4 [B4]: Partial Transport and Ladder Exhaustion

**Files:** Modify rate_limit_mapper.py:473-545,606-630,753-765; rate_limit_runner.py:45-58,425-438,718-735; both recon tests.

**Interfaces:** Consumes Task 3's `transport_errors`. Produces clean accepted bounds, `ladder_exhausted(evidence, budget) -> bool`, and an inconclusive/failed result that derives the 1 req/s fallback before admission.

- [ ] **Failing tests:**

~~~python
assert classify_mapping([
    _ev("s0","steady",1,transport_errors=2,codes={"200":8}),
    _ev("s1","steady",2,transport_errors=1,codes={"200":9}),
]).outcome == "inconclusive"
control = classify_mapping([
    _ev("s0","steady",1,codes={"200":10}),
    _ev("s1","steady",2,transport_errors=1,codes={"200":9}),
    _ev("s2","steady",5,rejected=5,codes={"429":5}),
])
assert (control.outcome, control.threshold_low_per_s) == ("mapped", 1.0)
~~~

Add truncated-budget assertions for policy rate/burst/concurrency `(1.0, 1, 1)`, arjun/ffuf exclusion, and a persisted `measurement_inconclusive` warning; add the positive default-budget `no_limiter==20.0` test.

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_mapper.py::test_partial_transport_never_becomes_an_accepted_bound tests/recon/test_rate_limit_mapper.py::test_real_refusal_uses_only_the_clean_lower_bound tests/recon/test_rate_limit_runner.py::test_budget_truncated_ladder_downgrades_to_fallback tests/recon/test_rate_limit_runner.py::test_default_budget_still_reaches_no_limiter -q`

Expected: partial/truncated assertions FAIL; the positive no_limiter control passes.

- [ ] **Implement:**

~~~python
accepted = [e for e in ladder if e.rejection_ratio <= _EPSILON
            and e.transport_errors == 0]
degraded = any(e.transport_errors > 0 for e in measured)
if (refused or concurrency_limited) and accepted: outcome = "mapped"
elif len(distinct_rates) >= 2 and not degraded: outcome = "no_limiter"
else: outcome = "inconclusive"
~~~

Add `ladder_exhausted` by comparing every `_ladder(budget)` rate with clean steady evidence. `_finish` changes unexhausted `no_limiter` to `inconclusive` before `derive_policy`; the existing policy/admission path then persists `measurement_inconclusive`, applies `(1.0, 1, 1)`, and excludes both request-intensive jobs.

- [ ] **GREEN/commit:** run both suites; expected PASS and reachable no_limiter.

~~~bash
git add src/polymerhus/recon/control/rate_limit_mapper.py src/polymerhus/recon/control/rate_limit_runner.py tests/recon/test_rate_limit_mapper.py tests/recon/test_rate_limit_runner.py
git commit -m "fix(rate-limit): require clean exhausted ladder"
~~~

### Task 5 [A1]: Valid Public Auth Fixture

**Files:** Modify tests/e2e/harness/driver.py:424-438; create tests/e2e/test_rate_limit_harness_contracts.py. Read records.py:35-68,198-306 only.

**Interfaces:** Consumes public `validate_overview(dict)` and `validate_account(dict)`. Produces contract-valid `SMOKE_OVERVIEW` and `SMOKE_ACCOUNTS` sent unchanged through `PUT /projects/{id}/auth`.

- [ ] **Failing test:** validate SMOKE_OVERVIEW with validate_overview and each SMOKE_ACCOUNTS value with validate_account in `test_smoke_auth_fixture_is_public_contract_valid`.

- [ ] **RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_harness_contracts.py::test_smoke_auth_fixture_is_public_contract_valid -q`

Expected: FAIL with `auth_invalid: overview.target is not a known overview field`, then the nested account is invalid.

- [ ] **Implement:**

~~~python
SMOKE_OVERVIEW = {"http-client-replayability": True,
                  "required_headers": ["X-E2E-Correlation"],
                  "notes": "Disposable issue 238 fixture."}
SMOKE_ACCOUNTS = {"smoke-account": {
    "origin": "operator", "status": "valid",
    "snapshot": {"headers":{"X-E2E-Correlation":"issue-238-smoke"},
                 "cookies":[{"name":"session","value":"e2e-smoke-cookie"}]}}}
~~~

- [ ] **GREEN/commit:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_harness_contracts.py tests/app/test_auth_records.py -q` must PASS.

~~~bash
git add tests/e2e/harness/driver.py tests/e2e/test_rate_limit_harness_contracts.py
git commit -m "fix(e2e): use valid public auth fixture"
~~~

### Task 6 [A2]: Public JSON Shapes

**Files:** Modify traffic_admission.py:204-276; test_traffic_admission.py; test_rate_limit_pipeline.py:540-790; E2E test:123-155. Read pg.py:381-399.

**Interfaces:** Consumes persisted admission/profile JSON. Produces canonical serialized `job: str`, accepts legacy input `job_name`, keeps `artifact_refs: list[str]`, and reads typed evidence objects from `rate_limit.evidence`.

- [ ] **Failing test:** decision.model_dump has job and not job_name; profile evidence entries have ref/sha256/experiment_id/count; artifact_refs entries are strings.

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_traffic_admission.py::test_public_issue_238_shapes_use_job_and_typed_evidence -q`

Expected: FAIL because the decision emits `job_name`.

- [ ] **Implement:**

~~~python
job: str = Field(validation_alias=AliasChoices("job", "job_name"))
@property
def job_name(self): return self.job
~~~

Construct with job=job.tool. E2E decisions/per_job read row["job"]; hashes come from rate_limit["evidence"].

- [ ] **GREEN/commit:** `.venv/bin/python -m pytest tests/recon/test_traffic_admission.py tests/recon/test_rate_limit_pipeline.py tests/e2e/test_rate_limit_harness_contracts.py -q` must PASS.

~~~bash
git add src/polymerhus/recon/domain/traffic_admission.py tests/recon/test_traffic_admission.py tests/recon/test_rate_limit_pipeline.py tests/e2e/test_rate_limit_admission_e2e.py
git commit -m "fix(issue-238): align persisted public shapes"
~~~

### Task 7 [B5]: Explicit Target Scheme

**Files:** Modify pipeline.py:87-101; test_rate_limit_pipeline.py:230-290; driver.py:441-470; runbook.

**Interfaces:** Consumes optional project setting `target_scheme`. Produces `_rate_target(settings: dict | None) -> tuple[str, str] | None` with explicit `http|https` validation and unchanged legacy inference when absent.

- [ ] **Failing tests:** `test_domain_target_can_explicitly_use_http` expects the HTTP URL; `test_invalid_target_scheme_fails_loudly` expects ValueError.

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py -k 'explicitly_use_http or invalid_target_scheme' -q`

Expected: first FAILS with HTTPS; second FAILS because no exception is raised.

- [ ] **Implement:**

~~~python
configured = (settings or {}).get("target_scheme")
scheme = ("http" if scope["mode"] == "host" else "https") if configured is None else str(configured).lower()
if scheme not in {"http", "https"}:
    raise ValueError("target_scheme must be 'http' or 'https'")
return host, f"{scheme}://{host}/"
~~~

Every #238 project writes target_scheme="http". Document that host mode would falsify production scope.

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py tests/e2e/test_rate_limit_harness_contracts.py -q`

Expected: PASS, including legacy inference.

- [ ] **Commit:**

~~~bash
git add src/polymerhus/recon/control/pipeline.py tests/recon/test_rate_limit_pipeline.py tests/e2e/harness/driver.py docs/design/rate-limit-job-admission-operations.md
git commit -m "fix(recon): make target transport scheme explicit"
~~~

### Task 8 [A4]: Rows Only for Materialized Jobs

**Files:** Modify pipeline.py:800-925; test_rate_limit_pipeline.py:33-60,547-583; test_pipeline.py:680-711.

**Interfaces:** Consumes Task 6 admission decisions. Produces one `recon_jobs` row only when `_run_one(job)` starts; excluded decisions remain queryable without a row, pod, runner, or target request.

- [ ] **Failing test:** excluded ffuf/arjun decisions exist, but registry.job_rows contains neither; admitted httpx row exists.

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py::test_pruned_jobs_have_decisions_but_no_job_rows -q`

Expected: FAIL because current line 834 created excluded `in_progress` rows.

- [ ] **Implement:** remove the current pre-admission `upsert_job` at line 834 and insert only this call in `_run_one`, after `job_configs[name]` proves materialization and before the execution clock starts. Keep the existing setup-exception `degraded` row because it records a candidate that failed during real setup, not an admission exclusion.

~~~python
async def _run_one(name: str) -> None:
    job, input_assets, prepared, extra = job_configs[name]
    await asyncio.to_thread(
        registry.upsert_job, run_id, phase_idx, name, "in_progress"
    )
    exec_t0 = time.monotonic()
    exec_started_at = _utc_now_iso()
~~~

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py tests/recon/test_pipeline.py tests/recon/test_pipeline_heartbeat.py -q`

Expected: PASS; admitted row and heartbeat/stall behavior remain intact.

- [ ] **Commit:**

~~~bash
git add src/polymerhus/recon/control/pipeline.py tests/recon/test_rate_limit_pipeline.py tests/recon/test_pipeline.py
git commit -m "fix(recon): avoid rows for pruned jobs"
~~~

### Task 9 [A5]: Truthful target_observed

**Files:** Modify `src/polymerhus/recon/domain/types.py:170-194`, `src/polymerhus/recon/domain/pod.py:556-617`, `src/polymerhus/recon/crawl/crawl_pod.py:230-269`, `src/polymerhus/recon/control/pipeline.py:912-945`, `tests/recon/test_pod.py` beside its PodExport tests, and `tests/recon/test_rate_limit_pipeline.py:585-632`.

**Interfaces:** Produces additive `PodExport.target_responses: int` and consumes it in `_pod_observed_target(export: PodExport) -> bool`; graph novelty is deliberately not part of this predicate.

- [ ] **Failing tests:**

~~~python
assert pipeline._pod_observed_target(PodExport(input_asset={}, verdict="success")) is False
assert pipeline._pod_observed_target(PodExport(input_asset={}, verdict="success",
                                               target_responses=1)) is True
~~~

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_rate_limit_pipeline.py -k 'without_response or observed_duplicate' -q`

Expected: collection/assertion FAIL because the field/helper is missing.

- [ ] **Implement:** add the field and predicate below. In both `src/polymerhus/recon/domain/pod.py:586-601` and `src/polymerhus/recon/crawl/crawl_pod.py:246-257`, set `target_responses=int(bool(assets or observations))` from pre-curation parser output, so a graph duplicate remains positive even when merge counts are zero.

~~~python
class PodExport(BaseModel):
    target_responses: int = Field(default=0, ge=0)

def _pod_observed_target(export: PodExport) -> bool:
    return export.verdict == "success" and export.target_responses > 0
~~~

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/recon/test_pod.py tests/recon/test_rate_limit_pipeline.py -q`

Expected: PASS for empty negative and duplicate-positive cases.

- [ ] **Commit:**

~~~bash
git add src/polymerhus/recon/domain/types.py src/polymerhus/recon/domain/pod.py src/polymerhus/recon/control/pipeline.py tests/recon/test_pod.py tests/recon/test_rate_limit_pipeline.py
git commit -m "fix(recon): ground target observation in responses"
~~~

### Task 10 [A6]: Redact Durable Commands

**Files:** Create domain/redaction.py and test_redaction.py; modify pipeline.py:45-65,981-987; test_pipeline.py:680-711; E2E secret scanner.

**Interfaces:** Consumes a command string plus auth-derived exact secret values. Produces `redact_command(command: str, secret_values: Iterable[str]) -> str`, used immediately before durable `job_stats["commands"]` construction.

- [ ] **Failing test:** assemble a sentinel from fragments; redact a cookie/header command; assert value absent without including it in failure text. Persistence twin asserts captured job stats contain [redacted].

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_redaction.py tests/recon/test_pipeline.py::test_job_stats_redact_header_and_cookie_values -q`

Expected: missing-module ERROR, then raw command assertion failure.

- [ ] **Implement:** use the concrete redactor below; collect non-empty header/cookie values from `extra["auth_context"]`, call it for every command before constructing `job_stats["commands"]`, and never include the rejected value in assertion messages. The E2E scanner checks stats, per_job, target counters/events, capped logs and referenced manifests; errors name only the surface.

~~~python
_SENSITIVE = re.compile(
    r"(?i)(authorization|cookie|x-api-key|api[-_]?key|token|password|secret)"
    r"(\s*[:=]\s*|\s+)([^\s;]+)"
)

def redact_command(command: str, secret_values: Iterable[str]) -> str:
    redacted = command
    for value in sorted({v for v in secret_values if v}, key=len, reverse=True):
        redacted = redacted.replace(value, "[redacted]")
    return _SENSITIVE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", redacted)
~~~

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/recon/test_redaction.py tests/recon/test_pipeline.py tests/e2e/test_rate_limit_harness_contracts.py -q`

Expected: PASS without printing the sentinel.

- [ ] **Commit:**

~~~bash
git add src/polymerhus/recon/domain/redaction.py src/polymerhus/recon/control/pipeline.py tests/recon/test_redaction.py tests/recon/test_pipeline.py tests/e2e/test_rate_limit_admission_e2e.py
git commit -m "fix(recon): redact durable job commands"
~~~

### Task 11 [A7]: All Required Model Roles

**Files:** Modify docker-compose.e2e.yml:21-43; harness/provider tests.

**Interfaces:** Consumes the deterministic OpenAI-compatible provider. Produces committed bindings for all five boot-required `LLM_*` variables and a two-second profile TTL used by the live stale scenario.

- [ ] **Failing test:** `test_e2e_overlay_configures_every_boot_required_llm_role` requires CONFIGURATOR, CRAWLER, JOB_ORCHESTRATOR, TRIAGER, ANALYSER, all `openai:rate-admission-fixture`.

- [ ] **RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_harness_contracts.py::test_e2e_overlay_configures_every_boot_required_llm_role -q`

Expected: FAIL naming the three missing roles.

- [ ] **Implement:** the `agent.environment` overlay contains exactly these committed values in addition to its existing database/service settings:

~~~yaml
LLM_GATEWAY_URL: http://rate-limit-llm:8080/v1
LLM_CONFIGURATOR: openai:rate-admission-fixture
LLM_CRAWLER: openai:rate-admission-fixture
LLM_JOB_ORCHESTRATOR: openai:rate-admission-fixture
LLM_TRIAGER: openai:rate-admission-fixture
LLM_ANALYSER: openai:rate-admission-fixture
API_KEY_OPENAI: e2e-inert-key
RATE_LIMIT_PROFILE_TTL_S: "2"
~~~

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_harness_contracts.py tests/e2e/test_deterministic_llm_provider.py -q` and `docker compose -f docker-compose.yml -f docker-compose.e2e.yml config --quiet` both exit 0.

- [ ] **Commit:**

~~~bash
git add docker-compose.e2e.yml tests/e2e/test_rate_limit_harness_contracts.py tests/e2e/test_deterministic_llm_provider.py
git commit -m "fix(e2e): configure every required model role"
~~~

### Task 12 [B2]: Isolated Container Authority

**Files:** Modify overlay:21-43,240-284; create test_rate_limit_stack_contract.py.

**Interfaces:** Produces project-private `polymerhus-agent:issue-238-e2e` and `polymerhus-kali:issue-238-e2e` image references. Consumes explicit operator authorization before any image build, recreate, or volume removal.

- [ ] **Failing test:** `test_issue238_overlay_never_uses_shared_latest_tags` requires the two issue-specific tags.

- [ ] **RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_stack_contract.py::test_issue238_overlay_never_uses_shared_latest_tags -q`

Expected: FAIL showing shared `latest` tags.

- [ ] **Implement/GREEN:** pin only the E2E overlay; do not change shared default tags in `docker-compose.yml`:

~~~yaml
services:
  agent:
    image: polymerhus-agent:issue-238-e2e
  kali:
    image: polymerhus-kali:issue-238-e2e
  kali-failing-governor:
    image: polymerhus-kali:issue-238-e2e
  kali-capture-off:
    image: polymerhus-kali:issue-238-e2e
~~~

Rerun the named test and expect PASS.

- [ ] **Commit:**

~~~bash
git add docker-compose.e2e.yml tests/e2e/test_rate_limit_stack_contract.py
git commit -m "test(e2e): isolate issue 238 container scope"
~~~

- [ ] **Pause and ask exactly:**

> Autorizzi l'esecutore a ricostruire e ricreare esclusivamente i servizi del progetto Compose polyphemus-238-e2e, a rimuoverne i soli volumi tra le due prove, e a creare i tag locali polymerhus-agent:issue-238-e2e e polymerhus-kali:issue-238-e2e, senza arrestare, rinominare o rimuovere container, volumi, reti o tag di altri progetti?

A denial blocks Tasks 13-18. Offline proof cannot substitute.

### Task 13 [A8]: Self-Contained Kali Image

**Files:** Modify Dockerfile.kali:1-120; remove all references then delete kali/Dockerfile:1-38; modify compose files; deployment/stack tests.

**Interfaces:** Consumes the Task 12 private Kali tag. Produces one reproducible image containing `mitmdump`, the governor/addon, Vegeta v12.13.0, the 4,750-line ffuf wordlist, and build provenance.

- [ ] **Failing test:** `test_compose_builds_the_self_contained_kali_image` pins Dockerfile, Vegeta, mitmproxy, copy, and no redamon base.

- [ ] **RED:** `.venv/bin/python -m pytest tests/kali/test_http_history_deployment.py tests/e2e/test_rate_limit_stack_contract.py -q`

Expected: FAIL because Compose selects `kali/Dockerfile` and `Dockerfile.kali` lacks mitmproxy.

- [ ] **Implement:** after the existing Vegeta/tool installation in `Dockerfile.kali`, fold in the capture runtime below, point the base Compose build to `Dockerfile.kali`, then remove `kali/Dockerfile` only after `rg -n 'kali/Dockerfile' . --glob '!docs/superpowers/plans/*'` returns no live reference.

~~~dockerfile
ARG UV_VERSION=0.9.7
ARG MITMPROXY_VERSION=12.2.3
ARG MITMPROXY_PYTHON=3.13
RUN /opt/venv/bin/pip install --no-cache-dir "uv==${UV_VERSION}" "httpx[http2]==0.28.1" \
 && /opt/venv/bin/uv python install "${MITMPROXY_PYTHON}" \
 && /opt/venv/bin/uv venv --python "${MITMPROXY_PYTHON}" /opt/mitmproxy-env \
 && /opt/venv/bin/uv pip install --python /opt/mitmproxy-env/bin/python \
      "mitmproxy==${MITMPROXY_VERSION}" "pydantic>=2,<3"
COPY kali /opt/kali
RUN chmod +x /opt/kali/entrypoint.sh /opt/kali/postrun.sh
ENV PYTHONPATH=/opt KALI_HTTP_HISTORY_ROOT=/data \
    KALI_HTTP_CAPTURE_ENABLED=true KALI_HTTP_GOVERNOR_ENABLED=true
ENTRYPOINT ["/opt/kali/entrypoint.sh"]
~~~

The Compose build stanza becomes `build: {context: ., dockerfile: Dockerfile.kali}` and retains the existing `SOURCE_REVISION` argument.

- [ ] **Offline GREEN:** rerun the RED command; expected PASS.

- [ ] **Authorized build GREEN:**

~~~bash
SOURCE_REVISION=$(git rev-parse HEAD) docker compose -p polyphemus-238-e2e -f docker-compose.yml -f docker-compose.e2e.yml build kali
docker run --rm --entrypoint /bin/sh polymerhus-kali:issue-238-e2e -lc 'test -x /opt/mitmproxy-env/bin/mitmdump && go version -m "$(command -v vegeta)" | grep "github.com/tsenart/vegeta/v12.*v12.13.0" && test "$(sed "/^[[:space:]]*$/d" /usr/share/seclists/Discovery/Web-Content/common.txt | wc -l)" = 4750 && test -f /opt/polymerhus/build-provenance.json'
~~~

- [ ] **Commit:**

~~~bash
git add Dockerfile.kali kali/Dockerfile docker-compose.yml docker-compose.e2e.yml tests/kali/test_http_history_deployment.py tests/e2e/test_rate_limit_stack_contract.py
git commit -m "build(kali): make issue 238 image self contained"
~~~

### Task 14 [A9]: Runtime Capability Negotiation

**Files:** Modify `src/polymerhus/app/clients/kali_mcp.py:1-27`; create `src/polymerhus/recon/domain/runtime_capabilities.py`; modify `src/polymerhus/recon/domain/traffic_admission.py:161-218`, `src/polymerhus/recon/control/traffic_admission.py:105-145`, and `src/polymerhus/recon/control/pipeline.py:125-178,620-925`; extend `tests/recon/test_traffic_admission.py:261`, `tests/recon/test_rate_limit_pipeline.py:758`, `tests/kali/test_http_history_service.py:31-55`, and `tests/kali/test_http_history_mcp_tools.py` beside proxy-status tests.

**Interfaces:** Consumes the public `proxy_status` response. Produces closed `RuntimeCapabilities` plus `compatibility_error() -> str | None`; admission reason is exactly `runtime_capability_incompatible` and detailed capability text remains in the warning/evidence, not the reason code.

- [ ] **Failing tests:** `test_incompatible_runtime_prunes_only_target_facing_jobs` and `test_wordlist_mismatch_is_selective` materialize only subfinder and require `runtime_capability_incompatible`.

- [ ] **RED:** `.venv/bin/python -m pytest tests/recon/test_traffic_admission.py tests/recon/test_rate_limit_pipeline.py -k 'incompatible_runtime or wordlist_mismatch' -q`

Expected: collection/assertion FAIL for missing type/reason.

- [ ] **Implement closed type:**

~~~python
class RuntimeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    governor_enabled: bool
    supported_policy_versions: tuple[str, ...]
    vegeta_version: str
    ffuf_wordlist_count: int = Field(ge=0)
    build_revision: str

    def compatibility_error(self) -> str | None:
        if not self.governor_enabled: return "governor_disabled"
        if "traffic-policy/v2" not in self.supported_policy_versions: return "policy_version"
        if self.vegeta_version != "v12.13.0": return "vegeta_version"
        if self.ffuf_wordlist_count != 4750: return "ffuf_wordlist_cardinality"
        return None
~~~

MCP reader calls proxy_status and validates governor/build/wordlist blocks; controller never imports Kali helpers. Check before mapping and again before first target-facing pod. Incompatibility skips mapping, persists failed fallback/warning, and prunes only target-facing jobs; it does not fail the whole run.

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/recon/test_traffic_admission.py tests/recon/test_rate_limit_pipeline.py tests/kali/test_http_history_service.py tests/kali/test_http_history_mcp_tools.py -q`

Expected: PASS; mismatch produces zero target-facing runner calls.

- [ ] **Commit:**

~~~bash
git add src/polymerhus/app/clients/kali_mcp.py src/polymerhus/recon/domain/runtime_capabilities.py src/polymerhus/recon/domain/traffic_admission.py src/polymerhus/recon/control/traffic_admission.py src/polymerhus/recon/control/pipeline.py tests/recon/test_traffic_admission.py tests/recon/test_rate_limit_pipeline.py tests/kali/test_http_history_service.py
git commit -m "fix(recon): negotiate Kali runtime capabilities"
~~~

### Task 15 [B1]: Versioned Stack Lifecycle

**Files:** Create scripts/issue_238_e2e_stack.sh; modify Dockerfile for agent revision; overlay; stack test; runbook.

**Interfaces:** Consumes operator authority and Tasks 11-14 images/config. Produces commands `config|build|up|health|assert-clean|reset-targets|down`, all fixed to project `polyphemus-238-e2e`, and machine-readable generation/revision evidence.

- [ ] **Failing test:** `test_stack_script_pins_project_files_and_safe_lifecycle` checks fixed project/files/revision/reset and forbids global prune.

- [ ] **RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_stack_contract.py::test_stack_script_pins_project_files_and_safe_lifecycle -q`

Expected: FileNotFoundError.

- [ ] **Implement:** the script starts with the fixed project and service set below and refuses unknown verbs. `assert-clean` queries PostgreSQL for zero `recon_runs`, reads `/state` from `rate-limit-llm` for zero provider requests, and calls `/counters` on every target, requiring zero requests and printing each non-empty generation. `health` compares agent/Kali provenance with `git rev-parse HEAD` and checks policy v2, Vegeta v12.13.0, wordlist 4750.

~~~sh
#!/bin/sh
set -eu
PROJECT=polyphemus-238-e2e
SERVICES="postgres neo4j rate-limit-llm rate-matrix-no-limiter rate-matrix-high-limit rate-matrix-low-limit rate-matrix-false-bypass rate-matrix-burst-inconclusive kali kali-failing-governor kali-capture-off agent"
compose() {
  docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.e2e.yml "$@"
}
case "${1:-}" in
  config) compose config --quiet ;;
  build) SOURCE_REVISION="$(git rev-parse HEAD)" compose build agent kali ;;
  up) compose up -d --wait $SERVICES ;;
  health) verify_health_and_provenance ;;
  assert-clean) assert_clean_state ;;
  reset-targets) reset_all_targets_and_record_generations ;;
  down) compose down --volumes --remove-orphans ;;
  gate-once) gate_once "${2:?run name required}" ;;
  gate-twice) gate_twice "${2:?artifact directory required}" ;;
  *) echo "usage: $0 {config|build|up|health|assert-clean|reset-targets|down|gate-once|gate-twice}" >&2; exit 64 ;;
esac
~~~

The helper bodies use the following concrete checks; the target-reset JSON printed by `reset_all_targets_and_record_generations` is redirected into the current run manifest by `gate_once`:

~~~sh
verify_health_and_provenance() {
  test "$(compose ps --status running --services | sort | tr '\n' ' ')" = \
       "$(printf '%s\n' $SERVICES | sort | tr '\n' ' ')"
  compose exec -T agent python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=5).read()'
  head_revision="$(git rev-parse HEAD)"
  test "$(compose exec -T agent sed -n 's/.*"revision": *"\([^"]*\)".*/\1/p' /opt/polymerhus/build-provenance.json)" = "$head_revision"
  test "$(compose exec -T kali sed -n 's/.*"revision": *"\([^"]*\)".*/\1/p' /opt/polymerhus/build-provenance.json)" = "$head_revision"
  compose exec -T kali go version -m /root/go/bin/vegeta | grep 'github.com/tsenart/vegeta/v12.*v12.13.0'
}
assert_clean_state() {
  test "$(compose exec -T postgres psql -U polymerhus -d polymerhus -Atc 'select count(*) from recon_runs')" = 0
  compose exec -T rate-limit-llm python -c 'import json,urllib.request; assert json.load(urllib.request.urlopen("http://127.0.0.1:8080/health"))["requests"] == 0'
  reset_all_targets_and_record_generations
}
reset_all_targets_and_record_generations() {
  compose exec -T agent python - <<'PY'
import json, urllib.request
targets = (
    "rate-matrix-no-limiter", "rate-matrix-high-limit",
    "rate-matrix-low-limit", "rate-matrix-false-bypass",
    "rate-matrix-burst-inconclusive",
)
generations = {}
for target in targets:
    base = f"http://{target}"
    request = urllib.request.Request(f"{base}/reset", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        generation = json.load(response)["generation"]
    with urllib.request.urlopen(f"{base}/counters?generation={generation}", timeout=5) as response:
        counters = json.load(response)
    assert counters["requests"] == 0
    generations[target] = generation
print(json.dumps(generations, sort_keys=True))
PY
}
~~~

`gate_once` exports `POLYPHEMUS_API_BASE=http://localhost:8080`, runs the provider check, Task 16 matrix, Task 17 enforcement, regressions, critical contracts and mutation verifier in that order, and records each exit. Task 18 adds its exact `gate_twice` body. No helper invokes MCP directly.

- [ ] **Offline GREEN:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_stack_contract.py -q`; expected PASS.

- [ ] **Commit:**

~~~bash
git add scripts/issue_238_e2e_stack.sh Dockerfile docker-compose.e2e.yml tests/e2e/test_rate_limit_stack_contract.py docs/design/rate-limit-job-admission-operations.md
git commit -m "ops(issue-238): version live stack lifecycle"
~~~

- [ ] **Authorized live GREEN:** run config, build, down, up, health, assert-clean; every command exits 0 and no role error occurs.

### Task 16: Seven-Posture Matrix Before Enforcement

**Files:** Modify `tests/e2e/rate_limit_matrix_target.py:35-337`, `tests/e2e/harness/driver.py:230-470`, `tests/e2e/test_rate_limit_admission_e2e.py:34-294`, and `tests/e2e/test_rate_limit_matrix_target.py` beside existing handler/counter tests.

**Interfaces:** Consumes Tasks 3-15 through the public API only. Produces the seven required live scenarios: five target postures (`no_limiter`, high compatible, low/no-bypass, low/false-bypass, burst-inconclusive), rate-stage failure, and stale profile. The sentinel cost remains an assertion on non-target jobs, not an invented eighth posture.

- [ ] **Make RED:** mark six parameter rows plus stale as issue238_matrix. Require both arjun/ffuf decisions and public rows, matching generation, and target events attributable to ffuf wordlist paths and arjun query-key names.

- [ ] **Run RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_admission_e2e.py -m issue238_matrix -vv -rs -p no:cacheprovider`

Expected: one or more FAIL, zero skips; auth/shape/scheme/measurement/traffic gaps are visible.

- [ ] **Implement fixture:** add an HTML sender and make a successful `/` response expose exactly this same-origin crawl/input surface; do not embed a hostname, credential, or external URL.

~~~python
INDEX_HTML = b"""<!doctype html><html><body>
<a href="/canonical?seed=1">canonical</a>
<form method="get" action="/canonical">
<input name="issue238_probe"><button type="submit">probe</button>
</form></body></html>"""
~~~

Extend each target event with `query_names=sorted(parse_qs(parts.query))` and the disposable `x-e2e-correlation` value after the same secret scrubber used for headers. Retain only `seq`, monotonic time, route, query names, correlation, status, current/peak inflight. `/health`, `/reset`, `/counters`, and `/events` return before `enter()` and therefore bypass all accounting.

- [ ] **GREEN:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_matrix_target.py -q` passes, then the RED command reports `7 passed`, `0 skipped`, including clean-ladder no_limiter.

- [ ] **Commit:**

~~~bash
git add tests/e2e/rate_limit_matrix_target.py tests/e2e/harness/driver.py tests/e2e/test_rate_limit_admission_e2e.py tests/e2e/test_rate_limit_matrix_target.py
git commit -m "test(e2e): prove seven rate postures live"
~~~

### Task 17 [A10]: Four Live Enforcement Paths and Mutation Proof

**Files:** Modify `docker-compose.e2e.yml:21-43,240-284`, `tests/e2e/harness/driver.py:230-470`, `tests/e2e/rate_limit_matrix_target.py:35-337`, `tests/e2e/test_rate_limit_admission_e2e.py:34-294`, `tests/e2e/test_rate_limit_stack_contract.py` (new from Task 12), and `tests/e2e/failing_governor_addon_entry.py:1-58`; create `scripts/verify_issue_238_mutations.py`.

**Interfaces:** Consumes a green seven-posture matrix and the real API-to-pod-to-Kali path. Produces four target-measured enforcement assertions plus a CLI that reports exactly seven `KILLED` mutations and exits non-zero for any survivor.

- [ ] **Failing live tests:** (1) same project/target multi-pod minimum spacing plus different-project immediate first request; (2) target max_in_flight==2; (3) governor exception gives governor_refused and zero requests; (4) capture-off has zero capture refs while timing/concurrency still hold. Mark issue238_enforcement.

- [ ] **Run RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_admission_e2e.py -m issue238_enforcement -vv -rs -p no:cacheprovider`

Expected: four FAIL (or explicit connection failures), zero skips.

- [ ] **Implement:** add committed `agent-governor-fault` on host port 18081 with `KALI_MCP_URL=http://kali-failing-governor:8000/mcp`, and `agent-capture-off` on 18082 with `KALI_MCP_URL=http://kali-capture-off:8000/mcp`; both inherit the real agent command/image and the five deterministic LLM role bindings. Parameterize the harness as `ControlPlane(api_base: str)` and drive those two agents only through their public API. Add target delay through a committed `RATE_FIXTURE_DELAY_S` setting and group events by the disposable correlation header. No test imports an orchestrator, `fake_run_job`, Kali service, or MCP client.

- [ ] **GREEN:** rerun the RED command; expected `4 passed`, `0 skipped`.

- [ ] **Mutation script:** implement the isolated runner below. Each `before` string must occur exactly once in its named file; a missing/duplicate seam is an error rather than an accidental pass.

~~~python
@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    before: str
    after: str
    nodeid: str

MUTATIONS = (
    Mutation("pod-policy", "src/polymerhus/recon/domain/pod.py",
             'args["traffic_policy"] = traffic_policy',
             'args["traffic_policy_removed"] = traffic_policy',
             "tests/recon/test_pod_capture_context.py::test_pod_forwards_mandatory_policy_v2"),
    Mutation("source-ip-key", "kali/http_history/governor.py",
             'key = (project_id or "", limits.target_key)',
             'key = (project_id or "", limits.target_key, (context.source_ip if context else ""))',
             "tests/kali/test_rate_limit_governor.py::test_same_project_different_source_ips_share_live_bucket"),
    Mutation("max-concurrency", "kali/http_history/governor.py",
             "state.inflight < limits.max_concurrency\n                    and bucket.tokens >= 1.0",
             "True\n                    and bucket.tokens >= 1.0",
             "tests/kali/test_rate_limit_governor.py::test_live_target_never_exceeds_policy_concurrency"),
    Mutation("low-rate-admission", "src/polymerhus/recon/domain/traffic_admission.py",
             "if safe_rate < settings.min_safe_rate_per_s:",
             "if False and safe_rate < settings.min_safe_rate_per_s:",
             "tests/recon/test_rate_limit_pipeline.py::test_low_rate_prunes_intensive_runners_and_traffic"),
    Mutation("variant-wire", "src/polymerhus/recon/control/rate_limit_runner.py",
             "canonical, spec.variant.payload if spec.variant is not None else None",
             "canonical, None",
             "tests/integration/test_rate_limit_mutation_transport.py::test_variant_reaches_target_request"),
    Mutation("governor-exception", "kali/http_history/addon.py",
             'self._refuse(flow, "governor_error", type(exc).__name__)\n            return\n        if decision.governed',
             'return\n        if decision.governed',
             "tests/kali/test_http_history_addon.py::test_governor_exception_has_zero_target_egress"),
    Mutation("capture-coupling", "kali/http_history/addon_entry.py",
             "if not (config.enabled or config.governor_enabled):",
             "if not config.enabled:",
             "tests/kali/test_http_history_addon.py::test_capture_off_keeps_live_governance"),
)
~~~

For each entry, `git ls-files -z` supplies the copy list under `TemporaryDirectory`; replace the one verified occurrence, run `[sys.executable, "-m", "pytest", mutation.nodeid, "-q", "-p", "no:cacheprovider"]` with `cwd=temp_root`, print `KILLED <name>` only for non-zero pytest exit, collect zero exits as survivors, and return 1 if any survivor exists. Never mutate the real worktree.

- [ ] **Commit:**

~~~bash
git add docker-compose.e2e.yml tests/e2e/harness/driver.py tests/e2e/rate_limit_matrix_target.py tests/e2e/test_rate_limit_admission_e2e.py tests/e2e/test_rate_limit_stack_contract.py scripts/verify_issue_238_mutations.py
git commit -m "test(e2e): certify four live enforcement paths"
~~~

### Task 18 [B7]: Two Independent Reset Gates

**Files:** Modify stack script, stack contract test, runbook.

**Interfaces:** Consumes Task 15 lifecycle and Tasks 16-17 gate suites. Produces `gate-once <run-name>` and `gate-twice <artifact-dir>`, with Run A/B manifests and `assert-independent` rejecting reused IDs or generations.

- [ ] **Failing test:** `test_gate_twice_requires_hard_reset_and_independence_checks` requires gate-twice, two assert-clean calls, run-a, run-b and assert-independent.

- [ ] **RED:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_stack_contract.py::test_gate_twice_requires_hard_reset_and_independence_checks -q`

Expected: FAIL because the operation is absent.

- [ ] **Implement exact sequence:**

~~~sh
down; up; health; assert-clean > run-a-clean; gate-once run-a
down; up; health; assert-clean > run-b-clean
assert-independent run-a run-b-clean; gate-once run-b
assert-independent run-a run-b
~~~

gate-once records HEAD, image IDs, project/run IDs, generations, provider counters and pytest exits. Independence requires Run B clean DB/provider zero, images at HEAD, and no Run A project/run/generation value in Run B.

- [ ] **Offline GREEN:** `.venv/bin/python -m pytest tests/e2e/test_rate_limit_stack_contract.py -q`; expected PASS.

- [ ] **Commit:**

~~~bash
git add scripts/issue_238_e2e_stack.sh tests/e2e/test_rate_limit_stack_contract.py docs/design/rate-limit-job-admission-operations.md
git commit -m "ops(issue-238): prove independent reset gates"
~~~

- [ ] **Live GREEN:** sh scripts/issue_238_e2e_stack.sh gate-twice artifacts/issue-238-final

Expected twice: provider PASS, 7 matrix passes, 4 enforcement passes, zero skips, Run B independent.

## Prerequisiti operativi e decisioni umane

1. Task 12 exact authorization is blocking and limited to polyphemus-238-e2e and its two tags.
2. Docker Compose v2 --wait, NET_ADMIN/SYS_ADMIN, namespaces, disk and build time are required. If absent, record the exact failure; no mock waiver.
3. Ports 8080, 18081, 18082 must be free. Otherwise ask which fixed alternatives to commit; no CLI override.
4. If build networking is blocked, ask for normal build-network authorization or an approved committed mirror; never patch running containers.
5. Leave P0 and main-tree operator changes untouched; new divergence pauses execution.
6. Closed decisions: configurable scheme; zero partial-transport tolerance; no excluded row; selective capability pruning; per-task commits.

## Verifica finale e criteri di chiusura

1. Provider/harness contracts:

~~~bash
.venv/bin/python -m pytest tests/e2e/test_deterministic_llm_provider.py tests/e2e/test_rate_limit_harness_contracts.py tests/e2e/test_rate_limit_stack_contract.py -q
~~~

2. Two reset gates:

~~~bash
sh scripts/issue_238_e2e_stack.sh gate-twice artifacts/issue-238-final
~~~

Expect each: provider deterministic, 7 posture passes, 4 enforcement passes, zero skips; Run B independent.

3. Regression:

~~~bash
.venv/bin/python -m pytest tests/recon tests/analysis tests/kali tests/attack -q
~~~

Expect zero failures; record actual totals and explain skips rather than copying historical counts.

4. Compare integration with dev in a clean temporary worktree:

~~~bash
git worktree add --detach /tmp/polyphemus-238-dev-baseline dev
(cd /tmp/polyphemus-238-dev-baseline && /home/alelxsalc03/Desktop/powerpoint/polyphemus/.worktrees/rate-limit-job-admission-e2e/.venv/bin/python -m pytest tests/integration -q)
.venv/bin/python -m pytest tests/integration -q
git worktree remove /tmp/polyphemus-238-dev-baseline
~~~

The parent worktree's already-provisioned interpreter executes both trees; do not create or edit baseline source files. Expect no branch-only failure; record exact node IDs on both sides.

5. Seven critical contracts:

~~~bash
.venv/bin/python -m pytest \
 tests/recon/test_pod_capture_context.py::test_pod_forwards_mandatory_policy_v2 \
 tests/kali/test_rate_limit_governor.py::test_same_project_different_source_ips_share_live_bucket \
 tests/kali/test_rate_limit_governor.py::test_live_target_never_exceeds_policy_concurrency \
 tests/recon/test_rate_limit_pipeline.py::test_low_rate_prunes_intensive_runners_and_traffic \
 tests/integration/test_rate_limit_mutation_transport.py::test_variant_reaches_target_request \
 tests/kali/test_http_history_addon.py::test_governor_exception_has_zero_target_egress \
 tests/kali/test_http_history_addon.py::test_capture_off_keeps_live_governance -q
~~~

Expected: 7 passed.

6. Mutation and hygiene:

~~~bash
.venv/bin/python scripts/verify_issue_238_mutations.py
.venv/bin/python scripts/check_issue_238_commit_series.py
git diff --check
rg -n 'job_name|status_counts.*"0"|redamon-kali-sandbox:latest|_HTTP_TRAFFIC_JOBS|unthrottled until.*#238' src kali docs tests docker-compose*.yml Dockerfile*
git status --short
~~~

Expected: seven KILLED, ordered commits, clean diff, only deliberate legacy-read hits, and only the untracked P0 plan.

Close #238 only after every stage passes, both live gates are independent/skip-free, every conservative path has a reason/warning, and no secret leaks. If authorization, build or live execution is unavailable, the issue remains open.

## Self-review finale del piano

- **Spec coverage:** A1→Task 5, A2→6, A3→3, A4→8, A5→9, A6→10, A7→11, A8→13, A9→14, A10→17; B1→15, B2→12, B3→1, B4→4, B5→7, B6→2, B7→18. Task 16 owns the required seven-scenario matrix rather than hiding it inside A10.
- **Dependency audit:** Tasks 3-4 precede Task 16; Task 16 precedes Task 17; Tasks 5, 7, 11, 13 and 14 make auth, transport, LLM roles, image contents and capability negotiation real before any live certification; Task 18 alone certifies repeatability.
- **Type audit:** `transport_errors` is additive on both sides of the wire; canonical decision output is `job` with legacy input alias only; `artifact_refs` remains `list[str]`; hashes remain in typed evidence; runtime pruning uses the single reason `runtime_capability_incompatible`.
- **Review Focus audit:** the DNS/HTTP test is in Task 7; mixed refusal/transport and reachable `no_limiter` are in Task 4; empty and duplicate-derived target observations are in Task 9; capability-version and wordlist mismatch are in Task 14; Run A identity rejection is in Task 18.
- **Operational audit:** no task treats a mock, scripted orchestrator, `fake_run_job`, direct MCP call, uncommitted override, shared image tag, per-scenario reset alone, or a skipped live test as closure evidence. Container mutation stops at Task 12 until the operator answers the quoted authorization question.
- **Gap result:** no A/B registry item or binding spec requirement is intentionally declined. If implementation proves one impossible without changing the binding spec, stop that task and obtain an operator/spec decision; do not silently delete its test or acceptance criterion.
