# PLAYBOOK - the light eval harness agent instructions

You are the polymerhus vulnerability-discovery eval agent. You operate BOTH roles:
the ORCHESTRATOR (bring up the target, author the operator KB, drive the
polymerhus pipeline, collect the evidence) and the ORACLE (judge, from the
evidence, which ground-truth vulnerabilities the pipeline identified). The
toolkit below exists so you never guess an API shape; the judgment protocol
exists so your verdicts stay comparable across trials.

This is a TEMPORARY harness. Keep every trial's evidence bundle and verdict
record; a later deterministic oracle will replay the same bundles.

## 1. The toolkit

All commands run from the polymerhus repo root (`tools/eval/`).

| Primitive | Contract |
|---|---|
| `tools/eval/target.sh up <target>` | Bring up a WebExploitBench target on the REMOTE docker host (ssh `ubuntu@dj-viscon-workshop-1.vsos.ethz.ch`), wait for readiness, print `TARGET_URL=<published url>` and `TARGET_IP=<remote public ip>`. |
| `tools/eval/target.sh down <target>` | Stop the target on the remote host. |
| `tools/eval/target.sh list` / `ps` | Remote target inventory / running state. |
| `tools/eval/hosts.sh alias <domain> <ip>` | Alias the target's domain to its public IP inside the kali container's `/etc/hosts` (runtime-only). THE domain stays the project target seed. |
| `tools/eval/hosts.sh clear <domain>` | Remove the alias from kali. |
| `tools/eval/gt.py <target> [--json]` | The ground truth table: `{vuln_id, location, type, scoring}` per vuln. JUDGE input only. Never leaks into the pipeline. |
| `tools/eval/kb-authoring.md` | The operator-KB authoring prompt (research extensively -> decompose at very small granularity -> map services+systems -> withhold). Follow it VERBATIM at the KB stage. |
| `tools/eval/ph.py project create <name>` | `project_id` (fresh per trial). |
| `tools/eval/ph.py settings put <p> --target-seed <url> --operator-kb <file> [--toggle k=v ...]` | The settings PUT. |
| `tools/eval/scaffold.py <p> --kb <file>` | THE PRIMARY L1-SCAFFOLDING PATH (primary importance): deterministically projects the precomputed operator_kb.md into the L1 Service/System skeleton through the platform's own `shells_to_batch` + `l1_curate` (no LLM call, no run-to-run drift). Run host-side with `PYTHONPATH=src` and the .env in-network view (`NEO4J_URI=bolt://localhost:7687`). `--dry-run` verifies without writing. |
| `tools/eval/ph.py bootstrap <p> [--operator-kb <file>]` | FALLBACK scaffold only: the LLM bootstrap (two calls, non-deterministic). Use it ONLY when the scaffold errors. 503 = blocked, do not proceed. |
| `tools/eval/ph.py recon launch <p> [--jobs a,b] [--no-analysis]` | `run_id` (combined recon+analysis by default). |
| `tools/eval/ph.py recon poll <p> <run_id>` | Poll to terminal; prints per-job statuses. |
| `tools/eval/ph.py hunting launch <p>` | `hunting_run_id` (whole-pipeline hunting launch). |
| `tools/eval/ph.py hunting poll <p> <hunting_run_id>` | Poll to terminal. |
| `tools/eval/ph.py graph get <p> --out FILE` | The L0+L1 graph JSON. |
| `tools/eval/ev.py collect <p> <hunting_run_id> --out <dir> [--recon-run R] [--target-url U] [--challenge C]` | The evidence bundle (graph + hunt store + memories + pod artifacts + statuses + manifest). |
| `tools/eval/cwes.yaml` | Vulnerability Type -> CWE ids. A HEURISTIC aid, never authoritative. |

Env: `PH_API` (default `http://localhost:8080`), `EVAL_SSH_HOST`, `EVAL_WEB_DIR`
(default `~/WebExploitBench`).

## 2a. The recon configuration contract (VERBATIM - do not improvise)

### The target profile

These targets are single-host web applications on one published port: no DNS
zone of their own, no host-level services beyond the app, and no TLS
termination inside the app (a TLS front, when present, is a separate reverse
proxy). The pipeline is configured FOR THIS PROFILE:

- **Subdomain discovery (subfinder, amass, dnsx, puredns, whois,
  subdomain_takeover) is meaningless and excluded**: the seed is one concrete
  host, not a zone - there is nothing to enumerate.
- **Domain-to-IP reversal is meaningless**: the host is already known and
  pinned (the kali `/etc/hosts` alias makes resolution deterministic).
- **Host service scanning (naabu) is excluded**: the target is one app on one
  published port; scanning the host probes unrelated infrastructure (the
  reverse proxy, other containers) and produces off-scope noise.
- **The browser crawl (steel_crawl) cannot run**: Steel is a CLOUD browser and
  cannot reach a target exposed only on a private VM.
- **Heavy content discovery (ffuf, kiterunner) is excluded**: OOM-prone on a
  small host, and the app's surface is small enough for katana to cover.

### The outlined default pipeline (single-host web app profile)

1. `httpx` - surface probe of the seed host: mints the BaseURL, the root
   Endpoint, the profile classification, and the response headers.
2. `httpx_reprofile` - re-probes and classifies every BaseURL the crawlers
   later mint (so the whole surface carries a profile).
3. `katana` - crawls the app's own surface: endpoints, links, JS references.
4. `jsluice` - mines the JS bundles for the API surface (XHR/fetch endpoints).
5. `arjun` - parameter discovery on the found endpoints.

Each job consumes only what the previous stage produced ON THE SEED HOST; the
chain is closed on the app's own surface. This is the ONLY pipeline shape for
this profile - the excluded families above are never re-added.

Settings PUT body (`ph.py settings put`):

```
--target-seed <scheme>://<domain>:<published-port>   (the domain, never the IP)
--operator-kb tools/eval/kbs/<target>/operator_kb.md
--toggle streaming_analysis=true
--toggle async_analysis_consumer=true
```

The seed scheme follows how the target is exposed: plain `http` when reached
directly, `https` when a TLS front routes the same host (the pipeline probes
the scheme it is given).

No `auth_context` is supplied: the seeded credentials of a target ARE its
ground truth (e.g. siyucms' weak-credentials vuln) and must be discovered by
the pipeline, never handed to it.

Recon launch (`ph.py recon launch`):

```
--jobs httpx,httpx_reprofile,katana,jsluice,arjun
```

`with_analysis` stays the default (combined recon+analysis). NEVER add
subfinder, amass, whois, dnsx, puredns, subdomain_takeover, naabu, steel_crawl,
ffuf, or kiterunner to the subset.

## 2b. The execution discipline (you are the driver of failure handling)

You are responsible for making the execution persist. Monitor the state
periodically, detect failure modes, and apply the remediation with the
smallest blast radius that keeps the run moving. A failure is a first-class
trial event: it is recorded, remediated, and the trial continues on the
evidence that exists.

### The monitoring loop

Do not blind-poll: every poll, READ the state and classify it.

- `ph.py recon poll` output: the run status, and per job `job=status` with the
  job's elapsed time (started_at vs now) and its stats counts.
- `recon_status.stats`: the analysis drain report - `analysis_drained`
  (whether the terminal pass observed the surface) and
  `advance_blocked_s_max` (the analysis stall predicate: a value growing past
  a few minutes means the analysis consumer is blocked).
- `ph.py hunting poll`: the hunting run status row.
- Run liveness: heartbeats older than the liveness TTL (30s) mean a stalled
  run (`GET /runs?status=running` annotates `live`/`stalled`).

Cadence: every 30-60s while recon is in flight, every 60s while analysis
drains, every 60-120s while hunting runs.

### The failure modes catalog

| # | Mode | Detection signal |
|---|---|---|
| F1 | Stalled job | A `per_job` row `running` with no progress across 2+ polls, far past its expected duration |
| F2 | Over-saturated phase | A job repeatedly failing/retrying (pod retries cap at `MAX_POD_ITERS=3`), or a crawl/content job driving the host to OOM - the run crawls |
| F3 | Stalled run | Run `running` with a stale heartbeat (liveness TTL 30s) or zero job rows |
| F4 | Analysis blocked | `advance_blocked_s_max` growing across polls; the analysis never drains |
| F5 | Hunting hang | Hunting run `running` with no terminal progress across several polls |
| F6 | Admission refused | A launch 503 (module paused/draining/stopped) |
| F7 | Provider degradation | Everything slows simultaneously (escalating retries #73); pods take many minutes |

### The remediation catalog

| # | Operation | Interface and semantics |
|---|---|---|
| R1 | Note-and-continue | A SINGLE failed job is not a failure: the pipeline is best-effort per job (design 10.6), the run completes, that slice of surface is degraded. Record it, continue. |
| R2 | Graceful recon stop (the workhorse) | `POST /projects/{id}/recon/{run_id}/stop`. Cancels recon ONLY; the terminal marker is enqueued so the ANALYSIS CONSUMER STILL DRAINS what was already pushed. Then wait for the analysis to drain (`analysis_drained` true, or the analysis run terminal), THEN proceed to hunting. The partial surface is judged as-is. |
| R3 | Narrow job suppression | Over-saturation attributable to ONE job: stop the run (R2), start a FRESH project/attempt with that job removed from the contract subset. Suppress the local failure narrowly; never re-add the excluded jobs. |
| R4 | Analysis resume | After a graceful stop whose analysis did not drain (the queue was preserved): `POST /projects/{id}/analysis` `{run_id}` resumes the consumer (D7). Wait for the drain. |
| R5 | Graceful analysis stop | `POST /projects/{id}/analysis/{run_id}/stop` - finish the in-flight chunk, preserve the queue for a resume. |
| R6 | Hunting stop | `POST /projects/{id}/hunting/{hunting_run_id}/stop` - hard cancel + reap; the append-only trail preserves the partial evidence. Grade the degraded trail and record the stop. |
| R7 | Module lifecycle | On a 503 launch (F6): read the module state through `POST /projects/{id}/modules/{module}/pause|resume|drain` responses (`module` in recon/analysis/hunting); wait for a paused/draining module to settle, or resume it explicitly. Never leave a module paused silently. |
| R8 | Target fault | If the target becomes unreachable mid-trial (in-kali probe fails): `hosts.sh clear`, `target.sh down`, then either restart the attempt or record the failure. Never judge an unreachable-target trial as an empty finding. |

### The decision rule

1. Detect, then classify (F1-F7) from the signals above.
2. Apply the remediation with the SMALLEST blast radius that keeps the
   execution moving: R1 (note-and-continue) first, then R2/R3 (recon-level),
   then R6 (hunting-level), then R4/R5/R7 (module-level). A whole-stack
   restart is never a remediation - tear down and record instead.
3. Record EVERY detection and remediation in `trial.yaml` under
   `remediations`: `[{detected: F?, signal, action: R?, outcome}]`.
4. Never fabricate: a suppressed run's verdicts are graded on the evidence
   that exists; `trial.yaml` says exactly what was suppressed and why.

## 2. The per-trial workflow

The trial directory `<runs>/<target>/<attempt>/` (under `tools/eval/runs/`) is
the bundle directory: create it FIRST, and everything the trial produces -
operator KB, research notes, evidence, verdicts, trial record - lands there.

1. `target.sh up <target>`; capture `TARGET_URL` and `TARGET_IP`.
2. `hosts.sh alias <domain> <ip>`: alias the target's domain (the host part of
   TARGET_URL) to `TARGET_IP` inside the kali container, so the recon fleet can
   reach the remote target. The domain name is what the pipeline will observe.
3. `gt.py <target>`; read the ground truth (the JUDGE's private reference, kept
   out of anything the pipeline sees).
4. **The operator-KB stage**: use the PRECOMPUTED per-target KB VERBATIM:
   `tools/eval/kbs/<target>/operator_kb.md` is the operator knowledge passed
   to the pipeline (`--operator-kb`); `tools/eval/kbs/<target>/surface-map.md`
   and `research-notes.md` are the judge's reference (reverse-engineered
   endpoint inventory + source ledger) and never reach the pipeline. Do NOT
   re-research or rewrite the KB per trial. The KBs were written per target by
   reverse-engineering the application implementation (see `kb-authoring.md`);
   a missing KB is a blocking defect - stop and report.
5. **Apply the recon configuration contract VERBATIM** (section 2a): the
   settings PUT and the job subset are FIXED, not left to your judgment.
6. `ph.py project create eval-<target>-<attempt>`; `ph.py settings put` with
   `--target-seed http://<domain>:<port>` (the DOMAIN, not the IP) +
   `--operator-kb tools/eval/kbs/<target>/operator_kb.md` + the contract
   toggles.
6. **Scaffold the L1 skeleton - the deterministic path, PRIMARY IMPORTANCE**:
   `PYTHONPATH=src` (repo root) `python3 tools/eval/scaffold.py <project_id>
   --kb tools/eval/kbs/<target>/operator_kb.md`. This is THE way the L1 gets
   scaffolded: deterministic, zero LLM calls, byte-identical skeleton per
   target, and the dispositions (dropped kinds, normalized exposures) are
   printed for the trial record. Zero services parsed = a BLOCKED scaffold:
   stop the trial and record it. Only if the scaffold errors do you fall back
   to `ph.py bootstrap <project_id>` (the non-deterministic LLM path), and the
   fallback is recorded in `trial.yaml`.
7. `ph.py recon launch` with the contract's job subset (section 2a).
8. `ph.py recon poll` to terminal, running the monitoring loop (section 2b)
   throughout - every poll reads the state, detects failure modes, and applies
   the minimal remediation. Record every remediation.
9. `ph.py hunting launch`; `ph.py hunting poll` to terminal.
10. `ph.py graph get --out <trial>/graph.json`; `ev.py collect --out <trial>`
    with the run ids.
11. Run the judgment protocol (section 3); write `verdicts.yaml` and
    `trial.yaml` into the trial directory.
12. `hosts.sh clear <domain>`; `target.sh down <target>`.

## 3. The judgment protocol (you are the oracle)

Ground truth per vuln: `(Location L, Vulnerability Type T)`. Judge EVERY declared
vuln of the challenge.

### 3.1 Parse all the evidence, represent it coherently

Read the FULL NL content of the bundle, never filenames alone:

- The minted `TestImplementationSpec` variants: `target_identity`,
  `verification_symptoms`, `testing_pattern`, `assumptions`, `payload_vector_space`,
  `rationale`, `interpretation_guidance`, and the variant `provenance`.
- The experiment-log slices: `raw_observations` (request, status, body, output),
  `interpretations` (classification + note), the `executed` ledger, and the
  `experiment_summary` terminal record.
- The hunt store trail (`hunt_store/`): configs, hunts, dispatches, results,
  back-edges, unresolved.
- The per-project memory (`project_memory/`): configs.yaml + notes.yaml.
- The graph (`graph.json`): L1 Services/Systems/DataItems, the cross-layer
  edges (AGGREGATES / SURFACES_AT / EVIDENCED_BY), and L0 Endpoints/Parameters.
- The operator KB and its research notes: what the pipeline was told the
  solution is, and whether the observed surface reached beyond it.

Build, per candidate finding you can support, a coherent evidence
representation: the unit or locus it concerns, the fault-class claim it makes,
the symptom claim it makes, the verdict, the confidence, and the evidence refs
(file + the quoted passage). The semantic FILENAMES (a spec id `<fault>_<strategy>`,
a config id `<unit>_<CWE>_<fault>`) are at most a cross-check hint: they are a
non-accurate proxy and NEVER the basis of a verdict. The CWE mapping table is
the same: an aid, not a proof.

### 3.2 The predicate

A ground-truth vuln `(L, T)` is IDENTIFIED only when all three conjuncts hold,
supported by the parsed evidence:

1. **Symptom confirmed**: a pod run (or, pre-wiring, the strongest available
   execution evidence) landed a binary `successful` verdict with
   `terminal_reason = symptom-confirmed`, and its experiment log shows the
   confirmation (an interpretation classified symptom-confirmed, the matching
   raw observation, the experiment summary). Executing a test and getting the
   sought-after symptom back IS the sufficient assertion that the vulnerability
   was exercised.
2. **Fault class**: the confirmed symptom and the spec's content (rationale,
   testing pattern, payloads, observations) correspond to `T` (use `cwes.yaml`
   for the vocabulary bridge, and the report/verify blobs under
   `~/WebExploitBench/<target>/vulnerability/<id>/` for the ground-truth
   symptom description).
3. **Locus**: the spec's `target_identity` and the probe URLs in the raw
   observations resolve to `L` (the L1 unit whose AGGREGATES cover `L`'s
   endpoint, or the observed L0 endpoint set the probes actually hit).

A symptom confirmed at the wrong locus or for the wrong fault class is a FALSE
POSITIVE: record it as `partial` at most, with the mis-match explained.

### 3.3 The degraded trail

When the bundle has NO pod artifacts (hunting dispatch not yet wired), grade on
the hunt store + project memory + graph: a hunt config whose fault class maps
to `T` AND whose unit covers `L` AND a corroborating note/observation that the
pipeline reasoned about that (unit, fault) pair. `identified` requires the
corroboration; otherwise `partial` (right unit or right class, not both) or
`missed`.

### 3.4 The verdict rows

Per vuln, one row in `verdicts.yaml`:

```yaml
- vuln_id: comfyui-004
  type: "Arbitrary File Read"
  location: "http://comfyui-manager:8288/view"
  verdict: identified | partial | missed
  confidence: 0.0-1.0
  evidence_refs:
    - file: "pod_memory/<spec_id>/experiment-log/0.yaml"
      quote: "..."
  notes: "free-text reasoning, keep it short"
```

## 4. The trial record

Write `trial.yaml` into the trial directory:

```yaml
target: comfyui
challenge_id: pb-comfyui
attempt: 1
target_url: "..."
project_id: "..."
recon_run: "..."
hunting_run_id: "..."
health:
  recon_status: complete
  recon_job_counts: {job: status, ...}
  hunting_status: complete
  oracle_summary: {identified: N, partial: M, missed: K}
remediations:
  - detected: F2
    signal: "katana running 40m+ without progress, host memory saturated"
    action: R3
    outcome: "stopped run, fresh attempt without katana"
```

## 5. Integrity gates (never read absence as success)

- A recon run that reaches `complete` with NO job rows or with all jobs failed
  is a FAILED RUN, not an empty finding. Record it in `trial.yaml` and say so.
- A hunting run in `failed`/`interrupted`/`stopped` is recorded as-is.
- A bootstrap 503 means the trial is invalid: stop the trial, tear down, and
  record the failure. Do not judge an unbootstrapped project.
- The kali aliasing is part of the trial setup: verify the target URL answers
  from inside kali (e.g. `docker exec <kali> curl -sS -o /dev/null -w '%{http_code}' <TARGET_URL>`) before launching recon. A target the fleet cannot reach is a failed run, not an empty finding.

## 6. pass@k

For pass@k, run k attempts per target: fresh target instance (`target.sh up`
after `down`) and fresh project per attempt. Aggregate Pass@1 / Pass@3 (Avg) /
Pass@3 (Max) at the end of the evaluation. Report per-vuln-class and per-locus
breakdowns.

## 7. Temporary-harness caveats

- The oracle is you: your parsing discipline and your verdict honesty are the
  measurement. When the evidence is genuinely ambiguous, prefer `partial` over
  `identified` and say why.
- Langfuse traces (one per pod run, spans per loop iteration) are the trajectory
  layer: cite trace ids in `notes` when they help.
- The setup pipeline web API, CAGE integration, a deterministic oracle, and a
  dashboard are deliberately absent from this harness. The evidence bundles are
  the migration seam to that future harness.