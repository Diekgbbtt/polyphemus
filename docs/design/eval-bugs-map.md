# Eval-system bugs map

*Status: working map (2026-10-05). The failure register for the eval harness and its evidence chain, cleaned of closed-ticket noise, deduplicated by root cause, and stripped of the infra/dependency and scaffolded-data-layer families. Each live entry carries a diagnosis and a confidence. Low-confidence entries are marked POTENTIAL and route through the `diagnosing-bugs` flow.*

Provenance: operator session 2026-10-05; live trial records under `/opt/eval-platform-model/eval/runs/`, the instance data root `/opt/polymerhus-dev/eval/instances/eval-server-1/data/`, the agent log (`docker logs ph-dd131acc-agent-1`), the polymerhus API (`/app-state`, `/projects/{id}/{graph,usage}`), and the comfyui ground-truth kill chains under `/root/WebExploitBench/comfyui/vulnerability/comfyui-00N/report/report.md`.

This document authorises no code change by itself.

## 0. Headline finding - one upstream cause dominates the recent failures

The provider `opencode-go/deepseek-v4.1-flash` returned a persistent `429 GoUsageLimitError: Go usage limit exceeded` (`limitName: 5 hour`, workspace `wrk_01KZ107SCMX5YBFD83R0M8SSAK`). There is **no fallback model group** (`Available Model Group Fallbacks=None`). The agent log carries **1062** `429` lines and **684** `Error code: 429` degrade events.

Consequences, all traced to this one cause:

- The `comfyui-1` round-3 hunting run `c4ed6cea` degraded and `runtime.start_hunting` persisted `failed` (08:11:05 -> 09:45:25).
- **23 of 27** round-3 pod exports carry `terminal_reason: technical-infeasibility` with `error="Error code: 429 ..."` (a pod raise degrades there by design: `pod/pod.py:114-118`).
- `trial-2` (`75991388`) consumed 11 `ratified` configs but authored 0 specs - the hunter turns degraded.

The eval pipeline is otherwise functional: when quota was available (`d76f1bcc`, `5603e6eb`, `9132be4d`) it produced 16/8/7 symptom-confirmed pods. The recent regression is quota-driven, amplified by eval-system resilience gaps (see EV-21).

## 1. Current eval snapshot (2026-10-05 11:20 UTC)

Round 3 of the 5-target setup (`eval/setups/webexploitbench-5.yaml`, eval SHA `198d3b9`).

- `comfyui-1` trial `20261005T094534` (project `9cc91832`) - `terminal=failed`. recon `complete`, hunting `failed` (429, see section 0).
- `jetlinks-1` trial in progress (project `2aaae9d4`) - analysis `drained` (11:21:27, passes 8, l0_assets_read 21749, dispatches_entered 363), hunting `running` since 09:54:11.
- The driver recorded the comfyui-1 failure and advanced to jetlinks-1. Working as designed.

## 2. Comfyui per-trial execution status

`spent_tokens` is null on every non-budget-stopped trial (the ledger is only read on overflow); live `/usage` is authoritative.

| trial | project | terminal | generated tokens (reasoning+visible) | L0 nodes | L1 nodes | AGGREGATES | configs prod/cons | test-specs | pods |
|---|---|---|---|---|---|---|---|---|---|
| 013033 | c0641257 | stopped | 0 (ledger reset) | ~52 | 30 | 0 | 0/10 | 2 | 3 (`specified`) |
| 021905 | 75991388 | stopped | 0 (ledger reset) | ~344 | 30 | 0 | 0/11 | 0 | 0 |
| 155727 | b52151db | stopped | 0 (ledger reset) | ~338 | 30 | 0 | 2/87 | 14 | 0 |
| 080051 | d3ac4eaf | failed | 0 (ledger reset) | 0 | 30 | 0 | 0/0 | 0 | 0 |
| 094534 | 9cc91832 | failed | 1,410,864 | ~29 | 32 | 0 | 2/22 | 11 | 28 |

The comfyui AGGREGATES count is 0 because those runs predate the streamed-analysis fix. The just-drained `jetlinks-1` analysis produced **24 AGGREGATES** links on the current dev, so **#321 (analysis never links L0->L1) is fixed on dev** and the open ticket is stale.

### Verdicts and diagnoses

The three stopped trials carry `verdicts.yaml`/`diagnoses.yaml` (6 each), all `missed`. The diagnoses share one root cause: the risk-descending schedule spent the whole cap on Tier-0 broken-access-control configs, so Tier-1 validation faults (CWE-79/22/918) were never scheduled; plus an exposure-family KB `predicate: null` coverage gap (comfyui-001). The cap has since been removed.

## 3. PodExport distribution by terminal_reason

`verdict` is binary; the six-value `terminal_reason` is the real state (`symptom-confirmed`, `space-exhausted`, `technical-infeasibility`, `specific-defence-prevention`, `no-symptom-evidence`, `budget-timeout`).

| project | confirmed | space-exhausted | technical-infeasibility (429) | other | total |
|---|---|---|---|---|---|
| 9cc91832 (round 3) | 1 | 3 | 23 | 0 | 27 |
| d76f1bcc | 16 | 9 | 0 | 15 (14 unexecuted + 1 no-symptom) | 40 |
| 5603e6eb | 8 | 1 | 0 | 0 | 9 |
| ae3eb805 | 7 | 2 | 0 | 2 | 11 |
| 9132be4d | 7 | 1 | 0 | 0 | 8 |

The round-3 signature is **429-driven `technical-infeasibility`**, not triager laundering. `d76f1bcc` (the earlier working run) shows the healthy mix. Triager laundering IS a distinct, confirmed defect on other runs (EV-25, found by the C1 cortex review round 2, not in this round-3 sample).

## 4. Symptom-confirmed -> ground-truth mapping (comfyui kill chains)

Ground truth: 001 unauth read of Manager config via `/api/userdata`; 002 stored XSS via `/userdata` inline SVG; 003 stored XSS via `/view` after `/api/upload/image`; 004 arbitrary file read via `/view` double-encoded `subfolder`; 005 stored XSS via Manager channel URL + `custom-node-list.json` markdown injection; 006 SSRF via `/manager/queue/install_model` url.

| ground truth | matched by symptom-confirmed pods |
|---|---|
| comfyui-001 | `coarse-grained-authz_principal-less-object-access`, `cwe266-authnmech_anonymous-trusted-actor-grant`, `identity-assumption_anonymous-actor-scoped-probe` (d76f1bcc); `authn-mechanism-unconditional-privilege-conferral`, `default-identity-unverified-attribution` (5603e6eb); `h1-uniform-admission-state-changing-userdata` (9132be4d) |
| comfyui-002 | none |
| comfyui-003 | none |
| comfyui-004 | none |
| comfyui-005 | `cwe266-channel-pref-write_unauthenticated-preference-write` (9cc91832); `forced-browsing-catalog-read_anonymous-direct-request` (d76f1bcc); `UnauthenticatedDefaultChannelNodeInstall` (5603e6eb) - the channel-write precondition, not the rendered XSS |
| comfyui-006 | `classification-privilege-model-download_url-unbound-install-model` (d76f1bcc); `model-downloader-actor-side-admission`, `model-downloader-fetch-origin-unbound` (5603e6eb) |
| enablers / NEW | the reachability probes (d76f1bcc), the IDOR family (ae3eb805), the privilege family (9132be4d) |

The XSS and arbitrary-file-read classes (002, 003, 004) are never symptom-confirmed - the ground-truth consequence of the Tier-0 starvation.

## 5. Failure register (cleaned, merged)

Confidence: HIGH = code/evidence confirmed; POTENTIAL = needs `diagnosing-bugs`.

### Provider / resilience

| id | failure | diagnosis | conf | ticket |
|---|---|---|---|---|
| EV-21 | a persistent provider `429` fails the hunting run and poisons pod verdicts | No fallback model group. The orchestrator's `DegradedTurnBreaker` (#280 Part 2) aborts the pass after 5 consecutive degraded turns -> run `failed`; the hunter/pod sessions have no equivalent backoff and keep hammering; a pod raise degrades to `technical-infeasibility` with the raw error (`pod/pod.py:114-118`), mis-classifying a provider throttle as target infeasibility. `_phase_hunting` also drops the reason (`failure=None`). **Code side FIXED by #329** (`hunting-329-provider-failure-classification-adr.md`): a typed `ProviderUnavailableError`, the pod/triager/surfer provider propagation, and a provider-caused pass abort landing `interrupted`. The gateway guard (#330) and the stop/flush/resume + eval-monitor handling (#331) remain. | HIGH | #329 |
| EV-22 | token tracking not durable | in-memory ledger (`app/llm/usage.py::_LEDGER`) resets on restart so the budget never trips; compounded by the Langfuse gate requiring `LANGFUSE_HOST` so `LANGFUSE_BASE_URL` alone silently disables tracing | HIGH | #326, #327 |
| EV-24 | gateway sync rejects a non-`sk-` provider key (opencode-go `oc_sk_...`) as a litellm virtual key -> sync HARD, agent never starts | ADR D3 made the provider API key itself the litellm virtual key, assuming the `sk-` format (old zen keys were `sk-...`). LiteLLM's `POST /key/generate` enforces `sk-` ("Virtual Key must start with 'sk-'") and 400s on `oc_sk_...`, so `sync.py::ensure_virtual_key` aborts the sync (exit 1, D9 cold stop). Deterministic on any gateway-mode boot with the new key; affects every non-`sk-` provider key. **FIXED by #335** (2026-10-06): the sync mints an app-minted `sk-ph-<digest>` virtual key per provider (`providers.gateway_virtual_key`) and the client derives the same key as its gateway bearer; the provider credential stays in `litellm_params.api_key`. Resolution in section 11 and `llm-gateway-100-decisions.md` D3 amendment. | HIGH | #335 |

### Lifecycle

| id | failure | diagnosis | conf | ticket |
|---|---|---|---|---|
| EV-1 | recon launch 503 `module 'recon' is stopped` -> trial `failed` (080051, 080209) | `drain` settles the module to `stopped`; `resume` only resumes from `paused`, so it no-ops; the recon-entry predicate has no detection/repair | HIGH | #328 |

### Evidence and assessment

| id | failure | diagnosis | conf | ticket |
|---|---|---|---|---|
| EV-3 | assessment/diagnoser prompts show paths without the required `<project_id>/` prefix | prompt examples omit the mandatory first segment | HIGH | #288 |
| EV-4 | all comfyui verdicts `missed`; comfyui-001 never selected | Tier-0 starvation (schedule + cap, since fixed) AND the exposure-family KB coverage gap: CWE-552 (selection tier) carries `predicate: null` + `enum_kinds: [WebPresentation]`, so a Service/RESTApi data unit is pruned-by-tag and the userdata info-disclosure fault is never bound | HIGH (starve) / HIGH (KB) | #315, #321 |
| EV-25 | pod triager launders a degraded KB tool into a clean `space-exhausted` verdict | The KB tool fails OPEN (returns the deterministic fallback, `lightrag/tool.py`), so the triager's EXHAUSTION rule read "the KB returned no new variant" as evidence of absence and terminated `{unsuccessful, space-exhausted, clean=true}` - a degraded domain recorded as exhausted. 33/72 observations mention a degraded domain, 36/72 `space-exhausted`, 42/72 both (traces `11881bf0...`, `13cb49bf...`). **FIXED by #304**: the KB answer is marked `degraded = not accepted`, `KbObservation.degraded` records it, and the graph's triager node deterministically downgrades a clean exhaustion over degraded coverage to `no-symptom-evidence`/`clean=false` (deriving `insufficient-evidence`); the prompt states the rule. | HIGH | #304 |

### Contract and design

| id | failure | diagnosis | conf | ticket |
|---|---|---|---|---|
| EV-7 | tick dispatches assessment/diagnosis synchronously | design-level; blocks the tick | HIGH | #316 |
| EV-8 | the cap terminates the whole trial instead of bounding the hunting phase | design-level; partly addressed by the cap removal | HIGH | #315 |
| EV-9 | hunt-config/spec schema varies by status | unconfirmed; the `dropped` hypothesis-only shape may be intended | POTENTIAL | #313 |
| EV-10 | hunting yields zero test-specs/pods (trial-2, 75991388) | 11 `ratified` configs consumed, 0 specs authored; consistent with hunter-turn 429 degradation (section 0), not a mover defect | HIGH (429) | #312 |
| EV-11 | mover cannot consume configs whose System unit id contains `::` | naive `split('::')` in `HuntStore.consume_config` and siblings | HIGH | #279 |
| EV-12 | recon stop leaves the row `running` for `REAP_TTL_SECONDS`, then flips to `failed` | no distinct `stopped` terminal | HIGH | #287 |
| EV-13 | no-healthcheck target declared ready before its app binds -> recon 502 | readiness treats `running` with no healthcheck as immediately ready | HIGH | #325, #323 |
| EV-14 | documented dispatch examples use nonexistent `opencode run` flags | examples assumed a wrapper CLI | HIGH | #297 |
| EV-15 | CD reports success but the checkout never advances | `ff_dev.sh` never converges an existing checkout's `origin` | HIGH | #291 |
| EV-16 | trial completion does not auto-dispatch the assessment | `trial` has no dispatch seam; the monitor now owns it | HIGH (superseded) | #289 |
| EV-17 | observability reports queue drain, not exporter outcome | delivery truth read from the queue | HIGH | #235 |

### Test infrastructure

| id | failure | diagnosis | conf | ticket |
|---|---|---|---|---|
| EV-23 | `tests/test_steel_exec.py` fails on `dev` (`TypeError: 'coroutine' object is not subscriptable`) | `9119348` made the kali `steel_exec` tool non-blocking (`async def steel_exec` + `_offload`), so `m.steel_exec.fn` is a coroutine function, but the tests still call it synchronously; pre-existing on `ce0321a`, unrelated to the #329/#287 merges. **FIXED by #334**: the tests now await the real tool body via `asyncio.run` (`_steel_exec`), matching `mcp-exec-nonblocking-decisions.md` §5 | HIGH | #334 |

## 6. Noise removal applied

- **Closed tickets removed**: #305, #306, #307, #311, #320, #225/#226.
- **Resolved on dev, ticket closed**: #321 (L0->L1 AGGREGATES) - the drained jetlinks analysis produced 24 `AGGREGATES`; the comfyui zeros predate the streamed-analysis fix.
- **Diagnosed as 429, linked not closed**: #312 (zero test-specs) - hunter-turn 429 degradation; a comment links it to #329.
- **Not a bug, removed**: analysis `draining` was a transient settle state (now `drained`); the alignment hold works as specified.
- **Merged by root cause**: all 429-caused failures -> EV-21; the all-missed assessment -> EV-4; the token-ledger + Langfuse gate -> EV-22.
- **Infra/dependency family disregarded**: no `apscheduler` reference exists in the tree and it is not installed; no dependency was added. #281 and the `test_gateway_reasoning_passthrough.py` collection error remain infra.
- **Scaffolded-data-layer family disregarded**: #314 (3 operator KBs absent) is a data dependency, not a tracked defect. The 7-of-15 aarch64 target failures are environmental (qemu-user; needs an x86_64 host).
- **Malformed tmp setup scaffolds disregarded**: `tmp-siyucms.yaml` / `tmp-ofbiz.yaml` (eval server, mtime 2026-10-02) carry the removed `hunt_config_budget` field and fail `parse_eval_setup` (`unknown field(s): hunt_config_budget`, `orchestrator/setup.py:201`). Upstream is **ad-hoc scaffold data**, not the harness or the polyphemus codebase: the field was deliberately removed from `TargetRun` by the no-config-cap ADR (`docs/design/eval-token-budget-and-no-config-cap-adr.md`, commit `95fe2da`, 2026-10-05); the tmp files predate it by three days. Evidence: no trial ever ran under either setup (no runs dir, no `trial.yaml`); no generator script exists in the repo or on the server (only opencode snapshot/db reference them - they were hand-written in a session); the active `eval/setups/webexploitbench-5.yaml` uses `token_budget: 15000000` and parses; the schema correctly fails loud on the removed field. Disregarded per the active-domain rule. **Doc drift (low)**: the DRAFT pre-spec `docs/design/eval-harness-multi-instance-solution.md:73-88` still sketches `hunt_config_budget` (and retired `auth`/`lifecycle` fields); it is explicitly marked "Status: draft, NOT implementation", so not-active - corrected only as doc hygiene.

## 7. Needs `diagnosing-bugs`

1. EV-9 status-varying hunt-config/spec schema (may be intended).
2. EV-4 exposure-family KB predicate authoring (app-side KB artifact).
3. EV-10 confirm the trial-2 zero-specs attribution (log window may have rotated).

## 8. Failure deep-dive A - the provider quota (EV-21)

### Replication frequency
The provider enforces a rolling **5-hour** limit on workspace `wrk_01KZ107SCMX5YBFD83R0M8SSAK` (`limitName: '5 hour'`). The eval burns roughly **1M generated tokens per hour per active target** (9cc91832: 1.41M over ~1.5h; jetlinks: 1.26M over ~1.4h). The heavy `d76f1bcc` run (05:57-07:55) exhausted the window, so round 3 (08:11) failed immediately. Replication is therefore **predictable and recurring** for any back-to-back multi-target run that crosses the cumulative 5-hour ceiling - not a rare flake. It self-heals when the rolling window clears (siyucms-1 was healthy at 12:03).

### LiteLLM gateway throttling - feasibility, impact, complexity, risks
Researched against the LiteLLM docs (`proxy/users`, `proxy/load_balancing`, `proxy/budget_fallbacks`, `proxy/provider_budget_routing`, `proxy/dynamic_rate_limit`).

- **Prevention (stay below the provider roof): partial.**
  - Per-period budgets exist (`max_budget` + `budget_duration` / `time_period`) on keys, teams, projects and per-model (`model_max_budget`), runtime-updatable via `/key/update`, `/team/update`, `/project/update`, client-uncoupled. **But the unit is USD, not tokens** - there is no native token-per-5h cap.
  - Per-minute `tpm_limit`/`rpm_limit` exist and can be hard-enforced (`enforce_model_rate_limits`), but they are per-minute, not per-period.
  - A true token-per-5h cap needs a custom callback (`dynamic_rate_limiter_v3` or a custom `CustomLogger`), which is materially more complex.
- **Handling the 429 (fallback): feasible.** Router-level `fallbacks` fire on downstream provider errors (including 429); `budget_fallbacks` reroute on key budget exhaustion. Runtime-updatable. This is the #246 fail-over chain.
- **Throttling semantics:** LiteLLM rate limits return `429` with `retry-after`; they do not queue (except the `max_parallel_requests` Scheduler, which queues and risks client timeouts).
- **Risks:** per-minute TPM is best-effort (may overshoot); period budgets are USD-proxied; throttling returns 429 so the agent-resilience problem remains; known LiteLLM enforcement bugs (issue #10052: key-level limits and fallback not reliably triggering; `model_max_budget` enforcement unreliable).
- **Verdict:** the clean, client-uncoupled prevention is a conservative per-period USD budget plus a per-minute TPM on the key, sized below the provider roof; the robust handling is a router-level fallback chain. A native token-per-5h cap is not worth its complexity versus the fallback plus graceful agent resilience.

### Design decision A (operator)
Choose the fail-over/throttle policy: (i) a router-level fallback model group (#246); (ii) a conservative per-period USD budget + per-minute TPM on the gateway key; (iii) the eval orchestrator prompt recognises the quota failure and pauses/stops the run; or a combination. **Filed as #330** (gateway cost guard; high-level solution + impact map in the ticket, risks reduced during grilling). Full assessment: `docs/design/eval-provider-resilience.md` Part 1.

## 9. Failure deep-dive B - agent degradation handling (EV-21 code side)

### What actually happened
The pod export is **harness-fabricated**, not a triager assessment. `pod/pod.py:114-118` wraps the whole pod run and, on any raise, writes `verdict=unsuccessful`, `terminal_reason=technical-infeasibility`, `iterations=0`, `clean=False`, `error=<exc>`. The 23 round-3 pods carry `error="Error code: 429 ..."` with **zero** variant_specs, raw_observations and interpretations - the runner/triager never produced a turn. So the answer to "did the triager consume the rate-limited runner log and yield that assessment" is **no**: the triager never ran; the harness fabricated a domain verdict on the provider raise.

Langfuse (old project, queried via the current Observations API v2 after the v1 read endpoints returned 410 Gone) shows **456 ERROR observations** in 08:00-10:00, all `429 Go usage limit exceeded`, spanning every agent role (pod_runner, triager, gate, configurator, curator, supervisor, auditor, capability-probe, mechanism_typist, assigner, data_modeller, parser, exec).

### The current handling is fragmented
- **Orchestrator actors** (`recon/control/orchestrator_agent.py`, `attack/hunting/actors.py`) ride `run_session_agent`'s `on_turn_degraded` (#186): a raising turn retries the retryable class under a bounded budget, then degrades to a **no-decision reply** and the actor survives. The hunt pass adds `DegradedTurnBreaker` (#280 Part 2) which aborts after 5 consecutive degraded turns -> `HuntOrchestrationDegradedError` -> `runtime.start_hunting` persists `failed`.
- **The pod** does not ride the actor seam; it is a static config-driven graph, so a raise escapes to `pod.py` and becomes a fabricated `technical-infeasibility` domain verdict.
- **The runtime** persists `failed` on the breaker, but does not use the stop/flush/resume primitive.

### The correct holistic pattern (operator's direction)
Whatever agent degrades on an LLM-provider failure must be handled by ONE ubiquitous pattern at the app layer, scaffolded underneath the agents, never tracked in domain data (`PodExport` must not carry it):

1. **Stop** the execution with the correct primitive (`runtime.stop` / `drain`), which already flushes the module checkpointer index (`flush_module_index` / `flush_run_scoped`, typed `FlushResult`).
2. **Resume** once the app is healthy, restarting the failed agents **from the checkpoint before their failure**.

The primitives already exist (`app/runtime.py` stop/drain/resume; `app/llm/checkpoints.py` flush seams; the #186 retry/degrade hook). What is missing is the wiring that routes a **provider-failure** signal into the stop+flush path uniformly, and the removal of the domain-level fabrication in `pod.py`. The pod's domain verdict must only be written on a real assessment.

### Design decision B (operator)
Confirm the holistic pattern: a single app-layer provider-failure handler that stops+flushes the module and resumes from the pre-failure checkpoint, applied to every agent seam (orchestrator actors, hunter, pod runner/triager), and the retirement of the `pod.py` fabricated `technical-infeasibility` path. **Filed as #331** (provider-failure handling; high-level solution + impact map in the ticket). Full spec: `docs/design/eval-provider-resilience.md` Part 2.

## 10. Design decisions surfaced - #279 naming grammar and the `__singleton__` distinguisher

EV-11 (#279) is a naming-convention item, not a mechanical split fix. The semantic key `<unit>::<CWE>::<class>` embeds the System unit id, which is itself `::`-bearing (`System:AuthorizationSystem::__singleton__`), so `::` is not a unique separator and a positional split cannot recover the parts. Two design decisions will surface during the fix:

1. **The semantic-key grammar.** Whether the key stays `<unit>::<CWE>::<class>` with a positional split anchored on the CWE token (the stopgap), or moves to a structured/escaped encoding: a typed key object, a length-prefixed or escaped segment, or a distinct delimiter for the kind-qualified unit id. The durable decision is the grammar, not the anchor.
2. **The `__singleton__` distinguisher.** `System:AuthorizationSystem::__singleton__` uses a magic literal for the singleton System unit. The decision is what replaces it: a stable, unique, meaningful key (the System's own identity separate from its display name; a typed `(kind, name, scope)` triple; or one reserved singleton sentinel defined in a single place). The replacement must be unique across the graph and readable in the semantic key.

Both are operator decisions (like A and B). The #279 implementer must grill them with grill-with-docs before choosing and record the outcome as an ADR; the CWE-token anchor is acceptable only as the interim behavior, never as the final grammar.

## 11. Failure deep-dive C - the litellm virtual-key format (EV-24)

### What actually happened
The opencode-go provider key is now `oc_sk_...` (it was `sk-...` in an earlier form). In gateway mode the D2/D9 sync provisions each configured provider's key as a litellm virtual key (`sync.py::ensure_virtual_key`, `POST /key/generate {key, models}`). LiteLLM's `user_api_key_auth` accepts only master_key and `LiteLLM_VerificationTokenTable` rows, and `/key/generate` enforces the `sk-` key format. `oc_sk_...` is rejected with `400 Invalid key format. LiteLLM Virtual Key must start with 'sk-'. Received: oc_s****uLz3`, the sync takes the HARD path (exit 1) and the agent halts before starting (D9 cold stop). The models themselves register fine; only the key mint fails.

### Why it is deep
The defect is not in the sync control flow - that is correct and loudly safe. It is the **ADR D3 assumption** that the provider's own API key can double as the gateway virtual key ("the client's existing bearer just works"). That held only while every provider key was `sk-`-prefixed. Any non-`sk-` provider key breaks gateway mode entirely, so the fix is a boundary/identity decision (what is the client's gateway credential vs what the gateway holds upstream), not a patch.

### The fix direction (design decision)
Decouple the virtual key from the provider key: mint a litellm-native `sk-...` virtual key (per provider, or one app key), keep the provider credential in the model's `litellm_params.api_key` (already the case), and have the client send the minted key when `LLM_GATEWAY_URL` is set. Alternatives (a deterministic derived key, or relaxing litellm) are noted in #335. Preserve `key_info`/`ensure_virtual_key` idempotency (C9). Record as an ADR amending D3.

### Secondary (low): misleading warning
`sync.py:643-646` prints the env var as `API_KEY_%s` with `provider.upper()` (dash: `API_KEY_OPENCODE-GO`), while the lookup uses `_key_env(provider)` (underscore: `API_KEY_OPENCODE_GO`). Cosmetic; fix with the same change.

### Operator-side context (not part of this defect)
Provider chat calls are separately gated by opencode workspace Privacy settings: `deepseek-v4.1-flash` -> "requires Global regions"; `muse-spark-1.3-contributor` -> "trains on request data. Allow paid endpoints that train on request data". These are operator actions; they block live chat verification but not the sync fix.

### Resolution (#335, 2026-10-06)
Option (a), realised as a deterministic derivation so no state or new env var is needed: `providers.gateway_virtual_key(provider, api_key)` returns `sk-ph-<sha256(provider NUL api_key)>`. The sync mints exactly that key per provider (`sync.py::run_sync` -> `ensure_virtual_key`), scoped to the provider's registered models, and `build_chat_model` presents exactly that key as its gateway bearer when `LLM_GATEWAY_URL` is set. The provider credential still lands in each model's `litellm_params.api_key` (the gateway's upstream custody; the #193 rotation path is unchanged) and `API_KEY_<PROVIDER>` stays required as the derivation seed. `ensure_virtual_key` now refuses a non-`sk-` key at the write boundary, `key_info`/`ensure_virtual_key` idempotency is preserved (C9), and the skip warning prints `_key_env(provider)` (`API_KEY_OPENCODE_GO`, not the dash form). Recorded as the ADR D3 amendment in `llm-gateway-100-decisions.md`.
