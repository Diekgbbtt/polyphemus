# DEBUG: pod throughput collapse and the enhancement room

Run: `white-jotter-1-20261027T074905-1618c524`.
Host: `ubuntu-16gb-nbg1-1`, 8 vCPU Neoverse-N1, 16 GiB, KVM guest, no cgroup CPU or memory limit.

## Observations

### The agent host is not saturated; one process is

| Measure | Value | Source |
|---|---|---|
| vCPU | 8 | `nproc`, `lscpu` |
| Load average at 13:45Z (idle) | 0.59 | `/proc/loadavg` |
| CPU pressure `some total` | 23,671 s over 24 days | `/proc/pressure/cpu` |
| Memory pressure `some total` | 1,413 s over 24 days | `/proc/pressure/memory` |
| IO pressure `some total` | 1,780 s over 24 days | `/proc/pressure/io` |
| Memory used | 9.5 GiB of 15 GiB, 2.1 GiB swap | `free -h`, `swapon` |
| Background CPU (sum of process pcpu) | 177 to 184 percent | `ps -eo pcpu` |

The whole machine is at roughly 1.8 of 8 cores when idle.

The hunting runtime is **one uvicorn process**, PID 2031481, `uvicorn polymerhus.app.main:app`, with 51 threads and no `--workers`:

| Measure | Value |
|---|---|
| CPU time since start | 30,968 s |
| Wall since start | 64,547 s |
| Average CPU | 0.48 core over its lifetime |
| Average CPU during the 11.9 h active window | about 0.72 core |
| Resident memory | 1.09 GiB |
| CPU per LLM call (2,458 calls) | 12.6 s |
| CPU per executed probe (936) | 33.1 s |

### The provider is fast; the client is not

LiteLLM spend logs (`LiteLLM_SpendLogs`) and Langfuse v2 observations for the same windows:

| Window | Proxy calls | Proxy TTFT p50 | Proxy total p50 | Client TTFT p50 | Client total p50 |
|---|---:|---:|---:|---:|---:|
| 2026-10-27 00:40 | 117 | 1.14 s | 3.78 s | 2.99 s | 29.7 s |
| 2026-10-27 04:40 | 88 | 1.11 s | 3.03 s | 4.95 s | 72.3 s |

Per-minute call counts match almost exactly between the two systems (3/15/13/12/10/8/6/9/5/7 against 3/15/13/11/11/8/5/10/5/7), so these are the same calls.

`request_duration_ms` in the spend log equals the timestamp delta to the millisecond (5,158 against 5,159), so the proxy really is finished in 3 to 5 s.

The client's generation span stretches 26 to 69 s past the proxy completion.
That gap is inside the Python process, not on the wire.

### Throughput did not rise with concurrency

| Arm | Concurrency | Pods | Probes | Pod-hours | Watchdogs | Finished pods per hour | Symptom-confirmed per hour |
|---|---:|---:|---:|---:|---:|---:|
| B.a | at most 5 | 37 | 919 | 16.6 | 1 | 5.9 | 3.8 |
| C | 14 to 15 | 55 | 936 | 52.6 | 41 | 2.5 | 2.1 |

Per-probe wall time by band:

| Band | Median per probe | Median probes |
|---|---:|---:|
| B.a at most 5 | 60 s | 25 |
| C at 6 to 9 | 145 s | 25 |
| C at 10 or more | 239 s | 14 |

C moved 60 percent more pods per hour than B.a and completed 58 percent fewer.

### Prompt size is very large

Proxy `prompt_tokens`, p50 by hour:

| Hour | Calls | p50 input tokens |
|---|---:|---:|
| 20:00 | 210 | 64,497 |
| 21:00 | 257 | 169,755 |
| 22:00 | 166 | 303,791 |
| 23:00 | 181 | 216,535 |
| 00:00 | 351 | 39,812 |
| 01:00 | 241 | 22,762 |
| 02:00 | 147 | 29,172 |
| 03:00 | 281 | 20,817 |
| 04:00 | 274 | 26,287 |
| 05:00 | 120 | 31,136 |
| 06:00 | 155 | 23,109 |
| 07:00 | 75 | 33,492 |

The modelling phase sends 170k to 304k tokens per call.
The pod phase sends 21k to 40k.

### Network and gateway are healthy

| Measure | Value |
|---|---|
| Egress interfaces | one, `eth0` 46.224.225.245/32, default via 172.31.1.1 |
| DNS to `api.swissai.svc.cscs.ch` | 39.8 ms |
| TCP connect | 54.3 ms |
| TLS handshake | 79.1 ms |
| Total to `/v1/models` | 113.7 ms, HTTP 200 |
| NIC errors, drops | 0 |
| Gateway non-success statuses in the run | 0 of 2,458 |

There is no second subnet to route through: the host has one public /32 and one default route.

### Runtime topology

| Component | Observation |
|---|---|
| Agent app | one uvicorn process, 51 threads, all hunting sessions as asyncio tasks |
| LLM gateway | one LiteLLM ASGI process, 2,175 s CPU over 17.9 h (0.4 s per call) |
| Target | `pentestbench-white-jotter:1.0.1`, image arch **amd64** on an arm64 host, running under `qemu-x86_64` |
| Target CPU | 9.7 percent, 1.9 GiB RSS, 104 MiB swapped |
| MariaDB | amd64 under qemu, 82 MiB swapped |
| ComfyUI | amd64 under qemu, 228 MiB swapped |
| Kali | `polymerhus-kali`, 865 MiB, MCP server 6 days old |
| Stale host processes | my iteration C monitor ran 17 h (2,168 s CPU), two `http.server 8899` pairs 19 h, a `v2.py` 6 days at 2 percent, VSCode server, two vite dev servers |

## Hypotheses

### H1: one Python process serialises every turn (ROOT HYPOTHESIS)

Supports: the app is one uvicorn worker with 51 threads; its CPU is 0.72 core during the run, close to one full core; the client gap is 26 to 69 s while the proxy is 3 s; per-probe cost rises with concurrency (60, 145, 239 s); the throughput of completed pods falls while dispatched pods rise; the watchdog timers fire five to six minutes late, which is event-loop delay.

Conflicts: the host has 8 cores and CPU PSI is low. That is consistent: one core saturated leaves seven idle.

Test: at concurrency 1 the client gap should collapse toward the proxy time; at concurrency 15 it should reappear. A py-spy profile of the app during a wave would name the hot frame.

### H2: the provider queues or rate-limits

Supports: remote shared academic provider (`api.swissai.svc.cscs.ch`); latency varied over the run.

Conflicts: proxy TTFT is 1.1 s in both windows; proxy total is 3.0 to 3.8 s; zero non-success statuses; gateway duration is flat while client time triples.

Verdict: rejected.

### H3: network egress bandwidth or route

Supports: remote provider, single egress.

Conflicts: RTT 54 ms, TLS 79 ms, zero drops, token traffic is kilobytes per second, gateway 3 s.

Verdict: rejected; there is no alternate subnet on this host.

### H4: memory pressure and swap stalls

Supports: 2.1 GiB swap used; qemu targets and lightrag are swapped; the app is 1.09 GiB.

Conflicts: memory PSI is 1,413 s over 24 days (0.07 percent); the app itself has only 25 MiB swapped; per-probe cost tracks concurrency, not memory.

Verdict: secondary at most.

### H5: the batch barrier wastes capacity

Supports: pods finish between 1,200 and 2,800 s but the block waits for the slowest; 37 percent of pod slot-time is idle.

Conflicts: B.a also ran at 55 percent utilisation; both arms leave 40 percent idle; throughput difference is explained by per-probe cost.

Verdict: real but third-order compared with H1.

### H6: per-turn prompt size drives CPU

Supports: 12.6 CPU-s per LLM call; 170k to 304k input tokens per modelling call; Python has to serialise, validate and count every token; provider caching hides this from the gateway but not from the client.

Conflicts: pod prompts are only 21k to 40k, and per-probe cost still tripled, so prompt size alone does not explain the pod phase.

Verdict: significant for the modelling phase, secondary for pods.

## Experiments

### E1: concurrency dose-response (observational, no new run)

Per-probe wall time rises monotonically with concurrency while the proxy stays flat.
A fixed per-turn overhead would not vary with concurrency; this does.
Result: confirms H1 and rejects H2.

### E2: client versus proxy duration (observational)

The same calls are 3 s at the proxy and 30 to 72 s at the client, with matching per-minute counts.
Result: the gap is client-side. Confirms H1, rejects H2 and H3.

### E3: throughput accounting (observational)

Finished pods per hour (any durable export): 5.9 in B.a, 2.5 in C.
Symptom-confirmed pods per hour: 3.8 in B.a, 2.1 in C.
Dispatched pods per hour: 6.1 in B.a, 9.8 in C.
Result: concurrency increased dispatch rate, not completion rate. Confirms H1.

### E4: stale process cleanup (interventional, reversible)

Stopped my own 17-hour monitor (PID 2111513, 2,168 s CPU).
Load average fell from 0.77 to 0.65; CPU sum from 183.7 to 177 percent.
Result: the cleanup is real but small; the remaining 1.8 cores of background CPU are containers and dev servers.

### E5: capacity and barrier projection (model, not a run)

Using B.a's measured 60 s per probe at concurrency 5, the same 936 probes need:
936 x 60 / 5 = 11,232 s = 3.1 h.

The observed pod phase was 5.56 h.
The gap is 2.4 h of barrier idle and per-probe contention, and at concurrency 5 every pod finishes inside the hour (25 probes x 60 s = 1,500 s).

At concurrency 8 with C's measured 145 s per probe the projection is 4.7 h; at 15 with 220 s it is 3.8 h with a 74 percent watchdog rate.
The projection favours concurrency 5, and it is a lower bound because spec authoring has to keep pace.

### Decisive experiment for the next run

Run one pod at concurrency 1 while sampling the app process CPU and the proxy duration.
Prediction under H1: client span falls to within a few seconds of proxy time, and app CPU stays below 0.2 core.
If the gap persists at concurrency 1, H1 is wrong and the cost is a fixed per-turn step (checkpointing, GC, or instrumentation), which py-spy can then name.

## Conclusions

Root cause: **the hunting runtime is a single Python process, and every agent turn pays client-side CPU that grows with concurrency.**
The VM has seven idle cores, the network adds 80 ms, and the provider answers in 3 s.
Concurrency above five converts idle capacity into queueing, then into watchdogs.

The optimal throughput point measured on this host is **concurrency 4 to 5 with the 3,600 s budget**: 60 s per probe, 25 probes per pod, 3.8 symptom-confirmed pods per hour, 1 watchdog in 37.
At 14 to 15 concurrent the same host confirms 2.1 pods per hour.

## Enhancement room, ranked by complexity and yield

| # | Dimension | Change | Complexity | Yield | Evidence |
|---|---|---|---|---|---|
| 1 | Stale process hygiene | reap expired monitors, duplicate listeners, old dev servers; cap users' sessions | low | medium | 1.8 cores and 2 to 3 GiB of background load |
| 2 | Admission control | cap pod concurrency at 4 to 5 (batch or global semaphore) | low | high | 5.9 against 2.5 finished pods per hour; 3.8 against 2.1 confirmed |
| 3 | Timeout policy | keep 3,600 s at concurrency 4 to 5; if concurrency stays high, raise to 5,400 to 7,200 s | low | medium | p95 spec needs 5,300 s at 239 s per probe |
| 4 | Memory and swap hygiene | lower swappiness, cap container memory, stop swapping the qemu targets | low-medium | medium | 2.1 GiB swap, qemu targets swapped |
| 5 | Prompt size discipline | cap modeller context, send model deltas, trim pod payloads | medium | high | 170k to 304k input tokens per modelling call |
| 6 | Isolate hunter from pods | run hunt authoring in its own process or service | medium | high | 69 s client gap with a 3 s proxy during mixed load |
| 7 | Native arm64 targets | rebuild white-jotter, mariadb, comfyui for arm64 | medium | medium | qemu-x86_64 on arm64, 9.7 percent CPU idle |
| 8 | Multi-process pod workers | 4 to 6 worker processes sharing the stores | medium-high | very high | one core busy, seven idle; 0.72 core average |
| 9 | Work-conserving scheduling | dispatch the next spec as a slot frees, not per block | medium-high | medium | 37 percent slot idle, but B.a also 45 percent |
| 10 | Egress distribution | add a second public IP and policy routing | high | none | single /32, 54 ms RTT, zero drops, 3 s proxy |

Do 1, 2 and 3 first: they are configuration and hygiene, and they recover the B.a operating point immediately.
Then 5 and 6, which cut the per-turn client cost without changing the architecture.
Then 7, which removes a separate CPU and memory tax.
Only then 8, which is the structural fix if the arm needs concurrency above five.

## Evidence appendix

| Source | What it settles |
|---|---|
| `LiteLLM_SpendLogs` | per-call TTFT, duration, tokens, status |
| Langfuse v2 observations | client-side generation spans for the same calls |
| `/proc/2031481/stat` | 30,968 s CPU over 64,547 s wall |
| `audit_pod_lifetimes.py` | per-pod wall, probes, tool time, terminal |
| `/proc/pressure/*` | host CPU, memory, IO stall totals |
| `ip addr`, `curl` timings | single egress, 54 ms RTT, 79 ms TLS |
| `docker inspect`, `docker stats` | image architectures, container limits |
| `src/polymerhus/attack/hunting/surfer.py:1078` | per-session 3,600 s watchdog |
