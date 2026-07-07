# Agent Context & Communication Architecture

*Foundational cognitive architecture for polymerhus recon.
Companion to `recon-mvp-design.md` (rev 5) and `recon-pipeline-forward-decisions.md`.
Scope: how memory is tiered across the substrates, what every agent/node reads and writes, and what the `asset_context` channel should carry.
This doc is design + recommendation only; where it proposes a change to a live module it says so explicitly (the orchestration stream owns `agent/recon/`).*

---

## 0. Why this document exists

The recon system is three nested agent layers (pipeline -> per-job agent -> pod) plus deterministic nodes, running over four persistence substrates (Neo4j, Postgres, pgvector, LangGraph state).
Context plumbing across those seams is load-bearing and was under-specified: a `project_id`/`run_id` conflation already broke cross-phase asset handoff, and `PodState.asset_context` is still a `""` stub that nothing populates.
This document fixes the specification gap.
It defines the memory tiers, the authoritative-vs-derived split, the precise reads/writes topology, and a concrete `asset_context` contract, all tied to the real state types in `agent/recon/types.py`.

The governing principle is **minimal high-signal context per agent**.
Every LLM role should receive the smallest slice of context that lets it do its job well, retrieved on demand from the authoritative store, never the whole graph dumped into a prompt.

---

## 1. Memory tiers

There are four memory tiers, each mapped to exactly one substrate, each with a distinct lifespan, authority, and access pattern.
The single most important rule: **domain knowledge lives in Neo4j; LangGraph state is a message bus, not a store.**

| Tier | Substrate | Lifespan | Authority | Written by | Read by |
|---|---|---|---|---|---|
| **Global / project memory** | Neo4j (Layer-0 graph + Observations) | Permanent, cross-run, cross-phase | **Authoritative** for all discovered attack surface + findings | curator (only) | pipeline `read_assets`, `build_asset_context`, later-phase agents |
| **Global / knowledge memory** | pgvector `doc_chunks` | Permanent, immutable after ingest | Authoritative for ingested external docs | ingestion agent (deferred) | retrieval (deferred), anchored to graph nodes by `doc_ref` |
| **Global / control memory** | Postgres `projects`/`settings`/`recon_runs`/`recon_jobs` | Permanent (settings), per-run (registry) | Authoritative for config + run/job progress | REST routes, pipeline registry calls | pipeline (`load_settings`), REST status polling |
| **Per-job memory** | `JobState` (LangGraph, checkpointed `checkpoint_ns=phase/job`) | One job-run | Derived / transient | job-agent nodes | job-agent nodes |
| **Per-pod memory** | `PodState` (LangGraph, nested subgraph) | One pod invocation | Derived / transient | pod nodes | pod nodes |

### 1.1 Global memory: the Neo4j Layer-0 graph

The Neo4j graph is the **only authoritative record** of what recon has discovered.
It is the cross-phase memory: phase `i+1` reads what phase `i` produced (`pipeline.read_assets` re-queries Neo4j by `consumes` label), and it is the cross-run memory (all writes are idempotent `MERGE`, so a re-run converges rather than duplicates).

What is authoritative here:
- Every Layer-0 asset node (`Domain`, `Subdomain`, `IP`, `Port`, `Service`, `BaseURL`, `Endpoint`, `Parameter`, `Technology`, ...), keyed by its identity + `project_id`.
- Every `Observation` node, hung off a broad anchor by `HAS_OBSERVATION`.

What is derived (and must never be re-derived into a prompt wholesale):
- Neighborhood summaries, counts, and NL renderings (these are built on demand by `build_asset_context`, section 4).

**How agents query it - and how not to.**
The two legitimate read paths are both narrow and typed:
1. `pipeline.read_assets(node_type, project_id)` re-hydrates the identity dicts of one label for the next phase's fan-out.
   The label is validated against `curator.ALLOWED_LABELS` before interpolation; values stay parameterised.
2. `build_asset_context(input_asset, ...)` (proposed, section 4) fetches a **bounded 1-hop slice** around a single asset for the configurator/triager.

There is no third path, and specifically **no agent may `MATCH (n) RETURN n` the project graph into an LLM prompt.**
The graph grows without bound across phases; dumping it destroys the signal-to-noise ratio every LLM role depends on and blows the token budget.
Retrieval is always keyed to the one asset a pod is working on.

### 1.2 Global memory: the pgvector doc store

`doc_chunks(id, doc_ref, source_type, anchor, chunk_text, embedding, created_at)` holds ingested external knowledge (API contracts, sitemaps, OSS code).
Ingestion and retrieval are deferred (`documentation-ingestion-design.md`), but the seam matters for this architecture: doc knowledge is **anchored to the graph**, referenced by `doc:<type>:<anchor>` on the anchoring broad element.
When retrieval lands, the pattern is the same as the graph: retrieve the top-k chunks relevant to the asset under work, never the whole corpus.
The doc store is unstructured knowledge retrieved by embedding similarity; the graph is structured knowledge retrieved by identity/traversal.
They compose: an agent working a `BaseURL` can pull both its graph neighborhood and its anchored doc chunks.

### 1.3 Global memory: the Postgres control plane

Postgres holds three unrelated things behind one connection:
- **Settings** (`settings.recon` JSONB), authoritative for `target_domain`, `max_pods`, and `auth_context` (the authN cookies). Loaded once per run into `ReconState.settings`.
- **Registry** (`recon_runs`, `recon_jobs`), authoritative for run/job status + stats, the operator's view via `GET /recon/{run_id}`.
- **Checkpoints** (LangGraph `AsyncPostgresSaver`, `thread_id=run_id`, `checkpoint_ns=phase/job`), the durability layer for the transient tiers.

The control plane is **not domain memory**.
An agent must never reach into the registry to reason about attack surface; the registry answers "how is the run going", the graph answers "what did we find".

### 1.4 Per-job memory (`JobState`)

`JobState` accumulates, for one job-run:
- `input_assets`: the consumed-type asset identities read from Neo4j for this phase (or the seed for phase 0).
- `asset_context`: today a single job-wide `""`; section 4 proposes it become **per-pod-input**, not job-wide.
- `extra`: the kwargs channel, carrying `project_id` always and `auth_context` only for `use_auth` jobs (the job agent strips it for non-auth jobs - a real, correct isolation boundary already in `default_preprocess_fn`).
- `pod_inputs`: the distribution of assets across pods (1:1 capped at `MAX_PODS` in the deterministic default).
- `pod_exports`: the `operator.add`-reduced roll-up of every pod's terminal export.

It is scoped by `checkpoint_ns=phase/job` and threaded only within the compiled job agent.
It never outlives the job-run; its durable residue is (a) what the pods merged into Neo4j and (b) the registry stats the pipeline writes from `pod_exports`.

### 1.5 Per-pod memory (`PodState`)

`PodState` is the pod's ephemeral working state for a single input asset, one pass through configurator -> execute -> gate -> parser -> triager -> curator.
It carries the working values each node hands the next: `invocation`, `exec_result`, `iteration`, `assets`, `observations`, `export`.

What is isolated per pod (never shared between concurrent pods):
- `session_id` -> the Kali `/work/{session_id}` workdir, so concurrent tool runs never collide on files.
- `iteration` -> the pod's own retry counter, bounded by `MAX_POD_ITERS`.
- All of `PodState` -> LangGraph fans out a fresh state per `Send`.

What is shared (read-only, copied in at fan-out):
- `job` (the `JobSpec`), `project_id`, `extra` (a per-pod `dict(base_extra)` copy), and `asset_context`.

The pod is deliberately **stateless with respect to the graph**: it reads nothing from Neo4j directly (its only graph contact is the curator's write at the end).
Everything the pod needs to reason (the target, its neighborhood, existing observations) must arrive pre-packaged in `input_asset` + `asset_context`.
This keeps the fan-out cheap and the pod's context minimal, and it is why `asset_context` is the linchpin of the whole design (section 4).

---

## 2. Communication topology: who reads and writes what

This is the precise map of context flow across every seam.
"State" = the LangGraph tier the node touches; "Substrate" = any external store it reads or writes.

### 2.1 Pipeline orchestrator (`pipeline.run_pipeline`)

| Reads | Writes |
|---|---|
| Postgres `settings.recon` via `load_settings` (once) | Postgres registry: `create_run`, `upsert_job`, `set_run_status` |
| Neo4j via `read_assets(job.consumes, project_id)` per phase>0 | `JobState` seed per job: `{job, input_assets, extra, run_id, phase}` |
| `settings.target_domain` for the phase-0 seed | `extra = {project_id}` (+ `auth_context` only when `job.use_auth`) |

The pipeline is the **bridge from global memory to per-job memory**: it lifts settings + produced assets out of the authoritative stores and seeds each job agent.
It is the only place `auth_context` crosses from settings into a job's `extra`, and it must gate that on `job.use_auth` (it does).
It writes nothing to the graph; its only writes are control-plane registry rows.

### 2.2 Per-job orchestrator agent (`job_agent`)

| Node | Reads (state) | Writes (state) | Substrate |
|---|---|---|---|
| `preprocess` | `input_assets`, `job`, `extra`, `asset_context` | `pod_inputs` (list of `{input_asset, asset_context, extra}`) | none today; **proposed**: Neo4j read to build per-asset `asset_context` |
| `fan_out` | `pod_inputs`, `job`, `run_id`, `phase` | `Send("pod_runner", ...)` per pod_input | none |
| `pod_runner` | `_pod_input`, `job`, `run_id`, `phase` | `pod_exports += [export]` | invokes the pod subgraph |

`preprocess` is the **context-distribution seam**.
Today it does a deterministic 1:1 asset->pod_input map and copies a job-wide `asset_context` (always `""`) into each.
It is also the declared home of the future LLM `job_orchestrator` role (asset cleaning/dedup/distribution), which is a stub in the MVP.
This is the correct place to build per-asset `asset_context` (section 4): it has `project_id` (via `extra`), the asset list, and it runs once per job rather than once per pod, so a batched Neo4j read here is cheaper than N reads inside N pods.

`extra` isolation is enforced here and is correct: `default_preprocess_fn` pops `auth_context` for non-`use_auth` jobs so a passive pod can never see cookies even if a caller over-supplied them.

### 2.3 Recon pod (`pod.build_pod_graph`)

| Node | Reads (state) | Writes (state) | Substrate | Kind |
|---|---|---|---|---|
| configurator | `job.command_template`, `input_asset`, `extra` (auth), `session_id` | `invocation`, `iteration` | none | deterministic fill (LLM in `agent` mode) |
| execute | `invocation`, `session_id` | `exec_result` | Kali MCP `execute_command` | side effect |
| gate | `exec_result.returncode`, stdout, `iteration` | routes parse/retry/fail | none | deterministic |
| parser | `exec_result.stdout`, `job.tool`, `input_asset` (target url) | `assets` | none | deterministic |
| triager | `exec_result`, `assets`, `job`, **`asset_context` (proposed)** | `observations` | LLM (+ deterministic findings parsers) | LLM |
| curator | `assets`, `observations`, `project_id` | `export` | **Neo4j `MERGE` (the only graph write)** | deterministic |
| fail | `exec_result.stderr`, `iteration` | `export` (failed) | none | deterministic |

Key observations about the pod topology:
- The **configurator does not currently read `asset_context`** in deterministic mode (it only fills placeholders from `input_asset` + `extra`).
  It should read it in `agent` mode (the crawler), where scope + already-discovered endpoints materially change behavior.
- The **triager reads `asset_context` in the proposed design** and it is the highest-value consumer: to write a non-duplicate, high-signal Observation on a *legal broad anchor*, the triager needs to know the asset's broad anchor and what Observations already exist there.
  Today it gets only `exec_result` + `assets` + `job` (see `default_triage_fn`), which is why it is prone to inventing illegal anchors (section 3).
- The **curator is the sole graph writer.**
  This is a hard invariant (`curator.py` is "the ONLY graph-write path"): it keeps the write contract in one auditable place and lets every other node stay graph-stateless.

### 2.4 Crawl pod (`configurator_mode="agent"`, the Steel crawler)

The agentic-crawl variant replaces configurator+execute+gate with a ReAct loop (`run_crawl`) driving Steel MCP tools, then rejoins parser -> triager -> curator.
Its reads/writes:

| Node | Reads | Writes | Substrate |
|---|---|---|---|
| crawl (ReAct loop) | `input_asset` (BaseURL), `extra.auth_context`, scope, **`asset_context` (proposed)**, the `steel_crawl` skill prompt | manifest `{endpoints, js_urls}` | Steel MCP `steel_*` tools |
| parser (steel) | manifest JSON | `assets` | none |
| triager, curator | as section 2.3 | as section 2.3 | Neo4j write |

The crawler is the second high-value `asset_context` consumer: knowing which endpoints/base URLs are *already in the graph* lets it prioritise unexplored surface and avoid re-crawling known pages (a direct budget saving on its bounded page/iteration allowance).

### 2.5 The end-to-end context flow (one line per hop)

```
settings(PG) + produced-assets(Neo4j)
  -> pipeline: seed JobState{input_assets, extra{project_id[,auth_context]}}
    -> job-agent preprocess: distribute -> pod_inputs[{input_asset, asset_context, extra}]
      -> Send -> PodState per asset
        -> configurator: input_asset + extra -> invocation
        -> execute (Kali) -> exec_result
        -> parser -> assets (AssetDelta[])
        -> triager: exec_result + assets + asset_context -> observations (Observation[])
        -> curator: MERGE assets+observations -> Neo4j  (global memory updated)
        -> export -> pod_exports (reduced)
    -> pipeline: pod_exports -> registry stats (PG)   (control memory updated)
  -> next phase reads the newly-merged assets from Neo4j
```

Global memory is written **only** at the curator step and read **only** at phase boundaries + context-build.
Everything between is transient per-job/per-pod state.
This is the tiering working as intended: a narrow, auditable coupling between the durable and transient tiers.

---

## 3. The latent anchor bug this architecture must fix

`curator.build_observation_cypher` enforces `ANCHOR_ALLOWLIST = {Domain, Subdomain, BaseURL, IP, Service}` and **raises `ValueError` (silently skipping the observation) for any other anchor type.**
But the triager's live prompt (`default_triage_fn`) says only *"anchor {type, identity}"* with no constraint, and the triager sees parsed `assets` that are frequently `Endpoint`/`Parameter`/`Technology` nodes.
A naive triager anchors its observation on the `Endpoint` it just saw - and the curator drops it on the floor.
The finding is computed, costs an LLM call, and never reaches the graph.

This is the same class of bug as the `project_id`/`run_id` conflation: an unspecified context contract silently losing data.
The fix has two halves, both in this architecture:
1. **`asset_context` surfaces the legal anchor** (the broad element the asset hangs off) so the triager has a correct anchor to use (section 4).
2. **The observation-writing skill makes the allowlist explicit and non-negotiable** (section 6 + the authored skill), so the triager never emits an `Endpoint`/`Parameter` anchor even when that is the asset it is reasoning about.

Section 6 records the recommended live-interface change (thread `asset_context` into `default_triage_fn` and load the skill as its system prompt).

---

## 4. The `asset_context` contract (the core new design)

`asset_context: str` is a **read-only, per-input-asset, token-bounded NL slice of the graph**, given to the configurator (in `agent` mode) and the triager.
It is currently an unpopulated stub.
This section specifies what it carries, how it is built, and its budget.

### 4.1 What it carries

For a single input asset, `asset_context` renders four things, in priority order, truncating from the bottom when over budget:

1. **The asset's identity + salient props** (1-2 lines).
   The pod already has `input_asset`, but the NL rendering names it for the LLM ("BaseURL https://app.example.com, nginx, HTTP 200, title 'Login'").
2. **The legal broad anchor** (1 line): the `Domain`/`Subdomain`/`BaseURL`/`IP`/`Service` this asset belongs to, with its identity.
   This is the single most valuable field for the triager: it is exactly the anchor the curator will accept.
3. **Existing Observations on that anchor** (compact list: `macro_kind` + `severity` only, no evidence text).
   This lets the triager avoid emitting a duplicate observation and lets it escalate/relate rather than repeat.
4. **A bounded neighborhood summary** (counts by type + a handful of high-signal neighbors: `Technology` names, open `Port`/`Service`, known `Endpoint` count).
   High-signal neighbors are enumerated; the long tail is summarised as counts ("47 Endpoints, 12 Parameters").

It deliberately does **not** carry: the full endpoint list, raw tool output, parameter values, or anything the parser already turned into an `AssetDelta`.
The parsed `assets` are already in `PodState`; duplicating them into `asset_context` is context pollution.

### 4.2 How it is built

A deterministic builder, invoked once per pod_input in the job agent's `preprocess` node (proposed; expressed here as an interface recommendation since `agent/recon/job_agent.py` is owned by the orchestration stream):

```python
# PROPOSED interface (recommendation, not a live edit).
# Home: agent/recon/context.py, called from job_agent.default_preprocess_fn.

CONTEXT_MAX_CHARS = 1200            # ~300-400 tokens; hard cap, truncate-from-bottom

def build_asset_context(
    input_asset: dict,
    job: JobSpec,
    project_id: str,
    *,
    driver=None,                    # injectable; defaults to neo4j_client._driver
) -> str:
    """Render a bounded NL slice of the graph around `input_asset`.

    One bounded Cypher read (1-hop out of the asset + its Observations),
    rendered to <= CONTEXT_MAX_CHARS. Never returns the whole graph; on a
    cold graph (phase 0, asset not yet merged) returns just the identity line.
    Deterministic and side-effect-free apart from the single read.
    """
    # 1) MATCH the asset by identity+project_id (label from an allowlist).
    # 2) OPTIONAL MATCH its broad anchor (BELONGS_TO/HAS_BASE_URL/... up-edges)
    #    and any (:anchor)-[:HAS_OBSERVATION]->(:Observation).
    # 3) OPTIONAL MATCH 1-hop neighbors, aggregated by label (counts) with a
    #    LIMIT on enumerated high-signal types (Technology, Service).
    # 4) Render to NL, priority-ordered, truncating tail to the char cap.
```

Design choices and their rationale:
- **Built in `preprocess`, not the pod.**
  `preprocess` runs once per job and has `project_id` and the whole asset list, so one batched read (or N cheap reads) is amortised better than a read inside each of N fanned-out pods, and it keeps the pod graph-stateless (section 1.5).
- **One bounded read, deterministic.**
  No LLM in the builder; it is a retrieval, not a summarisation, so it is cheap, testable, and cannot hallucinate.
  When retrieval-over-summarisation is possible, prefer it (context-engineering principle).
- **Per-pod-input, not job-wide.**
  The current `asset_context` is a single string copied to every pod; that is wrong once it carries per-asset graph slices.
  The recommended `pod_inputs` shape keeps `asset_context` a field of each pod_input (it already is), just populated per asset.
- **Char-capped, truncate-from-bottom.**
  The priority order guarantees the anchor (the load-bearing field) survives truncation; the neighborhood tail is the first thing dropped.

### 4.3 Budget

`CONTEXT_MAX_CHARS = 1200` (~300-400 tokens) is the recommended default, a new setting alongside `OUTPUT_BYTE_CAP`.
Rationale: across a 2-level fan-out with up to `MAX_PODS` concurrent pods, each making 1-2 LLM calls (configurator in agent mode, triager), an unbounded context multiplies fast.
A hard per-asset cap keeps total context linear in `MAX_PODS` and keeps each prompt in the high-signal regime.
The cap is a truncation point, not a target: most `asset_context` values (especially early phases) will be far shorter.

---

## 5. Memory-tiering decision table

Where does a given piece of context belong?
The rule of thumb: **durable domain knowledge -> Neo4j; durable knowledge-corpus -> pgvector; durable control state -> Postgres; everything transient -> LangGraph state, and as little as possible.**

| Piece of context | Tier | Why |
|---|---|---|
| A discovered subdomain / endpoint / service | Neo4j | Authoritative attack surface, cross-phase, idempotent |
| A security observation | Neo4j (`Observation` node) | Durable finding on a broad anchor; queryable by later phases |
| Ingested API-contract / sitemap chunks | pgvector | Unstructured knowledge, retrieved by similarity, anchored by `doc_ref` |
| `target_domain`, `max_pods`, `auth_context` | Postgres `settings` | Config; loaded once per run |
| Run/job status + stats | Postgres registry | Operator-facing control state |
| The command a configurator built | `PodState.invocation` | Transient, handed to execute, then irrelevant |
| Parsed `AssetDelta`s pre-merge | `PodState.assets` | Transient, handed to triager+curator, then merged to Neo4j |
| The per-asset graph slice for a prompt | built on demand into `asset_context` | **Derived**, never stored; rebuilt from Neo4j each run |
| Auth cookies for a pod | `extra.auth_context` (from settings) | Transient copy, isolated to `use_auth` pods |
| Cross-pod shared discovery within a phase | **Neo4j only** | Pods do not share LangGraph state; they converge via `MERGE` |

The last row is a deliberate design stance: within a phase, pods do **not** talk to each other through state; they converge through idempotent `MERGE` into the graph, and the *next* phase sees the union.
This is what makes the fan-out embarrassingly parallel and free of shared-state races.
The cost is that intra-phase cross-pollination (pod A's discovery informing pod B mid-phase) is not available; the design accepts this because phase boundaries are the natural synchronisation points and the barrier already enforces them.

---

## 6. Context-engineering principles applied

1. **Minimal high-signal context per agent.**
   The configurator gets a template + one asset; the triager gets its tool output + parsed assets + a bounded anchor slice; neither gets the graph.
2. **Retrieval over dumping.**
   `asset_context` is a keyed 1-hop retrieval, not a graph dump; doc retrieval (deferred) is top-k, not the whole corpus.
3. **Tiering.**
   Durable knowledge is in the stores; state carries only what one node hands the next.
   Checkpointing persists state for durability, not for it to become a knowledge store.
4. **Avoid context bloat across the 2-level fan-out.**
   A hard `CONTEXT_MAX_CHARS` cap keeps total prompt context linear in `MAX_PODS`; `exec_result.stdout` is already capped by `OUTPUT_BYTE_CAP`.
5. **Avoid context pollution.**
   `asset_context` never restates the parsed `assets`; the triager skill forbids restating assets as observations; auth cookies are stripped from non-auth pods.
6. **One writer per store.**
   The curator is the sole graph writer; the pipeline is the sole registry writer for run status.
   Single-writer invariants make the reads/writes map above trustworthy.

### Recommended changes to live interfaces (recommendations only)

These require edits to modules owned by the orchestration stream; they are recorded here for that stream to adopt, not applied.

- **R1 - Populate `asset_context`.**
  Add `agent/recon/context.py::build_asset_context` (section 4.2) and call it per pod_input in `job_agent.default_preprocess_fn`, replacing the job-wide `""`.
  Add `CONTEXT_MAX_CHARS` to `agent/recon/config.py`.
- **R2 - Thread `asset_context` into the triager and load the skill.**
  Change `pod.default_triage_fn` to accept and use `state["asset_context"]` and to load its system prompt from the authored `skills/recon/triager/writing-observations/SKILL.md` (via a small loader), replacing the inline prompt string.
  The pod's `triager` node already has `asset_context` in `PodState`; it just needs to pass it through.
- **R3 - Make the anchor allowlist explicit at the triager boundary.**
  Independently of the skill, the triager's structured-output schema (or a post-filter) should reject/repair non-allowlisted anchors before curation, converting a silent curator drop into either a repaired broad anchor or a logged, visible skip.
  Today the mismatch between the triager prompt (any anchor) and the curator allowlist (5 types) is invisible.
- **R4 - Give the `agent`-mode configurator/crawler `asset_context`.**
  The crawl ReAct loop should receive `asset_context` (already-known endpoints + scope) to prioritise unexplored surface within its bounded page budget.

---

## 7. Summary

The architecture is four tiers over four substrates with one writer each for the durable stores, and a strict discipline that LangGraph state is a transient message bus while Neo4j is the authoritative memory.
The one genuinely new mechanism is `asset_context`: a bounded, per-asset, retrieval-built graph slice that turns the pod from graph-blind into graph-aware without making it graph-stateful, and that closes the latent anchor bug by handing the triager a legal anchor.
The jobs/tools/skills taxonomy that sits on top of this context substrate is specified in `jobs-tools-skills-taxonomy.md`.
