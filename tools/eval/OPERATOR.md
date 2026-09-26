# OPERATOR.md - using the light eval harness

A brief operator guide: what to tell the eval agent, and how to watch it work.

## 1. Launching an eval run

Start an agent (opencode, or any agent with bash + web-search access) with this
prompt, replacing the two knobs:

```
You are the polymerhus vulnerability-discovery eval agent.

Read /Users/diekgbbtt/polymerhus/tools/eval/PLAYBOOK.md and follow it
VERBATIM. The toolkit lives in /Users/diekgbbtt/polymerhus/tools/eval/.

Evaluate the WebExploitBench target <TARGET> with pass@k=<K>:
- run the full per-trial workflow from the playbook section 2 (target up,
  kali aliasing, ground truth, the precomputed operator KB per target, the
  recon configuration contract in section 2a VERBATIM, project + settings,
  the deterministic L1 scaffold via scaffold.py as PRIMARY - the LLM
  bootstrap only as fallback, recon + hunting via ph.py, evidence bundle via
  ev.py, the judgment protocol, verdicts) and apply the execution discipline
  in section 2b - monitor the state, detect failure modes, remediate with the
  smallest blast radius (e.g. a stalled recon job: stop recon gracefully so
  analysis still drains, then continue to hunting), and record every
  remediation in trial.yaml
- tear down the target after every trial
- report at the end: Pass@1 / Pass@3 (Avg) / Pass@3 (Max), the per-vuln-class
  and per-locus breakdowns, and the trial.yaml health rows

Env if the defaults do not hold: PH_API, EVAL_SSH_HOST, EVAL_WEB_DIR.
```

Knobs: `<TARGET>` in `comfyui, jetlinks, prestashop, siyucms, white-jotter`;
`<K>` is the attempt count (start with 1). For a targeted job subset, tell the
agent, e.g. "skip the heavy browser/brute jobs (steel_crawl/ffuf/kiterunner)".

Prerequisites: the polymerhus stack up (kali + agent API on `localhost:8000`),
ssh access to the remote docker host, and the bundled targets reachable there.

## 2. Observation interfaces

### The trial directories (the primary record)

`tools/eval/runs/<target>/<attempt>/` - one dir per trial, everything in it:

| File | What it tells you |
|---|---|
| `verdicts.yaml` | The oracle's per-vuln rows: `identified / partial / missed`, confidence, evidence refs with quoted passages |
| `trial.yaml` | Run metadata + the integrity gates (recon status + job counts, hunting status, oracle summary) + the `remediations` log (every failure detected, the minimal-impact action taken, and its outcome) |
| `manifest.json` | What `ev.py` collected and what was absent (per-store `present` flags, statuses, KB files) |
| `operator_kb.md` / `research-notes.md` | What the pipeline was told the deployed application is (per-target, precomputed in `tools/eval/kbs/<target>/`), and the reverse-engineering source ledger |
| `surface-map.md` (in `tools/eval/kbs/<target>/`) | The reverse-engineered endpoint inventory the KB was derived from - judge's reference only, never piped |
| `graph.json` | The L0+L1 graph the pipeline built |
| `hunt_store/`, `project_memory/`, `pod_memory/`, `wiring_memory/` | The raw evidence the oracle judged on |

### Live pipeline status

- `tools/eval/ph.py recon poll <p> <run_id>` / `hunting poll <p> <hunting_run_id>` -
  the same polling the agent uses; watch a run in flight.
- `GET /projects/{id}/recon/{run_id}` shows the per-job breakdown (the liveness
  gate: `complete` with no job output = failed run, not an empty finding).

### The hunting trail on disk

`src/polymerhus/attack/hunting/data/hunts/<hunting_run_id>/*.md` - the
append-only orchestration trail (configs, dispatches, results, back-edges);
`.../hunts/projects/<project_id>/` - the per-project research memory.

### Langfuse (the trajectory layer)

Configured via `LANGFUSE_*` in `.env` (the stack traces by default). One trace
per agent session, spans per loop iteration. Session ids are semantic:
`hunting:<run_id>:orchestrator`, `hunting:<run_id>:hunt:<config_id>`,
`hunting:<run_id>:pod:<config_id>:<spec_id>` - searchable when a verdict needs
a closer look.

### The environment state

- `tools/eval/target.sh ps` - which targets are up on the remote host (and
  their published URLs).
- `tools/eval/hosts.sh show` - the aliases currently injected into the kali
  container's `/etc/hosts`.
- `target.sh down <target>` / `hosts.sh clear <domain>` - the teardown verbs,
  also part of the agent's workflow.

## 3. Reading a verdict honestly

- `identified` requires all three conjuncts (symptom confirmed + fault class +
  locus) with quoted evidence refs. A `partial` with a matching quote is a
  near-miss; a bare `identified` with no refs is a judgement to distrust.
- The integrity rows and the `remediations` log in `trial.yaml` decide whether
  absence means anything: a trial with a dead recon run says nothing about the
  pipeline; a suppressed job explains a degraded slice of the surface.
- Cross-trial variance is the norm (the benchmark's own runs vary run to run);
  trust pass@3 over pass@1.