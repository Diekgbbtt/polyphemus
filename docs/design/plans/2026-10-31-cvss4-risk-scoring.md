# Plan: CVSS 4.0 risk scoring

*Status: active, 2026-10-31.*
*Spec: `docs/design/cvss4-risk-scoring-spec.md`.*
*Impact map: `docs/design/cvss4-risk-scoring-impact-map.md`.*
*Decisions: `docs/design/threat-model-cvss4-risk-scoring-adr.md`, `docs/design/impact-assessment-atomic-write-adr.md`.*

## Goal

Replace the likelihood-times-impact score with the CVSS 4.0 base score over factors compiled from the kill chain.
Move the score to the impact assessment row.
Make `assess_impact` the sole writer.
Remove confidence from threats and vulnerabilities.
Order the dispatch queue by threat risk.
Make the two thresholds floats.
Land schema v5 with a v4 raw read.

## Workspace

- Worktree: `cvss4-risk-scoring`.
- Branch: `feat/cvss4-risk-scoring`, based on `hunt-enhancement-trunk` at `ae0955fd`.
- No push and no merge without the operator.
- One commit per ticket. The final commit is the adversarial review pass.

## Ticket sequence

The sequence is expand-contract.
The expand tickets add the v5 form beside the v4 form and keep the suite green.
The migrate tickets switch the readers and the writers.
The contract ticket deletes the v4 form and the old tests.
The final ticket is the live walkthrough.

| # | Ticket | Blocked by | Delivers |
|---|---|---|---|
| T1 | Risk module and known-vector tests | none | `compute_risk`, `build_vector`, `severity_band`, `validate_metrics`, `FACTOR_DESCRIPTIONS` over `cvss==3.6`. |
| T2 | Schema v5 models and v4 raw read | T1 | `RiskMetrics`, `SeverityBand`, the v5 assessment and threat shapes, the v5 profile, the v4 raw read, the model validators. |
| T3 | Store v5 write, completion, and threat mirror | T2 | The tool-only assessment write, the state advance, the threat risk mirror, the v5 threat file, the v5 prior-art paths, the v4 write refusal. |
| T4 | `assess_impact` tool, modeller pass, and prompt | T3 | The tool in the surface, the `hunts_store` section removed, the factor semantics and examples in the prompt, the gate hints. |
| T5 | Threat file, prior-art, payload, and hunter prompt | T4 | The payload renders the score, the band, the vector, the factors, the two prose blocks, and the assumption confidences. |
| T6 | Per-threat dispatch queue and float mover | T3 | Float risk in the mover, the float promotion floor, the global threat order, no per-unit cap. |
| T7 | Run lifecycle and settings API | T3 | Float total, band breakdown, the scaled default, the float environment parse, the float API and repository. |
| T8 | Eval metric and impact review | T5 | The v5 metric path, the v4 raw path, the review schema, the setup floats. |
| T9 | Contract deletion and documentation convergence | T5, T6, T7, T8 | Delete the likelihood and impact code, the old tests, and the old docs; the full documentation pass. |
| T10 | Scripted end-to-end walkthrough | T6, T8, T9 | One v5 model written through the tool, scored, and dispatched through the queue. |
| T11 | Final adversarial review | T10 | The compliance, coverage, and pattern review. |

## The loop per ticket

1. Dispatch one implementer subagent with the ticket text, the spec sections, the impact map rows, and the verification commands.
2. The implementer works test-first, commits, and self-reviews.
3. Run the targeted tests and the ticket's grep gate in the controller.
4. Record the ticket status in this plan.
5. Move to the next frontier ticket.

There is no per-ticket spec or code-quality review.
The one critical adversarial review runs at T11 over the whole branch.
It checks the spec, the outliers, the test breadth and depth, and the `src/polymerhus/attack/hunting/CONTEXT.md` patterns.

## Verification commands

- Unit: `.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/integration`
- Targeted: `.venv/bin/python -m pytest tests/attack tests/project_management tests/eval -q`
- Lint: the repo's configured linter over the changed files.
- Grep gates:
  - no production reference to `Likelihood`, `RISK_WEIGHTS`, `impact_weight`, `impact_severity`, `RiskFactors` after T11;
  - no `Threat.confidence` or `Vulnerability.confidence` after T11;
  - no `likelihood` in the hunting prompt after T4.

## Risks and mitigations

- The v5 schema and the v4 read can diverge. Mitigation: T2 adds a v4 raw-read test before any writer changes.
- The tool-only gate can strand a model. Mitigation: T3 tests the state advance and the completion findings; T4 tests the pass.
- The per-threat queue can starve a unit. Mitigation: T7 tests a one-threat unit against a four-threat unit.
- The float thresholds can break the run-record resume. Mitigation: T8 tests the record round-trip and the resume.
- The payload can lose the assumption confidence. Mitigation: T6 asserts the assumption refs and the confidence in the payload.
- The eval metric can silently fall back to v4. Mitigation: T10 has a v5 fixture and a v4 fixture with distinct expected values.

## Out of scope

- The pod and triager workstream.
- The recon and Steel crawl.
- The CVSS threat, environmental, and supplemental metrics.
- A FIRST validation pass.
- The frontend.
- The `threat_model_scope` fence.

## Status

| # | Status | Commit |
|---|---|---|
| T1 | done | 224b916a + review fixes |
| T2 | done | 882d36ac |
| T3 | done | 5eb1f710 |
| T4 | done | 81232bb1 |
| T5 | done | df7995c7 |
| T6 | done | 3f6d1dbc |
| T7 | done | 123ce4e2 |
| T8 | done | c522b43d |
| T9 | done | d3bba8f3 |
| T10 | done | 328583a3 |
| T11 | done | review approved; polish commit pending |
