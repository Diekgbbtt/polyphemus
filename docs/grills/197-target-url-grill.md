# Grill report - #197 hunting pods dispatched without a target URL

Date: 2026-08-27
Ticket: #197 - hunting pods are dispatched without a target URL - every pod probes a guessed host (localhost:8080) and returns unsuccessful
Worktree: fix/hunting-197-target-url
Author: implementer

This is the mandated first pass: stress-test the fix before writing a single line.
Per point: decision, rejected alternative, edge case it covers.
If the grill contradicts the known-good shape, the grill wins with reason recorded.

---

## 1. SOURCE of truth

**Decision:** `settings.recon.target_seed` (canonical) / `settings.recon.target_domain` (deprecated alias) via `resolve_seed` is the sole authoritative target.
The normalizer reads `settings['recon']['target_seed']` through `load_settings(project_id)` (pg.py:293) and `recon/control/scope.py:50 resolve_seed`.

**Defended:** The L0 graph's observed `BaseURL`/`Endpoint` nodes are an unreliable target source because of the CSR-SPA ceiling: the real API base URLs are often NOT observed (JS-rendered routes, `httpx_reprofile` only lifts what was crawled). The eval stretch showed pods that relied on L0 evidence never saw the vhost's API prefix and fell back to guessing. The seed is the operator contract: every eval target in `eval-targets.yaml` carries `settings.target_seed` as a bare domain (`soupmarket.shop`, `moodique.com`) that maps onto `POST /projects/{id}/settings {recon:{target_seed}}`. The recon launch guard (`project_management/repository.py:139-152`) already refuses a targetless run for the same reason - hunting must follow the same discipline.

**Rejected alternative:** Feeding L0 endpoint BaseURLs (e.g. `graph_view`'s `ENDPOINT` set) into the pod. Rejected because (a) coverage is partial and noise-heavy (off-scope links, static assets), (b) the pod would need a disambiguation heuristic (which BaseURL is the target?), (c) it couples hunting to recon completeness, violating the bounded-context separation (`project_management -> recon` is lazy, hunting does not depend on recon graph). Observed L0 endpoints are evidence for the hunting AGENT's probe concretization, never the target ADDRESS.

**Edge case covered:** A project with an L0 graph that contains zero or many BaseURLs (e.g. WAF-blocked `magnific.com`) still gets a deterministic target from the seed. A seed that is a bare IP (`93.184.216.34`) is also authoritative for host-mode - the same seed logic handles it, while L0 would have to infer which IP is primary.

---

## 2. Scheme/port normalization

**Decision:** Derive the pod base URL defensively from the seed string. The seed contract is a BARE domain, but the normalizer accepts three shapes and always produces `scheme://host[:port]/` with a trailing slash and no path/query/fragment. Implementation in `attack/hunting/target.py:normalize_target_seed`.

Input -> Output table (exact):

| Input (raw `target_seed`) | Output (`target_url`) | Note |
|---|---|---|
| `soupmarket.shop` | `http://soupmarket.shop/` | bare domain -> default `http` |
| `example.com:8080` | `http://example.com:8080/` | port-bearing bare -> default `http`, port preserved |
| `192.33.91.87` | `http://192.33.91.87/` | bare IPv4 -> `http` |
| `192.33.91.87:8000` | `http://192.33.91.87:8000/` | IPv4 with port |
| `http://example.com` | `http://example.com/` | already scheme'd, add slash |
| `https://example.com` | `https://example.com/` | preserve `https` |
| `http://example.com:8443` | `http://example.com:8443/` | scheme + port preserved |
| `https://soupmarket.shop:443/` | `https://soupmarket.shop:443/` | trailing slash kept |
| `http://example.com/api` | `http://example.com/` | path stripped - base only |
| `https://example.com:443/path?q=1#frag` | `https://example.com:443/` | query/fragment stripped |
| `  soupmarket.shop  ` | `http://soupmarket.shop/` | whitespace trimmed |
| `""`, `None`, `"   "`, `"http://"`, `"://bad"` , `"http:///a"`, `"example com"`, `"*.example.com"` | `None` | failure -> INIT-reject |

Normalization steps:
1. Trim. If empty/None -> `None`.
2. Reject if contains whitespace.
3. If matches `^https?://` (case-insensitive): parse with `urllib.parse.urlparse`. Require non-empty `netloc` and scheme `http`/`https`. Reject if `netloc` empty or contains whitespace. Return `f"{scheme.lower()}://{netloc}/"` (lowercase scheme, preserve case of host, drop path/query/fragment, force single trailing `/`).
4. Else (bare): take `raw.split("/")[0].split("?")[0].split("#")[0]` as `hostport` (strip any accidental path). Validate `hostport` non-empty, no whitespace, not `*`, not starting with `*.`. Validate via `urlparse("http://" + hostport)` that `hostname` exists and `netloc` equals hostport (catches `:` or `.`-only). Return `f"http://{hostport}/"`.

**Failure mode:** `None` (not an exception). Caller treats `None` as "no target" -> pod builder produces a `technical-infeasibility` INIT-rejection envelope with `init_validation=["no target URL available: ..."]` and `clean=False`, never raises through the control plane. This preserves the IA-4 fail-open ring.

**Rejected alternatives:**
- Defaulting to `https` for bare domains: rejected - eval's `soupmarket.shop` is `http` behind kali's self-signed TLS where `curl -k` is used; `http` is the safe default because the pod's `curl -k` handles both, and the seed contract never implies TLS. The pod can still follow redirects to `https` if the target enforces it.
- Preserving input path (`http://example.com/api` -> `http://example.com/api`): rejected - the payload vector's `path` (`/api/users/{id}`) is appended to the BASE; preserving an input path would double-prefix. Base must be origin only.
- Raising `ValueError` on bad input: rejected - the pipeline is fail-open; a raise would have to be caught at every call site. `None` is the explicit absence signal that threads to INIT-reject.

**Edge cases covered:**
- Port-bearing seeds (`example.com:8080`) survive - important for non-standard ports in host-mode.
- Already-scheme'd seeds with path (`https://example.com/foo`) are reduced to origin - prevents double path.
- IPv4 seeds work; IPv6 seeds are pre-rejected by the recon launch guard (`seed_kind == ipv6` -> 400) so hunting never sees them, but the normalizer would also reject `[...]`-less IPv6 (whitespace/containment check) -> `None` -> INIT-reject, never a guessed host.
- Wildcard `*.example.com` is rejected -> INIT-reject rather than silently probing `*.example.com` (DNS invalid). The correct apex is `example.com` via `parse_scope`, but hunting's contract is bare domain, so wildcard is a configuration error that must be surfaced.
- Whitespace or control chars -> `None`, not a malformed URL probe.

---

## 3. The SEAM

**Decision:** BOTH seams are needed, but with asymmetric weight.

- **Seam (a) INJECT at dispatch** - REQUIRED and SUFFICIENT for live whole-pipeline pods: `start_hunting` reads `settings` via `asyncio.to_thread(load_settings, project_id)`, normalizes to `target_url`, and threads it into the `pod_builder` closure built at `runtime.py:577 build_run_dispatch`. The closure captures `target_url` and `_default_pod_builder(spec, ..., target_url=...)` forwards to `arun_pod(..., target_url=...)`. This is the primary fix; every pod dispatched through the surfer sees the same `target_url` that was snapshotted at run start.

- **Seam (b) SPEC carry** - NOT required for the minimal live fix, but retained as the deterministic pod's EXISTING contract: `hunting_pod.py:38 _target_url` reads `injected OR spec.target_identity.url`. The spec-authoring seam (hunter writing `target_identity.url` into the spec) is **not changed in this patch**. Reason: the hunter's authored spec currently carries `target_identity` as the L1 unit name (`Service:account-registration`) - changing it would require the hunter to read `target_seed`, compose a URL, and embed it per spec, which adds LLM prompt surface and a second source of truth that could diverge from the dispatch injection. The deterministic pod's spec-side path stays as the contract-tier/hermetic-test path; the live ReAct pod's injected path is the production path. The two agree because `hunting_pod._target_url` prefers the injected value and falls back to spec-side, so a spec that later carries a URL would still work, but dispatch injection alone already makes whole-pipeline pods probe correctly.

**Rejected alternative (a-only vs b-only):**
- `b-only` (make hunter author spec with URL, leave dispatch untouched): rejected because `arun_pod`'s ReAct loop does not read `target_identity.url` from the spec's typed base - it would still need a prompt change to surface that field, and the LLM could still ignore it. The dispatch injection is the one place that guarantees the exec surface sees the origin without relying on LLM compliance. A spec-only fix depends on the LLM being told the URL, which is not fail-closed.
- `a-only` leaving `hunting_pod` spec-side untouched: ACCEPTED as minimal - it leaves the contract tier blind? No: `hunting_pod` tests inject `target_url` directly or set `spec.target_identity.url` via `_spec(target_url=...)`; they never go through the surfer, so they already test the spec side. The live `arun_pod` path is tested via the threading test that asserts the injected `target_url` reaches the builder. The two tiers stay green without touching the hunter prompt.

**Edge case - contract tier disagreement:** If a future test calls `HuntingHttpPod` without injected `target_url` and without `spec.target_identity.url`, the pod returns `technical-infeasibility` with `init_validation=["no target URL available: populate target_identity.url or inject the asset base URL into the pod"]`. This is the same envelope the live `arun_pod` would produce when `target_url is None` - so the vocabulary converges even though the write seams differ.

**Grill vs known-good shape:** Known-good shape proposed only seam (a). The grill ENDORSES that as the minimal version, with the amendment that `arun_pod` must ALSO gain an `injected OR spec-side OR INIT-reject` internal check (defense in depth) so a direct `arun_pod(spec, target_url=None)` without dispatch still fail-closes rather than guessing `localhost:8080`. The spec-authoring seam (b) is deferred, not rejected permanently - a follow-up could make the hunter embed `target_identity.url` for hermetic spec portability, but it is not required to make every pod in the eval stretch probe the seeded domain.

---

## 4. EVERY dispatch path must recover the target

Trace each path with the chosen seam (a):

**Whole-pipeline** (`POST /projects/{id}/hunting {candidates}`):
`api.py:314 launch_hunting` opens `hunting_runs` row, schedules `hunting_runtime.start_hunting(project_id, run_id=hunting_run_id, candidates=...)` via `schedule_hunting` onto the hunting loop. `start_hunting` (async) does `settings = await asyncio.to_thread(pg.load_settings, project_id)` -> `seed = resolve_seed(settings)` -> `target_url = normalize_target_seed(seed)` at the TOP of the bootstrap, before any session is started. It then builds `state = RunDispatchState()` and `coro_for = build_run_dispatch(..., pod_builder=partial(_default_pod_builder, target_url=target_url))`. Every `TestSpecItem` whose `status == "specified"` later yields `run_pod_session(..., pod_builder=closure)` which calls `await pod_builder(spec, run_id, project_id, memory_store, spec_id, target_url=target_url)` -> `arun_pod(..., target_url=target_url)`. No path bypasses the closure. The first probe therefore is `curl http://<seed>/` (seeded domain), never `localhost:8080`.

**Singular `POST /hunting/pod` resume** (identity-based refactor 2026-08-25):
This endpoint NEVER fabricates a new pod dispatch. It resumes ONE stored/paused pod session by `session_id` (`hunting:<run_id>:pod:<config_id>:<spec_id>`) via `runtime.resume_session("hunting", session_id)`. The session's coroutine was already created by the whole-pipeline's `coro_for` and is parked at the hunting dispatch gate (`await gate`). The `target_url` is baked into its closure (`pod_builder` partial). Resuming just releases the gate - no new `target_url` derivation needed. A replayed resume is the runtime's safe no-op (at-most-once). There is no code path that fabricates a `specified` spec into `HunterMemoryStore.produced`; so there is no targetless fabrication path.

**Resumed-after-pause run** (module `pause`/`resume` or per-session `hold`/`resume`):
`POST /projects/{id}/modules/hunting/pause` sets the module state to `paused`; `runtime.schedule` then refuses admission with `ModuleAdmissionRefused` and the mover's `run_delivery_tick` leaves items in `produced` (at-least-once). Pods already dispatched are `gate`-blocked: `run_pod_session` does `async with gate: export = await _run()` where `gate` is the shared hunting dispatch gate (`HUNTING_DISPATCH_GATE_WIDTH=20`). A held session's next unit boundary at the gate waits. `resume` flips `running` and the gate unblocks; the same coroutine with the same `target_url` closure continues. A `hold_session`/`resume_session` per pod id works identically. No re-derivation, no guess.

**Rejected alternative:** Re-reading `target_seed` per pod tick: rejected because it would add a DB round-trip per tick and could cause a mid-run target flap if settings change.

**Edge case - settings change mid-run:** Snapshot at `start_hunting` means a `PUT /settings` that changes `target_seed` after the run started does NOT affect in-flight pods; the next whole-pipeline run picks it up. This matches recon's snapshot-at-launch and is deliberate - a live run's target is immutable.

---

## 5. FAIL-CLOSED invariant

**Invariant:** A project with no target (no seed, or a non-normalizable seed) must produce an INIT rejection (`technical-infeasibility` + `init_validation`), never a guessed host.

**Enforced at:**
1. **Normalization boundary** (`attack/hunting/target.py:normalize_target_seed`): `None`/empty/whitespace/`http://`/`*.example.com` -> `None`.
2. **Dispatch builder** (`attack/hunting/runtime.py:_default_pod_builder`): if `target_url is None`, it does NOT call `arun_pod`. It returns the envelope directly:
   ```python
   {
     "verdict": "unsuccessful",
     "evidence": {
       "terminal_reason": "technical-infeasibility",
       "init_validation": ["no target URL available: populate target_identity.url or inject the asset base URL into the pod"],
       "iterations": 0, "clean": False,
       "interpretations": ["target URL missing"],
     }
   }
   ```
   This is the same vocabulary `hunting_pod` uses, and it is persisted via the pod's deterministic terminal persistence (`graph.py:_persist_pod_export`) when a `PodMemoryStore` is bound. The surfer still records the export durably via `_record_durable_pod_export` keyed by `config_key`, so the idle hunter sees the failure.

3. **Pod internal gate** (defense in depth) (`attack/hunting/pod/graph.py: init` and `pod/pod.py:arun_pod`): if `target_url is None` and `spec.get("target_identity")` is not an `http://`/`https://` URL (the flat spec's string check), the graph's `init` returns `init_validation=["target URL missing: no injected target_url and spec target_identity is not a URL"]` and routes `init_router -> reject -> terminal` with `technical-infeasibility`, `iterations=1`, `clean=False`. This catches any direct `arun_pod(spec)` call that bypasses the builder.

**Rejected alternative:** Returning `unsuccessful`/`no-symptom-evidence` with `iterations=1` and a localhost probe: this is the bug. The pod would appear to have "tried" but with no discriminating evidence. The verdict derivation (`attack/hunting/hunting_agent.py:derive_verdict`) would map `no-symptom-evidence` + `clean=False` -> `insufficient-evidence`, but the retry loop would be wasted. Fail-closed is the correct signal for the hunting AGENT's verdict layer: `technical-infeasibility` + `init_validation` -> `underspecified-spec`, which the hunter can surface.

**Edge cases:**
- Empty seed in DB (project created but never PUT settings): `load_settings` returns `{}` or `{"recon": {}}` -> `resolve_seed` -> `None` -> normalize -> `None` -> INIT-reject for every pod, run completes with all pods `technical-infeasibility` rather than 7x `no-symptom-evidence` on `localhost:8080`. The `hunting_runs` row still lands `complete` (fail-open at run level), but the per-pod evidence is honest.
- Non-normalizable seed (`"http://"`): same INIT-reject, not a DNS probe that would be `clean=False` but with a different classification.
- Spec-side fallback: if a future hunter DOES embed `spec["target_identity"] = "https://example.com"` and `target_url is None`, the pod's internal gate treats that as present and does NOT reject - the spec-side path is preserved for hermetic tests that set it.
- `arun_pod` direct call with no `project_id` and no `target_url`: the builder is not used, so the pod's internal gate is the sole enforcer.

---

## 6. Settings-read timing

**Read point:** `start_hunting` is `async` and fire-and-forget (scheduled via `runtime.schedule("hunting", coro, name=...)` onto the hunting worker loop). The first `await` inside it is `settings = await asyncio.to_thread(pg.load_settings, project_id)` (blocking-sync-pg offload onto the shared executor, never the worker loop - #123 discipline). This is BEFORE opening the `hunting_runs` row's `running` write already happened (the API opened it synchronously via `create_hunting_run` before scheduling), but the row was opened without needing the seed. The seed read therefore does NOT block the HTTP POST's 201 - the row is already returned. The pod dispatch gate is not reached until after the seed read, so no pod can be dispatched before the seed is known.

**Absence handling:** `pg.load_settings` may raise (`psycopg.OperationalError`) or return `{}`. Both are fail-open at the run level: a raise is caught, logged, and `target_url` is set to `None`; an empty dict normalizes to `None`. The run does NOT crash - it proceeds to dispatch pods that all INIT-reject. This matches the recon pipeline's fail-open rings (per-item, per-pod, per-run).

**Settings change mid-run:** As in point 4, the seed is snapshotted once. A concurrent `PUT /settings` that changes `target_seed` after `start_hunting`'s read does NOT affect the live run's `target_url` closure. The next hunt run reads fresh. This is intentional: a live run's `target_url` is immutable, avoiding a mid-run target flap where some pods probe `old.com` and others `new.com`.

**Rejected alternative:** Reading `target_seed` per pod (`_default_pod_builder` doing its own `load_settings`): rejected because it would add N DB reads (one per spec) on the worker loop or need extra `to_thread` per pod, and would make the run's target non-deterministic if settings change mid-run.

**Edge case - PG down at read:** The offloaded `load_settings` raises -> `target_url = None` -> every pod INIT-rejects. The `hunting_runs` row (already `running`) later lands `complete` (quiesce with no dispatchable work left, because pods still run and produce INIT-reject exports that are durably recorded and move `produced->consumed`). No `failed` status is needed - the run is honest.

---

## 7. Exec-side resolution

**Division of responsibility:** The platform fix passes the URL (`http://soupmarket.shop/`); the kali exec environment's `/etc/hosts` alias (`192.33.91.87  soupmarket.shop` / `dj-viscon-workshop-1.vsos.ethz.ch`) is deployment's concern. The pod's `exec` tool (`polymerhus.attack.hunting.pod.tools.default_exec_fn` -> `recon.domain.pod.default_exec_fn` -> kali MCP `execute_command`) runs `curl -k -sS ... http://soupmarket.shop/...` on the kali host, which resolves the domain via the hosts file to the remote host's public IP. No code in `attack/hunting/` touches `/etc/hosts`; it just emits the correct Host-based curl.

**Verification that first probe hits seeded domain:** The production `pod_runner` system prompt (P0 feast validation) plus the injected `target_url` in the lap-opener `compose_runner_delta` tells the Runner the exact origin to probe. The synthetic `RunnerStep` default (`default_runner_step_fn`) is not used in production; the LLM's first `exec` call will be `curl -k -sS -X GET http://soupmarket.shop/` (or with the spec's `payload_vector_space.path` appended via `_probe_url`). The experiment log's first `raw_observations[0].request.command` must contain `soupmarket.shop` (or `moodique.com`, etc.), never `localhost:8080`/`127.0.0.1:8080`. The E2E verification reads `PodMemoryStore.read_experiment_log(spec_id, 0)` and asserts the command string does NOT contain `localhost` and DOES contain the seeded domain.

**Rejected alternative:** Making the pod synthesize `/etc/hosts` entries itself: rejected - that is the eval harness's network prep (see `environmental_caveats: hosts-file-alias` in `eval-targets.yaml`), not the pod's. The pod must be target-aware, the platform must be network-aware; conflating them would hide the real DNS/hosts topology.

**Edge case - self-signed TLS:** The pod's `curl` always uses `-k` (insecure), so `http` vs `https` difference is not fatal; the hosts alias works for both. The normalizer's default `http` is therefore safe - the probe will still reach the vhost, and a redirect to `https` would be observed as a 3xx in the trail (if follow-redirects is off, the pod records the 30x).

---

## 8. TEST STRATEGY

**How the fix is proven:**

**Unit - normalizer table cases:**
File `tests/attack/test_hunting_target.py` (new). Parametrized `test_normalize_target_seed_table` covers the exact input->output table from point 2, including bare, port-bearing, already-scheme'd, path-stripping, IPv4, whitespace, and failure `None` cases. Also `test_normalize_rejects_wildcard` and `test_normalize_rejects_empty`.

**Unit - threading (injected target reaches `arun_pod`):**
Two levels:
1. `tests/attack/test_hunting_runtime.py` addition: `test_start_hunting_threads_target_url_to_pod_builder` - fakes `pg.load_settings` to return `{"target_seed": "soupmarket.shop"}`, fakes `HuntStore`/`HunterMemoryStore`, injects a `pod_builder` recorder that captures `target_url` kwarg. Asserts the recorder was called with `"http://soupmarket.shop/"`.
2. `tests/attack/pod/test_graph.py` addition: `test_pod_init_rejects_when_target_missing` - calls `arun_pod(VALID_SPEC, target_url=None, exec_fn=...)` and asserts `terminal_reason == "technical-infeasibility"` and `init_validation` contains `"target URL"` and `calls == []` (C1: no tool call). And `test_pod_probes_seeded_domain_when_target_injected` - calls `arun_pod` with `target_url="http://soupmarket.shop/"` and a recording `exec_fn`, asserts the captured `command` contains `"soupmarket.shop"` and NOT `"localhost"`.

**E2E signal (dispatched pod's experiment-log first probe targets the seeded domain):**
Method: launch a hunting run with a candidate batch on a project whose seed is a bare domain (`soupmarket.shop`) via the vertical slice: `POST /projects/{id}/settings {recon:{target_seed:"soupmarket.shop"}}` then `POST /projects/{id}/hunting {candidates:[{unit_id:"Service:...", fault_class:"CWE-352"}]}` on a live dev stack (or via the hermetic `start_hunting` with a fake control that still exercises the real `build_run_dispatch` -> `run_pod_session` path). After quiesce, read `PodMemoryStore(project_id=...).read_experiment_log(spec_id, 0)` or the persisted `PodExport`'s `raw_observations`. Assert the first `command` is `curl ... http://soupmarket.shop/...` and evidence `terminal_reason` is not `no-symptom-evidence` with `iterations==1` on `localhost:8080`. Paste the probe command + output as evidence in the verification section. The negative signal is also valuable: `grep -r "localhost:8080" data/<project_id>/test-executor-pod/` must be empty.

**Rejected test strategy:** An integration test that boots a real kali and curls the live target for every case: rejected - it would be flaky and slow. The contract tier's `httpx.MockTransport` for `HuntingHttpPod` plus the pod's `ExecTool` recording gives the same guarantee deterministically. The live E2E is a single manual smoke, not the regression gate.

**Edge case for tests:** A test that changes `target_seed` mid-run and asserts pods switch target mid-run must NOT pass - the spec asserts snapshot immutability. A test that sets `target_seed` to an invalid value and asserts every pod's export is `technical-infeasibility` with `init_validation` proves the fail-closed path.

---

## End of grill

The minimal version this grill endorses is the dispatch-injection path (a) with a deterministic `normalize_target_seed` helper, `asyncio.to_thread(load_settings)` at `start_hunting` top, threading `target_url` through `build_run_dispatch` -> `_default_pod_builder` -> `arun_pod`, preserving `hunting_pod._target_url`'s OR semantics and adding the same OR check to `arun_pod`'s graph init, plus the normalizer table tests and the threading test. Spec-authoring (b) is deferred.

If the grill contradicts the known-good shape, the grill wins: the known-good shape omitted the defense-in-depth check inside `arun_pod`'s graph; this grill adds it, with reason recorded above (a direct `arun_pod` call must also fail-closed).

