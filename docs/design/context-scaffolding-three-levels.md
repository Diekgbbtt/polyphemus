> **SUPERSEDED.** Retained for historical trace only.
> The authoritative doc is `recon-pipeline-design.md` §9, which folds in the L1/L2/L3 decomposition rationale and the resolved grey points (A1-A5) as an explicit "designed, not yet implemented" section.

# Context Scaffolding - Three Levels (L1 / L2 / L3)

*Companion to `agent-context-architecture.md` (the memory-tier model) and `recon-pipeline-forward-decisions.md` (D2, the re-entrant targeted-recon seam).
This document supersedes the single, universal `asset_context` builder proposed in `agent-context-architecture.md` §4.
It keeps everything else in that doc that is sound - the four memory tiers, the single-writer curator invariant, retrieval-over-dumping, the token caps, the `project_id`/`run_id` discipline, and the latent anchor-allowlist bug fix.
Operator correction of 2026-07-06 is the authority for the shape below; where this doc and `agent-context-architecture.md` §4 disagree, this doc wins.*

> **Merge dependency.** The canonical copy of this file (and of `agent-context-architecture.md`) is committed on the sibling worktree branches `feat/recon-pipeline` / `worktree-agent-aae77ec117b0088cc` / `worktree-agent-a015e725140839228`, not on `feat/platform-stack`.
> This copy reproduces that canonical text and then integrates the operator's answers (A1-A5) of 2026-07-06/07 into §2-§4 (inline **RESOLVED** callouts) and §8 (rewritten from open grey points into resolutions).
> On merge, this resolved version supersedes the open-grey-point version (it is strictly newer and additive).
>
> **Operator answers (A1-A5), authoritative.** The five grey points of §8 are now decided:
> - **A1 (L1 source):** blocks are detected **by the pod triager** (already an LLM), which writes failure/limitation signals into a **sparse shared pod memory** (a Postgres control-plane table, run+host+kind keyed). *Not* a gate-level heuristic detector, *not* a new exec-path heuristic. The **next job's job-agent reads it after the earlier pods have run.**
> - **A2 (L2 baseline):** keep completeness **LLM-judgement-based and minimal** for now (the structural/checklist grounding of Q2 is *deferred*). Make the seam for a future **analyser -> probing-request** path (a re-entrant D2 call) explicit.
> - **A3 (fail-open):** L2's verdict is **actionable but fail-open**: if a specific probe cannot succeed, the **root orchestrator stops gracefully** rather than looping/blocking.
> - **A4 (L1 mechanism):** **no tunable configurator.** Templates stay fixed. Instead the **job-agent LLM is fed the shared pod memory and accounts for the collected limitations when distributing/parameterising pods.** This *enables the currently-stubbed LLM preprocess (`job_orchestrator`) path.*
> - **A5 (L3):** a **core pipeline always runs** (the phase DAG); extensions are **finding-triggered** (GraphQL API found -> GraphQL scan; JWT present -> JWT decode). **Hybrid:** deterministic candidate generation from findings + LLM ranks/prunes under a hard **request cap**. This is the D2 re-entrant targeted-recon interface.
>
> The full end-to-end trace (sources, owners, consumers, data contracts, core functions, control flow) lives in the companion `context-memory-end-to-end.md`.

---

## 0. Why the one-hop heuristic was rejected

`agent-context-architecture.md` §4 proposed one mechanism - `build_asset_context` - that gathers a bounded 1-hop graph neighbourhood around each input asset and hands the same shape to both the configurator and the triager.
The operator's objection: "gather data one hop further on the graph" is a **purely topological heuristic**.
It answers "what is near this node" when the three LLM roles actually each need a different, purpose-built answer:

- the per-job orchestrator needs to know **what went operationally wrong before**, so it configures its pods to not repeat it;
- the pod triager needs to know **what is already observed about this exact target**, so it can judge whether recon on it is *complete*;
- the root pipeline needs the **macro picture of the whole run**, so it can decide where to go deeper *after* the linear DAG finishes.

None of those three is "1-hop on the graph."
Two of them (L1, L3) are not sourced from the asset graph at all.
So the universal builder is replaced by three distinct scaffolds, one per real agent level, each with its own source, build site, and budget.

The one part of §4 that survives - refocused - is the triager slice, now L2: it stops being "the neighbourhood" and becomes "the Observations already recorded on this target."

---

## 1. The three real agent levels (mapped to code)

There are exactly three LLM decision points in the recon control loop.
Each scaffold targets one of them.

| Level | Consumer (code) | Today | Scaffold gives it | Purpose |
|---|---|---|---|---|
| **L1** | per-job orchestrator - `job_agent.default_preprocess_fn` (the stubbed `job_orchestrator` LLM seam) | deterministic 1:1 asset->pod fan-out, no LLM | operational failure-modes seen in **earlier phases**, target-keyed | configure this job's pods to **avoid repeating** WAF blocks / rate-limits / auth walls / tech-stack quirks |
| **L2** | pod triager - `pod.default_triage_fn` | LLM, sees `exec_result` + parsed `assets` + `job` only | the **Observations already on this target's broad anchor** | make a **grounded completeness judgement**: did we gather enough on THIS target? |
| **L3** | root pipeline - `pipeline.run_pipeline` | deterministic phase-DAG driver, no LLM | **macro/architectural synthesis** of the whole run's Observations | after the core DAG, **extend** with deep, narrow, targeted probes (ties to D2) |

Two of these three consumers are **not LLM agents today**.
L1 targets the `job_orchestrator` seam that `default_preprocess_fn` documents but does not exercise.
L3 targets the pipeline, which is a deterministic driver with no reasoning step at all.
This is the first structural fact the operator's argument commits us to: **L1 and L3 require standing up two new LLM decision points**, not just feeding existing ones.
Only L2 feeds an agent that already exists.

---

## 2. L1 - to the per-job orchestrator: cross-phase failure-avoidance context

> **RESOLVED (A1, A4).** Source is settled: the **pod triager** (already an LLM) detects a WAF/rate-limit/auth-wall/tech-quirk while triaging its tool output and **writes a sparse signal into a new Postgres control-plane table `recon_signals`** (run+host+kind keyed). No gate-level detector, no new exec-path heuristic (§6.2's "needs a detector" gap is closed by *reusing the triager* as the classifier). Mechanism is settled too: **no tunable configurator** (§2's "actionability precondition" and Q4 are resolved by *not* re-opening the template surface). Instead the **job-agent's LLM preprocess (`job_orchestrator`) path is enabled** and fed the L1 digest; it acts by **choosing/prioritising/deduping which pods to spawn** (e.g. skip or deprioritise a host known to be walled) under the `MAX_PODS` cap - the command templates stay fixed. See `context-memory-end-to-end.md` §3 for the record schema, writer, reader, and digest contract.

**Consumer.** `job_agent`'s preprocess node, running the `job_orchestrator` role (the LLM seam `default_preprocess_fn` reserves).
It uses L1 to shape each `pod_input` - specifically the per-pod `extra` overrides the configurator will bake into the command.

**What it contains.** A compact, target-keyed digest of *operational* failure signals observed in **already-completed phases** of this run (and, if made durable, prior runs):

- a probe that was WAF-blocked on host H (403 / block-page fingerprint);
- a rate-limit hit on host H (429 / throttling);
- an auth wall reached on endpoint E (401/403 behind a login);
- a tech-stack quirk (e.g. "app.example.com is Cloudflare-fronted", "the API rejects non-browser UA").

Keyed by **target/host**, not by job, because the useful unit is "this asset lives on a host that blocked us," not "some earlier job failed somewhere."

**Where it is sourced from.** This is the load-bearing gap: **there is no tier that holds these signals today.**
See §6 - operational failure signals are neither detected nor persisted by the current pipeline.
L1 therefore requires a **new per-run operational-signal store** (proposed: a Postgres control-plane table `recon_signals(run_id, host, kind, evidence, phase, observed_at)`, sitting beside `recon_jobs`).
It is control-plane memory, not domain memory: it answers "how did probing go against host H," which is exactly the registry's remit, not Neo4j's.
It must **not** be an `Observation` (Observations are security findings on broad anchors; a rate-limit is neither).

**Where/when it is built.** In the **pipeline**, at the bridge from global memory to per-job memory (`run_pipeline`, just before it seeds each phase>0 job's `JobState`).
The pipeline already loads settings and reads produced assets here; it additionally reads `recon_signals` for the hosts this job's `input_assets` belong to, digests them, and threads the digest into the job via a new `JobState` field (`job_context: str`) alongside `input_assets`/`extra`.
Phase 0 has no earlier phases, so L1 is empty there (clean cold start).

**How it stays bounded.** Filtered to the hosts this job will actually probe (target-keyed), capped to the top-k most recent/severe signals per host, rendered as `kind + host + one-line evidence` (no raw stdout).
A hard char cap mirrors `CONTEXT_MAX_CHARS`.

**The actionability precondition.** For L1 to change behaviour, the configurator and command templates must expose *operational knobs* the orchestrator can set (rate/delay, user-agent, proxy/route, backoff).
Today templates are **fixed** - the configurator fills only `{target}`/`{domain}`/`{baseurl}`/`{session}`/`{auth_header}` (`pod.fill_template`), and format-affecting flags are baked in on purpose (`jobs-tools-skills-taxonomy.md` §1.1).
L1 that produces advice no pod can act on is inert.
This is a second gap: L1 needs a tunable-configurator surface, which the design has so far deliberately deferred.

---

## 3. L2 - to the pod triager: grounded completeness context

> **RESOLVED (A2, A3).** Keep the completeness judgement **LLM-based and minimal now**: the triager, given the Observations already on the target's legal anchor (the surviving §4 `asset_context` slice) plus this run's parsed assets, emits a lightweight **coverage verdict** (`adequate | gap`). The structural/checklist baseline of Q2 is **deferred** - accepted as a conscious "minimal now" trade (see the validation note in `context-memory-end-to-end.md` on the §6.5 tension). The verdict is **actionable but fail-open (A3)**: a gap becomes a `coverage_gap` Observation that L3 reads during synthesis; L3 may raise a targeted re-probe, but **if that probe cannot succeed the root stops gracefully - it never loops or blocks** (§4 and `context-memory-end-to-end.md` §7). The **future analyser -> probing-request** path (an analyser agent that needs more attack surface issues a re-entrant D2 request) is the same seam L3 uses; it is made explicit here so the interface is built once.

**Consumer.** The pod triager (`pod.default_triage_fn`), on every job.

**What it contains.** For the single target under work, the **Observations already recorded on its legal broad anchor** (`Domain`/`Subdomain`/`BaseURL`/`IP`/`Service`), compact (`macro_kind` + `severity` + `source_job`, no evidence text), plus the identity of that anchor itself.
This is the surviving, refocused core of `agent-context-architecture.md` §4: it still hands the triager a *legal anchor* (closing the anchor-allowlist bug, §3 of that doc), but its purpose shifts from "avoid duplicate observations" to "**judge coverage**."

**What "completeness" means - and the trap in it.** The triager is being asked not just to add observations blind, but to assess "did we gather enough on THIS target."
That requires a baseline of what *enough* looks like.
Three candidate baselines (see grey point Q2): the phase DAG's own `consumes`/`produces` edges (structural coverage), an explicit per-asset-type coverage checklist, or free LLM judgement.
Free LLM judgement is itself a heuristic - the very thing the operator rejected for the one-hop builder - so L2 must be grounded in one of the first two, not left to the model's taste.

**Where it is sourced from.** Neo4j Observations on the asset's broad anchor - authoritative domain memory, read-only.

**Where/when it is built.** In `job_agent.preprocess`, once per `pod_input`, exactly as `agent-context-architecture.md` §4.2 places `build_asset_context` - one bounded Cypher read per asset, rendered to a cap, snapshotted into the `pod_input` and carried down to the triager via `PodState`.
Building it in preprocess (not the pod) keeps the pod graph-stateless (`agent-context-architecture.md` §1.5) and amortises the read.
Consequence of this placement: the snapshot is taken at **job start**, so L2 sees Observations from **prior phases only**, never from sibling pods in the same job - consistent with the design's no-intra-phase-crosstalk stance (pods converge through `MERGE`, not shared state).

**How it stays bounded.** `macro_kind` + `severity` only, capped count, priority-ordered so the anchor line survives truncation - the §4.3 budget carries over verbatim.

**The output question.** If the triager concludes "recon on this target is incomplete," what does it emit?
Either a new coverage-gap `Observation` (informational, sits in the graph) or a signal routed onward to L3's re-entrant interface (actionable re-probe).
This is where L2 stops being independent and feeds L3 - see §5 and grey point Q3.

---

## 4. L3 - to the root pipeline: macro synthesis for targeted extension

> **RESOLVED (A5, A3).** The **core phase DAG always runs** unchanged. After its final barrier, a new root step **synthesises** the run's Observations (+ coverage gaps + L1 signals) into a bounded macro digest, then **plans finding-triggered extensions**: deterministic rules turn findings into candidate probes (GraphQL introspection enabled -> nuclei GraphQL tag set; JWT observed -> JWT-decode tool; ...), and an **LLM ranks/prunes them to a hard request cap** (Q5 option (c), confirmed). Each surviving candidate is dispatched through the **D2 re-entrant targeted-recon interface**, reusing the existing pod machinery. **Fail-open (A3):** the extension loop is single-pass and capped; a probe that cannot succeed (or whose host L1 marks walled) is recorded as degraded and the loop moves on / terminates - the run always reaches `set_run_status(..., "complete")`. See `context-memory-end-to-end.md` §5 for the candidate/request contracts and §7 for the stop condition.

**Consumer.** A **new** synthesis/decision step at the root, running *after* the phase DAG completes and *before* `set_run_status(..., "complete")`.

**What it contains.** A macro, architectural read of the run: the Observation set aggregated and synthesised (not dumped) - e.g. "app.example.com exposes an introspection-enabled GraphQL API and an unauthenticated admin surface; the WAF only guards `/api`; 40 endpoints, 12 parametrised, 0 fuzzed under auth."
This is a **higher altitude than any single Observation**; it is a synthesis over them plus the L2 coverage gaps.

**What it drives.** The decision of **where to go deep**: which specific attack-surface areas warrant a narrow, targeted probe outside the linear plan.
This is exactly the re-entrant targeted-recon interface `recon-pipeline-forward-decisions.md` **D2** defines, and the on-demand `nuclei` entry point.
L3 is the *caller* of that interface: macro picture in, targeted `{component, template/tag set}` recon requests out, resulting assets/observations merged back.

**Where it is sourced from.** Neo4j Observations (the whole run's, aggregated) + the L2 coverage-gap signals + the L1 `recon_signals` (a WAF-guarded area is a "go deep here, differently" cue).
All three tiers feed L3; it is the confluence.

**Where/when it is built.** At the root, as a terminal pipeline phase after the DAG barrier of the last phase.
It requires introducing the pipeline's **first reasoning step** - today `run_pipeline` is purely deterministic.

**How it stays bounded.** Synthesis, not enumeration: counts by type/severity, the top-k anchors by severity, and the coverage gaps - never the full Observation list.
Its output is a **bounded list of targeted-recon requests** (capped), each a D2 call, not an open-ended plan.

---

## 5. The scaffolds are not independent - the implicit data flow

The operator presents three parallel scaffolds.
They are three *consumers*, but they sit on only **two source substrates** and they **feed each other**:

- **Sources.** L2 and L3 both draw from **Observations** (L2 = one anchor's slice; L3 = the whole run's synthesis) - the same substrate at two zoom levels. L1 draws from a **different, not-yet-existing** substrate (operational signals). So "three distinct scaffolds" is really *two substrates, three views* - and one substrate is missing.
- **Flow.** L2's completeness verdict is the natural input to L3's "where to go deep" decision (a gap found per-target aggregates into the macro picture). L1's operational signals also feed L3 (a WAF-guarded area is a targeted-probe candidate). So the honest topology is a **funnel**: `L1 signals + L2 per-target gaps -> L3 macro decision -> D2 targeted re-probe`, not three parallel lanes.

Stating this explicitly matters because it changes the build order (§7) and because it exposes grey point Q3 (is L2's verdict informational or actionable).

---

## 6. Critical evaluation (stress-test, not rubber-stamp)

Applying the critical-thinking discipline to the integrated L1/L2/L3 model.
The conclusion up front: **the three-level model is sound and a real improvement on the one-hop heuristic, but two of the three levels rest on substrate and detection that do not exist, and the operator's framing hides a target-keying imprecision and an inter-level data flow.**
No fatal circularity was found - the phase barrier saves it - but several load-bearing assumptions are unstated.

### 6.1 The circularity question - answered: there is none, but the barrier is load-bearing

The obvious worry ("does L1 need signals that only exist after the jobs it is meant to inform?") **does not hold**, and it is worth stating plainly so no one re-litigates it.
The phase DAG runs behind a hard barrier (`pipeline.run_pipeline`, `recon-mvp-design.md` §3): phase `i+1` does not start until every phase-`i` job returns.
So earlier-phase failure signals (L1) and earlier-phase Observations (L2) **exist before** the later phases that consume them.
Likewise L3 runs strictly *after* the whole DAG.
The flow is a strict DAG in phase order - forward, acyclic, not circular.

The caveat: this non-circularity is **entirely dependent on the barrier**.
It also means **same-phase jobs cannot inform each other** (they run concurrently via `asyncio.gather`).
If subfinder and amass both hit rate-limits in phase 0, neither can configure the other.
L1 cross-job learning is really **cross-phase** learning; the operator's "earlier jobs" should read "earlier *phases*."

### 6.2 Hidden assumption 1 (L1): the signals L1 consumes are neither detected nor stored today

L1 assumes a durable record of WAF-blocks / rate-limits / auth-walls exists to read.
It does not - on two counts:

- **Not stored.** `PodExport` carries `verdict` + `error` + coarse `stats`; these roll into the Postgres registry as job status. The *specific* operational signal lives in `exec_result.stderr`/`stdout`, which is transient `PodState` and is **discarded** when the pod exports. No tier holds "host H was WAF-blocked."
- **Not even detected.** The pod's `gate` branches only on `returncode == 0 && non-empty stdout` (`pod.py`). A WAF returning an HTTP 200 block-page, or `httpx` reporting a 403, is `returncode 0` - i.e. **"success"** - and flows to the parser as if nothing were wrong. The exact failure modes L1 is meant to prevent are **invisible** to the current control loop.

So L1 needs *two* new pieces, neither trivial: a **detector** (heuristic or LLM classifier over tool output that recognises "this was blocked/throttled/walled") and a **store** (`recon_signals`).
This is the single biggest feasibility gap in the operator's argument.
It is fixable, but it is net-new machinery, not a context-plumbing change.

### 6.3 Hidden assumption 2 (L1): the configurator can act on the advice

Even given detection + storage, L1 changes nothing unless the configurator exposes operational knobs (rate/delay/UA/proxy/backoff).
Templates are fixed by design (§1.1 of the taxonomy).
L1 presupposes a **tunable-configurator surface the design has deferred**.
Without it, L1 is a well-informed recommendation into a component that can only fill `{target}`.

### 6.4 Hidden assumption 3 (L1): job-keyed vs target-keyed

The operator frames L1 as "failures from earlier jobs."
But the per-job orchestrator fans out **per asset**, and the failure modes cited are **host-scoped**.
A WAF block on `app.example.com` during `httpx` is relevant to `arjun`'s pod on `app.example.com/login` but irrelevant to `arjun`'s pod on a *different* subdomain.
Useful L1 must be **target/host-keyed**, joined to each pod's asset - not a job-global blob.
This is an imprecision in the framing, not a fatal flaw, but it materially changes the `recon_signals` schema (must key on host) and the digest logic (must filter per pod_input).

### 6.5 Hidden assumption 4 (L2): "completeness" needs a baseline, or it is the rejected heuristic

L2 asks the triager to judge "did we gather *enough*."
"Enough" is meaningless without a model of expected coverage.
If that judgement is left to free LLM reasoning, L2 **is a heuristic** - precisely what the operator rejected for the one-hop builder.
To be grounded, L2 must anchor completeness in something explicit: the DAG's `consumes`/`produces` structure, or a per-asset-type coverage checklist (Q2).
This is the sharpest internal-consistency point: the correction that rejects heuristics must not re-introduce one at L2.

### 6.6 Hidden assumption 5 (L2 -> triager scope creep)

The MVP triager is deliberately "**adds observations only**" (`recon-mvp-design.md` §9).
L2's "grounded completeness evaluation" is a **new behaviour and likely a new output** (a coverage-gap signal).
Either the triager's contract widens (it now emits coverage verdicts, not just findings), or a new role owns completeness.
Left unstated, this silently overloads the triager - the same class of under-specified-contract problem that produced the anchor-allowlist bug.

### 6.7 Hidden assumption 6 (L3): "macro architectural observations" do not exist as data

Observations are per-anchor security findings.
"Macro architectural" is a *synthesis* over them (an emergent, cross-anchor picture) that no node type holds.
L3 needs either a synthesis step over the Observation set or a new "macro observation" concept.
Plus L3 introduces the pipeline's first reasoning step (it is deterministic today).
Neither is a blocker, but both are net-new, and "give L3 macro observations" reads as if they were sitting in the graph ready to query - they are not.

### 6.8 What is genuinely strong

- L2 is well-founded and mostly already designed (§4 of the prior doc); refocusing it on Observations + completeness is a clean, correct sharpening.
- L3 ties cleanly and non-circularly to an already-decided seam (D2); it is the right home for the "go deep" decision.
- The level-per-consumer decomposition is correct: the three roles genuinely need different context, and the one-hop heuristic genuinely served none of them well.
- No circularity: the barrier makes the whole thing a forward DAG.

---

## 7. Build-order consequence

Because the scaffolds funnel (§5) and rest on uneven substrate maturity, they should **not** be built together:

1. **L2 first.** Its substrate (Observations) exists; it is a refocus of already-designed code; it closes the live anchor bug; and it produces the coverage signal L3 later needs. Lowest risk, highest immediate value.
2. **L3 second.** Consumes L2's output, targets an already-decided interface (D2). Needs a new root reasoning step but no new store.
3. **L1 last.** Needs the most net-new machinery (a detector, the `recon_signals` store, and a tunable-configurator surface). Highest risk, and it is an *optimisation* (avoid repeating failures) rather than a *correctness* fix, so it earns its place behind the two that improve graph quality directly.

> **RESOLVED update to §7.** A1 and A4 collapse two of L1's three blockers: the **detector is the existing triager** (no new node) and there is **no tunable configurator** (removed from scope). L1's only net-new store is `recon_signals`, and its only net-new behaviour is enabling the job-agent LLM preprocess. L1 is therefore *substantially cheaper* than this ordering assumed - but the build order (L2 -> L3 -> L1) still holds, because L2 and L3 remain the correctness-improving levels and L3 consumes L2's `coverage_gap` output. L1 stays last as an optimisation, now a much smaller one.

---

## 8. Grey points - RESOLVED (operator answers A1-A5, 2026-07-06/07)

The five grey points below are now decided. Each retains its original framing and options for the record, with the operator's resolution appended in bold. The mechanics of each resolution are traced end-to-end in `context-memory-end-to-end.md`.

### Q1 - Where do L1's operational signals live, and who detects them?

**Grey point.** L1 has no source: WAF/rate-limit/auth-wall signals are neither detected (the gate treats a 403/200-block as success) nor stored (`exec_result` is transient). This blocks L1 entirely.
**Why it blocks.** Without a detector + a store, L1 is unimplementable; the shape of both (schema, keying, who runs the classifier) determines the pipeline read L1 depends on.
**Options.**
(a) New Postgres control-plane table `recon_signals(run_id, host, kind, evidence, phase, observed_at)`, populated by a lightweight **heuristic detector** in the pod gate (status-code + block-page fingerprints).
(b) Same table, but populated by an **LLM classifier** node (higher recall on subtle blocks, costs a call per pod).
(c) Reuse the existing registry `stats` JSONB - no new table, coarser signal.
**Recommendation. (a)** - control-plane table + heuristic detector. It matches the "operational, not domain" nature of the signal, keeps it out of Neo4j, and a heuristic gate check is cheap and deterministic; escalate to (b) only for job families where subtle blocks matter. Cross-run durability (learn across runs, like the graph does) is a follow-on toggle on the same table.
**RESOLVED (A1): the store is the new Postgres table (a), but the detector is the existing pod triager, not a gate heuristic.** The triager is already an LLM per pod; it detects the block while judging the tool output and writes a sparse signal to `recon_signals(run_id, host, kind, evidence, source_tool, phase, observed_at)`. This is effectively option (b)'s "LLM classifier" *at zero marginal cost* (no new node - the triager already runs). The `recon_signals` shape stays host-keyed (§6.4). Signals are per-run now; cross-run durability remains the deferred follow-on toggle.

### Q2 - What is L2's completeness baseline?

**Grey point.** "Did we gather enough on this target" needs a definition of *enough*, or L2 becomes the heuristic the correction rejects.
**Why it blocks.** The baseline choice determines whether L2 is grounded and what the triager's prompt/skill must encode.
**Options.**
(a) **Structural**: completeness = every DAG job whose `consumes` matches this asset's type has run and produced >0 assets. Derivable from the phase plan + graph; fully deterministic.
(b) **Checklist**: an explicit per-asset-type coverage schema (e.g. a `BaseURL` should have tech + endpoints + params + headers + auth-surface); richer, but hand-maintained.
(c) **Free LLM judgement** - rejected (it is the heuristic).
**Recommendation. (a) now, (b) later.** Structural coverage is grounded, free, and immediately available; layer the checklist on when asset volumes justify the maintenance. Explicitly rule out (c).
**RESOLVED (A2): (c) minimal LLM judgement now; (a)/(b) deferred.** The operator chose the minimal path deliberately: keep L2 an LLM judgement with the existing anchor-Observations slice as its only grounding, and defer structural/checklist grounding. This knowingly leaves §6.5's tension open in the short term (the "completeness" judgement is not yet grounded in a coverage model); it is accepted because L2 minimal is additive and the *actionable* consequence is bounded by L3's fail-open cap (A3), so an over- or under-confident verdict cannot cause runaway probing. The future grounding path is the **analyser -> probing-request** re-entrant interface (an analyser agent, with a richer coverage model, issues explicit D2 requests) - flagged as a validation item in the end-to-end doc.

### Q3 - Is L2's completeness verdict informational or actionable?

**Grey point.** When the triager finds a coverage gap, does it write a coverage-gap `Observation` (sits in the graph) or emit a re-probe signal routed to L3's D2 interface (triggers targeted recon)?
**Why it blocks.** This decides whether the three scaffolds are parallel or a funnel (§5), and whether the triager's output contract widens beyond "add observations."
**Options.**
(a) **Informational** - a `coverage_gap` Observation; L3 reads it during synthesis. Minimal contract change; decoupled.
(b) **Actionable** - a first-class re-probe request queued for L3. Tighter loop, but couples the triager to the D2 interface and widens its contract.
(c) **Both** - write the Observation *and* let L3 decide whether to act.
**Recommendation. (c)** - the triager emits a `coverage_gap` Observation (grounded, auditable, in the authoritative store), and L3 owns the act/don't-act decision from the aggregate. This keeps the triager's job additive (it still only writes Observations) and keeps the "where to go deep" judgement at the one level that has the macro picture.
**RESOLVED (A3): (c) - both, with a fail-open guarantee.** The triager writes the `coverage_gap` Observation (informational, in Neo4j); L3 owns whether to act. The added constraint from A3: when L3 *does* act and the resulting targeted probe cannot succeed, the **root stops that extension line gracefully** rather than re-queuing or blocking. So the loop is `L2 gap Observation -> L3 aggregate decision -> capped D2 probe -> fail-open on failure`. The funnel of §5 is confirmed as the topology.

### Q4 - Does L1 require the deferred tunable configurator, or can it ship inert?

**Grey point.** L1 advice is useless unless the configurator can act on it (rate/UA/proxy knobs), but the tunable configurator is deferred and templates are fixed by design.
**Why it blocks.** It sets L1's true scope: a context change alone, or a context change *plus* re-opening the configurator surface.
**Options.**
(a) **Defer L1 entirely** until the tunable configurator exists (honest, matches §7's "L1 last").
(b) **Ship a minimal knob set now** - `{delay, user_agent, retry_backoff}` threaded through `extra` into a small set of auth/active-HTTP templates - and grow it.
(c) **Route-level only** - L1 can cause a job to *skip* a host it knows is walled, without tuning (a coarse but real action).
**Recommendation. (a) with (c) as the cheap interim.** Full L1 waits for the tunable configurator (do not build a detector whose output nothing can use); but a coarse "skip/deprioritise a known-walled host" action is nearly free and delivers L1's core promise (don't repeat the failure) without re-opening the template surface.
**RESOLVED (A4): no tunable configurator - the action lives in the job-agent's pod distribution, i.e. option (c) generalised.** The operator ruled out re-opening the template surface entirely. Templates stay fixed; the configurator keeps filling only `{target}`/`{domain}`/`{baseurl}`/`{session}`/`{auth_header}`. L1's actionability moves up a level: the **job-agent's LLM preprocess is enabled** and fed the L1 digest, and it acts by shaping the **pod set** - skip/deprioritise/dedup the hosts a prior phase found walled, spend the `MAX_PODS` budget on hosts likely to yield. This makes L1 buildable *now* (no deferred configurator dependency), at the cost of enabling an LLM call in preprocess - flagged as a validation item (cost/latency) in the end-to-end doc.

### Q5 - Does L3 introduce an LLM reasoning step in the pipeline, or stay heuristic?

**Grey point.** The pipeline is deterministic today; L3's "decide where to go deep" is a reasoning task. Making the root an LLM agent is a significant architectural commitment.
**Why it blocks.** It determines whether `run_pipeline` gains a model dependency and how L3's output (targeted-recon requests) is bounded and validated.
**Options.**
(a) **LLM synthesis step** at the root - richest "where to go deep," but the pipeline now depends on a model and must bound/validate its requests.
(b) **Deterministic rules** over the Observation aggregate (e.g. "GraphQL introspection enabled -> queue the graphql nuclei tag set") - auditable, no model, but only as good as the rules.
(c) **Hybrid** - deterministic candidate generation, LLM ranking/pruning under a hard request cap.
**Recommendation. (c)** - deterministic rules propose targeted-recon candidates (keeps the pipeline's best-effort determinism and gives D2 a validated `{component, template set}`), an LLM ranks/prunes to a capped shortlist. This bounds the model's authority (it cannot invent arbitrary scans, only rank pre-validated ones) and keeps the root robust.
**RESOLVED (A5): (c) - hybrid, confirmed.** A core DAG that always runs, plus finding-triggered extensions where deterministic rules generate candidates from findings and an LLM ranks/prunes under a hard request cap. The LLM cannot invent scans - only rank pre-validated `{component, tool, template_set}` candidates. This is the D2 re-entrant interface; the concrete rule registry, candidate/request contracts, and cap live in `context-memory-end-to-end.md` §5.

---

## 9. Summary

Three consumers, two source substrates, one funnel.
L2 (triager, completeness against a grounded baseline) is ready to build and closes the live anchor bug; L3 (root synthesis -> D2 targeted extension) is the right home for "go deep" and ties to a decided seam; L1 (per-job orchestrator, cross-*phase* failure-avoidance) is the most valuable idea and the least buildable today - it needs a detector, a store, and a tunable configurator that none of the current design provides.
The model is not circular (the phase barrier makes it a forward DAG), but it rests on that barrier, cannot learn intra-phase, must key L1 on host not job, and must not let L2's "completeness" or L3's "macro observations" smuggle the rejected heuristic back in.
Build L2 -> L3 -> L1, and resolve Q1-Q5 before committing to L1's plumbing.
