# ADR: the endpoint-first prefix - feed the surface in the first human message

**Status:** EXPERIMENT, operator-directed (2026-10-13; branch `exp/endpoint-first-prefix`, off `dev` `68d430a`).
**Related:** `docs/design/proposer-per-batch-cache-adr.md` (the per-batch session + constant request shape this builds on), `docs/design/session-cache-measurement-348-adr.md`, `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md` (the arms D/E measurement this iterates on).
**Touches:** `analysis/reasoning_workflow.py`, `analysis/pod.py`, `analysis/{assigner,mechanism_typist,data_modeller}.py`, `app/llm/providers.py`.

---

## 1. The decision, in one line

Hoist the volatile base artifacts (the unit's observed L0 surface, the inventory, the unit context) into the FIRST human message of each proposer session - and feed the surface directly - so the largest, most-shared block is a stable request prefix the provider caches once and every later sub-problem turn re-reads from cache.

## 2. Why (the arm D failure mode)

Arms D and E ran the `service_sourced` / `batched_l1unit_first` pipeline, which is L1-unit-first: each proposer DISCOVERS its own surface through `graph_view` and the HTTP-history tools, and the settled surface is deliberately NOT pre-fed. Two measured consequences:

- **Endpoint placement regressed against arm A.** Arm D placed 70 of 290 endpoints (24.1%) against arm A's 82 (28.3%), and arm C (the prior L1-unit-first run) placed 21 (7.2%). The discovery path is a recall bottleneck: a Service whose contract does not name the right path-word harvests nothing.
- **The volatile base artifacts were re-injected into every sub-problem turn.** `render_turn` renders each `inject` source into each turn's human message, so the unit context and inventory were re-sent on every turn (6 turns for the assigner, 8 for the typist and data-modeller). The request prefix shared across a session's turns was therefore only the system prompt; the large volatile block never formed a stable cached prefix.

The operator's direction: move all endpoints to a first human message, and keep the identical prefix across cross-consumed units so the prefix cache hits reliably.

## 3. Change 1 - hoist the base artifacts into the first human message

**Rule.** The base artifacts (`surface`, `inventory`, `service`/`unit`, `vocabulary`, ...) ride the FIRST sub-problem's human message ONLY. Every later sub-problem injects only its derived dependencies (an earlier sub-problem's rendered artifact), never a base source.

**Implementation.** `reasoning_workflow.run_workflow` renders `render_base_block(base_artifacts)` once and prepends it to the first sub-problem's message; `render_turn` gains a `base_names` skip set so a base source named in `inject` is not re-rendered. The stateful session trail then carries the base block as the stable leading prefix of every later request, so the provider prefix cache re-reads it.

**Why this is safe.** The base artifacts are pure functions of the unit and the live inventory, resolved once at the body before the chain. The derived-dependency re-injection (the ADR D24 contract, so compaction cannot evict a dependency) is unchanged: dependencies are still rendered verbatim from the recorded turns.

## 4. Change 2 - the `surface` base artifact (feed the endpoints)

**Rule.** Each proposer's first human message carries an `OBSERVED L0 SURFACE` block: the unit's settled L0 assets rendered deterministically (`METHOD /path (baseurl)` for an Endpoint, `Type key=value, ...` otherwise), de-duplicated and sorted.

**Implementation.** `pod.surface_block(assets)` renders it. It is listed FIRST in each role's `base_artifacts`, so the largest block heads the request prefix. The assigner's chunk already carries the WHOLE settled surface in `assign_services` / `assign_global`, so its `surface` block is IDENTICAL across every Service unit - the "cross-consumed unit, identical prefix" property the operator named. The typist and data-modeller carry their unit's own aggregated surface.

**Determinism is load-bearing.** The block is byte-stable for the same surface, which is what lets the prefix cache match across units and across runs.

## 5. Change 3 - remove the per-role compaction thresholds

**Rule.** No role carries a `compaction_threshold` default; every role resolves through the global `LLM_COMPACTION_THRESHOLD` (0.2 on the eval instance).

**Why.** The arm E trial lowered the analysis proposers' thresholds (`mechanism_typist` 0.08, `data_modeller` 0.016) and measured a regression: compaction churn (8 `consecutive-pass cap` warnings against 0) rewrote the prefix, dropping cache hygiene to 76.2% against arm D's 87.8%, and quality fell with it (29 aggregates against 70). The operator directed a reset to the arm D value (0.2) for all agents. Removing the defaults makes the global authoritative rather than merely overriding.

## 6. What this does NOT change

- The role prompts, the sub-problem chains, the shaping gates, the fail-closed reflection gates, and the per-batch session address are untouched.
- The one-shot legacy seam (`prepend_prompt`) and the contract tier are untouched: `render_base_block` is inert with no base artifacts.
- The dependency re-injection contract (ADR D24) is untouched.

## 7. Consequences and the confirmation step

The three changes compose: the surface is fed once as the stable prefix (recall + cache), the later turns are small (cache), and no role compacts early (cache). The confirmation step is the live eval: measure whether endpoint placement recovers toward arm A and whether all Service units complete before the 4M capped-token budget.
