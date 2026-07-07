> **SUPERSEDED.** Retained for historical trace only.
> The authoritative doc is `recon-pipeline-design.md` §9, which folds in this document's L1/L2/L3 data contracts and core-function signatures as an explicit "designed, not yet implemented" section, verified against the live codebase (zero occurrences of any type/function named below).
> The operator-validation items (V1-V7, §9 of this document) remain open and are preserved by reference.

# Context & Memory - End to End

*Companion and build-facing successor to `context-scaffolding-three-levels.md` (the L1/L2/L3 model), `agent-context-architecture.md` (the four memory tiers), and `recon-pipeline-forward-decisions.md` (D2, the re-entrant targeted-recon seam).*

This document traces **every** context/memory component the three-level model introduces - end to end - so it can be sliced directly into SDD tasks.
For each component it states: **Source** (which node/agent/tool produces the content), **Owner** (which store/tier holds it authoritatively and who owns writes), **Consumer** (which agent reads it, and when in the control flow), **How provided** (the exact mechanism and how it stays token-bounded), the concrete **Data contracts**, and the **Core functions** implementation will focus on.
It closes with the full control-flow trace, the fail-open stop condition + request cap, a core-functions index, and the decisions still needing operator validation.

> **Merge dependency.** `context-scaffolding-three-levels.md` and `agent-context-architecture.md` are canonical on the sibling branches `feat/recon-pipeline` / `worktree-agent-*`, not on `feat/platform-stack`.
> This doc is authored on `feat/platform-stack` and references them; when the branches merge, this doc and the resolved `context-scaffolding-three-levels.md` in this worktree supersede the open-grey-point versions.
> No code in `agent/recon/` is modified by this stream - all code shapes below are **proposed contracts** for the orchestration stream to implement.

The operator's answers A1-A5 (2026-07-06/07) are the authority for every decision below.
They are summarised at the head of `context-scaffolding-three-levels.md`.

---

## 1. What is new, in one paragraph

Three LLM decision points each get a purpose-built context scaffold, riding on the existing four-tier memory model with **one new store**:

- **L1** (per-job orchestrator) reads a **new sparse Postgres control-plane table, `recon_signals`**, written by the pod triager, so a later phase's job-agent avoids repeating operational failures (WAF/rate-limit/auth-wall) seen earlier.
- **L2** (pod triager) reads the **Observations already on the target's anchor** (the existing `asset_context` slice, Neo4j) and emits a **minimal LLM coverage verdict**; a gap becomes a `coverage_gap` Observation.
- **L3** (root pipeline) runs a **new terminal synthesis + finding-triggered extension step** that aggregates Observations + coverage gaps + signals, plans capped targeted probes via deterministic rules + LLM ranking, and dispatches them through the **D2 re-entrant interface** with a **fail-open** stop.

Two source substrates, three consumers, one funnel (`L1 signals + L2 gaps -> L3 -> D2`), exactly as `context-scaffolding-three-levels.md` §5 states.

---

## 2. The memory tiers this rides on (recap + the one addition)

From `agent-context-architecture.md` §1, unchanged except for the new `recon_signals` table, which sits in the **Postgres control plane** beside `recon_runs` / `recon_jobs`.

| Tier | Substrate | Authority | Writer(s) | New for this design? |
|---|---|---|---|---|
| Global domain memory | Neo4j (Layer-0 graph + `Observation`) | Authoritative attack surface + findings | curator (sole graph writer) | No - L2/L3 read it; L2 adds a `coverage_gap` Observation *macro_kind*, no schema change |
| Global control memory | Postgres `projects`/`settings`/`recon_runs`/`recon_jobs` **+ `recon_signals`** | Authoritative config + run/job progress + **operational signals** | REST routes, pipeline registry calls | **Yes - `recon_signals` is the shared pod memory (L1)** |
| Per-job memory | `JobState` (LangGraph) | Transient | job-agent nodes | Extended: new `job_context` field carries the L1 digest |
| Per-pod memory | `PodState` (LangGraph) | Transient | pod nodes | Extended: `PodExport` carries emitted signals + coverage up to the pipeline |

**Why `recon_signals` is control-plane, not domain memory.**
A WAF block or rate-limit answers *"how did probing go against host H"* - the registry's remit - not *"what did we find"* (Neo4j).
It is explicitly **not** an `Observation` (Observations are security findings on broad anchors; a 429 is neither).
This preserves the single-graph-writer invariant: the curator remains the only Neo4j writer; `recon_signals` is written on the control-plane path.

---

## 3. L1 - the shared pod memory (`recon_signals`)

**The load-bearing new component.**
A sparse, per-run, host-keyed record of operational limitations, written by the triager of an earlier phase and read by the job-agent of a later phase.

### 3.1 Source

The **pod triager** (`pod.default_triage_fn`, already an LLM per pod).
While judging a completed tool run it recognises operational failure/limitation modes and emits **`PodSignal`** records alongside its Observations.
Per A1 this replaces the rejected "new gate-level detector": the triager is the classifier, at zero marginal LLM cost (it already runs).

Detectable kinds (the triager prompt/skill enumerates them):
`waf` (403 / block-page fingerprint on a 200), `rate_limit` (429 / throttling), `auth_wall` (401/403 behind a login), `tech_quirk` (e.g. "Cloudflare-fronted", "rejects non-browser UA"), `tool_unavailable` (binary missing / gap-fill failed), `timeout`.

### 3.2 Owner

**Postgres control plane, table `recon_signals`.**
Writes are owned by the **pipeline** (symmetric to it being the sole registry writer): the triager *emits* signals into `PodState` -> `PodExport`; the pipeline *persists* them from `pod_exports` after each job returns, via `write_pod_signals`.
This keeps the pod free of any Postgres dependency (it stays graph-stateless and now also control-plane-stateless) and keeps a single control-plane writer.

> This writer placement is a **validation item** (§9-V2): A1 says the triager "documents it", which could instead mean the triager writes to Postgres directly.
> Recommended: pipeline flush, for writer-discipline symmetry.

### 3.3 Consumer

The **job-agent preprocess** of a **later phase's** job, running the now-enabled `job_orchestrator` LLM role (A4).
It reads a **bounded digest** of the signals for the hosts its `input_assets` belong to, and uses it to shape the pod set (skip / deprioritise / dedup walled hosts under `MAX_PODS`).
The phase barrier (`asyncio.gather` per phase) guarantees the earlier phase's signals are persisted before the later phase resolves its inputs - the flow is a forward DAG, never circular (`context-scaffolding-three-levels.md` §6.1).
Phase 0 reads nothing (cold start).

### 3.4 How provided (and kept bounded)

Built in the **pipeline**, at the global->per-job bridge (`run_pipeline`, just before seeding each phase>0 job's `JobState`) - the same site that already reads settings + produced assets.
`build_job_context` reads `recon_signals` filtered to this job's hosts, caps to the top-k most recent/severe per host, and renders `kind + host + one-line evidence` (no raw stdout).
The digest is threaded into the job via a new `JobState.job_context: str` field.
Hard char cap mirrors `CONTEXT_MAX_CHARS`.
Sparsity at the source (dedup key, §3.5) keeps the read small.

### 3.5 Data contracts

```python
# agent/recon/types.py  (proposed additions)

from typing import Literal
from pydantic import BaseModel, Field

SignalKind = Literal[
    "waf", "rate_limit", "auth_wall", "tech_quirk", "tool_unavailable", "timeout",
]

class PodSignal(BaseModel):
    """One operational limitation observed against a host during a pod run.
    Emitted by the triager; persisted to recon_signals by the pipeline."""
    host: str                       # target/host key, e.g. "app.example.com"
    kind: SignalKind
    evidence: str                   # one line, no raw stdout (e.g. "403 + 'Attention Required' block page")
    severity: Literal["blocking", "partial", "info"] = "info"
    source_tool: str                # the tool that hit it (job.tool)
    phase: int | None = None
    # run_id / source_pod(session_id) are attached by the pipeline at persist time.
```

```python
# PodExport gains two fields (agent/recon/types.py) so signals/coverage ride up to the pipeline:
class PodExport(BaseModel):
    # ...existing fields...
    signals: list[PodSignal] = Field(default_factory=list)   # NEW (L1)
    coverage: "CoverageVerdict | None" = None                # NEW (L2, §4.5)
```

```sql
-- db/postgres/init.sql  (proposed addition, beside recon_jobs)
CREATE TABLE IF NOT EXISTS recon_signals (
    id           BIGSERIAL PRIMARY KEY,
    run_id       TEXT NOT NULL,
    host         TEXT NOT NULL,
    kind         TEXT NOT NULL,            -- waf | rate_limit | auth_wall | tech_quirk | tool_unavailable | timeout
    evidence     TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'info',
    source_tool  TEXT NOT NULL,
    source_pod   TEXT,                     -- session_id
    phase        INT,
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Sparse: one row per (run, host, kind, tool); a re-hit refreshes evidence/observed_at.
    CONSTRAINT recon_signals_dedup UNIQUE (run_id, host, kind, source_tool)
);
CREATE INDEX IF NOT EXISTS recon_signals_run_host ON recon_signals (run_id, host);
```

The `UNIQUE (run_id, host, kind, source_tool)` + `ON CONFLICT DO UPDATE` is what makes the memory **sparse**: repeated hits collapse to one refreshed row, so the digest never balloons.

**The L1 digest handed to the job-agent** is just `JobState.job_context: str`, a rendered block, e.g.:

```
Known limitations from earlier phases:
- app.example.com: waf (403 block-page via httpx), auth_wall (login redirect via katana)
- api.example.com: rate_limit (429 via ffuf)
```

### 3.6 Core functions

```python
# agent/app/clients/pg.py  (control-plane helpers, mirror the existing registry pattern)

def write_pod_signals(run_id: str, source_pod: str, signals: list[PodSignal]) -> None:
    """Upsert emitted PodSignals into recon_signals (ON CONFLICT on the dedup
    key refreshes evidence/severity/observed_at). Called by the pipeline from
    each job's pod_exports. No-op on empty list."""

def read_pod_signals(run_id: str, hosts: list[str]) -> list[PodSignal]:
    """SELECT signals for run_id whose host is in `hosts`, newest first.
    The one read L1 depends on; returns [] for phase 0 / unknown hosts."""
```

```python
# agent/recon/context.py  (new module; also home to build_asset_context / L2, §4.6)

def host_of(asset: dict) -> str | None:
    """Extract the host key from an asset identity (name/domain/url host)."""

def build_job_context(run_id: str, input_assets: list[dict], *, registry) -> str:
    """L1 digest: read_pod_signals for the hosts of `input_assets`, cap top-k
    per host by recency/severity, render to <= CONTEXT_MAX_CHARS. '' when no
    signals (phase 0 or clean hosts). Deterministic; the intelligence is in the
    job-agent LLM that consumes it, not here."""
```

```python
# agent/recon/job_agent.py  (enable the job_orchestrator LLM seam - A4)

def llm_preprocess_fn(
    input_assets: list[dict], job: JobSpec, extra: dict,
    asset_context: str, job_context: str,
) -> list[dict]:
    """The enabled job_orchestrator path. Given the L1 digest (`job_context`),
    the LLM selects/prioritises/dedups which assets get pods under MAX_PODS -
    e.g. skip a host earlier phases found hard-walled. Falls back to
    default_preprocess_fn (deterministic 1:1) when job_context is '' (§9-V1).
    Command templates are NOT touched - only the pod SET and its ordering."""
```

Note the `preprocess_fn` signature gains `job_context` (or `job_context` rides in `extra`); this is a job-agent contract change (§9-V4).

---

## 4. L2 - the grounded completeness context

**A refocus of the already-designed `asset_context` slice, plus a minimal LLM coverage verdict.**

### 4.1 Source

Two inputs, both already available to the triager:

1. The **Observations already recorded on the target's legal broad anchor** - the surviving core of `agent-context-architecture.md` §4, built by `build_asset_context` (Neo4j read).
2. This run's freshly **parsed `assets`** in `PodState` (what the tool just found).

### 4.2 Owner

The completeness *context* is **derived, never stored** - rebuilt per pod from Neo4j each run (`agent-context-architecture.md` §5, "the per-asset graph slice").
The *verdict output*, when it is a gap, is owned by **Neo4j** as a `coverage_gap` Observation (curator-written, like every Observation).
No new store.

### 4.3 Consumer

The **pod triager** itself (it both produces the context's use and consumes it to judge), and downstream **L3** (which reads the `coverage_gap` Observations during synthesis).

### 4.4 How provided (and kept bounded)

`build_asset_context` runs once per pod_input in `job_agent.preprocess`, snapshots the anchor + its Observations (`macro_kind` + `severity` only, no evidence text) into `pod_input.asset_context`, carried to the triager via `PodState`.
Budget: `CONTEXT_MAX_CHARS = 1200`, priority-ordered so the anchor line survives truncation.
The triager's structured-output schema is widened to return a `CoverageVerdict` alongside its Observations - **minimal** per A2: free LLM judgement grounded only by the anchor-Observations slice, no structural/checklist coverage model yet.

### 4.5 Data contracts

```python
# agent/recon/types.py  (proposed)
class CoverageVerdict(BaseModel):
    status: Literal["adequate", "gap"] = "adequate"
    gap_kinds: list[str] = Field(default_factory=list)  # e.g. ["params_unfuzzed", "auth_surface_unprobed"]
    note: str = ""                                       # one line, LLM rationale
    anchor: dict = Field(default_factory=dict)           # the legal broad anchor {type, identity}
```

```python
# The triager LLM's widened structured output (agent/recon/pod.py):
class _TriageResult(BaseModel):
    observations: list[Observation] = Field(default_factory=list)
    signals: list[PodSignal] = Field(default_factory=list)              # L1
    coverage: CoverageVerdict = Field(default_factory=CoverageVerdict)  # L2
```

The `coverage_gap` Observation is a normal `Observation` with `macro_kind="coverage_gap"`, `severity="info"`, `evidence=note`, anchored on the legal broad anchor - so it needs **no** graph-schema change and rides the existing curator path.
A converter mirrors `findings.finding_to_observation`.

### 4.6 Core functions

```python
# agent/recon/context.py
CONTEXT_MAX_CHARS = 1200  # add to agent/recon/config.py

def build_asset_context(input_asset: dict, job: JobSpec, project_id: str, *, driver=None) -> str:
    """One bounded Cypher read: asset identity + legal broad anchor +
    Observations on that anchor + 1-hop neighbour counts, rendered to
    <= CONTEXT_MAX_CHARS, priority-ordered. Deterministic; cold-graph safe
    (returns just the identity line in phase 0). This IS the L2 slice; it is
    also the fix for the anchor-allowlist bug (hands the triager a legal
    anchor). Unchanged from agent-context-architecture.md §4.2."""

def build_triager_context(input_asset: dict, job: JobSpec, project_id: str, *, driver=None) -> str:
    """Thin alias/wrapper over build_asset_context naming the L2 role at the
    triager call site; may narrow to the anchor + Observations sub-slice."""
```

```python
# agent/recon/findings.py
def coverage_to_observation(verdict: CoverageVerdict, *, source_job: str, source_tool: str) -> Observation | None:
    """Turn a CoverageVerdict(status='gap') into a coverage_gap Observation on
    verdict.anchor (allowlisted broad anchor). Returns None for 'adequate' or a
    non-allowlisted/absent anchor (logged), mirroring finding_to_observation."""
```

The triager node (`pod.build_pod_graph`) is threaded `asset_context` and emits `observations + signals + coverage`; the `coverage_gap` Observation is appended to `observations` before curation.
`triage_fn`'s signature widens to `triage_fn(exec_result, assets, job, asset_context) -> _TriageResult` (§9-V4).

---

## 5. L3 - macro synthesis + finding-triggered extension engine

**A new terminal reasoning step at the root, and the first in-tree caller of the D2 re-entrant interface.**

### 5.1 Source

Three tiers converge (`context-scaffolding-three-levels.md` §4):

1. **Neo4j**: the whole run's Observations (incl. the L2 `coverage_gap` ones).
2. **Postgres `recon_signals`**: the L1 operational signals (a walled area is a "go deep differently" cue).
3. The **phase plan** (for what the core DAG already covered).

### 5.2 Owner

- The **macro digest** is transient (built at run end, not stored) - LangGraph/root-local.
- The **extension requests** are transient; their **results** (assets/observations from targeted probes) are owned by Neo4j (curator-merged, exactly like core-DAG pods).
- Each targeted probe's control-plane status is a `recon_jobs` row (`job="ext:<tool>:<component>"`), so the operator sees extensions in `GET /recon/{run_id}`.

### 5.3 Consumer

The **root pipeline** (`run_pipeline`), in a new terminal `run_extension_phase` step after the last phase barrier and before `set_run_status(..., "complete")`.
This introduces the pipeline's first reasoning step (A5/Q5-c).

### 5.4 How provided (and kept bounded)

Synthesis, not enumeration: `synthesize_macro_observations` returns counts by type/severity, top-k anchors by severity, the coverage gaps, and the L1 signal summary - never the full Observation list.
`plan_finding_triggered_extensions` generates candidates **deterministically** from findings (a rule registry), then an **LLM ranks/prunes to a hard `EXTENSION_REQUEST_CAP`**.
The LLM cannot invent scans - only rank pre-validated `{component, tool, template_set}` candidates.

### 5.5 Data contracts

```python
# agent/recon/synthesis.py  (new module)

class MacroDigest(BaseModel):
    """Bounded synthesis over the whole run - the L3 macro picture."""
    run_id: str
    project_id: str
    obs_counts: dict[str, int]                 # macro_kind -> count
    severity_counts: dict[str, int]            # severity -> count
    top_anchors: list[dict]                    # [{anchor:{type,identity}, severity, macro_kind}], top-k
    coverage_gaps: list[dict]                  # [{anchor, gap_kinds, note}] from L2
    signals: list[PodSignal]                   # L1 operational summary
    endpoint_stats: dict = Field(default_factory=dict)  # e.g. {"endpoints":40,"params":12,"fuzzed":0}

class ExtensionCandidate(BaseModel):
    """A deterministically-generated probe candidate (pre-LLM-ranking)."""
    trigger: str                               # rule id, e.g. "graphql_introspection_enabled"
    component: dict                            # graph component to probe {type, identity}
    tool: str                                  # e.g. "nuclei"
    template_set: list[str]                    # caller-supplied templates/tags (D2 stub)
    rationale: str

class ExtensionRequest(BaseModel):
    """What L3 hands to the D2 re-entrant interface (post-rank, capped)."""
    run_id: str
    component: dict
    tool: str
    template_set: list[str]
    origin: Literal["l3_synthesis", "analyser_probe"] = "l3_synthesis"  # seam for the future analyser (A2)
```

**The finding-trigger rule registry** (deterministic candidate generation):

```python
# agent/recon/synthesis.py
class ExtensionRule(BaseModel):
    id: str
    matches: Callable[[MacroDigest], list[ExtensionCandidate]]

EXTENSION_RULES: list[ExtensionRule] = [
    # GraphQL introspection observed -> nuclei GraphQL tag set on that BaseURL
    # JWT observed              -> jwt-decode tool on the emitting endpoint's anchor
    # Admin surface unauth'd    -> targeted auth/misconfig template set
    # ... one rule per finding->probe mapping; extended as the fleet grows.
]
```

### 5.6 Core functions

```python
# agent/recon/synthesis.py
def synthesize_macro_observations(run_id: str, project_id: str, *, driver=None, registry=None) -> MacroDigest:
    """Aggregate the run's Observations (+ coverage_gap), recon_signals, and
    endpoint counts into a bounded MacroDigest. Retrieval + counting, no LLM."""

def plan_finding_triggered_extensions(macro: MacroDigest, *, cap: int, ranker=None) -> list[ExtensionRequest]:
    """Deterministic: run EXTENSION_RULES over `macro` -> candidates. Then LLM
    (ranker) ranks/prunes to <= cap ExtensionRequests. LLM authority is bounded
    to ordering pre-validated candidates; it cannot add tools/templates."""

# agent/recon/targeted.py  (new; the D2 re-entrant interface - see forward-decisions D2 addendum)
def request_targeted_recon(run_id: str, component: dict, tool: str, template_set: list[str]) -> list[PodExport]:
    """Build a synthetic single-pod JobSpec around {component, tool,
    template_set} and invoke the EXISTING pod machinery (no new subgraph).
    Best-effort: returns a failed PodExport rather than raising. Reused by both
    L3 (origin=l3_synthesis) and the future analyser (origin=analyser_probe)."""

# agent/recon/pipeline.py  (new terminal step)
async def run_extension_phase(run_id: str, project_id: str, *, cap: int, registry=None, driver=None) -> None:
    """L3 loop: synthesize -> plan (capped) -> dispatch each ExtensionRequest via
    request_targeted_recon, curator-merging results. Single-pass, fail-open
    (§7): a probe that cannot succeed is recorded degraded and the loop moves
    on. Always returns; the pipeline then sets 'complete'."""
```

`EXTENSION_REQUEST_CAP` lives in `agent/recon/config.py` (proposed default 5).

---

## 6. End-to-end control-flow trace

One line per hop; **NEW** marks what this design adds to the flow in `agent-context-architecture.md` §2.5.

```
settings(PG) + produced-assets(Neo4j) [+ recon_signals(PG)  <- NEW]
  pipeline (per phase>0 job):
    input_assets = read_assets(consumes)            # or seed_assets in phase 0
    job_context  = build_job_context(run_id, input_assets, registry)     # NEW (L1 digest; '' in phase 0)
    seed JobState{job, input_assets, extra, run_id, phase, job_context}   # NEW field: job_context
      job-agent preprocess:
        pod_inputs = llm_preprocess_fn(input_assets, job, extra, asset_context, job_context)  # NEW (A4: LLM shapes pod set from limitations; deterministic fallback when job_context == '')
        for each pod_input: asset_context = build_asset_context(input_asset, job, project_id)  # L2 slice (+ anchor-bug fix)
      Send -> PodState per pod_input
        configurator (FIXED template) -> execute (Kali) -> gate -> parser -> assets
        triager LLM(exec_result, assets, asset_context)          # L2 context in
            -> observations + signals + coverage                 # NEW: signals (L1) + coverage (L2)
            -> coverage.status=='gap' ? append coverage_gap Observation
        curator MERGE assets + observations -> Neo4j             # global domain memory updated
        export = PodExport{verdict, ..., signals, coverage}      # NEW fields ride up
    pod_exports -> pipeline:
        write_pod_signals(run_id, session_id, [s for e in pod_exports for s in e.signals])  # NEW: persist L1 to recon_signals
        upsert_job(... stats ...)                                # control memory updated
    ---- phase barrier (asyncio.gather); next phase's build_job_context now sees these signals ----
  after last phase barrier:
    run_extension_phase(run_id, project_id, cap=EXTENSION_REQUEST_CAP):   # NEW (L3)
        macro    = synthesize_macro_observations(run_id, project_id)      # Neo4j Obs + recon_signals + coverage_gaps
        requests = plan_finding_triggered_extensions(macro, cap=cap)      # deterministic rules + LLM rank/prune <= cap
        for req in requests:                                             # single pass, capped
            exports = request_targeted_recon(run_id, req.component, req.tool, req.template_set)  # D2 -> reuse pod machinery -> curator merge
            upsert_job(run_id, phase=EXT, job=f"ext:{req.tool}:...", status)  # fail-open: degraded on failure, no re-queue
  set_run_status(run_id, "complete")                              # always reached
```

Where each scaffold is **built** vs **consumed**:

| Scaffold | Built (site) | Consumed (site) |
|---|---|---|
| L1 digest (`job_context`) | pipeline `build_job_context`, phase>0 job seed | job-agent `llm_preprocess_fn` |
| L1 raw signals | pod triager (emit) -> pipeline `write_pod_signals` (persist) | later phase's `build_job_context` |
| L2 context (`asset_context`) | job-agent `preprocess` per pod_input | pod triager |
| L2 verdict (`coverage_gap`) | pod triager -> curator (Neo4j) | L3 `synthesize_macro_observations` |
| L3 macro digest | pipeline `run_extension_phase` | `plan_finding_triggered_extensions` |
| L3 extension requests | `plan_finding_triggered_extensions` | `request_targeted_recon` (D2) |

---

## 7. Fail-open stop condition (A3) + request cap (A5)

The L3 extension loop is the only place the pipeline can "go deeper", so it is where runaway/blocking risk lives.
Two guards, both hard:

1. **Request cap (A5).**
   `plan_finding_triggered_extensions` returns at most `EXTENSION_REQUEST_CAP` requests.
   The LLM ranks/prunes to the cap; it cannot enlarge the set.
   So the number of D2 calls per run is bounded a priori.
2. **Fail-open, single-pass (A3).**
   `run_extension_phase` iterates the capped request list **once**.
   For each request:
   - if `request_targeted_recon` returns a `failed` PodExport (the probe cannot succeed), **or** the component's host is flagged in `recon_signals` as blocking, the request is **recorded as a degraded `recon_jobs` row and skipped** - never re-queued, never retried, never blocking the loop;
   - successful probes curator-merge their assets/observations as normal.

**The stop condition** is therefore purely structural: the loop terminates when the capped list is exhausted; there is no success criterion to satisfy and no gap to "close", so no cycle can form.
A probe that cannot succeed does not stall the run - it degrades and the pipeline proceeds to `set_run_status("complete")`.
This is the existing best-effort pipeline stance (`pipeline.py` docstring, design §10.6) extended to L3.
It also means the future analyser -> probing-request path (A2 seam) inherits the same guarantee for free, since it calls the same `request_targeted_recon`.

---

## 8. Core-functions index (signatures)

| Function | Home | Responsibility |
|---|---|---|
| `write_pod_signals(run_id, source_pod, signals)` | `app/clients/pg.py` | Persist emitted PodSignals into `recon_signals` (sparse upsert) |
| `read_pod_signals(run_id, hosts)` | `app/clients/pg.py` | Read signals for a run's hosts (the L1 read) |
| `host_of(asset)` | `recon/context.py` | Extract host key from an asset identity |
| `build_job_context(run_id, input_assets, *, registry)` | `recon/context.py` | Render the bounded L1 digest -> `JobState.job_context` |
| `llm_preprocess_fn(input_assets, job, extra, asset_context, job_context)` | `recon/job_agent.py` | Enabled job_orchestrator: LLM shapes pod set from L1 limitations |
| `build_asset_context(input_asset, job, project_id, *, driver)` | `recon/context.py` | Bounded Neo4j slice = L2 context + legal anchor (anchor-bug fix) |
| `coverage_to_observation(verdict, *, source_job, source_tool)` | `recon/findings.py` | CoverageVerdict(gap) -> coverage_gap Observation |
| `synthesize_macro_observations(run_id, project_id, *, driver, registry)` | `recon/synthesis.py` | Bounded macro digest over Obs + signals + gaps |
| `plan_finding_triggered_extensions(macro, *, cap, ranker)` | `recon/synthesis.py` | Deterministic rules + LLM rank/prune -> capped requests |
| `request_targeted_recon(run_id, component, tool, template_set)` | `recon/targeted.py` | D2 re-entrant probe via reused pod machinery |
| `run_extension_phase(run_id, project_id, *, cap, registry, driver)` | `recon/pipeline.py` | Terminal L3 loop: synth -> plan -> dispatch, fail-open |

New config: `CONTEXT_MAX_CHARS = 1200`, `EXTENSION_REQUEST_CAP = 5` (`recon/config.py`).
New types: `PodSignal`, `SignalKind`, `CoverageVerdict`, `MacroDigest`, `ExtensionCandidate`, `ExtensionRequest`, `ExtensionRule` (`recon/types.py` / `recon/synthesis.py`); `PodExport` gains `signals` + `coverage`; `JobState` gains `job_context`.
New table: `recon_signals` (`db/postgres/init.sql`).

---

## 9. Decisions needing operator validation

These are significant (they change a core contract, a memory tier, cost/latency, or agent topology); the operator is away, so they queue.

- **V1 - Enabling the LLM preprocess path changes the job-agent's cost/latency profile.**
  A4 requires the `job_orchestrator` LLM in `preprocess`.
  Recommended: **gate it on `job_context != ''`** - phase 0 and any phase>0 job whose hosts carry no signals stay on the deterministic `default_preprocess_fn` (zero added LLM cost when there is nothing to reason about); the LLM runs only when there are real limitations to account for.
  Confirm this gating vs always-on.
- **V2 - Shared-pod-memory writer.**
  Recommended: the **pipeline** flushes signals from `pod_exports` via `write_pod_signals` (single control-plane writer, symmetric to the curator being the single graph writer, keeps the pod store-free).
  Alternative (a literal reading of A1 "the triager documents it"): the **triager writes to Postgres directly**.
  Confirm the pipeline-flush placement.
- **V3 - L3 reuses the pod/job machinery, not a new subgraph.**
  Recommended: `request_targeted_recon` builds a synthetic single-pod `JobSpec` and invokes the existing `pod_graph` (D2 addendum).
  Confirm vs a dedicated extension subgraph.
- **V4 - Triager and preprocess contract widening.**
  The MVP triager is "adds Observations only"; this design widens `triage_fn` to `(exec_result, assets, job, asset_context) -> _TriageResult{observations, signals, coverage}`, and `preprocess_fn` to take `job_context`.
  Confirm the contract changes (they touch `pod.py` / `job_agent.py`, owned by the orchestration stream).
- **V5 - L2 minimal now knowingly leaves "completeness" ungrounded (the §6.5 tension).**
  A2 accepts free LLM judgement now and defers the structural/checklist baseline to the future analyser -> probing-request path.
  Confirm the deferral is acceptable given the fail-open cap (A3) bounds any mis-judgement's blast radius.
- **V6 - `recon_signals` scope: per-run now, cross-run later.**
  Recommended: run_id-scoped now (no cross-run learning), cross-run durability a later toggle on the same table (learn across runs like the graph does).
  Confirm.
- **V7 - `EXTENSION_REQUEST_CAP` default (proposed 5) and the initial `EXTENSION_RULES` set.**
  The rule registry is the deterministic half of A5; its initial contents (GraphQL, JWT, unauth-admin, ...) and the cap need a first-cut value to plan against.
  Confirm/seed.

---

## 10. Build slicing (into SDD tasks)

Ordered by `context-scaffolding-three-levels.md` §7 (L2 -> L3 -> L1), which the resolutions leave intact:

1. **L2** - `build_asset_context` + thread `asset_context` into `triage_fn`; widen triager output to `CoverageVerdict`; `coverage_to_observation`; the anchor-allowlist fix.
   (Substrate exists; closes the live anchor bug; produces the signal L3 needs.)
2. **L3** - `MacroDigest` + `synthesize_macro_observations`; `EXTENSION_RULES` + `plan_finding_triggered_extensions`; `request_targeted_recon` (D2); `run_extension_phase` wired terminal in `run_pipeline` with cap + fail-open.
   (Consumes L2's `coverage_gap`; needs a new root reasoning step, no new store.)
3. **L1** - `recon_signals` DDL; `write_pod_signals` / `read_pod_signals`; `PodSignal` emission in the triager; `PodExport.signals`; pipeline flush; `build_job_context`; enable `llm_preprocess_fn`.
   (Now the smallest of the three after A1/A4 removed the detector and tunable-configurator blockers - see the resolved §7 of the scaffolding doc.)
