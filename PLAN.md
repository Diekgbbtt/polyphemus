# Plan: Overview entity + mechanised external bootstrap

Created 2026-10-16. Status: active.
Execution contract for the two operator tasks, approved in shape before implementation started.
This session is the orchestrator; workers are subagents.

## Task 1 - the Overview entity (+ the quality-assessment framework)

Add a structured `Overview` entity to the bootstrapped L1 surface: domain name, generalised feature description, and canonical navigation journeys (250-word budget).
Build the quality-assessment framework for bootstrapped artifacts, ready before the regeneration run.

## Task 2 - the mechanised external bootstrap

A self-contained module under `tools/bootstrap/` that mechanises the reverse-engineered external bootstrapping workflow.
It always uses opencode as the agent harness.
The target environment is a parameter: attach to a reachable target, or run a local or remote container lifecycle (build, launch, teardown).

## Settled decisions (operator, 2026-10-16)

- `Overview` is a structured skeleton attribute, not a graph node.
- `settings.application_overview` becomes `{domain, description, journeys[]}`.
- The KB `## Overview` section is upgraded; `l1-surface.yaml` gains a top-level `overview:` block.
- No new graph label; the consumer data flow stays contained.
- The external-bootstrap sources live canonically in `tools/bootstrap/` (recovered from the uncommitted `eval-data-dependencies` worktree copy).
- E2E scope: regenerate all artifacts for the 8 pre-pulled targets (comfyui, dataease, geoserver, jetlinks, phpbb, prestashop, siyucms, white-jotter) from scratch on the eval server, then assess them.
- Worktrees: W1 `feat/overview-entity` (base: local `dev` at `fbb3ae8` + cherry-picks `7dd4891`, `8e9a25d`, `4ea1246` from `feat/eval-platform-local`); W2 stacks on W1.

## Worktrees

- W1: `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/overview-entity` on `feat/overview-entity`.
- W2: created when W1 closes; branch `feat/external-bootstrap` stacked on W1's tip.

## W1 phases (task 1) - COMPLETE (2026-10-17)

- W1.0 Ontology grilling, one brief round (skill: `grilling`). DONE (`1f7601a`).
  Answers land in "Ontology decisions" below and feed the ADR.
- W1.1 Recover the bootstrap sources into `tools/bootstrap/`: `DATA-DEPENDENCIES.md`, `prompts/data-dep-{authn,l1,critic}.md`, `validate_data_dependencies.py` - from the `eval-data-dependencies` worktree copy. DONE (`c9a0270`, gitignore safety `a312def`).
- W1.2 Impact map. DONE (`1296614`, refined to the Q4 model in `b294858`).
  Enumerate every touchpoint of the structured Overview: scaffold parse and persistence, settings storage, inventory read and render, proposer reasoning, validator, creator and critic prompts, `l1-surface.yaml`, the contract, docs, tests, and the 8 committed KBs.
  Output: `docs/design/overview-entity-impact-map.md`.
- W1.3 TDD implementation (skill: `tdd`). DONE (`0888175` entity + parse/persist/read/render; `5970d53` delivery to the four consuming agents, validator gate, prompts, docs).
  Red tests first on the platform seams, then implementation, then the prompts and the validator.
- W1.4 Quality-assessment framework: criteria, scales, metrics, tooling. DONE (`aa5ecc2`; home `tools/bootstrap/assessment/`, baseline `baseline-pre-regeneration.json`).
  See "Assessment framework" below.
- W1.5 Documentation: `analysis/CONTEXT.md`, the ADR (`docs/design/application-overview-entity-adr.md`, a new ADR amending `operator-kb-overview-attribute-adr.md`), the impact map, the contract, the prompts. DONE (`5970d53`); the durable `to-spec` GitHub issue remains for the finalization step.
- W1.6 Commit series on `feat/overview-entity`. DONE (7 commits, tree clean).

## W2 phases (task 2)

- W2.1 Dependency audit.
  Data and functional dependencies of the reverse-engineered workflow; flag and address missing ones.
- W2.2 Artifact inventory.
  Prompts, scripts, staging layout, environment mechanics, eval-server recipe, per-API surfaces.
- W2.3 Architecture.
  Component diagram and workflow model (mermaid; skill: `show-me`).
  Persist to the system design specification (skill: `to-spec`; GitHub issue plus a `docs/design` ADR).
- W2.4 Implementation in `tools/bootstrap/`: package, environment adapters, orchestration assets, references.
- W2.5 Tests: unit and integration at the module seams; a local smoke run.
- W2.6 E2E: regenerate the 8 targets from scratch on the eval server (authn first, L1 second, critic, delivery).
  Orchestrator: this session; workers: subagents.
- W2.7 Assessment: run the W1 framework over the 8 fresh artifact sets; report per target and portfolio.
- W2.8 Docs and commits on `feat/external-bootstrap`.

## Gates

- G1 Operator answers the ontology grilling round.
- G2 Impact map complete before implementation.
- G3 W1 tests green; lint clean.
- G4 Operator confirms the spec seams (the `to-spec` step asks).
- G5 All 8 fresh artifact sets pass the deterministic validator and the quality assessment; docs current.

## Assessment framework (deliverable shape) - BUILT (`aa5ecc2`)

- Home `tools/bootstrap/assessment/`: `RUBRIC.md` (criteria, anchors, acceptance), `assess.py` (deterministic engine + portfolio), `llm_judge_prompt.md` (per-target semantic assessor), `README.md` (runbook), `baseline-pre-regeneration.json` (committed-view baseline).
- Criteria families: the structured Overview (A1-A4); the L1 KB (B1-B4); the l1-surface (C1-C3); the auth bundle (D1); research artifacts and the integrity boundary (E1-E2); semantic judgement by an LLM assessor (L1-L5: journey plausibility, description quality, contract discrimination, threat-model coverage, auth coherence).
- Scales: 0-4 ordinal with explicit anchors per criterion; per-target rollup; portfolio means/mins, failing list, baseline deltas.
- Mechanics: the validator gates; `assess.py` grades deterministically and merges the LLM verdicts from `<target>/assessment.yaml`.
- Baseline findings (committed view, 2026-10-17): all 8 targets score A1=2, A2=0, A4=0 (legacy prose Overviews - the W2 regeneration must lift A2/A4 to >= 3); B/C/E clean except siyucms E2=0 (research notes tie "template RCE" to a service - a true integrity hit to eliminate); D1=0 by design in the committed view (auth is staged outside git).

## Risks

- The eval server must still hold the 8 pre-pulled target images; verify before W2.6.
  Never run `docker system prune -a` on it.
- W2.6 is long; batch by phase and target.
- Hidden dependencies in the reverse-engineered workflow surface in W2.1; the audit exists to catch them early.

## Ontology decisions (W1.0 answers)

- Q1, domain: a domain name never changes - real targets keep theirs.
  In a benchmarking setting this requires the minted domain alias to be created consistently per target.
  The current eval system does not do this; recorded as lack L-1 below.
  The `domain` value is the target's stable canonical domain (for a benchmark target, its identity, for example `wordpress`), never the per-run synthetic Host.
- Q2, journeys: `journeys: [{name, steps: [str]}]`; at least 2 journeys, 3+ steps each; every step names at least one concrete surface part (route, form, menu entry, page navigation) and the activated component(s) by their KB identity.
- Q3, budget: the 250-word cap covers the whole Overview content and is enforced at every checkpoint: the creator (self-check), the critic (criteria), and the deterministic validator (hard count).
  The creator and the critic are LLM checks; they must both actively verify the cap.
- Q4, reasoning text (refined 2026-10-17 after operator feedback): the four item-consuming agents - assigner, mechanism typist, hunt orchestrator, hunter - each send a DEDICATED HumanMessage containing ONLY the Overview at the head of their turn.
  It is coupled cohesively to the following item-feeding humanMessages by specific introductory verbatims and chaining between the messages.
  The coupling is realised as: a shared intro verbatim on the Overview message, a per-site chaining verbatim opening the item message, and a clean deterministic render without formatting noise.
  The Overview message heads the thread once; later calls (typist calls 2-3) and later phase turns (orchestrator ratify/note) continue the same thread.
  Curation and sweep (housekeeping passes) do NOT get the Overview; the earlier "prepend at every inventory dump" reading is superseded.
  The in-system bootstrap message is the creation pass (no overview exists yet) and its mechanism is being retired; it keeps its current shape.
- Q5, KB format: the least complex, most structurally reliable parse wins; the ephemeral KB format itself is not a concern.
  Decision: a fenced YAML block under `## Overview`, read with `yaml.safe_load`; legacy prose stays accepted (mapped to `description`).
- Q6, assessment framework: extensive - rubric across all artifact families (Overview, L1 surface, auth bundle, cross-artifact consistency, graph loadability), ordinal scales with explicit anchors, per-target and portfolio metrics, deterministic checks plus an LLM assessor; lives in `tools/bootstrap/assessment/`.
- Q7, e2e artifacts: the fresh from-scratch artifacts replace the committed 8-target set on the W2 branch, gated by the validator and the assessment; auth bundles and skills stay out of git.

## Recorded lacks

- L-1, minted domain consistency: the eval front mints a per-run-unique synthetic Host (`eval/orchestrator/routing.py`: `synthetic_host` returns `t-<short>.target` per TargetRun).
  A stable domain per target is required for the Overview `domain` to be meaningful and for canonical journeys to hold across runs.
  Handle in the W2.1 dependency audit: the minted alias must be created consistently per target (fix or follow-up ticket).
