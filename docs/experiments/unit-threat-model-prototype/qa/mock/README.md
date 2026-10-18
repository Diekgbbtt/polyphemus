# Mock-hunter package - TestImplementationSpecs QA (S3)

Purpose: mock the respecified hunter feed-forward contract as realistically as the harness allows, over the 22 loops minted by the two trial threat models (T1: 13, T2: 9).
The artifact under measure is the TestImplementationSpecs set per loop.

**Superseded for production (2026-10-18).** This package is a measurement artifact only; the operator ruled it is not the production prompt. The production prompt redesign decisions (role framing, decision-tree integration, typed-surface reframe, the two new frontiers) live in workbench R8-1..R8-3 and workflow-doc section 3.6.

## Layout

- `system-prompt.md` - the improved hunter prompt: loop-entity ontology, attack-engineering reasoning, discrimination axes, well-formedness definition, output contract pointer.
- `task-template.md` - the human-message template for one loop (abduction rendering; failure modes withheld).
- `output-contract.md` - the YAML schema of the spec set plus a worked fragment.

## Inputs

- Payloads: `../t1/input/loop-*.yaml`, `../t2/input/loop-*.yaml` (+ `manifest.yaml` in each).
- Built by `../build_payloads.py` from the trial models; the S1 gate verified: every payload parses, refs resolve, and no failure-mode material is present.
- Skills: `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/` (class skills as fs files: `ssrf`, `path-traversal-lfi-rfi`, `insecure-file-uploads`, `business-logic`, `csrf`, `xss`, `information-disclosure`, `race-conditions`, plus the rest of the suite).

## Outputs

- `../t1/output/loop-*.yaml`, `../t2/output/loop-*.yaml` - one spec set per loop.
- `../t1/run-log.md`, `../t2/run-log.md` - per-loop run notes.

## Mock fidelity and deviations (named)

- Tools: filesystem (read/list/write), shell, web search/fetch - as many as the harness grants; **no `lightrag_query`** (the design-time KB retrieval is excluded by operator order).
- No live target probing and no test execution: the real hunter's pod step closes as not-executed by design in this mock; the spec set is the artifact under measure.
- No attack-surface graph or HTTP-history database: target facts come from the payload's sharpening, trust, and deployment fields only.
- Isolation for validity: the mock reads only its payload, this package, and the skills directory; it must never read the trial model YAML or the measurement document (which contain failure modes).
