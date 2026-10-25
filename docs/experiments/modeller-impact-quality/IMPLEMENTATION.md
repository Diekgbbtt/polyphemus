# Impact-elicitation workstream: implementation result

*Status: implemented on `feat/threat-model-impact-elicitation`, based on `hunt-enhancement-trunk` at `5c73ab82`. The A/B is pending the operator's protocol.*

## What landed

### Scoring

- Every loop carries `impact` with `VC`, `VI`, `VA`, each `none/low/medium/high`, and a literal `end_impact`.
- The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight `0..4`, and `loop risk = likelihood_weight * impact_weight`.
- The ordinal bands are `1` at `(0, 0.25]`, `2` at `(0.25, 0.50]`, `3` at `(0.50, 0.75]`, `4` above `0.75`.
- The ranking is risk, impact, likelihood, write order. A loop with zero risk is stored and never dispatched.
- The run record carries `risk_weights`, `impact_weights`, `risk_total`, `risk_breakdown`, `impact_breakdown`, and the per-unit sums.
- The provisional threshold is `360`; the A/B sets it per arm.

### Trust modelling

- The prompt works four axes: `identity`, `spatial`, `temporal`, `controls_semantics`.
- Identity names the concrete artifacts (sessions, cookies, tokens, claims, delegation headers, workload identities) and the downstream re-establishment.
- Spatial enumerates the spatially significant variables at each interface and during processing, traces their origin and lifecycle, and distinguishes resource-selecting identifiers from identity claims.
- Temporal covers state and time, concurrency assumptions, replay, freshness, partial states, stale caches, fail-open fallbacks, TOCTOU, and DNS rebinding.
- Controls semantics characterizes the invariant checks, their placement across stages, their effective representation downstream, and the gap between syntactic validity and semantic safety.
- Each trust agreement names the artifact, the controlling principal, the security-sensitive decision, and the worst-case end impact.

### Well-formedness loop

- Between `VULNERABILITIES_WRITTEN` and `COMPLETED`, the modeller loads each bound class skill, reads the title, the Trust Assumptions section, and the closing summary, and adds the missed assumptions.
- A local gap patches the affected agreement, assumption, or vulnerability and re-checks.
- A structural gap loops back over the undermodelled part. There is no iteration bound; the run cap is the bound.
- The exit is one `wellformedness` note plus the `COMPLETED` write. A lower-gate write is the re-entry signal; the passive tracker already records it as `lower_gate`.
- The note records the vulnerabilities checked, the skills loaded, the assumptions added, the absent Trust Assumptions sections, the structural finding, and the final action.

### Failure modes removed

- The `failure_modes` section, `Loop.failure_mode_refs`, the prompt phase, the encoding floor, the pod `failure-mode` variant basis, and the hunter failure-mode vocabulary are removed.
- The drop rule has two clauses: the data is not attacker-influenced, or the trust agreement is misspecified because the artifact does not reach a security-sensitive decision. Unobserved assumptions survive. A missing observation or a failed probe is not a drop reason.
- The modeller still judges exploitability through the likelihood, which names the adversarial capabilities the attack needs. The hunter and the pod own technical feasibility and effective attempt.

### Class binding

- Every vulnerability binds a suite class parent or leaf.
- Technique families (`defence-bypass`, `proxy-techniques`, `two-principal-authz`) are forbidden as the class and stay in the characterisation.
- A novel class binds its nearest parent and keeps the novel name in `canonical_class`.
- `suite_gap` is removed.
- The completion checker records a non-blocking `class_findings` entry for an empty class, a technique family, or a non-suite name. It never makes the model invalid. The store accepts an optional `class_names` index for the non-suite check.

### Composite example

The prompt carries one synthetic SSRF/TOCTOU example:
- a `source_host` field concatenated into a URL;
- an allowlist checked at initialisation, not at fetch;
- a TOCTOU assumption;
- `VC=high`, `VI=low`, `VA=none` -> `0.6568` -> weight `3`;
- the SSRF skill's Trust Assumptions countercheck and a local patch;
- a soft-404 contrast that stays stored with impact zero and no priority dispatch.

## Commits

- `9eb66a0a` - baseline measurement.
- `e7fc64b1` - plan, impact map, tickets 402-420.
- `9b5f97c6` - impact model and combined risk (402, 404, 405).
- `6f4b5385` - hunter impact and combined run/dispatch (406-409).
- `de9cb2c5` - failure-mode schema removal (416, pulled forward).
- `8a5bf072` - modeller prompt rewrite, well-formedness pass, class guard, example (410-414).
- `2e2037a5` - pod basis removal, hunter vocabulary cleanup, docs (415, 417-420).

## Verification

| Suite | Result |
|---|---|
| `tests/attack` | 1094 passed |
| pod contracts and e2e walkthrough | 27 passed |
| project management plus settings deep merge | 8 passed, 2 skipped |
| eval orchestrator trial | 68 passed |
| `compileall` on the hunting module | clean |
| `git diff --check` | clean |

## A/B plan

- The success gate is more than 90% green loops over all stored loops.
- A green loop is a loop whose `web_vulnerability_class` is in the ratified high-yield set plus CSRF and clickjacking, rolled up to its class parent.
- Secondary metrics: severe share, sharp-boundary share, class-binding rate, severe loops below the medium risk bucket, capped tokens per green loop.
- The operator will specify the 7M budget split, the unit set, the fresh-instance reset, and the measurement window after implementation.
- Both arms must use the same threshold, or the comparison is not fair.

## Follow-ups

- The eval measurement prompt still uses the phrase "failure-mode slice" in its checklist. That is the eval measurement vocabulary, outside the hunting module. Update it when the eval measurement workstream next runs.
- The production store does not yet pass a suite class index to `check_completion`, so the non-suite finding runs only where a caller supplies `class_names`. The empty and technique-family findings run always.
- The `360` threshold is provisional until the first re-model writes real `VC/VI/VA` values. The A/B sets it per arm.
- The A/B is the remaining step; it is an experimentation item, not a tracked ticket.
