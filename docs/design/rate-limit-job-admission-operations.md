# Rate-Aware Job Admission — Operations

Status: built (#238 follow-up). Authority: `docs/superpowers/specs/2026-09-24-rate-limit-job-admission-e2e-design.md`.

This is the operator-facing view of the rate-limit job-admission feature: what
happens automatically, which knobs exist, what the persisted state means, and
what to do when a run refuses traffic. The design document is the argument; this
page is the runbook.

## 1. The automatic flow (no human pause)

Every recon run takes the same trajectory with **no operator input at any
point**:

```
run start
  -> auth gateway turn        (ReconOrchestratorActor, session thread)
  -> rate-limit mapping turn  (same actor, same thread, second turn)
  -> rate profile persisted   (stats["rate_limit"], rate-profile/v2)
  -> phase boundary           (deterministic admission per candidate job)
  -> admission envelope persisted (stats["traffic_admission"], traffic-admission/v1)
  -> materialized pods        (only the admitted jobs)
  -> target traffic           (through Kali's proxy + governor)
  -> run status complete
```

Two model turns feed it, and neither can change its arithmetic. The
model-facing verdicts are **closed** contracts (`extra="forbid"`): a
`GatewayVerdict` or a `RateLoopVerdict` that arrives carrying a rate, a
concurrency, a budget, an admission decision or a phase list is *refused at
validation*, not silently ignored. The profile's `safe_rate_per_s` is validated
to equal its `traffic_policy.rate_per_s`, so the number admission reads is
always the number the governor enforces.

**A bypass finding never authorizes more traffic.** A confirmed variant is
evidence: it is persisted, it is named in the verdict, and it changes neither
the effective policy nor the materialized phase list nor the pace of any later
request. There is no "confirmed bypass" path that re-enables `arjun` or `ffuf`.

## 2. The knobs

| Variable | Default | Meaning |
|---|---|---|
| `RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S` | `2.0` | The minimum measured safe rate at which a `request_intensive` job may run. Must be finite and `> 0` or the process refuses to start. |
| `RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S` | `300.0` | The maximum projected duration (`estimated_requests / safe_rate_per_s`) an intensive job may take. Must be finite and `> 0`. |
| `RATE_LIMIT_MAX_REQUESTS` / `RATE_LIMIT_MAX_DURATION_S` / `RATE_LIMIT_MAX_RATE` / `RATE_LIMIT_MAX_CONCURRENCY` / `RATE_LIMIT_MAX_BYPASS_VARIANTS` | see `RateLimitSafetyBudget` | The mapping's hard budget: the controller never offers more than this while measuring. |
| `RATE_LIMIT_ALLOW_IDENTITY_MUTATIONS` | `false` | Arms the `identity-header` mutation family. OFF by default: those mutations change *who the target thinks is asking*. |
| `RATE_LIMIT_PROFILE_TTL_S` | `PROFILE_TTL_DEFAULT_S` | How long a measured profile stays fresh. Admission re-checks freshness at the phase boundary; an expired profile prunes the intensive jobs. |
| `RATE_LIMIT_AWAIT_TIMEOUT_S` | `1800.0` | The bound on the *wait* for the rate turn's reply (not on the turn's own harness budget). |

### Boundary semantics (inclusive)

A job is admitted exactly when
`profile.outcome == "mapped"` **and** the profile is fresh **and**
`safe_rate_per_s >= RATE_LIMIT_INTENSIVE_MIN_SAFE_RATE_PER_S` **and**
`projected_duration_s <= RATE_LIMIT_INTENSIVE_MAX_PROJECTED_DURATION_S`.
Both comparisons are inclusive: a job at exactly `2.0 req/s` with a projected
duration of exactly `300 s` is admitted. `arjun` and `ffuf` are the
`request_intensive` jobs today; every other job is either `bounded_http`
(admitted under a conservative policy) or `non_target` (never paced).

## 3. Where to read the outcome

`GET /projects/{project_id}/recon/{run_id}` returns `stats`, which carries two
additive keys:

* **`rate_limit`** (`rate-profile/v2`) — what was *measured*: `outcome`
(`mapped` / `no_limiter` / `inconclusive` / `failed`), `safe_rate_per_s`,
`threshold_low_per_s` / `threshold_high_per_s`, `burst_capacity`,
`recovery_s`, `confidence`, `signals`, `bypass_outcome`, the immutable
`artifact_refs` (relative `rate-artifact/v1:` coordinates + lowercase sha256),
`measured_at` / `expires_at`, the operator budget and its consumption, and the
`traffic_policy` (v2) every later request obeys.
* **`traffic_admission`** (`traffic-admission/v1`) — what was *decided and
executed*: `profile_version`, `profile_outcome`, `effective_policy`,
`candidate_phases`, `materialized_phases`, one `decisions` row per candidate
(`job_name`, `cost_class`, `input_count`, `estimated_requests`,
`safe_rate_per_s`, `projected_duration_s`, `decision`, `reason_code`),
`event_order`, `warnings`, and `refusals`.

`event_order` is the run's trajectory, in order:

```
auth, rate_mapping, rate_profile_persisted, admission_persisted,
pod_started, target_observed, run_finalized
```

`admission_persisted` repeats at every phase boundary; `pod_started` appears
once, before the first materialized runner; `target_observed` appears once,
after the first **target-facing** pod returned; `run_finalized` is the terminal
act. A run whose every candidate was pruned records neither `pod_started` nor
`target_observed` — the trajectory never claims an execution that did not
happen.

`refusals` carries the runtime governor refusals (`reason_code`, `target_key`,
`policy_version`); the pre-run decision is **never rewritten** by a refusal, so
"what was decided" and "what the proxy refused" stay separately legible.

### Structured reason codes

A pruned job always carries exactly one code from the closed vocabulary
(`AdmissionReason`), never prose:

| Code | What it means |
|---|---|
| `admitted` | The job is in the materialized phase. |
| `no_inputs` | The upstream phase produced nothing for this job to consume. |
| `profile_inconclusive` | The mapping could not bracket a limiter (`inconclusive`). |
| `profile_failed` | The rate turn failed, timed out or degraded. |
| `profile_stale` | The profile expired before this phase's admission. |
| `below_min_safe_rate` | `safe_rate_per_s` is under the operator threshold. |
| `projected_duration_exceeded` | The projected duration exceeds the ceiling. |
| `cost_model_invalid` | The job's traffic-cost declaration is unusable. |
| `policy_missing` | No enforceable policy could be derived. |
| `governor_refused` | The runtime governor refused the flow. |

## 4. Refusals are local, loud and terminal

With a policy **armed**, an enforcement that cannot run must not become traffic:

* an unenforceable policy, a missing governor, or a governor exception makes the
  proxy refuse the flow **locally** (HTTP 503 with
  `X-Polymerhus-Traffic-Refusal`) — zero upstream requests;
* Kali refuses *before* it runs anything when the namespace, the governor
  switch or the proxy readiness probe fails: `returncode=78` plus a
  `traffic_warning`, no runner invocation, nothing egresses;
* the pipeline records the refusal in the admission envelope and never rewrites
  the decision that preceded it.

`KALI_HTTP_CAPTURE_ENABLED=false` disables **storage only**. Governance is a
separate switch (`KALI_HTTP_GOVERNOR_ENABLED`), the two ride the same mitmdump
process, and capture-off never disarms an armed policy. The governor's bucket
key is `(project_id, target_key)` and never includes the source address: how a
namespace reaches the target cannot buy it a second allowance.

Secrets never appear in any of this: raw hit streams live in the immutable
artifact store addressed by a relative ref + sha256, and profiles, stats, logs
and prompts carry neither credentials nor response bodies.

## 5. Versions, migration and rollback

* **Wire versions advance together.** `rate-profile/v2` and
  `traffic-policy/v2` are the only versions emitted. v2 exists because
  `max_concurrency` changed from inert data to an enforced semantic — a
  validator that ignores it would look compliant while bursts exceeded the
  simultaneous-load limit.
* **Reading old rows is isolated.** A persisted `rate-profile/v1` row is
  ingested only through `upgrade_rate_profile_v1`; nothing else reads v1 and
  nothing writes it.
* **Kali rejects what it cannot enforce.** An unsupported or unvalidated policy
  version is refused with `returncode=78` and **zero target calls** — never
  enforced approximately. `proxy_status()["traffic_governor"]` advertises the
  versions the image supports, so the controller and Kali negotiate rather than
  assume.
* **Rolling back is a two-sided operation.** Controller and Kali must move
  together: a v1 controller talking to a v2 Kali is refused (loudly, before any
  traffic) rather than silently ungoverned.
* **No destructive database migration.** `traffic_admission` is an additive
  JSONB key inside the existing `recon_runs.stats`, so a rollback leaves the
  historical rows readable.

## 6. Health and capability negotiation

`proxy_status()` (MCP `proxy_status`, and the `view`/exec surfaces) reports the
governor and capture switches **separately**, the supported policy versions, the
refusal counters, the image's build provenance (source revision + the Vegeta
module version parsed from Go build metadata) and the pinned wordlist
cardinality. `arjun`'s estimate is a fixed constant; `ffuf`'s is the non-empty
line count of the pinned SecLists wordlist, and a mismatch between the image's
wordlist and the declared cardinality **refuses** rather than estimating.

## 7. The deterministic E2E targets

The functional tier never aims at the internet. Five isolated Compose services
instantiate one fixture application with a different posture each:

| Service | Posture |
|---|---|
| `rate-matrix-no-limiter` | no limiter |
| `rate-matrix-high-limit` | compatible limiter |
| `rate-matrix-low-limit` | low limiter, no bypass |
| `rate-matrix-false-bypass` | low limiter with an unconfirmed bypass shape |
| `rate-matrix-burst-inconclusive` | ambiguous/bursty behaviour |

Each exposes `GET /health`, `POST /reset`, `GET /counters` and `GET /events`.
`/counters` and `/events` **require the current generation** (`?generation=<id>`,
minted by `/reset`); a stale or missing generation is a `409`, so a reader can
never mistake another scenario's counters for its own. The control endpoints
bypass limiter accounting *and* in-flight accounting, so reading them can never
look like target traffic. Sensitive header values and configured secrets are
redacted before they are recorded.

The E2E also routes both long-horizon model roles at a deterministic local
provider (`tests/e2e/deterministic_llm_provider.py`), so the tier exercises the
real actor loop and the real pipeline with reproducible model output. Only
inference is replaced; the actor, tools, pipeline, pods, MCP/Kali proxy and the
target are production code.

## 8. What to do when a run refuses everything

1. Read `stats.traffic_admission.decisions` — every pruning has a code.
2. `profile_inconclusive` / `profile_failed` / `profile_stale`: check the
   target's health and the mapping budget; the conservative fallback is
   deliberate, not a bug.
3. `below_min_safe_rate` / `projected_duration_exceeded`: the measured safe rate
   is genuinely below what the intensive jobs need. Raising the threshold
   variables does not create capacity — it only changes where the line sits.
4. `policy_missing`: the profile carried no enforceable policy; look for the
   rate turn's own log line.
5. `refusals` non-empty: the governor refused at runtime. Check
   `proxy_status()["traffic_governor"]` inside Kali (namespace pool, switch
   state, refusal counters, supported versions).
6. Never "fix" a refusal by disabling the governor. The run's bounded work
   continues by design; the intensive work waits for a measured posture.
