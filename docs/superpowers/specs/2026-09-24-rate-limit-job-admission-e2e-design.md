# Rate-Limit Job Admission and QA E2E Design

**Status:** proposed design, approved section-by-section in conversation on
2026-09-24; awaiting written-spec review before implementation planning.

**Scope:** deterministic admission and pruning of request-intensive recon jobs,
real enforcement of rate and concurrency, mutation transport, and a complete
functional E2E trajectory for the rate-limit posture introduced by issue #238.

**Supersedes:** this document does not replace the original #238 mapping design.
It defines the corrective follow-up required by the gaps found after that design
was implemented. Where the documents conflict on job admission, concurrency,
governor failure, mutation transport, or QA depth, this follow-up is authoritative.

## 1. Goal

The rate-limit posture measured after authentication must become a deterministic
input to the configuration of every later recon phase.

`arjun` and `ffuf` are request-intensive. When the canonical target posture does
not safely support their real request cost, they must be absent from the
materialized phase configuration. Slowing them after a runner starts is not an
acceptable substitute for pruning them before materialization.

The resulting behavior must be proven through the production trajectory:

```text
control-plane launch
  -> auth gateway
  -> rate mapping
  -> profile persistence
  -> deterministic phase admission
  -> materialized phase configuration
  -> pod
  -> Kali/MCP
  -> proxy governor
  -> target
  -> persisted output and stats
```

The trajectory is automatic end to end. It contains no human pause and no
mid-run operator decision.

## 2. Design invariants

1. The controller and deterministic code own rate, burst, concurrency, cost,
   duration projection, and job admission.
2. No new actor or LLM node is introduced.
3. The LLM cannot raise a budget, alter a cost class, change a threshold,
   enlarge a policy, or reintroduce an excluded job.
4. A bypass is a finding only. `confirmed`, `no_bypass`, and `inconclusive`
   have no effect on job admission or the enforced policy.
5. An HTTP-targeting job cannot run without an enforceable traffic policy.
6. With a policy armed, governor failure is fail-closed at the request hook as
   well as at the pre-run exec boundary.
7. Capture and governance remain independent. Disabling capture never disables
   rate or concurrency enforcement.
8. Raw results and credential material never enter profiles, stats, logs,
   prompts, or versioned documents.
9. #238 artifacts remain capped, secret-safe, and referenced through relative
   coordinates plus cryptographic hashes.
10. Every inclusion and exclusion is structured, persisted, and attributable
    to a closed reason code.

## 3. Confirmed current-state findings

Read-only inspection at branch `dev`, HEAD `39d859f3`, confirms the following
gaps. They are implementation-plan inputs, not changes made by this design
session.

### 3.1 Governor exceptions are fail-open inside the proxy

`kali/http_history/addon.py::HttpHistoryAddon.request` catches every exception
from registration lookup, policy validation, and `TargetGovernor.acquire`,
increments `governor_failed`, and returns. Returning lets the request continue
to the target. The pre-run readiness check cannot protect against a governor
fault that occurs after the command has been admitted.

### 3.2 Mutation transport is incomplete

`ExperimentSpec.variant` is populated by
`RateLimitHarness._variant_spec`, but
`recon/control/rate_limit_runner.py::kali_spec_payload` omits it.
`kali/rate_limit/models.py::KaliExperimentSpec` has no mutation or effective
request contract. Production variant probes therefore replay the canonical
request. The current E2E demonstrates a mutation by constructing a different
URL directly, outside the production variant transport.

### 3.3 `max_concurrency` is validated but not enforced

`kali/http_history/governor.py` parses `max_concurrency`, but
`TargetGovernor.acquire` only operates a token bucket. No request-lifetime
permit is acquired or released, so concurrent inflight requests are unbounded
by the policy field.

### 3.4 The current E2E skips critical production seams

`tests/e2e/test_rate_limit_mapping_e2e.py` measures the target and governor
live, but its pipeline ordering test supplies `_ScriptedOrchestrator` and
`fake_run_job`. It does not exercise the real actor, model protocol, job agent,
pod runner, or materialized job commands as one trajectory.

### 3.5 The Kali image and Vegeta smoke are not reproducible enough

The implementation ledger records that the local Kali image was stale and did
not contain Vegeta. It also records that a Vegeta binary produced by
`go install` reports empty human version fields, while `Dockerfile.kali`
currently checks `vegeta -version | grep 12.13.0`. The source pin exists, but
the smoke assertion cannot reliably prove the built binary version.

### 3.6 Documentation has obsolete claims

Current documentation correctly describes much of #238, but stale statements
remain. For example, the `ffuf` `JobSpec` comment still says request phases run
unthrottled until #238 lands, and the residual AMV-17 description still refers
to retired `_RATE_FLAGS` and steering behavior. These claims must converge with
the implemented admission and governor model.

### 3.7 Capture-off/governor-on lacks a complete live trajectory proof

Unit and seam tests pin policy transport with capture disabled and independently
exercise addon switches. The current functional E2E does not prove the full
capture-off path from materialized job through live target timing and persisted
stats.

## 4. Decisions and rejected alternatives

### 4.1 Bypasses never affect admission

**Decision:** a bypass remains informational, even when all four evidence gates
confirm it. The automatic run continues to use the canonical request posture.

**Rejected:** automatic re-enablement after confirmation. A finding is not
proof that mutation transport, aggregate rate enforcement, and concurrency
enforcement remain correct for downstream tool traffic.

**Rejected:** a human pause during the run. It would violate the required
automatic E2E process.

### 4.2 Cost belongs to the canonical job specification

**Decision:** every `JobSpec` has an explicit typed target-traffic cost
declaration. Admission never depends on a scattered set of job names.

**Rejected:** a fixed threshold plus a hard-coded `{"arjun", "ffuf"}` list.
It would drift when request-intensive jobs are added or renamed.

**Rejected:** a fixed threshold compiled into controller code. It would require
a release to calibrate policy and would not expose the effective run setting.

### 4.3 Admission uses safe rate and projected duration

**Decision:** admission combines the enforced safe rate with a deterministic
estimate of the job's request volume. It does not rely on residual-quota
headers, which many targets omit or misreport.

**Rejected:** rate-only admission. The same rate can be safe for a bounded
probe but operationally unsuitable for thousands of fuzzing requests.

**Rejected:** quota-only admission. Quota is not universally observable and is
not a stable prerequisite for deterministic pipeline configuration.

### 4.4 Admission occurs at the phase materialization chokepoint

**Decision:** admission occurs after the consumption set is derived and before
`job_configs`, job agents, pods, or runners are created.

**Rejected:** pruning the global plan immediately after mapping. Later-phase
input cardinality is not yet known, so projected duration would be fabricated.

**Rejected:** a skip inside the job agent or pod. At that point the excluded
job has already been materialized.

### 4.5 Uncertainty is fail-closed selectively

**Decision:** failed, inconclusive, or stale profiles remove request-intensive
jobs while allowing lower-cost work to continue under a conservative policy.

**Rejected:** running intensive jobs at the fallback rate. Uncertainty must not
authorize request-intensive traffic.

**Rejected:** aborting the entire run. Passive and bounded work remains useful
and can proceed safely.

### 4.6 Production E2E uses a deterministic local model provider

**Decision:** the E2E traverses the real actor and model protocol through a
local deterministic provider fixture.

**Rejected:** an external live LLM as a functional gate. It introduces secrets,
cost, latency, and nondeterministic replies.

**Rejected:** a scripted orchestrator. It skips the actor and tool-binding
seams under test.

## 5. Job traffic-cost model

### 5.1 Types

The recon domain gains a closed traffic-cost vocabulary:

```text
TrafficCostClass = non_target | bounded_http | request_intensive

JobTrafficCost:
  class
  estimated_requests_per_input
  estimation_basis
```

The field is mandatory on `JobSpec`; there is no permissive default. A new job
cannot enter the registry until its traffic relationship is explicit.

- `non_target` does not send HTTP requests to the measured target.
- `bounded_http` sends target HTTP traffic but is allowed under a conservative
  policy because its work is tightly bounded.
- `request_intensive` must pass posture, minimum-rate, and projected-duration
  gates.

The same field replaces `pipeline._HTTP_TRAFFIC_JOBS` as the source of truth for
whether `traffic_policy` is mandatory. A `bounded_http` or
`request_intensive` job without a policy is refused, never run through the
legacy ungoverned path.

### 5.2 Cost estimates

`arjun` declares a conservative estimate of 260 requests per input. This is
the measured value already recorded in its `JobSpec` commentary and tests.

`ffuf` declares the cardinality of its pinned
`/usr/share/seclists/Discovery/Web-Content/common.txt` wordlist. The value is
verified in the Kali image contract tests against the real file. Changing the
wordlist requires changing and re-verifying the cost declaration in the same
slice.

An unavailable or inconsistent estimate is `cost_model_invalid`. For a
request-intensive job this is an exclusion, not an invitation to guess.

## 6. Admission configuration

The startup configuration adds:

```text
RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S=2.0
RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S=300
```

Both values must be finite and strictly positive. Missing values use the
defaults. Zero, negative, nonnumeric, `NaN`, or infinite values fail startup
loudly. Values are parsed once into a typed admission-policy value object.

The defaults are grounded in existing runtime facts:

- at approximately 260 requests per input, `arjun` at 1 request/second nearly
  consumes the entire existing `EXEC_TIMEOUT_S=300` without headroom;
- 2 requests/second is the lower bound already justified by the `arjun`
  template contract;
- 300 seconds is the current execution-time boundary rather than a new
  unrelated duration.

Every run persists the effective values it used.

## 7. Deterministic admission algorithm

For each candidate job at the current phase boundary:

1. Derive its consumption set through the existing canonical batching and
   filtering path.
2. Read its mandatory `JobTrafficCost`.
3. Resolve the current effective profile using an injected UTC clock.
4. If `expires_at <= now`, mark the profile stale and derive the conservative
   effective policy without remapping.
5. For `non_target`, admit without attaching a target traffic policy.
6. For `bounded_http`, require a valid effective policy and admit under it.
7. For `request_intensive`, reject immediately when the outcome is `failed` or
   `inconclusive`, or when the profile is stale.
8. For a usable `mapped` or `no_limiter` profile, set
   `safe_rate_per_s = effective_policy.rate_per_s`.
9. Compute:

   ```text
   estimated_requests = input_count * estimated_requests_per_input
   projected_duration_s = estimated_requests / safe_rate_per_s
   ```

10. Admit only when `safe_rate_per_s >= 2.0` and
    `projected_duration_s <= 300`, using the effective configured values rather
    than literal constants.
11. Persist the decision before dispatch.
12. Build `job_configs` only for admitted jobs.

`no_limiter` means no transition within the tested bounds. Its policy uses the
highest rate actually tested and never an unbounded sentinel.

Bypass state is deliberately absent from the algorithm.

## 8. Outcome and failure matrix

| Profile state | Effective policy | Request-intensive admission |
|---|---|---|
| `mapped`, fresh | measured conservative policy | rate and duration gates |
| `no_limiter`, fresh | highest actually tested rate | rate and duration gates |
| `inconclusive` | conservative fallback | excluded |
| `failed` | conservative fallback | excluded |
| stale | conservative fallback | excluded |

`no_bypass`, false bypass, inconclusive bypass, and confirmed bypass are all
no-ops for this matrix.

If a profile expires between phases, later phases use the stale row. There is
no mid-run remapping and no continuation under the expired higher-rate policy.

## 9. LLM authority boundary

The model-facing verdict contains interpretation, signal names, mutation
hypotheses, and evidence identifiers only. It contains no admission decision,
job name, cost class, request estimate, threshold, rate, duration, burst,
concurrency, or policy.

Candidate phases come from the static job registry, the operator's requested
subset, and existing deterministic scope/auth gates. The final materialized
phase is the intersection of that candidate phase with the controller's
admitted decisions. There is no union operation with model output.

This structural boundary, rather than a prompt instruction, prevents the LLM
from raising limits or reintroducing jobs.

## 10. Mutation transport and bypass evidence

The current generic `MutationSpec.parameters: dict[str, str]` is replaced by a
discriminated union whose payload is closed per mutation family. It remains
impossible for a model-facing mutation to carry request counts, rate, duration,
concurrency, or budget.

A pure controller function applies an admitted mutation:

```text
apply_mutation(canonical_request, typed_mutation) -> EffectiveRequest
```

`EffectiveRequest` contains the concrete read-only method, URL, allowed headers,
and optional bounded body required by the selected family. The controller
validates semantic and safety constraints before execution. Identity-header
families remain disabled unless the existing explicit operator opt-in is true.

Kali receives the already-materialized `EffectiveRequest` over private stdin.
Kali does not interpret mutation semantics. The manifest records only the
mutation ID, family, a canonical hash, and redacted request shape. Raw parameter
values and credentials are not persisted or returned to the model.

The E2E must observe the mutated route/header/body at the target. A comparison
that only changes the evidence object without changing the request on the wire
is a failure.

Even after all four evidence gates pass, the finding does not modify the
effective policy or any admission decision.

## 11. Rate and concurrency enforcement

`TargetGovernor` continues to use the key `(project_id, target_key)`. Source IP
is lookup transport only and must never enter the bucket or concurrency key.

Each key owns:

- the token-bucket state for rate and burst;
- a concurrency limiter for live requests;
- policy-version and replacement state;
- counters for admitted, waiting, refused, failed, and peak inflight flows.

The request hook acquires a rate token and a concurrency permit before egress.
The permit is associated with the flow and is released exactly once from the
response or error hook. Cancellation, error, and double-callback paths must not
leak or over-release permits.

An empty token bucket or exhausted concurrency permit waits. Invalid policy,
unsupported policy version, registry inconsistency, or an exception inside the
governor refuses the flow locally. The target receives no request. Refusal is
structured and visible through addon status and pod/run stats.

The exec seam retains its existing early refusal: an armed command does not
start without a namespace lease, a registered policy, an enabled governor, and
a ready proxy. Runtime fail-closed handling complements this check; it does not
replace it.

## 12. Persistence and observability

### 12.1 Rate profile v2

New runs write `rate-profile/v2` under
`recon_runs.stats["rate_limit"]`. Evidence references are typed:

```text
EvidenceReference:
  ref             relative rate-artifact/v1 coordinate
  sha256          manifest/content integrity hash
  experiment_id
  count
```

Existing v1 rows remain readable. No SQL migration is required because the
store is the existing JSONB column.

### 12.2 Traffic-admission envelope

The controller owns a separate
`recon_runs.stats["traffic_admission"]` envelope, version
`traffic-admission/v1`. It contains:

- effective admission configuration;
- profile version, outcome, `measured_at`, and `expires_at`;
- effective traffic policy;
- candidate and materialized phases;
- one decision per candidate job;
- structured warnings and refusals;
- an ordered trajectory event list.

Each decision contains only secret-safe values:

```text
phase
job
cost_class
input_count
estimated_requests
safe_rate_per_s
projected_duration_s
decision: included | excluded
reason_code
```

The closed reason-code vocabulary contains at least:

```text
admitted
profile_inconclusive
profile_failed
profile_stale
below_min_safe_rate
projected_duration_exceeded
cost_model_invalid
policy_missing
governor_refused
```

The envelope is persisted before each phase dispatch. A failed run therefore
retains the last materialized configuration and the terminal event it reached.

### 12.3 Secret safety

Profiles, admission envelopes, target counters, logs, prompts, and committed
fixtures must not contain raw request or response bodies, credentials,
authorization headers, cookies, tokens, or operator secrets. Tests use
disposable sentinel values and scan every #238 artifact and persisted payload
for those sentinels.

## 13. Wire versions and stale-image refusal

The policy becomes `traffic-policy/v2`. The shape remains recognizable, but the
version change is required because `max_concurrency` changes from inert data to
enforced semantics.

Kali health/readiness reports:

- supported traffic-policy versions;
- Vegeta module and binary version;
- image/build provenance.

The application refuses an incompatible governor version instead of assuming
the field is enforced.

The Vegeta image smoke reads Go build metadata using:

```text
go version -m "$(command -v vegeta)"
```

and verifies the pinned `github.com/tsenart/vegeta/v12` module version. The
human-readable `vegeta -version` output is not the source of truth.

## 14. Deterministic fixture topology

One fixture server implementation is instantiated as separate Compose services.
Each instance has an isolated hostname, limiter state, and counters, and selects
one posture through environment configuration:

- no limiter;
- high compatible limit;
- low limit without bypass;
- low limit with a false/unconfirmed bypass shape;
- bursty/ambiguous behavior producing `inconclusive`.

Every instance exposes deterministic control endpoints:

```text
GET /health
POST /reset
GET /counters
GET /events
```

Control endpoints bypass limiter accounting. Target events record monotonic
timestamps, route, status, current inflight count, and peak inflight count.
Disposable test correlation values may be recorded, but never credentials.

Governor and rate-stage failures are injected at their owning runtime seams,
not faked by a target response.

## 15. Functional E2E architecture

The functional suite launches through the ordinary control-plane API and uses:

- the real Postgres registry and run rows;
- the real `ReconOrchestratorActor` and session machinery;
- a local deterministic provider implementing the same model protocol;
- the real auth and rate turns;
- the real pipeline, job agent, pod graph, MCP client, and Kali service;
- the real proxy addon/governor;
- the real Vegeta, `arjun`, and `ffuf` binaries;
- the deterministic target instances.

The local provider makes tool calls and structured replies deterministically.
It is a controlled replacement for model inference only; it does not replace
the actor, prompts, tools, pipeline, or execution path.

## 16. Minimum E2E matrix

| Scenario | Required assertions |
|---|---|
| No limiter | `no_limiter` within tested bounds; admission evaluated from tested rate and real cost; intensive runners start only when both gates pass |
| High compatible limiter | `mapped`; `arjun` and `ffuf` present in materialized phases; real runners and target traffic observed |
| Low limiter, no bypass | both jobs absent; zero runner invocation and zero matching target traffic |
| Low limiter, false bypass | `no_bypass`; both jobs remain absent |
| Bursty/ambiguous limiter | `inconclusive`; conservative policy; both jobs absent |
| Rate-stage failure | `failed`; conservative policy; both jobs absent; warning persisted |
| Governor failure | local refusal; target request count remains zero |
| Same project/target, multiple pods | aggregate timestamp spacing and peak inflight respect one shared bucket/permit set |
| Different projects, same target | independent bucket state; the second project is not delayed by the first project's depleted bucket |
| Capture off, governor on | no capture records; rate and concurrency timing still hold |

Each scenario asserts:

1. event order from run creation through terminal stats;
2. detected posture and effective policy;
3. evidence references and hashes;
4. final materialized phase list;
5. invoked and non-invoked runners;
6. target counters, timestamps, and peak inflight;
7. persisted profile, admission decisions, and pod traffic stats;
8. absence of secret sentinels;
9. warnings or refusals on every conservative path.

## 17. Adversarial regression requirements

The suite must fail if any of these regressions is introduced:

- `traffic_policy` is no longer passed from materialized job to pod/Kali;
- a bucket or concurrency key includes `source_ip`;
- `max_concurrency` is parsed but not enforced;
- `arjun` or `ffuf` starts below the admission threshold;
- `ExperimentSpec.variant` does not alter the effective wire request;
- a governor exception lets a request reach the target;
- disabling capture also disables governance.

These are behavioral assertions against target observations and persisted state,
not source-text assertions alone.

## 18. Test-tier boundaries

### Unit

- typed cost/config validation;
- pure admission decisions and reason codes;
- stale-profile behavior with injected clock;
- request-volume and duration calculation;
- mutation validation and pure application;
- governor token/concurrency lifecycle with injected clock and sleeper;
- runtime fail-closed exception behavior.

### Contract

- every `JobSpec` declares a cost;
- `arjun` and `ffuf` are request-intensive;
- ffuf estimate matches the image wordlist cardinality;
- rate-profile v1 read compatibility and v2 writes;
- policy v2 negotiation and refusal of unsupported versions;
- mutation survives controller-to-Kali serialization;
- Vegeta Go module version is the pinned version.

### Integration

- phase admission and incremental JSONB persistence;
- profile expiry between phases;
- pod-to-MCP policy and effective-request transport;
- addon permit acquisition/release and refusal reporting;
- capture and governor switch independence.

### Functional E2E

The full matrix in Section 16, driven through the normal launch API, with no
scripted orchestrator or fake job runner.

## 19. Compatibility and rollout

1. Introduce readers for rate-profile v1/v2 before switching writers to v2.
2. Add Kali health/version reporting before requiring traffic-policy v2.
3. Deploy a rebuilt Kali image and verify its provenance.
4. Switch the application to require policy v2 for target HTTP jobs.
5. Enable phase admission and admission-envelope persistence.
6. Retain a rollback path that disables the new deployment as a whole; do not
   roll back to ungoverned HTTP traffic. On incompatible components, refuse
   request jobs while allowing non-target work.

Historical v1 profiles remain audit data. They are not reused as fresh profiles
for new runs.

## 20. Documentation convergence

The implementation must update, at minimum:

- `src/polymerhus/recon/CONTEXT.md`: job traffic cost, materialized admission,
  fail-closed target traffic, and bypass non-authority;
- `docs/design/technical-architecture.md`: controller flow, policy v2,
  concurrency permits, admission envelope, and image readiness;
- `docs/design/after-mvp-work-items.md`: remove obsolete steering and
  `_RATE_FLAGS` descriptions and distinguish the residual retry concern;
- `src/polymerhus/recon/control/jobs.py`: remove obsolete “unthrottled until
  #238” comments and document cost estimates at their canonical declarations;
- deployment/operator documentation: effective environment values, health
  contract, refusal semantics, and E2E fixture operation.

Documentation must describe the materialized configuration, not merely the
candidate `PHASES` registry.

## 21. Acceptance criteria

The design is implemented only when all of the following are true:

1. Every job has one explicit traffic-cost class.
2. Effective admission configuration is validated at startup and persisted.
3. `arjun` and `ffuf` are absent from materialized phases under low, failed,
   inconclusive, or stale posture.
4. Excluded jobs create no pod, runner invocation, or target traffic.
5. The LLM cannot alter or bypass admission through any model-facing type.
6. A production variant probe visibly changes the wire request while remaining
   finding-only.
7. Aggregate rate and concurrency are both enforced by project and target.
8. A governor exception is fail-closed and visible.
9. Capture-off leaves governance armed.
10. Profiles and admission stats include relative evidence references and
    verified hashes without secrets.
11. The Kali image proves its Vegeta module version and supported policy
    version through reproducible metadata.
12. The complete deterministic E2E matrix passes through the normal launch
    path with real job execution.
13. Existing focused, Kali, recon, and relevant integration suites remain
    green, with every skip gate inspected for non-vacuity.

## 22. Baseline evidence and its limit

The existing ledger records:

- focused suite: 112 passed;
- Kali suite: 194 passed;
- recon suite: 1069 passed, 21 skipped;
- current rate-limit E2E: 8 passed, twice, in approximately 64 seconds;
- shared-bucket pacing for the same project and immediate progress for a
  different project;
- invalid policy refusal with return code 78 and zero target calls;
- pre-execution budget refusal;
- valid #238 artifact hash and sensitive-header redaction.

These results are regression baselines. They do not prove the complete
trajectory because the current E2E substitutes the orchestrator and job runner,
does not materialize/prune request-intensive jobs, does not enforce
`max_concurrency`, and does not fail-close an in-proxy governor exception.
