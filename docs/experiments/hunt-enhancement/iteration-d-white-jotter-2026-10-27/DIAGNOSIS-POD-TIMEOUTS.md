# Pod watchdog and node timeout diagnosis (iteration D)

Status: diagnosis from the last ingested Langfuse traces, the pod run records, and the live host metrics.
Date: 2026-10-28T11:15Z.

## Verdict

The failing pods are **not host-resource bound**.
The saturated resource is the **LLM provider's throughput and concurrency**, amplified by two
design facts:

1. `pod_batch_size` limits the **hunt block**, not the **pod-spec fan-out**. A hunt dispatches
   every variant spec as its own pod session at once. The current run has 39 pod specs over 9
   hunts; the first BFLA hunt alone ran 11 pod sessions concurrently.
2. Every pod-runner model call carries a **large context**: 25,982 tokens median, 32,746 max
   on the traced pod. The output is small (265 tokens median), so the wall is reading and
   reasoning, not generating.

The pod watchdog is wall-clock, not progress-based. At a 43.8 s median model call, 3,600 s is
about 82 model calls. The pods need more than that; the watchdog fires first. The node idle
timeout is 600 s, which a single queued or very slow model call can exceed on its own.

## Langfuse is partially blind

The observability pipeline is **not** the source of the missing traces alone; it is suspended:

- The legacy `GET /api/public/traces` is gone on this v4 project (410). The v2
  `GET /api/public/v2/observations` read still works.
- The OTLP ingestion endpoint returns
  `403 {"message":"Ingestion suspended: Usage threshold exceeded. Please upgrade your plan.","error":"ForbiddenError"}`.
- The first 403 in the app log is **02:35:33Z**. The exporter retries four times, then drops
  the batch. Every later span is lost. The reads keep working, which is why the earlier spans
  are visible and the later ones are not.
- The traced sample therefore stops at the first BFLA block (02:00-02:35). The
  mass-assignment, insecure-deserialization, and information-disclosure pods have **no**
  traces. The run cannot be retroactively traced; the plan must be upgraded (or a fresh
  project with quota used) before a re-run can collect them.

This is an observability defect separate from the pod failures. The app is fail-open: it keeps
running, blind, and logs `dropping batch`.

## Evidence: the traced BFLA pod

Session `aac5ecac-...:broken-function-level-authorization__role-grant-write__direct-verb:pod_runner`
(Pod `role-grant-write`, 38 probes, maximum probe 1,593 ms, total probe time 9,516 ms):

| Metric | Value |
|---|---|
| Window | 02:00:41 to 02:33:49 |
| Wall | 1,988 s |
| Model generations | 28 |
| Model latency median | 43.8 s |
| Model latency p95 | 188.9 s |
| Model latency max | 197.9 s |
| Model latency total | 1,509.5 s (75.9% of the wall) |
| Input tokens median / max | 25,982 / 32,746 |
| Output tokens median / max | 265 / 753 |
| `exec` calls | 25 |
| `exec` median / p95 / max | 4.0 s / 7.7 s / 110.3 s |
| `exec` total | 213.1 s (10.7% of the wall) |

The remaining 13% is middleware, compaction, and the event loop.

At 02:33 the pod had already spent 1,988 s. Its watchdog fires at 3,600 s, so it dies around
03:00 with roughly 50 model calls done and its probes still cheap.

## Evidence: all 15 timeout pods

The probe time is seconds, not minutes, in every one:

| Terminal reason | Pod | Probes | Max probe | Sum probe |
|---|---|---|---|---|
| node-timeout | insecure-deserialization heap-dump command-execution | 13 | 11,789 ms | 32,364 ms |
| watchdog | BFLA account-write direct-verb | 40 | 3,270 ms | 18,961 ms |
| watchdog | BFLA book-content-write direct-verb | 31 | 2,768 ms | 12,841 ms |
| watchdog | BFLA content-management matrix | 35 | 1,508 ms | 14,530 ms |
| watchdog | BFLA role-grant-write direct-verb | 38 | 1,593 ms | 9,516 ms |
| watchdog | BFLA user-roster-read direct-get | 22 | 7,118 ms | 30,956 ms |
| watchdog | BFLA user-roster matrix | 59 | 10,200 ms | 41,360 ms |
| watchdog | info-disclosure configprops | 14 | 23,629 ms | 30,220 ms |
| watchdog | info-disclosure httptrace literal-prefix | 13 | 168 ms | 816 ms |
| watchdog | info-disclosure mappings | 41 | 727 ms | 4,286 ms |
| watchdog | insecure-deserialization callback-oracle | 39 | 15,156 ms | 86,301 ms |
| watchdog | insecure-deserialization forged-principal | 56 | 23,434 ms | 100,650 ms |
| watchdog | mass-assignment contentmanager-role | 40 | 34,625 ms | 59,827 ms |
| watchdog | mass-assignment role-grant-set | 65 | 61,834 ms | 138,242 ms |
| watchdog | mass-assignment sysadmin-role | 30 | 33,382 ms | 62,854 ms |

The `httptrace` pod spent **0.8 s** in probes and still hit a 3,600 s watchdog. The
`node-timeout` pod spent 32 s in probes; its runner node then sat idle for 600 s, with a total
node elapsed of 1,638.8 s. The probes are not the bottleneck; the model loop is.

## Evidence: the host is idle

At 11:09Z, while the mass-assignment pods were still running:

- Load average 1.18 (1 min), 1.41 (5 min), 1.44 (15 min).
- Memory 9.3 GiB used of 15.2 GiB, 6.3 GiB available.
- Agent container 6.2% CPU, 1.45 GiB; target 3.9%, 1.78 GiB; kali 3.5%, 829 MiB;
  Neo4j 0.8%, 1.5 GiB; Postgres 0.02%.

No CPU, memory, or IO saturation. The provider calls are remote; the host is not the
constraint.

## Root causes, ranked

1. **Provider throughput and concurrency.** The pod-runner's model calls are 76% of the wall,
   with a 43.8 s median and a 188.9 s p95. The provider (opencode-go/deepseek-v4.1-flash)
   cannot keep up with the concurrent pod sessions. This is the saturated resource.
2. **Pod-spec fan-out.** `pod_batch_size: 1` serializes the hunts, not the specs. The first
   BFLA hunt ran 11 pod sessions at once; the 9 hunts produced 39 pod specs. The provider sees
   the fan-out, and its per-call latency rises.
3. **Large per-call context.** 26k input tokens median, 33k max. The output is small, so the
   time is reading and reasoning. The context is the main lever on latency after provider
   capacity.
4. **Wall-clock timeouts.** The pod watchdog (3,600 s) and node idle (600 s) are not
   progress-based. A 188.9 s p95 call plus the compaction overhead leaves little room before
   3,600 s; one queued call exceeds the 600 s idle window.
5. **Observability suspension.** Langfuse ingestion stopped at 02:35; the later failures are
   invisible. This does not cause the timeouts, but it prevents per-pod confirmation.

## What would move the needle

- **Cap the pod-spec concurrency.** Add a spec-level semaphore (2-3 concurrent pods), or
  serialize the specs of a hunt. `pod_batch_size` alone does not bound the provider load.
- **Cut the per-call context.** Lower the compaction threshold, trim tool and KB payloads, and
  keep the pod role's thinking level at `high` or below. The 26k input is the latency floor.
- **Make the timeouts progress-based.** Reset the node idle timer on a probe or model
  response; size the watchdog from the observed p95 call latency and the remaining step count,
  not a fixed hour.
- **Give the pods a provider quota or a faster model.** The design roles run at `max`
  thinking; the pods run at `high`. The pod path is still provider-bound.
- **Upgrade the Langfuse plan or use a fresh project with ingestion quota.** Add an alert on
  the exporter's dropped-span counter and the 403, so an observability outage is never silent.
