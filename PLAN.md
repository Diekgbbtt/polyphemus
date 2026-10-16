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

## W1 phases (task 1)

- W1.0 Ontology grilling, one brief round (skill: `grilling`).
  Answers land in "Ontology decisions" below and feed the ADR.
- W1.1 Recover the bootstrap sources into `tools/bootstrap/`: `DATA-DEPENDENCIES.md`, `prompts/data-dep-{authn,l1,critic}.md`, `validate_data_dependencies.py` - from the `eval-data-dependencies` worktree copy.
- W1.2 Impact map.
  Enumerate every touchpoint of the structured Overview: scaffold parse and persistence, settings storage, inventory read and render, proposer reasoning, validator, creator and critic prompts, `l1-surface.yaml`, the contract, docs, tests, and the 8 committed KBs.
  Output: `docs/design/overview-entity-impact-map.md`.
- W1.3 TDD implementation (skill: `tdd`).
  Red tests first on the platform seams, then implementation, then the prompts and the validator.
- W1.4 Quality-assessment framework: criteria, scales, metrics, tooling.
  See "Assessment framework" below.
- W1.5 Documentation: `analysis/CONTEXT.md`, `docs/design/domain-model.md` where the model changes, the ADR (`eval-data-dependency-placement-decisions.md` extension), the contract, the prompts.
- W1.6 Commit series on `feat/overview-entity`.

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

## Assessment framework (deliverable shape)

- Criteria families: Overview ontology conformance; L1 surface completeness and grounding; auth bundle conformance; cross-artifact consistency; graph loadability.
- Scales: per-criterion ordinal scale with explicit anchors; per-target rollup; portfolio metrics.
- Mechanics: deterministic checks (validator extensions) plus an LLM-assessor rubric; one report artifact per target.
- The per-target critic stays the delivery gate; the framework is the graded measurement layer.

## Risks

- The eval server must still hold the 8 pre-pulled target images; verify before W2.6.
  Never run `docker system prune -a` on it.
- W2.6 is long; batch by phase and target.
- Hidden dependencies in the reverse-engineered workflow surface in W2.1; the audit exists to catch them early.

## Ontology decisions (W1.0 answers)

Pending.
