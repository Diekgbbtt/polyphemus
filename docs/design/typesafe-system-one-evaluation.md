# TypeSafe System One Use-Case Evaluation for polymerhus

*Status: RESEARCH/EVALUATION, 2026-09-17. This document is a proposal, not a ratified decision. No design spec is amended by it. Where a use case below would contradict a ratified spec, the conflict is flagged explicitly by spec name.*

## 1. Scope and method

Scope is the full agent inventory of the statefulness pattern matrix (`docs/design/statefulness-pattern-matrix.md`), crossed against the TypeSafe System One decision model.

Method followed the research skill (`/Users/diekgbbtt/.claude/skills/research/SKILL.md`): primary sources only, every claim traced to the page that owns it.

Part A grounded in the repo first: the matrix, `CONTEXT-MAP.md`, all six context glossaries (`src/polymerhus/recon/CONTEXT.md`, `src/polymerhus/analysis/CONTEXT.md`, `src/polymerhus/project_management/CONTEXT.md`, `src/polymerhus/attack/CONTEXT.md`, `src/polymerhus/attack/hunting/CONTEXT.md`, `src/polymerhus/attack/exploit/CONTEXT.md`), the reasoned ontology (`docs/design/domain-model.md`), the role-architecture and hunting design docs, then the implementation seams themselves (prompts, output schemas, loop bodies, not filenames).

Part B read the TypeSafe docs in the mandated order: primer, System One concept, how-to-build, patterns index, composite scoring, confidence routing, fan-out, primitives index, then the owning pages via `https://docs.typesafe.ai/llms.txt` (`/primitives/choice`, `/primitives/score`, `/primitives/noul`, `/confidence`, `/concepts/state`, `/api`, `/models`, `/sdk`, `/model-jaggedness/jev-1.13`).

No page failed to fetch, so no curl or steel-browser fallback was needed and no second-hand source was substituted.

Each TypeSafe claim below is cited to its `docs.typesafe.ai` URL. Each repo claim is cited `file:line`. Judgments marked INFERENCE are the author's synthesis, not sourced fact.

## 2. Executive summary

The highest-value use cases are the fixed-taxonomy classifiers that already emit a schema today: the Assigner ownership judgment, the anatomy webpage-profile classifier, the pod triager terminal decision, the hunt-orchestrator gate and re-match verdicts, and the sweep stale-ownership proposer.

The strongest non-candidates are the looped environment-interacting agents: the agentic crawler, the pod runner probe loop, the hunting-hunter spec author, the Bootstrapper reasoning pass, and the mechanism-typist reflection plus system-minting chain.

The recurring high-leverage shape is confidence routing: System One returns a calibrated distribution, code thresholds it, low-confidence cases escalate to the existing generative turn, so the current LLM path becomes the fallback rather than being deleted.

The recurring guardrail is the envelope asymmetry (`docs/design/domain-model.md` section 4.3): graded confidence is reserved for `AGGREGATES` alone, so System One scores must drive routing and gating in code and must never be persisted onto `SURFACES_AT` or `EVIDENCED_BY`.

The cheapest first experiment is the Assigner ownership Choice on a recorded chunk batch, scored against the existing `evaluation.bar_sweep` curve with zero production wiring.

## 3. The model: what System One and Jev are and are not

System One models make fast structured decisions for software, and Jev is TypeSafe flagship model and the first System One model (https://docs.typesafe.ai/concepts/system-one).

A System One model evaluates a state and returns typed answers and probabilities (https://docs.typesafe.ai/concepts/system-one).

Like an LLM it understands natural-language input, but it returns typed decisions and probabilities rather than generated text (https://docs.typesafe.ai/concepts/system-one).

It does not write replies, produce code, or generate explanations of its reasoning (https://docs.typesafe.ai/concepts/system-one).

Training is RLCD (reinforcement learning for calibrated decisions), which trains the model to return decisions and calibrated probabilities instead of generated text (https://docs.typesafe.ai/introduction/machine-learning-primer).

Calibration means outcomes assigned probability 0.2 should occur about 20 percent of the time across groups of predictions, and the same logic holds at 0.8 and 1.0 (https://docs.typesafe.ai/introduction/machine-learning-primer).

Calibration is measured across groups of predictions and does not guarantee that any individual answer is correct (https://docs.typesafe.ai/concepts/system-one).

RLHF optimizes for responses people prefer and can reward sycophancy and confident-sounding hallucinations, while RLVR produces strong but slower and more expensive reasoning models (https://docs.typesafe.ai/introduction/machine-learning-primer).

The composable properties are structured output, parallel independent evaluation, comparability, speed, calibrated confidence, and self-consistency (https://docs.typesafe.ai/concepts/how-to-build-with-system-one).

Most queries complete in about 100 ms, which makes the model fast enough for real-time request paths (https://docs.typesafe.ai/concepts/how-to-build-with-system-one).

Pricing is per input token only (output tokens are free), currently $42 per Btok and $0.042 per Mtok for `jev-1.13.0` (https://docs.typesafe.ai/models).

Rate limits are 250000 tokens per second and 1200 requests per minute, and the docs warn these adjust dynamically under load (https://docs.typesafe.ai/models).

The SDK default model alias is `jev-latest`, currently pointing at `jev-1.13.0`, and the response `model` field reports the versioned ID that answered (https://docs.typesafe.ai/models).

### 3.1 State construction

State is the content the model evaluates, passed in the `state` field alongside the questions (https://docs.typesafe.ai/concepts/state).

State may be a string, a JSON object, or an array of text, and Jev currently accepts text input only with no image, audio, or video support (https://docs.typesafe.ai/concepts/system-one, https://docs.typesafe.ai/concepts/state).

Objects are preferred for most requests so each part has a descriptive name, and questions reference nested values with backticked dot-and-index paths such as `` `ticket.messages[0].text` `` (https://docs.typesafe.ai/concepts/state, https://docs.typesafe.ai/primitives).

The build guidance is to include only the context relevant to the current questions, because unrelated detail acts as a distractor (https://docs.typesafe.ai/concepts/how-to-build-with-system-one, https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Context budgets are 64k tokens for all state plus questions together, and 32k tokens for state plus the longest question (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

### 3.2 The three primitives and their response fields

Choice selects one option from a defined set of up to 255 options, and returns `choice` (highest-probability option), `probabilities` (distribution summing to 1), and `confidence` (https://docs.typesafe.ai/primitives/choice, https://docs.typesafe.ai/primitives).

Score rates content against an ordered array of 2 to 10 descriptive levels, and returns `score` (probability-weighted position, possibly fractional), `legend`, `probabilities`, and `confidence` (https://docs.typesafe.ai/primitives/score, https://docs.typesafe.ai/primitives).

The Score `score` is the level numbers weighted by their probabilities and summed, for example 0 x 0.0 + 1 x 0.70 + 2 x 0.30 = 1.30 (https://docs.typesafe.ai/primitives/score).

Noul answers a yes or no question with a single number `noul` from 0 to 1, the probability the answer is yes, and it carries no separate `confidence` field (https://docs.typesafe.ai/primitives/noul, https://docs.typesafe.ai/primitives).

Question IDs are caller-chosen keys, answers return under the same IDs, and the model never sees the IDs (https://docs.typesafe.ai/primitives, https://docs.typesafe.ai/api).

Every answer is constrained to the supplied options, so the model returns a distribution over them and code never recovers a value from prose (https://docs.typesafe.ai/primitives).

Every question in one request sees the same state, is evaluated independently, and can be added or removed without changing the others (https://docs.typesafe.ai/primitives).

The HTTP surface is `POST /v1/systemone` with `state`, `model`, and `questions`, and typed client SDKs exist for Python and JavaScript with automatic retry handling (https://docs.typesafe.ai/api, https://docs.typesafe.ai/sdk).

### 3.3 Confidence and calibration semantics with documented limits

Confidence is a statistic computed from the answer probability distribution, returned on every Choice and Score answer so the common case needs no extra math (https://docs.typesafe.ai/confidence).

A flat distribution means low confidence and a single peak means high confidence, and low Score confidence usually means overlapping levels, a multi-dimensional question, or insufficient state (https://docs.typesafe.ai/confidence, https://docs.typesafe.ai/primitives/score).

Callers are never locked into the built-in definition because the full `probabilities` are always returned for custom measures (https://docs.typesafe.ai/confidence).

Noul near 1 is strong yes, near 0 is strong no, and near 0.5 gives yes and no similar probability (https://docs.typesafe.ai/primitives/noul).

A Noul of 0.5 does not mean a medium level of anything, so skill level must be a Score with defined levels, never a Noul (https://docs.typesafe.ai/primitives).

Documented limits: calibration describes groups of predictions, never a single answer, and confidence 1.0 describes the answer distribution, not a guarantee of correctness (https://docs.typesafe.ai/concepts/system-one, https://docs.typesafe.ai/primitives/score).

Thresholds must be fit to the domain on the operator own data, starting conservative and adjusting with observation (https://docs.typesafe.ai/confidence).

### 3.4 Composite scoring

Composite scoring splits a complex judgment into independent Score dimensions, normalizes each to 0-1, and combines them with weights controlled in code (https://docs.typesafe.ai/patterns/composite-scoring).

Each Score question keeps one dimension, because a level description measuring three things at once cannot place an input high on one and low on another (https://docs.typesafe.ai/primitives/score).

Levels must describe situations, not degrees, and every level is evaluated separately with no knowledge of its number or neighbours (https://docs.typesafe.ai/primitives/score).

Scores must not be used to reconstruct exact magnitudes by interpolating between levels, because score levels are weak in numerical calibration (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

### 3.5 Confidence routing

Confidence routing uses the answer as the what and the confidence as the whether-to-act, with a floor catching genuine uncertainty and per-action thresholds scaled to the stakes (https://docs.typesafe.ai/patterns/confidence-routing).

The documented pattern is three bands: high confidence acts automatically, medium confidence proceeds with confirmation or review, low confidence routes to a human or fallback (https://docs.typesafe.ai/confidence).

A read-only action can proceed at moderate confidence while a destructive action needs very high confidence plus confirmation (https://docs.typesafe.ai/patterns/confidence-routing).

### 3.6 Fan-out

Fan-out sends many questions in a single call, including speculative ones whose answers only matter for some inputs, and code decides afterward what is relevant (https://docs.typesafe.ai/patterns/fan-out).

Questions in one request evaluate in parallel, so adding questions barely changes latency and costs only the extra question tokens (https://docs.typesafe.ai/primitives, https://docs.typesafe.ai/patterns/fan-out).

One cookbook reports batching 13 questions into one call at 12.2x cheaper and 10.0x faster with no change in answers (https://docs.typesafe.ai/primitives).

When one judgment genuinely depends on another answer (needs it to fetch data, build state, or pick options), a second request in code is correct, but that is the exception rather than the rule (https://docs.typesafe.ai/primitives).

### 3.7 The how-to-build workflow

The workflow is to keep control flow, deterministic rules, and side effects in code, decompose broad judgments into narrow atomic typed questions, give each question only the context it needs, and route on uncertainty (https://docs.typesafe.ai/concepts/how-to-build-with-system-one).

Decomposition into atomic questions is named as probably the most important concept in the guide, because broad questions hide several judgments behind one answer (https://docs.typesafe.ai/concepts/how-to-build-with-system-one).

The worked support-ticket example composes a Choice topic, Noul signals, and a Score frustration with weights and confidence gates in ordinary `if` statements (https://docs.typesafe.ai/concepts/how-to-build-with-system-one).

### 3.8 When NOT to use System One (documented)

Generation is out: Jev is not trained to generate text, chaining choices to force generation works poorly and slowly, and extraction should become a Choice over options produced by regex or a generative model (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

System Two tasks are out: multi-hop indirection, double negatives, and properties of properties cost accuracy, so instructions must be direct and state references explicit (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Anything code computes exactly stays in code: counting, arithmetic, date ordering and duration, and numeric nearness judgments (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

One-question-per-judgment is required: a question hiding several judgments must be split and combined in code (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Oversized state is out: accuracy falls as unrelated detail grows, so retrieve and filter in code first (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Adversarial content is a known weakness: Jev does not treat state as hostile by default, so criteria must be explicit and integrations tested before deployment (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Literal reading is the default: the model answers the written question, not the intended one, so boundary cases belong in the criteria (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

## 4. Per-agent analysis

Role registry facts used throughout: roles are `Role(role_id, model_key, agent_mode, thinking)` records (`src/polymerhus/app/llm/providers.py:298-306`).

App-boot roles list the recon and analysis agents (`src/polymerhus/app/llm/providers.py:326-339`).

Hunting roles are separate (`HUNTING_ROLES`, `src/polymerhus/app/llm/providers.py:349-354`) and validated at hunting bootstrap, never app boot.

Session agents run through `stateful_turn` or `arun_session_turn` on checkpointer threads, and one-shot agents run through `invoke_role` (matrix legend, `docs/design/statefulness-pattern-matrix.md:15-16`).

### 4.1 Recon configurator (pod)

Generative role today: per-pod throttle decision returning `PodConfig{rate_profile, rationale}` with `rate_profile` in `{default, throttle}`, via `stateful_turn("configurator", ...)` when a pod session context is bound else `invoke_role("configurator", ...)` (`src/polymerhus/recon/domain/pod.py:701-751`).

The prompt is the job command template plus input asset plus live steering signals, and failure degrades to `None` so the pod runs at default rate (`src/polymerhus/recon/domain/pod.py:718-751`).

Subproblems: (S1) read steering signals for host-specific throttle evidence, (S2) decide `default` versus `throttle`, (S3) write a rationale sentence.

Q1: S2 is a decision over a predefined 2-option set (yes). Q2: S2 resolves from the template, asset, and signals already in context with no environment call (yes). Q3: the turn makes no tool call and iterates nothing (no).

Verdict: S2 is a System One candidate (Choice of 2), S3 rationale is generative text Jev cannot produce (rejected subproblem, keep as code-side constant or drop).

INFERENCE: quality comes from matching signal text against the target host, which is a snap judgment over supplied context.

### 4.2 Recon triager (pod)

Generative role today: reads tool stdout plus parsed asset deltas and returns `_ObservationBatch{observations}` where each Observation carries adversarial NL insight plus anchor, macro_kind, severity, evidence, rationale (`src/polymerhus/recon/domain/pod.py:754-808`, `src/polymerhus/recon/domain/pod.py:639-673`).

The system prompt is the writing-observations skill, assets are capped at `_MAX_TRIAGE_ASSETS` with sampling, and parse failure degrades to no observations (`src/polymerhus/recon/domain/pod.py:676-808`).

Subproblems: (S1) decide whether anything in this tool output is noteworthy, (S2) select which items merit insight, (S3) author the adversarial insight prose plus anchor and severity.

Q1: S3 is open NL authorship over an unbounded answer space (no). Q2: S3 needs judgment over novel tool output, but that is not the blocker. Q3: authoring quality insight prose is the load-bearing generative act (yes, generative).

Verdict: full replacement rejected; S1 is a Noul gate candidate and per-observation severity is a Score candidate, both as augmentation around the kept generative turn.

INFERENCE: the triager is the highest-volume LLM call in recon (one per pod), so even a gate that skips empty turns has large token leverage.

### 4.3 ReconOrchestratorActor and legacy decide_routing

Generative role today: per-run mailbox actor on the `job_orchestrator` session thread (`OrchestratorSession(run_id)`), fed each phase steering signals and replying a structured `RoutingDecision{exclusions, rationale}` on the same thread (`src/polymerhus/recon/control/orchestrator_agent.py:103-247`).

The prompt frames cross-job routing of WAF-flagged hosts away from request-based crawlers toward the agentic crawler, and failure maps to the neutral `{}` decision (`src/polymerhus/recon/control/orchestrator_agent.py:44-94`).

Subproblems: (S1) decide whether each flagged host is genuinely WAF-relevant, (S2) decide per (job, host) pair whether to exclude, (S3) emit the minimal exclusion map plus rationale.

Q1: S3 as a whole is combinatorial over jobs times hosts, not a predefined finite set (no as posed). Q2: S1 and S2 resolve from the formatted signals plus `describe_job_kind` context with no fresh probing (yes). Q3: no tool call or iteration inside the turn (no).

Verdict: S2 decomposes into per-pair Noul fan-out (candidate), S1 is a Noul relevance filter (candidate), S3 rationale is generative (rejected).

INFERENCE: the actor memory across phases is the feature the stateless legacy seam lacks, so any replacement must preserve the per-run thread, not just the per-turn decision.

### 4.4 Crawl agent (agentic crawler)

Generative role today: vendored async ReAct loop driving steel browser tools (`steel_crawl_start`, `steel_navigate`, `steel_frontier`, `steel_eval`, `steel_click`, `steel_await_auth`, `steel_crawl_finish`) with a credentialed-login branch and a pre-loop tool-calling capability gate (`src/polymerhus/recon/crawl/crawl_agentic.py:1-100`).

Subproblems: (S1) navigate and operate a live browser session, (S2) observe page results and adapt the frontier, (S3) decide when the crawl is complete.

Q1: navigation choices are unbounded and state-dependent (no). Q2: nothing is decidable without interacting with the live target (no). Q3: long-horizon tool interaction with observation and iteration is fundamental (yes).

Verdict: rejected outright; this is the canonical System Two loop the jaggedness page excludes.

### 4.5 Analysis assigner

Generative role today: sole owner of the `AGGREGATES` hinge, classifying streamed Endpoints onto existing Services with per-edge confidence and evidence refs, shaped by `narrow_to_assignment`, `resolve_l0_refs`, `drop_out_of_inventory`, `normalise_confidence`, `withhold_below_bar` (`src/polymerhus/analysis/assigner.py:520-561`, analysis CONTEXT Assigner entry).

Production invokes the `assigner` session role per run via `stateful_turn` with `ToolStrategy(L1DeltaBatch)` (`src/polymerhus/analysis/assigner.py:578-609`).

Subproblems: (S1) match endpoint path nouns against each candidate `service_contract`, (S2) pick the owning service slug from the live inventory, (S3) grade confidence 0-1, (S4) cite evidence refs, (S5) drop out-of-inventory and below-bar proposals deterministically.

Q1: S2 is a Choice over the inventory slug set plus an explicit none-fits option (yes). Q2: S2 resolves from the chunk plus inventory contracts with no tool call (yes). Q3: the turn itself makes no environment call (no).

Verdict: S2 is the strongest full-catalogue candidate (Choice), S3 is a Score or Noul-threshold candidate feeding the existing bar, S5 already lives in code and stays there.

CONFLICT FLAG: the withholding bar lives in the proposer seam, never the sole-writer, per `AMV-14` and `domain-model.md` section 3.2. A System One confidence gate must ride the same seam (`shape_proposal` in `assigner.py`), never move into `l1_curator.py`.

CONFLICT FLAG: graded confidence is reserved for `AGGREGATES` per the envelope asymmetry (`docs/design/domain-model.md` section 4.3). System One probabilities on this path are safe only because they feed that one enveloped edge.

### 4.6 Analysis mechanism-typist

Generative role today: sole owner of mechanism typing, running a three-call chain over each chunk (free-text reflection, structured systems extraction, structured services linking) through the `mechanism_typist` session role (`src/polymerhus/analysis/mechanism_typist.py:390-426`, analysis CONTEXT TechnicalSystem entry).

Subproblems: (S1) hypothesize which Systems the assets evidence (prose reflection), (S2) mint or extend System nodes (open identity space), (S3) link Systems to Services with exact edge labels, (S4) compound System descriptions on extend.

Q1: S2 mints identities outside any predefined set (no). Q2: S1 needs whole-chunk adversarial synthesis (judgment yes, but not finite). Q3: reflection quality is the load-bearing generative act (yes).

Verdict: S1 and S2 rejected (generative, open vocabulary); S3 edge-label selection over the fixed edge vocabulary with verbatim slug copying is a Choice candidate; new-vs-extend per candidate is a Choice candidate.

INFERENCE: the typist is the most expensive proposer (~126s per chunk per the Analysis feed entry), so even partial replacement of S3 has latency leverage.

### 4.7 Analysis data-modeller

Generative role today: sole owner of the Tier-1 data substrate, running reflection plus one structured extraction per chunk through the `data_modeller` session role, with six shaping gates including `enforce_groundedness` and `bind_fields_to_observed` (`src/polymerhus/analysis/data_modeller.py:680-729`, analysis CONTEXT DataPlane entry).

Subproblems: (S1) lift logical DataItems from Parameters, Headers, Secrets (identity minting), (S2) bind `SURFACES_AT` to observed sites, (S3) map `PRODUCES`/`CONSUMES` flows onto settled Services, (S4) propose DataItem-to-DataItem relationships over the six-kind allowlist.

Q1: S1 mints `item_key` identities in open vocabulary (no). Q2: S3 resolves from the chunk plus the live `AGGREGATES` answer (yes). Q3: S1 lifting quality is generative judgment (yes).

Verdict: S1 rejected; S3 owner-join is a Choice candidate over settled service slugs; S4 relationship-kind selection over the six-value allowlist is a Choice candidate; S2 is already near-deterministic shaping and stays in code.

CONFLICT FLAG: the four data proposal shapes deliberately carry no confidence field per the envelope asymmetry (analysis CONTEXT Ground entry). System One scores on S3/S4 must gate in code and must not be persisted as new envelope fields without amending `domain-model.md` section 4.3.

### 4.8 Bootstrapper

Generative role today: two-call pre-analysis phase (free-text five-stage reasoning, then structured shell extraction into Service and System shells), fail-closed on exhaustion, with prompt config settled empirically (`src/polymerhus/analysis/bootstrap.py:880-956`, analysis CONTEXT Bootstrap entry).

Subproblems: (S1) architect-decompose the operator KB into candidate business functions, (S2) expand and ground hypotheses in KB vocabulary, (S3) critically withhold, (S4) extract typed shells from the reasoning.

Q1: S1 invents the service population, which is open vocabulary by design (no). Q2: breadth quality needs whole-KB synthesis no finite context window slice guarantees (no). Q3: the five-stage reasoning is the load-bearing generative act (yes).

Verdict: rejected; call-2 extraction is structured but downstream of generative reasoning, so replacing it saves no reasoning cost.

CONFLICT FLAG: the Bootstrapper is fail-closed by design while System One calls degrade fail-open. Any augmentation here must preserve the blocking behavior, or the `bootstrap.py` fail-closed contract needs explicit amendment.

### 4.9 Anatomy (webpage-profile)

Generative role today: classifies the two independent dimensions `navigation_model` (SPA/MPA/Hybrid) and `rendering_model` (CSR/SSR/SSG/StreamingSSR/HydratedSSR) from a signal bag, returning the triple of classifications, corroborating Observation, and backward-recon probe (`src/polymerhus/analysis/anatomy.py:120-199`).

The fallback prompt pins independence of the two dimensions and the fingerprint-insufficiency rule (`src/polymerhus/analysis/anatomy.py:155-187`).

Subproblems: (S1) classify navigation_model from signals, (S2) classify rendering_model from signals, (S3) set fingerprint-only flags, (S4) author corroborating Observation and probe note.

Q1: S1 and S2 are decisions over fixed closed enums (yes). Q2: both resolve from the assembled signal bag with no live interaction (yes). Q3: the turn makes no tool call (no).

Verdict: S1 and S2 are strong full-replacement candidates (two Choice questions, one fan-out call); S3 is deterministic rule code already; S4 stays generative or becomes template code.

INFERENCE: the fixed enums plus the explicit anti-inference rule (never infer rendering from navigation) make this the cleanest criteria-authoring task in the catalogue.

### 4.10 Curation

Generative role today: proposes `CurationBatch{merges, deletes, relabels, rehome}` over the live inventory plus index cards plus stale pool, with a pairwise-comparison precision guard in the prompt (`src/polymerhus/analysis/curation.py:200-241`).

Subproblems: (S1) judge per unit-pair whether two units are the same mechanism or function, (S2) pick the canonical key, (S3) propose deletes, relabels, rehomes, (S4) enforce the precision guard.

Q1: S1 per pair is a yes-or-no over a finite per-run pair set (yes). Q2: S1 resolves from the two index cards with no environment call (yes). Q3: S3 repair planning and S4 global balancing need whole-graph judgment (partial yes).

Verdict: S1 is a Noul fan-out augmentation candidate feeding the kept generative proposer; full replacement rejected because merge-set coherence is global, not per-pair independent.

INFERENCE: per the fan-out guidance, speculative per-pair questions cost one batched call regardless of inventory size, which removes the pairwise-comparison token scaling worry.

### 4.11 Sweep (stale-ownership)

Generative role today: proposes `StaleOwnershipBatch` placing stale L0 assets onto existing Services or known system kinds, grounded primarily in inventory and secondarily in the kinds enumeration (`src/polymerhus/analysis/sweep.py:120-199`).

Subproblems: (S1) judge per stale asset which existing unit owns it, (S2) fall back to a known system kind, (S3) leave unplaceable assets out.

Q1: S1 is a Choice over existing slugs plus an explicit unplaceable option (yes). Q2: resolves from inventory plus the stale asset record (yes). Q3: no tool call in the turn (no).

Verdict: candidate (Choice, partial or full replacement of `default_stale_propose_fn`).

INFERENCE: this is the Assigner dual for the assets the Assigner withheld or never saw, so both agents can share one Choice harness with different state assembly.

### 4.12 Hunt orchestrator (gate and re-match)

Generative role today: the per-pair hypothesise-ratify-note REASON body runs as graph nodes, with the Q8 gate turn and D2 re-match judge riding one `HuntOrchestratorActor` on the `hunting_orchestrator` thread with union `ToolStrategy(GateDecision | MatchVerdict)` (matrix `docs/design/statefulness-pattern-matrix.md:47`, `src/polymerhus/attack/hunting/llm.py:696-718` per seam names, `src/polymerhus/attack/hunting/hunt_orchestrator.py:169-342` per schema names).

Gate outputs are `GateDecision` and three-valued match verdicts (`applies`, `does-not-apply`, `insufficient-evidence`) consumed as prune signals (hunting CONTEXT match-verdict entry).

Subproblems: (S1) judge fault applicability at the unit from the typed projection plus materialisation content, (S2) emit the three-valued verdict, (S3) elicit vulnerability classes and research direction, (S4) ratify preconditions and observed defences, (S5) write configs and notes via store tools.

Q1: S2 is a fixed 3-option decision (yes). Q2: S1 resolves from the assembled symbolic render plus KB content with no live probing inside the turn (yes). Q3: S3 and S4 concretisation prose is generative (yes for those).

Verdict: S2 is a strong Choice candidate with confidence routing (low confidence feeds the `insufficient-evidence` park path); S3-S5 stay generative and tool-driven.

CONFLICT FLAG: same-class merge and novelty reflection are specified as pure LLM reflection with no module-side output parsing (hunting CONTEXT same-class-merge and novelty-reflection entries). Replacing those reflections with Choice calls contradicts the candidates-rewrite spec unless the spec is amended.

INFERENCE: the deterministic typed applies-if predicate (#63) already prunes the easy negatives, so the System One gate would operate on the filtered remainder where calibration matters most.

### 4.13 Hunting hunter (author and judge lanes)

Generative role today: turn-by-turn ReAct host over the state-graph hunter, one `arun_session_turn` per step on the per-hunt thread, executing tools itself with `hunts_store`, `notes`, `graph_view`, `kb_query`, `exec`, and persisting specs keyed by the 3-part config key (hunting CONTEXT hunting-agent entry).

Subproblems: (S1) decompose the fault class into concrete faults, (S2) author `TestImplementationSpec`s, (S3) drive lifecycle verbatims (`hypothesised`, `verified`, `dropped`, `specified`), (S4) query the methodology KB and interpret results.

Q1: S2 authors open NL bodies with typed bases (no). Q2: S2 needs KB retrieval plus surface evidence plus iterative concretisation (no single sufficient context). Q3: tool interaction plus iteration is fundamental (yes).

Verdict: full replacement rejected; S3 lifecycle transitions are already handled by the deterministic passive state tracker (#164), which is the code-shaped answer to the same need.

CONFLICT FLAG: the #164 passive-lifecycle ruling forbids blocking tool calls on state (hunting-164-state-graph-spec.md section 2.2). A System One lifecycle classifier must do detection and push only, never gate tool calls, or the spec needs amendment.

### 4.14 Test-executor pod runner

Generative role today: pure ReAct plan designer, one `create_agent` turn per stretch with `tools=[exec, note]` plus the KB tool, the P0-P3 stretch plan as system prompt, bounded by `HUNT_POD_MAX_TOOL_CALLS` with dedup and raw recording in the harness (`src/polymerhus/attack/hunting/pod/agents.py:1-100`).

Subproblems: (S1) design probes, (S2) execute against the live target, (S3) observe and interpret results, (S4) decide exhaustion or continuation.

Q1: probe design is open vocabulary (no). Q2: every step needs the live target response (no). Q3: looped feedback-driven execution is definitional (yes).

Verdict: rejected outright; live tool execution between reasoning steps is the exact property System One cannot absorb.

### 4.15 Test-executor pod triager

Generative role today: one `stateful_turn` with `ToolStrategy(TriagerDecision)` reading the verbatim P3 note plus filtered context, deciding `terminate` versus `variant` with binary verdict, Q3-amended terminal reason, and `clean` boolean (`src/polymerhus/attack/hunting/pod/agents.py:41-59`, `src/polymerhus/attack/hunting/pod/agents.py:131-251` per seam name).

The harness guard `validate_decision` enforces the binary verdict vocabulary plus terminal-reason vocabulary deterministically (`src/polymerhus/attack/hunting/pod/verification.py:1-80`).

Subproblems: (S1) classify the stretch outcome into the six-way terminal vocabulary, (S2) decide terminate versus mine-a-variant, (S3) derive the binary verdict plus `clean`, (S4) author variant specs and feedback prose.

Q1: S1 is a fixed 6-option decision and S2 is binary (yes). Q2: both resolve from the experiment log plus P3 note with no further probing (yes). Q3: the triager turn itself makes no tool call (no).

Verdict: S1 plus S2 are strong partial-replacement candidates (Choice fan-out); S3 stays deterministic via `derive_verdict` (`src/polymerhus/attack/hunting/hunting_agent.py:152` per seam name); S4 stays generative.

INFERENCE: the existing `validate_decision` guard becomes the confidence-routing fallback: low-confidence System One answers degrade to the safe honest terminal instead of corrupting the envelope.

### 4.16 Deterministic seams (not agents, recorded for completeness)

Supervisor, pod_graph, and job_agent are deterministic routers with no LLM call (matrix `docs/design/statefulness-pattern-matrix.md:24-25`, `docs/design/statefulness-pattern-matrix.md:34`).

The L0 and L1 curators, `noise_filter.classify_profile`, the typed applies-if predicate evaluator, `validate_spec`, `validate_probe_chain`, and `derive_verdict` are deterministic code already.

These are not System One candidates because there is no judgment to replace; several (curators, validators, predicate) are the code-side composition layer a System One integration would feed into.

## 5. Use-case catalogue (ordered by expected value x feasibility)

Each entry carries exactly the four required fields plus its mode tag.

### UC1 - Assigner ownership Choice with confidence-routed withhold

Mode: partial replacement of one seam (`assign` invoke path in `src/polymerhus/analysis/assigner.py`, shaping gates unchanged).

**Problem to be solved**: classify each streamed Endpoint onto exactly the existing Service slugs that own it, or onto an explicit none-fits option, with a graded ownership signal per edge.

**Rationale**: this is a decision over the finite per-run inventory slug set, resolvable from the chunk plus service contracts alone with no environment interaction, and the measurable enhancements are assignment precision and recall against the eval-target ground truth, the kept-versus-bar curve shape from `evaluation.bar_sweep`, per-chunk latency, token spend, and flakiness rate across repeated runs.

**Required refactor**: add a System One client seam beside `stateful_invoke_fn` (`src/polymerhus/analysis/assigner.py:578-609`) that assembles state (endpoint record plus candidate contracts plus the no-owner null hypothesis from `skills/analysis/assigner/SKILL.md`) and asks one Choice per endpoint (options are inventory slugs plus `no_owner`) with a Score ownership-strength question in the same fan-out call, then maps the winning slug plus normalized score into the existing `AggregatesProposal` shape before `shape_proposal`.

**Implicit edits to the agent workflow**: the supervisor schedule is unchanged; the Assigner body keeps its `(messages) -> batch` seam contract so `make_assigner_body` is untouched; `withhold_below_bar` stays the single enforcement point but reads the System One distribution (peak probability or score) with the bar re-fit on the existing sweep; the session thread becomes optional context rather than the memory carrier, with chunk history supplied as state; tests move from prompt-shape assertions to decision-accuracy assertions on recorded chunk fixtures plus the comparative `evaluate_assigner` harness.

### UC2 - Anatomy webpage-profile two-Choice fan-out

Mode: full replacement of one seam (`default_webpage_profile_fn` in `src/polymerhus/analysis/anatomy.py:171-187`, triple assembly unchanged).

**Problem to be solved**: classify `navigation_model` and `rendering_model` from the assembled signal bag into their fixed enums.

**Rationale**: two decisions over predefined finite enums, resolvable from the signal dict alone with no live interaction, and the measurable enhancements are classification agreement against labelled signal bags, removal of the SPA-implies-CSR class of modelling error by construction, per-call latency, and token spend.

**Required refactor**: replace the `invoke_role("analyser", ..., schema=WebpageProfileProposal)` call with one System One request carrying two Choice questions (options SPA/MPA/Hybrid and CSR/SSR/SSG/StreamingSSR/HydratedSSR, each with the skill criteria text), then construct the existing `WebpageProfileProposal` from the two answers in `src/polymerhus/analysis/anatomy.py`.

**Implicit edits to the agent workflow**: the anatomy skill file keeps the human-readable discipline but its criteria text is mirrored into the Choice criteria; the fingerprint-only downgrade rule stays deterministic code after the answers; the corroborating Observation and backward-recon probe legs are unchanged; tests swap live-LLM classification fixtures for answer-mapping unit tests plus a labelled signal-bag accuracy suite.

### UC3 - Pod triager terminal-reason Choice with terminate-versus-variant gate

Mode: partial replacement of one seam (`default_triager_fn` in `src/polymerhus/attack/hunting/pod/agents.py`, harness and envelope unchanged).

**Problem to be solved**: classify each stretch outcome into the six-way terminal vocabulary and decide terminate versus mine-a-variant, from the P3 note plus experiment log.

**Rationale**: a decision over a predefined finite set (six terminal reasons, binary action), resolvable from the persisted log alone with no further probing, and the measurable enhancements are terminal-classification agreement with the current triager, verdict correctness via the unchanged `derive_verdict`, variant-mining precision, and per-lap latency.

**Required refactor**: replace the `stateful_turn("pod_triager", ..., ToolStrategy(TriagerDecision))` call with one System One request (Choice over the six terminal reasons plus a Noul continue-versus-terminate judgment), then fill the existing `TriagerDecision` shape and pass it through the unchanged `validate_decision` guard (`src/polymerhus/attack/hunting/pod/verification.py`).

**Implicit edits to the agent workflow**: the pod graph nodes, the `HuntSession` spec threads, and the binary envelope contract are unchanged; low-confidence answers route to the safe honest terminal the validator already produces; variant-spec authoring stays on the generative lane; contract-tier symbolic fakes are untouched; tests add terminal-agreement fixtures and low-confidence fallback-path coverage.

### UC4 - Hunt-orchestrator gate MatchVerdict Choice with confidence routing to park

Mode: partial replacement of one seam (gate and re-match turns in `src/polymerhus/attack/hunting/llm.py`, store tools and phase machine unchanged).

**Problem to be solved**: emit the three-valued applicability verdict (`applies`, `does-not-apply`, `insufficient-evidence`) per (unit, fault) pair from the assembled projection plus materialisation content.

**Rationale**: a decision over a predefined three-option set, resolvable from the symbolic render plus fault content with no live probing inside the turn, and the measurable enhancements are gate precision and recall against adjudicated pair labels, yellow-verdict calibration (parked candidates that resolve on re-match), and per-pair latency.

**Required refactor**: add a System One call beside `build_gate_reason_fn` and `build_rematch_fn` (`src/polymerhus/attack/hunting/llm.py:696-718` per seam names) taking the pair frame state already composed for the actor turn, asking one three-option Choice, and mapping high-confidence answers to verdicts while routing low-confidence answers to `insufficient-evidence` with the park-and-resume path.

**Implicit edits to the agent workflow**: the hypothesise-ratify-note phase machine, the `hunts_store` and `notes` tools, and the actor thread are unchanged; the gate turn becomes a System One-first with actor-fallback ordering under test; hypothesise elicitation and ratification prose stay generative; tests add pair-frame verdict fixtures plus threshold-sensitivity coverage on the park path.

### UC5 - Sweep stale-ownership Choice

Mode: partial replacement of one seam (`default_stale_propose_fn` in `src/polymerhus/analysis/sweep.py:167-185`, resolution unchanged).

**Problem to be solved**: place each stale L0 asset onto an existing Service slug or known system kind, or leave it unplaced.

**Rationale**: a decision over the finite per-run inventory plus the fixed kinds enumeration, resolvable from inventory plus the stale record with no environment interaction, and the measurable enhancements are placement agreement with adjudicated labels, stale-pool drain rate without over-assignment (the AMV-9 over-assignment hazard as negative metric), and per-run latency.

**Required refactor**: replace the `invoke_role("analyser", ..., schema=StaleOwnershipBatch)` call with one fan-out System One request (one Choice per shown stale asset, options are existing slugs plus kinds plus `unplaceable`), then map answers into the existing `StaleOwnershipBatch` shape before `resolve_stale_owners`.

**Implicit edits to the agent workflow**: the sweep stays a one-shot pass with no session thread; the inventory-primary plus kinds-secondary grounding order is encoded in state assembly, not prose; over-assignment is policed by a confidence floor routing to unplaced; tests add stale-pool fixtures with adjudicated owners plus over-assignment regression coverage.

### UC6 - Configurator rate-profile Choice

Mode: full replacement of one seam (`default_configure_fn` in `src/polymerhus/recon/domain/pod.py:701-751`).

**Problem to be solved**: decide per pod whether to run at default rate or preventive throttle from the job template, asset, and steering signals.

**Rationale**: a binary decision over a predefined two-option set, resolvable from already-assembled context with no tool call, and the measurable enhancements are throttle-decision agreement with the current role, false-throttle rate (throttle slows the run, so precision matters more than recall), and per-pod latency.

**Required refactor**: replace the `stateful_turn`/`invoke_role` branch with a two-option Choice call over the same prompt content rendered as state, defaulting to `default` on low confidence or error to preserve the fail-open contract.

**Implicit edits to the agent workflow**: the pod graph configurator node and the per-pod session binding are unchanged; the rationale field is dropped or templated since Jev emits no prose; tests swap role-output fixtures for Choice-answer fixtures plus fail-open coverage.

### UC7 - Triage Noul gate skipping empty tool output

Mode: augmentation (System One as a pre-filter the generative triager calls through, triager unchanged).

**Problem to be solved**: decide per completed tool run whether the output contains anything worth a full generative triager turn.

**Rationale**: a binary relevance decision over a predefined answer set, resolvable from stdout head plus asset counts with no further interaction, and the measurable enhancements are LLM-call and token reduction per recon run at parity observation recall on eval targets.

**Required refactor**: add a pre-check in `default_triage_fn` (`src/polymerhus/recon/domain/pod.py:754-808`) that sends stdout excerpt plus asset-count summary to one Noul question and short-circuits to no observations below threshold, leaving the stateful triager path intact above it.

**Implicit edits to the agent workflow**: no graph, prompt, or schema change; the gate threshold is tuned per tool family since verbose tools differ from terse ones; the fail-open direction is gate-open (run the triager) on error; tests add per-tool gate precision and recall fixtures proving no dropped Observations on eval-target replays.

### UC8 - Curation duplicate-pair Noul fan-out feeding the proposer

Mode: augmentation (System One as evidence the generative curation proposer consumes, proposer unchanged).

**Problem to be solved**: score every same-kind unit pair for same-meaning duplication from the two index cards.

**Rationale**: per-pair binary decisions over a finite per-run pair set, resolvable from card text with no environment interaction, and the measurable enhancements are duplicate-pair recall and precision against adjudicated inventory pairs and end-to-end merge correctness with fewer missed duplicates.

**Required refactor**: add a pair-scoring pass in `src/polymerhus/analysis/curation.py` before `default_propose_fn` (`src/polymerhus/analysis/curation.py:228-241`) that fans out one Noul per pair in a single batched request and injects the scored pair list into the curation prompt state.

**Implicit edits to the agent workflow**: the `CurationBatch` schema, the sole-writer path, and the precision-guard prompt stay; the prompt cites pair scores as input rather than re-deriving them; tests add pair-label fixtures plus end-to-end merge-set agreement coverage.

### UC9 - Recon routing exclusion Noul fan-out beside the orchestrator actor

Mode: augmentation (System One as a tool the actor path consults, actor unchanged).

**Problem to be solved**: judge per (downstream job, flagged host) pair whether the host should be excluded from that job.

**Rationale**: per-pair binary decisions over the finite phase job set times flagged hosts, resolvable from formatted signals plus job-kind descriptions with no fresh probing, and the measurable enhancements are routing accuracy (WAF-block avoidance on eval targets), exclusion precision (over-exclusion starves coverage), and per-phase latency.

**Required refactor**: add a fan-out helper in `src/polymerhus/recon/control/orchestrator_agent.py` beside `ReconOrchestratorActor.decide_routing` (`src/polymerhus/recon/control/orchestrator_agent.py:225-247`) that asks one Noul per pair and intersects the result with the actor `RoutingDecision` (actor exclusions union high-confidence Noul exclusions, disagreements resolve to the actor).

**Implicit edits to the agent workflow**: the actor thread and its cross-phase memory are untouched; the prompt-owned rationale stays on the actor; the Noul path is independently disableable per run; tests add phase-frame fixtures with expected exclusion maps plus disagreement-resolution coverage.

### UC10 - Mechanism-typist service-linking edge-label Choice

Mode: partial replacement of one step (linking call only, reflection and extraction unchanged).

**Problem to be solved**: select the exact edge label binding each touched System to each primary Service.

**Rationale**: a decision over the fixed edge-label vocabulary with verbatim slug copying, resolvable from the proposed-plus-defined system lists plus primary and secondary service lists already in the linking prompt, and the measurable enhancements are edge-label accuracy against adjudicated links and per-chunk latency on the linking step alone.

**Required refactor**: replace the linking structured call in `src/polymerhus/analysis/mechanism_typist.py` (linking prompt composer near `src/polymerhus/analysis/mechanism_typist.py:370-385`) with one Choice per (system, service) pair over the edge labels plus `no_edge`, keeping the verbatim-copy validation in code.

**Implicit edits to the agent workflow**: the three-call chain shape and session thread are unchanged; the reflection and extraction calls stay generative; the edge-label vocabulary becomes criteria text owned beside the curator allowlist; tests add linking fixtures with expected edge sets.

### UC11 - Hunt candidate risk composite scoring

Mode: augmentation (System One scores the generative ranker consumes, ranker unchanged).

**Problem to be solved**: grade each (unit, fault) candidate on the separable risk facets (ranking severity, observability depth, defences, exploitation severity, chaining potential, symptom evidence) as parallel Scores.

**Rationale**: each facet is a position on a describable spectrum, resolvable from the unit projection plus fault content, and the measurable enhancements are rank correlation against operator-prioritized hunt orderings, prioritization stability across runs, and the ability to reweight facets in code without prompt edits.

**Required refactor**: add a scoring call in the hunt-orchestrator path consuming the same pair frame as the gate, asking one Score per facet in a single fan-out request, and combine normalized scores with weights in code per the composite-scoring pattern.

**Implicit edits to the agent workflow**: the risk-descending schedule policy keeps its shape but reads computed scores; facet weights become code constants with tuning tests; the LLM ranker prose stays as fallback below a confidence floor; tests add facet-label fixtures plus weight-sensitivity coverage.

### UC12 - Data-modeller flow-mapping Choice over settled Services

Mode: partial replacement of one step (flow mapping only, lifting and extraction unchanged).

**Problem to be solved**: attach each grounded DataItem `PRODUCES`/`CONSUMES` flow to the owning settled Service.

**Rationale**: a decision over the finite settled service set, resolvable from the chunk plus the live `AGGREGATES` answer with no extra interaction, and the measurable enhancements are flow-attachment accuracy against adjudicated graphs and trust-boundary edge correctness.

**Required refactor**: add a Choice call in `model_data` (`src/polymerhus/analysis/data_modeller.py:722-729` per body name) mapping each item to owning service slugs plus `unowned`, feeding the existing flow-shaping gates.

**Implicit edits to the agent workflow**: the reflection plus extraction calls, the `enforce_groundedness` gate, and the A1-only phase guard are unchanged; ungrounded items still drop by code; tests add flow-mapping fixtures with expected edge sets.

## 6. Rejected candidates with reasons

Crawl agent: long-horizon browser tool loop with observation and iteration between steps (Q3 yes), rejected per the System Two exclusion (https://docs.typesafe.ai/model-jaggedness/jev-1.13).

Pod runner: live-target probe execution with raw observation and reinterpretation between steps (Q3 yes), rejected for the same reason.

Hunting-hunter spec authorship: open-vocabulary NL test design grounded in KB retrieval plus surface evidence, requiring iteration (Q1 no, Q3 yes).

Bootstrapper reasoning pass: open-vocabulary service-population invention whose quality is whole-KB synthesis (Q1 no, Q3 yes).

Mechanism-typist reflection and system minting: free-prose hypothesis plus open-identity minting (Q1 no, Q3 yes).

Data-modeller DataItem lifting: open-vocabulary `item_key` invention plus adversarial characterization prose (Q1 no, Q3 yes).

Triager insight authorship: unbounded adversarial prose plus anchor judgment (Q1 no, Q3 yes for the authoring subproblem).

Recon routing as a single decision: combinatorial exclusion maps are not a predefined finite set (Q1 no as posed, recoverable only via per-pair decomposition in UC9).

Supervisor, pod_graph, job_agent: deterministic routers with no LLM judgment to replace.

Curators, `noise_filter.classify_profile`, typed applies-if predicate, `validate_spec`, `validate_probe_chain`, `validate_decision`, `derive_verdict`: deterministic code already, which is the composition layer System One outputs would feed, not a replacement target.

## 7. Open questions and cheapest experiments

All experiments run against recorded fixtures first (no live spend), then against the eval harness (`tests/e2e/fixtures/eval-targets.yaml`, `docs/design/eval-harness-design.md`).

OQ1: does Jev ownership judgment match the Assigner on real chunks, and where does the bar land on its distribution.

Cheapest experiment: replay five recorded chunk batches through one Choice-per-endpoint request, plot the kept-versus-bar curve with the existing `evaluation.bar_sweep` reader, and report precision and agreement at bars 0.5, 0.75, and 0.9.

OQ2: are the anatomy enums separable by Jev from signal bags alone, especially SSR versus HydratedSSR.

Cheapest experiment: label forty historical signal bags, run the two-Choice fan-out, and report per-dimension agreement plus the confusion pairs.

OQ3: does the pod-triager Choice preserve terminal outcomes and the binary envelope.

Cheapest experiment: replay thirty stretch logs with known triager decisions, compare terminal reason plus action agreement, and force low-confidence cases through `validate_decision` to confirm safe-terminal fallback.

OQ4: is the hunt gate calibratable, meaning low confidence predicts wrong or yellow verdicts.

Cheapest experiment: adjudicate sixty historical (unit, fault) pairs, run the three-option Choice, and plot accuracy against confidence to pick the park threshold before any wiring.

OQ5: what is the token and latency delta per recon run for the triage gate at parity recall.

Cheapest experiment: replay two eval targets (`tests/e2e/fixtures/eval-targets.yaml`) pod by pod through the Noul gate offline, and report skipped-turn fraction versus Observation recall loss.

OQ6: do duplicate-pair Noul scores improve merge recall without precision collapse.

Cheapest experiment: score all same-kind pairs from three settled inventories, inject the ranked list into the existing curation prompt, and compare merge sets with and without the injection.

OQ7: which integration seam carries a System One client (new provider beside `app/llm`, or a tool the agents call).

INFERENCE: a sidecar client module with recorded-fixture tests is cheapest, because it touches no session, checkpointer, or role-registry path until a use case proves out. This is an engineering judgment, not a sourced fact.

## 8. Source gaps

None on the TypeSafe side: all eight mandated pages plus the owning pages for Choice, Score, Noul, confidence, state, API, models, SDK, and the jev-1.13 jaggedness record fetched successfully on first attempt.

One repo-side approximation to record: line numbers for `build_gate_reason_fn`, `build_rematch_fn`, `derive_verdict`, and the hunt-orchestrator schema classes rest on grep evidence plus the statefulness matrix, not full file reads, so a verifier should confirm `src/polymerhus/attack/hunting/llm.py:696-718`, `src/polymerhus/attack/hunting/hunting_agent.py:152`, and `src/polymerhus/attack/hunting/hunt_orchestrator.py:169-342` before quoting them in a follow-up ticket.
