# Plan - Recon coverage verification and outcome-eval well-formedness (2026-10-17)

Status: executing (operator directive of 2026-10-17).
Lineage: operator feedback on the arm J trials; this plan is the work contract for the two task areas it defines.
Worktree: `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/recon-coverage-eval-wellformedness`, branch `feat/recon-coverage-and-eval-wellformedness`, base `6c25613` (= `dev`).

## 0. Operator directive (execution contract)

Two task areas, executed sequentially, with tight feedback loops.
Stop conditions: the goal is reached, or a fundamentally blocking technical condition appears.

Task Area 1 - recon authentication, API enumeration, tickets, access checks:
- Answer whether the recon phase ran in an authenticated setting, and whether the API-enumeration phase ran with the correct authentication headers.
- Check the presence of, and optionally create or specify, the tickets for: local Steel browsing stack for targets not reachable via the internet; steel_crawl recon-phase improvement; recon-phase job-specialised agents.
- Check that the mechanism typist and the assigner have access to the project auth-context store through the respective tool, and that at least the typist tried to query it or the http-history database for request shapes.

Task Area 2 - outcome-oriented evaluation framework:
- Goal 1: every ground-truth Service is fully specified and edged to the required underlying failing Systems, and those Systems are themselves sufficiently specified for a threat modeller to identify the ground-truth vulnerability.
- Goal 2: the average caching ratio of the analysis-phase agents alone is above 70%.
- Specify more precisely the ground-truth services/systems and their typed surface in the ground-truth corpus.
- Define a `gt-unit-well-formedness` criterion with metrics covering, per unit: the necessary edges to L0, the typed backbone fields in the unit content, and the specific concrete service-to-system edges required.
- Re-measure the J trials with the new criterion and report an outcome quality defect assessment.
- Work backward: define the optimal end-to-end paths (decision trees with branches, rationale, tool calls, result interpretations) the typist and the assigner should take per relevant recon L0 chunk; use the observability system (Langfuse) to identify the actual chunks and paths; tabulate the workflow deltas per chunk; define failure-mode clusters for joint debugging.
- Re-explain the T5 open decisions (D1-D3) if the operator did not answer them implicitly.

## 1. Verified grounding facts (pre-plan recon, read-only)

Sources: eval server (`eval-server-polyphemus`), containers `ph-dd131acc-*`; Postgres `recon_jobs`/`recon_runs`; Neo4j graph; kali http-history sqlite stores; Langfuse observation censuses in `/root/armj-formal-*-census.json`; repository code.

### 1.1 Recon job records (Postgres)

- white-jotter baseline (`bf0d9408-...`): `kiterunner` skipped (hard `profile=restapi` gate never fired); `graphql-cop` skipped.
- comfyui formal (`d04b947f-...`): `kiterunner` success, 3 pods, commands `kr scan http://t-1fc05262.target/ -w /opt/localbin/routes-small.kite`, `kr scan .../api/ ...`, `kr scan .../internal/ ...`; capture refs 150; consumed 34; exec 262.53 s.
- white-jotter formal (`f16de150-...`): `kiterunner` success, 1 pod, command `kr scan http://t-1618c524.target/api/ -w /opt/localbin/routes-small.kite -H 'Cookie: rememberMe=...; JSESSIONID=...'`; capture refs 50.
- The formal-run `/api/` anchors exist because of the WS1 chained endpoints (`chained_prefix`/`chained_from` properties), which is the correction landed in `1163f33`.
- Note: the wj kiterunner command shows duplicated cookie pairs (`JSESSIONID` twice, `rememberMe` twice); tolerated in practice but worth an eye in W1.1.

### 1.2 Endpoint inventory (Neo4j, per project)

- comfyui baseline: 183 httpx, 105 katana, 1 jsluice, 1 steel; 0 chained.
- comfyui formal: 228 httpx, 102 katana, 4 jsluice, 1 steel; 91 chained.
- white-jotter baseline: 54 httpx, 2 katana, 1 steel; 0 chained.
- white-jotter formal: 65 httpx, 25 jsluice, 2 katana, 1 steel; 36 chained.
- No endpoint carries `source=kiterunner` in any of the four projects, despite the formal runs executing kiterunner; the yield question is a W1.1 evidence item.

### 1.3 Auth store and the analysis tool surface

- comfyui: no authentication surface (`credentials.yaml`: `mechanism: none`, `accounts: {}`, `required_headers: []`); the deployment runs single-user, so the authenticated-setting question is not-applicable by design.
- white-jotter: credentials store populated with account `wjprobe_1790894002-first_authn_bootstrap`, tokens `JSESSIONID` and `rememberMe`, `login_endpoint http://t-1618c524.target/api/login`, `mechanism: password`, defence `shiro-session-authentication`.
- The recon orchestrator role (`job_orchestrator`) is the auth gateway; it called `auth_store` (8 calls in the wj formal run census).
- Hunting pod runners called `auth_store` too (8 on wj, 1 on comfyui).
- The analysis agents bind no `auth_store` tool: the assigner binds only the HTTP-history pair (`search_http_history`, `get_http_artifact`); the mechanism typist binds `graph_view` plus the HTTP-history pair plus bounded `exec` (`src/polymerhus/analysis/proposer_turn.py`, `_surface_tools`).
- The read-only auth-capable binding exists (`app/auth/seams.py::auth_capable_binding`); the pod triager uses it, and `recon/CONTEXT.md` states explicitly that the analysis-domain agents never bind it.
- Typist HTTP-history usage in the formal runs is non-zero (comfyui: 32 `search_http_history` + 10 `get_http_artifact`; white-jotter: 14 + 12); assigner usage: comfyui 42 + 6, white-jotter 14 + 8.

### 1.4 http-history store

- Per-project sqlite on the kali container: `/data/<project_id>/http-history/history.sqlite3`, tables `flows`, `attributes`, `flows_fts`, `bodies`.
- `record_json` is `http-artifact/v1` with full `request` (headers, cookies, query), `response` (status, headers, body_ref), `connection`, and `capture_context` (run_id, session_id, spec_id).
- Flow counts: comfyui formal 33,554; white-jotter formal 22,426; comfyui baseline 33,148; white-jotter baseline 5,441.

### 1.5 Ground-truth corpus and the eval worktree

- The GT corpus lives at `/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth` (private, local-only, not a git repo; stated in `MINE.md`).
- Per-vulnerability bundles: `chain.md`, `gaps.md`, `hunting/`, `kb.yaml`, `l0-surface.yaml`, `l1-profile.md`, `skills.md`, `symptoms.md`.
- `l1-profile.md` carries a render block with the spine keys, outgoing edges, data items, data relationships, and aggregated endpoints; this is the closest existing form of the unit spec.
- GT units: comfyui has 5 distinct Service units across 6 bundles (`user-data-file`, `image-upload`, `image-viewing`, `manager-preferences`, `model-download`); white-jotter has 6 distinct units across 7 bundles (`account-sign-in`, `AuthorizationSystem`, `article-publishing`, `book-search`, `book-cover-serving`, `account-registration`).
- `/Users/diekgbbtt/.claude/worktrees/eval-vuln-groundtruth` is the eval-harness worktree (branch `feat/eval-vuln-groundtruth`: `eval/` = harness, kbs, orchestrator, setups, prompts; no GT bundles inside). The directory was prunable and has been re-created with `git worktree prune` + `git worktree add`.

### 1.6 Ticket landscape (GitHub issues)

- Exists: #245 (local Steel deploy, motivated by egress/reCAPTCHA stability), #50 (steel_crawl parent), #38 (login), #51 (DOM-delta dedup), #353 (XHR-only routes never captured), #336 (recon orchestrator configures only by auth posture, no target-type job-set decision node), #238 (post-authn rate-limit mapping loop), #41 (Phase B service/system deepening), #355 (alpha-omega projection).
- Missing: a ticket for CDP network-interaction history (HAR) capture and store integration; a ticket for chaining-branch probe validation; a ticket for the per-phase job-specialised request-shape agents; a ticket for the analysis-phase read-only auth-store binding.

### 1.7 Criterion measurement tooling (as-is)

- Ad-hoc bash + `cypher-shell` scripts on the eval server (`/root/arm-h-measure.sh`, `/root/arm-j-formal-extras.sh`), plus the usage API `GET /projects/<pid>/usage`.
- Precedent for a repo-hosted measurement script: `tools/measure_session_cache.py`.
- So the new criterion is implemented as a committed, testable script under `tools/`, not another ad-hoc script.

## 2. Task Area 1 work items (execute first, strictly sequential)

### W1.1 - Verdict pull: authenticated setting, API enumeration, chaining defect

Deliverable: `docs/experiments/recon-auth-coverage-verification.md` (new).

Steps:
1. White-jotter formal: flow-store counts (total; requests carrying `JSESSIONID`/`rememberMe`; `/api` path counts with status mix); verify the stored session was live (front-log or replay evidence); kiterunner and auth-loop flows identified by `capture_context.session_id`.
2. comfyui (baseline + formal): same counts; expect no auth material (mechanism none).
3. kiterunner yield: captured refs versus graph delta; determine what the enumerator returned and why no `source=kiterunner` endpoint exists; check whether kiterunner status codes merged into existing endpoints.
4. Chaining defect quantification: for each formal run, the chained endpoints (`chained_prefix IS NOT NULL`) and their recorded statuses; count wrong branches (404/400/401/403/50x); exhibit the garbage candidates (for example `/I4U`, `/bpg`, `/i/W`, `/static/js/.js`) that entered `httpx_reprofile`.
5. Verdict table answering Q1 (authenticated setting) and Q2 (API enumeration with correct auth headers), with per-target nuance.

Verification: flow totals reconcile with the store; the status mix sums to the total; three flows spot-checked by hand; the baseline white-jotter numbers re-derive the coverage doc (4,864/4,897).

### W1.2 - Tickets (check presence, then create or specify)

Deliverables: the tickets below, each grounded in this plan's evidence and cross-linked.

- T-A: Steel local stack for targets not reachable via the internet.
  `#245` exists but is motivated by egress stability and cost; the eval-side requirement is different: the eval targets are sandbox-local (not internet-reachable), so the cloud Steel pool cannot crawl them at all.
  Disposition: read `#245` fully, then either (i) add a scoped requirements comment to `#245`, or (ii) create a child ticket `recon/eval: local Steel stack for sandbox-local (non-internet) targets` linking `#245`.
  Default: child ticket when the eval wiring (kali to target-network reachability, harness addressing) is a separable deliverable.
- T-B: steel_crawl improvement - CDP network-interaction history (full HAR of browser-issued requests, including JS-issued XHR) dumped to a queryable store.
  New ticket, parent `#50`, links `#353`, `#245`, `#245`-child.
  Content: CDP Network domain capture through the Steel session; store as http-history artifacts (same `http-artifact/v1` schema); make the store queryable by analysis proposers so the correct authentication material and request shapes are derivable; record crawl coverage as evidence (the baseline follow-up item 2).
- T-C: recon-phase job-specialised agents (request-shape derivation before dispatch).
  New ticket; builds on the existing symbolic layers: `recon/control/auth_feed.py` (per-phase projected auth material, D223-11), `recon/control/batching.py` input prep, `recon/control/jobs.py` JobSpec, and the `preprocess` node seam of `recon/control/job_agent.py` (today `default_preprocess_fn` is deterministic).
  The agent sits before a downstream phase (API enumeration, parameters discovery) and derives the correct request shape (API-root anchors, headers/cookies from the auth store, body/parameter carriers) for an optimal run.
  Cross-links: `#336` (job-set decision node; adjacent, not the same concern), `#238` (orchestrator-side loops), T-B.
- T-D: probe validation of relative-endpoint chaining branches.
  New ticket; for each chaining branch, a light HTTP probe classifies the branch (404/400/401/403/50x = wrong branch, pruned) before the endpoint enters the surface.
  Based on the WS1 `chained_from`/`chained_prefix` mechanics; the heuristic limit (unknown auth headers) is stated; T-B is the structural fix.
- T-E: analysis-phase read-only auth-store binding for typist and assigner.
  New ticket; bind the read-only auth capability (`auth_capable_binding` pattern, as the pod triager has) to the typist and assigner roles so request shapes for authenticated endpoints are reachable; cross-links `#353`, T-B.

Verification: `gh issue view` each ticket; every ticket carries evidence references, a "what to build" section, and cross-links; labels set per repo convention.

### W1.3 - Auth-store access and request-shape usage check (typist + assigner)

Deliverable: a section in the W1.1 report.

Steps:
1. Tool-binding verdict from code (`proposer_turn._surface_tools`, `app/auth/seams.py`, `recon/CONTEXT.md`).
2. Census recount: `auth_store` and HTTP-history calls per role per formal run, with obs ids.
3. Sample at least ten typist `search_http_history` queries per target from Langfuse (inputs), classify each: endpoint-shaped query, request-shape/header query, artifact fetch; note whether any attempted to recover auth material.
4. Verdict: access (no auth-store tool; the HTTP-history pair is the only request-shape seam) and behaviour (the typist did query the HTTP-history store; whether the queries pursued request shapes is stated with samples).

Verification: sampled queries quoted with observation ids in the report.

### W1.4 - Task Area 1 consolidation

- Merge W1.1-W1.3 into `docs/experiments/recon-auth-coverage-verification.md`.
- Commit and push; relay the summary.

## 3. Task Area 2 work items (start only after Task Area 1 is done)

### W2.1 - Ground-truth unit-spec enrichment (corpus)

Deliverables: one `unit-spec.yaml` per bundle in the corpus (comfyui 6, white-jotter 7), plus the spec-format description in this plan's execution report.

Decision: authored in the corpus (`/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/<target>/<bundle>/`), NOT in the pipeline repo, because the ground truth must never reach the pipeline and the corpus is declared local-only.
A mirror into the eval worktree can be produced on request.

Spec content per unit (draft shape):
- identity: kind (`Service`/`System`), key (`business_function_slug`, or `kind` + `discriminator` for Systems);
- typed backbone: required fields with expected values or non-emptiness (`api_paradigm`, `auth_methods`, `exposure`, `business_function`, `service_contract`, plus kind-specific fields);
- edges to L0: required aggregated endpoint identities (`method`, `path`) and required parameter identities where the chain demands them;
- service-to-system edges: concrete required edges (`rel`, direction, target kind, discriminator, role note);
- threat-modeller sufficiency (System units): what the unit must state for a modeller to identify the vulnerability.

Verification: every spec parses as YAML; every field traces to `l1-profile.md`/`l0-surface.yaml`/`chain.md`; a completeness lint reports zero units without at least one L0 requirement and one backbone field.

### W2.2 - `gt-unit-well-formedness` criterion (definition + implementation)

Definition (per GT unit, measured against the produced graph):
- M1 placement: the produced L1 node matching the unit key exists (gate).
- M2 L0 grounding: share of required endpoints aggregated by the produced unit (`AGGREGATES` edge to the endpoint identity; `EVIDENCED_BY` accepted as a fallback per the existing grounding discipline).
- M3 typed backbone: share of required backbone fields present and non-empty.
- M4 service-to-system edges: share of required edges present (`rel` + target kind/discriminator).
- Unit score: mean of M2, M3, M4, gated by M1; target score: mean over GT units.

Implementation: `tools/measure_gt_wellformedness.py` (spec loader + metric math as pure functions; a graph query layer against Neo4j, credentials from env/args) with `tests/tools/test_measure_gt_wellformedness.py`.

Verification: unit tests pass; a live run against the comfyui formal project reproduces three units hand-checked with cypher.

### W2.3 - Re-measurement and outcome quality defect assessment

- Run the criterion on the four J projects (two baseline, two formal).
- Compute Goal 2: the average caching ratio of the analysis-phase agents alone (roles: triager, assigner, mechanism_typist) from the durable usage pulls; report per run against the 70% target.
- Deliverable: `docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md` with per-unit tables and a defect assessment (which units fail which metric, and the diagnosed surface).

Verification: numbers reproducible from the committed script with the commands printed in the doc.

### W2.4 - Optimal-path decision trees (typist and assigner) per relevant L0 chunk

- Select the relevant recon L0 chunks per GT unit from the J formal window pulls (`/root/armj-formal-*-window.json`) and Langfuse observations.
- Author the optimal end-to-end path per chunk: decision tree with branches, rationale, exact tool calls, and result interpretations, using only the roles' real interaction capabilities.
- Pull the actual executed path per chunk (turns, tool calls, outcomes) and tabulate the workflow deltas.
- Deliverable: `docs/experiments/2026-10-17-typist-assigner-optimal-paths.md`.

Verification: every optimal branch names an available capability; every delta cites an observation id.

### W2.5 - Failure-mode clusters

- Cluster the deltas into typed failure modes with evidence, suspected root cause, and a candidate structural fix.
- Deliverable: a section of the W2.4 doc (or a companion).

Verification: every delta maps to exactly one cluster; each cluster carries at least two evidence items or is marked a singleton.

### W2.6 - T5 wider explanation

- Section 6 of this plan; relayed to the operator with the report.

### W2.7 - Task Area 2 consolidation

- Commit and push the docs and the script; relay the summary; propose the joint debugging session on the failure-mode clusters.

## 4. Deliverables map

| id | deliverable | path |
|---|---|---|
| D1 | TA1 verification report | `docs/experiments/recon-auth-coverage-verification.md` |
| D2 | tickets T-A..T-E | GitHub issues |
| D3 | GT unit specs | corpus `unit-spec.yaml` per bundle |
| D4 | criterion implementation | `tools/measure_gt_wellformedness.py` + tests |
| D5 | outcome assessment | `docs/experiments/2026-10-17-gt-wellformedness-outcome-assessment.md` |
| D6 | optimal paths + deltas + clusters | `docs/experiments/2026-10-17-typist-assigner-optimal-paths.md` |
| D7 | T5 re-explanation | section 6, relayed |

## 5. Sequencing, feedback loops, stop conditions

- Task Area 1 completes (D1, D2, W1.3 verdict) before Task Area 2 starts.
- Every work item ends with its verification step; a failure halts the item, not the plan, unless it is a fundamentally blocking technical condition.
- Stop conditions: all deliverables verified, or a blocking condition reported with questions.

## 6. T5 open decisions (wider explanation, for the operator)

T5 is the next assigner prompt change: class-first candidate pull (Move A) plus the single-candidate direct admit (Move B), specified in `docs/design/plans/2026-10-15-T5-class-first-candidate-pull.md`.
The change is one prompt file, no code or schema change.
Its motivating case: on `GET /experiment/models` the payload is a folder map, but the contract that names that class (`server-diagnostics`) never entered the candidate differential; Move A makes the payload class a candidate-generation key, so the class-naming rival always enters.
Move B skips the runner-up search only under five guards (unique candidate, two independent signals, no class competition, artifact held, signal independence).

- D1 - degenerate-set artifact trigger.
  When the surface-pulled candidate set is empty or single and an artifact exists, the assigner today may judge without reading the body, so class blindness persists exactly where the set is too thin to differentiate.
  The option: require ONE artifact read before judging in that degenerate case.
  Cost: one widening read per thin-set endpoint.
  Benefit: closes the T5 blind spot where it bites hardest.
  Spec default: NOT included (keeps the widening bound flat).
  Question: include or not?
- D2 - class vocabulary.
  Open (the model's own one-or-two-word class words, bound by the shape-not-topic rule) versus a closed starter list in the prompt (folder map, log stream, file listing, external catalog, membership check, ...).
  Closed list trade-off: comparable and auditable classes, but an incomplete list manufactures misfits and grows the prompt.
  Spec default: open, with the worked examples.
  Question: keep open, or introduce a closed list?
- D3 - the label.
  Requiring the literal label `SINGLE-CANDIDATE ADMIT` in the reasoning when the shortcut fires; it is the census hook for the acceptance counters (label occurrences per turn and run).
  Cost: one line per eligible judgment.
  Spec default: required.
  Question: keep the label required?

Note: the operator's prompt of 2026-10-17 addressed recon-side probing and per-phase agents; it did not address D1-D3, so no implicit answer was assumed.

## 7. Decision notes and assumptions

- The GT corpus (not the eval worktree) is the authoring locus for W2.1; rationale in the work item. Flagged for operator override.
- The analysis-phase role set for Goal 2 is triager, assigner, mechanism_typist; stated again in D5 with the raw usage numbers.
- Ticket T-A may become a comment on `#245` instead of a new issue; the W1.2 disposition is recorded either way.
- The three pre-existing test failures recorded during arm J are out of scope and stay untouched.
