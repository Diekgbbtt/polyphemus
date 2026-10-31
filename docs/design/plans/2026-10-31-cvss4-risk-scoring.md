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
| T2 | Schema v5 expand | T1 | `RiskMetrics`, `SeverityBand`, the v5 assessment and threat shapes, the v5 profile, the v4 read path. |
| T3 | `assess_impact` tool and store method | T2 | One atomic assessment write, the state advance, the success/fail response, the commit-time score. |
| T4 | Modeller pass and prompt switch | T3 | The tool in the surface, the `hunts_store` section removed, the factor semantics and examples in the prompt. |
| T5 | Store v5 and threat mirror | T4 | The v5 completion, the threat risk mirror, the v5 threat file, the v5 prior-art paths, the v4 write refusal. |
| T6 | Hunter payload and prompt | T5 | The payload renders the score, the band, the vector, the factors, the two prose blocks, and the assumption confidences. |
| T7 | Per-threat dispatch queue | T5 | Float risk in the mover, the float promotion floor, the global threat order, no per-unit cap. |
| T8 | Run lifecycle and risk accumulator | T5 | Float total, band breakdown, the scaled default, the float env parse. |
| T9 | Settings API and repository | T8 | Float thresholds in the API, the repository, and the setup reader. |
| T10 | Eval metric and impact review | T5 | The v5 metric path, the v4 raw path, the review schema, the setup floats. |
| T11 | Contract and documentation convergence | T6, T7, T8, T9, T10 | Delete the likelihood and impact code, the old tests, and the old docs; the full documentation pass. |
| T12 | Scripted end-to-end walkthrough | T7, T10, T11 | One v5 model written through the tool, scored, and dispatched through the queue. |
| T13 | Final adversarial review | T12 | The compliance, coverage, and pattern review. |

## The loop per ticket

1. Dispatch one implementer subagent with the ticket text, the spec sections, the impact map rows, and the verification commands.
2. The implementer works test-first, commits, and self-reviews.
3. Dispatch the spec-compliance reviewer. The reviewer checks the ticket acceptance criteria against the diff.
4. Dispatch the code-quality reviewer. The reviewer checks the tests, the patterns, and the edge cases.
5. Fix and re-review until both approve.
6. Record the ticket status in this plan.
7. Move to the next frontier ticket.

The final ticket is one adversarial review over the whole branch.
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
| T1 | pending | |
| T2 | pending | |
| T3 | pending | |
| T4 | pending | |
| T5 | pending | |
| T6 | pending | |
| T7 | pending | |
| T8 | pending | |
| T9 | pending | |
| T10 | pending | |
| T11 | pending | |
| T12 | pending | |
| T13 | pending | |
