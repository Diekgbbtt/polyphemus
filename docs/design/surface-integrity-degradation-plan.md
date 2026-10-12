# Plan: L0 surface integrity, assigner degradation, and the operator_kb Overview attribute

Status: draft, written 2026-10-12 on branch `feat/surface-integrity` (worktree `/Users/diekgbbtt/.claude/worktrees/surface-integrity`, off `dev` at `5e30332`).
Authority: the operator's feedback of 2026-10-12 on the comfyui analysis-only diagnosis.
Scope: four work items, sequenced W-a -> W-c -> W-b -> W-d.

## Evidence base

The comfyui analysis-only run stalled on `community-sharing` and proposed zero aggregates for `comfyui-update`.
The root-cause chain, from the live stack:

1. The recon crawl recorded a fuzzing-polluted surface and never reached the ComfyUI-Manager API.
2. The skeleton names nine Manager Services the surface cannot satisfy.
3. The assigner's `graph_view` queries were well-formed and broad, but found nothing for a Manager Service, so the model fell back to the raw HTTP firehose.
4. `search_http_history` returned about 250 KB per call; the store holds 110,809 URLs with a maximum of 3,546 chars, 13,011 over 1 KB, 36.8 MB total.
5. The context blew to 422k-681k tokens; compaction churned, the assigner proposed nothing for one Service, and the next Service stalled.

Measured facts that bound the work:

- The project graph holds 290 Endpoints; the raw history holds 110,741 flows.
- Zero `/api/manager`, zero `/manager/`, zero `/customnode`, zero `comfyworkflows` in the graph and in the raw history.
- The "manager"/"share" hits are wordlist probes (`/wp-dbmanager`, `/sqlmanager`) and another application's routes (`/datasourcemanager/`, `/api/heroes`).
- The store also contains the kali container's own tool-update traffic (`api.pdtm.sh`).
- The project holds zero `AGGREGATES` edges: the assign stage has never produced an assignment here.

## Decisions taken (operator, 2026-10-12)

- All four work items are in scope, sequenced W-a -> W-c -> W-b -> W-d.
- The fuzzing gate lives at whichever of the proxy or the store is simplest and most reliable.
  The proxy sees TCP/HTTP, not the local process, so a source-tool denylist is infeasible there; a capture-time content-shape predicate is the reliable option.
- HTTP-history scope is enforced at BOTH capture time and query time.
- The macro Overview is a SKELETON ATTRIBUTE, not a new node.
- The external bootstrapper's prompt is the operator's to adjust; this plan only lands the in-repo contract and the downstream plumbing.

## W-a: HTTP-history capture integrity (feedback 1 + 2)

Goal: the store holds ONLY in-scope navigational traffic to the target.

The invariant: a recorded flow is (a) correlated to the target project, and (b) not a fuzzing/param-mining/tooling artifact.

Changes:

- Add a capture-time content-shape predicate in `kali/http_history/addon.py` (or its `normalize.py` seam) that drops a flow whose request shape is a fuzzing artifact.
  The predicate is deterministic and conservative: a query-parameter count over a threshold, or a path segment over a length limit, or a repeated-parameter signature.
  It bumps a status counter (`excluded_fuzzing`) that `proxy_status()` discloses, exactly as `excluded_websocket` does today.
- Verify and, if needed, harden the capture-time scope: the resolver already routes an uncorrelated flow to `unscoped`; confirm the container's own tooling traffic cannot correlate to the project.
- Assert the query-time scope: `search_http_history` must refuse a request with no project scope and must never read the `unscoped` store.

Feedback loop (red-capable, deterministic):

- A unit test in `tests/kali/` that a fuzzing-shaped flow is excluded and a normal navigation flow is recorded.
- A unit test that an `unscoped` flow is never returned by a project-scoped query.
- An assertion that `excluded_fuzzing` appears in `proxy_status()`.

Open sub-question to resolve while implementing: whether the fuzzing predicate must also be applied to flows already in a live store (a one-shot migration) or only to new captures.
The default is new captures only; a live store is re-derivable, and the eval re-runs the crawl.

## W-c: recon surface acquisition for the Manager API (feedback 4)

Goal: decide, with evidence, whether the recon crawl must change, or whether a clean capture already suffices.

The hypothesis to falsify: with the W-a gate in place, the existing crawl reaches the Manager API, so no crawler change is needed.

Investigation, in order:

1. Read the recon crawl configuration (the katana/httpx depth and scope settings) and the comfyui `surface-map.md`.
2. Determine why `/api/manager/*` is absent: was the Manager UI reached at all, or was only path-fuzzing performed.
3. If the crawl never navigates the UI, specify the smallest change that makes it reach the Manager API (a seeded route set, or a UI-navigation step), and record it as a follow-up ticket rather than building it here.

Feedback loop:

- If the hypothesis holds, a live recon of a clean store, asserting `/api/manager` appears in the L0 graph.
- If it fails, a written finding plus a follow-up ticket; no code change in this work item.

This work item is diagnostic-first.
It may conclude "no change", and that is a valid outcome.

## W-b: assigner degradation branches (feedback 3)

Goal: when a Service's contract finds no related surface after a bounded search, the assigner degrades explicitly instead of escalating to the firehose.

The search order, per the operator: multiple `graph_view` queries FIRST, then SURGICAL `search_http_history` queries.

Changes:

- Bound the `harvest_surface` discipline in `analysis/prompts/assigner-batched-l1unit-first.md`: replace "HARVEST AGGRESSIVELY ... query BROADLY" with surgical, bounded, path-filtered queries.
  Require an explicit url-path filter string on every `search_http_history` call.
- Add a degradation branch to the `WORKFLOW` in `analysis/assigner.py`: when `falsify_harvest` yields no survivors, halt to a `no_surface` terminal instead of running `candidate_owners`/`assign`.
  `ReasoningWorkflow` already supports `halt_when` (the mechanism-typist uses it).
- Make the degraded outcome observable: the `modelling-closure` note records `no_surface`, and the run census distinguishes it.

Feedback loop (red-capable, deterministic):

- A unit test that the workflow halts at `falsify_harvest` with no survivors and does not run `candidate_owners`.
- A unit test that the closure note kind/verdict records the degraded outcome.
- A prompt-content test asserting the surgical-query discipline replaced the aggressive one.

## W-d: operator_kb Overview as a skeleton attribute (feedback 5)

Goal: the macro Overview rides the skeleton as an attribute, and every Service's HumanMessage is prefixed with it.

The Overview already exists in every `operator_kb.md` under `## Overview`; `scaffold.py` currently ignores it (it parses only Services, Systems, Roles).

Changes, upstream to downstream:

- `analysis/scaffold.py`: parse `## Overview` and return it alongside the shells.
- The skeleton attribute: carry the Overview as an L1 skeleton attribute (operator decision: attribute, not node).
  Determine the exact carrier while implementing (the settings blob, the shells batch, or an L1 project attribute) and record it as an ADR.
- Downstream: thread the attribute to the effective querying component so each Service's HumanMessage is prefixed with it (an `inject` source on the assigner, and the same on the typist and data-modeller turns).
- Prompt contract: add the Overview requirement to the base prompt and to `analysis/prompts/bootstrapper.md`.
- Retrofit the five existing `eval/data/webexploitbench/<target>/operator_kb.md` files.
- The external bootstrapper prompt (`tools/eval/kb-authoring.md`, recovered from session `ses_f8ef9ce44`): the operator adjusts it; this plan does not.

Feedback loop (red-capable, deterministic):

- A unit test that `parse_kb` returns the Overview text.
- A unit test that the skeleton write carries the attribute.
- A render test that a Service's user message contains the Overview prefix.

## Documentation pass (per CLAUDE.md, before each commit)

- An ADR for the Overview skeleton attribute, and one for the capture fuzzing gate.
- Update the owning `CONTEXT.md` glossaries and `docs/design/domain-model.md` for the new attribute.
- Amend any superseded decision.

## Sequence and commit gates

1. W-a: red tests, implementation, `pytest tests/kali -q`, docs, commit. DONE (`15c2aed`).
2. W-c: investigation report; a ticket if a crawler change is needed; no code change if not. DONE (`5a5eb32`, ticket #353).
3. W-b: red tests, implementation, `pytest tests/analysis -q`, docs, commit. DONE (`f4e9a43`).
4. W-d: red tests, implementation, `pytest tests/analysis -q`, docs, commit. DONE (`63334d2`).

Each work item ended with its targeted suite green and its documentation landed.

## Status (2026-10-12)

All four work items are landed on `feat/surface-integrity`.
Full non-e2e gate: 5203 passed, 45 skipped, 1 xfailed; the 12 failures are the
live `tests/test_steel_exec_live.py` suite, which calls `docker compose up` and
fails because Docker is not installed locally (pre-existing, environmental).

Remaining slices (follow-up, not in this change):

- W-d: prepend the Overview in the mechanism-typist and data-modeller unit
  contexts, and retrofit any `operator_kb.md` without an Overview.
  DONE (`28a17af`): all three proposers prepend it; all five kb files already
  carry an Overview, so no retrofit was needed.
- W-c: the crawl-hint ticket #353.
- W-a: a live run to confirm the store is clean and the capture counters move.

## Release and measure

Once every work item is implemented and the relevant part of the test suite is
green:

1. Commit the work (done: W-a `15c2aed`, W-c `5a5eb32`, W-b `f4e9a43`, W-d
   `63334d2` + `28a17af`).
2. Merge `feat/surface-integrity` into `dev`.
3. Push `dev`.
4. Check the alignment of the stack (the version-advance / alignment action:
   restart, recreate, or config-layer adjustment for each impacted component).
5. Run the SAME trial as the diagnosed run (comfyui, `webexploitbench-8-run2`),
   starting ONLY the analysis pipeline.
6. Measure again, following `/measure-experiment-results`, with a COMPARATIVE
   approach against the best prior version.
7. Write the report in the comparison document
   (`docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`),
   always.

