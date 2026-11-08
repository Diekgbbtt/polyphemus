# Threat-model risk scoring on the CVSS 4.0 base algorithm - ADR

*Status: proposed 2026-10-31. Decision owner: operator. Grilled 2026-10-31.*
*Supersedes the risk formula in `docs/design/threat-model-impact-elicitation-adr.md` and the `likelihood` enum in `docs/design/unit-threat-model-workbench.md` (Q33, R3-1).*
*Companion: `docs/design/impact-assessment-atomic-write-adr.md`.*

## Context

The iteration D assessment (white-jotter, 2026-10-27) returned 2 identified, 2 partial, and 3 missed ground-truth vulnerabilities out of 7.
The scored model held 27 threats.
Three scoring defects are visible in the persisted rationales, and none of them is a discovery defect:

- A stored XSS was scored `medium` likelihood and risk 6.
  Its rationale lowered the class because "a reader opens the article, which is a victim action the writer cannot force".
  That is a victim-action precondition, not an attacker capability requirement.
- Two directions were explicitly demoted for an `ASSUMED` premise.
  The remember-me deserialization says "Load-bearing premise is ASSUMED, so the class is lowered".
  The client-render disclosure says "Premise assumed, so the class is lowered one step from high".
- The likelihood is a free-form summary.
  `RiskFactors` (attack vector, attack requirements, privileges required, complexity) are stored but never feed the score.
  The score is `likelihood_weight * impact_weight`.

The impact model is a first-party CVSS-4.0-like formula: `1 - (1-VC)(1-VI)(1-VA)` over four levels (`none/low/medium/high`), with an ordinal weight from monotone thresholds.
CVSS 4.0 has no `medium` impact value. The valid set is `high`, `low`, and `none`.
CVSS 4.0 also defines no exploitability sub-score. The base score is a macrovector lookup that always includes impact.

The pipeline needs one severity score that the model cannot author, that is standard where the standard applies, and that is deterministic from enumerated factors.

## Decision

### 1. One score, the CVSS 4.0 base score

`risk` is the CVSS 4.0 base score of the threat's impact assessment.
It is a float in `0.0 .. 10.0`, rounded to two decimals.
It is the only severity number.
The qualitative band is derived on read from the standard CVSS bands:

| band | range |
|---|---|
| none | `0.0` |
| low | `0.1 .. 3.9` |
| medium | `4.0 .. 6.9` |
| high | `7.0 .. 8.9` |
| critical | `9.0 .. 10.0` |

There is no separate severity field, and no `likelihood x impact` product.

### 2. The metric set is the CVSS 4.0 base group, with mirrored subsequent-system impact

The authored metrics are `AV`, `AC`, `AT`, `PR`, `UI`, `VC`, `VI`, and `VA`.
`SC`, `SI`, and `SA` mirror the vulnerable-system values: `SC = VC`, `SI = VI`, `SA = VA`.
No threat, environmental, or supplemental metrics are authored.
The vector is a derived serialization of the eight authored metrics plus the three mirrors.
It is persisted for audit, never authored, and never echoed to the model.

### 3. The factors are compiled from the kill chain

The factors describe the attack as it would run if the fault is present.
They are never discounted for an unverified premise.

- `PR` is the role and the permissions needed to use the application primitives in the chain.
- `AC` is the defence that must be circumnavigated: sanitizers, rate limiters, CSP, CORS, cookie attributes, authorization controls, and the trust controls elicited in the trust-control-semantics phase.
- `AT` is any other attacker capability that adds a phase: a planted XSS payload for exfiltration, DNS rebinding for an SSRF and TOCTOU RCE, JWKS access for forged tokens and session fixation, and the rest of that class.
- `AV` is the network position.
- `UI` is passive for a routine operational flow or a common application state, and active for a specific non-routine victim action.
  The prose leaves passive interaction implicit and states active interaction briefly.

A multi-request chain is not `AT:P`.
The step count is not a factor. The capability the step requires is.

### 4. Impact values are `high`, `low`, and `none`

`VC`, `VI`, and `VA` use the standard values.
The decision prose maps a direct, serious loss to `high`, a partial or bounded loss to `low`, and no loss to `none`.
Brief examples live in the tool contract, one line per value.

**Correction to the 2026-10-31 grilling answer.**
The grilling accepted `high/none` after I stated that CVSS 4.0 has no `medium`.
The standard also has `low`, and `cvss==3.6` accepts `VC:L`.
This ADR uses `high/low/none` for standard fidelity.
If the operator prefers the binary collapse, this is the one decision to reverse.

### 5. Confidence is removed from threats and vulnerabilities

`Threat.confidence` and `Vulnerability.confidence` are removed.
`Confidence` remains on the six technical and trust-model claims: `Agreement`, `TrustAgreement`, `DynamicState`, `Transition`, `Violation`, and `Assumption`.
It is a verification-planning attribute: it tells the hunter which premises to probe.
It never feeds the score.

### 6. `likelihood` is retired

`Likelihood`, `RISK_WEIGHTS`, `Threat.likelihood`, and `Threat.likelihood_rationale` are removed.
`Threat.exploitability_rationale` is retired in favour of the assessment's `exploitability_description`, which describes the exploitability, not the evidence state.
`Threat.risk_factors`, `Threat.impact`, `Impact`, `ImpactLevel`, `ImpactSeverity`, `IMPACT_METRIC_WEIGHTS`, `impact_weight`, and `impact_severity` are removed.

### 7. The score is computed at persistence, never by the model

A thin local component wraps `cvss==3.6` (LGPLv3+).
It builds the vector from the structured factors, computes `CVSS4(vector).base_score`, rounds to two decimals, and validates the factor set.
It runs inside the persistence commit, after validation and before the write is durable.
The model never sees the score.
A detached worker is rejected: it would write a null score, force every consumer to handle the window, and add a reconciliation gate for a sub-millisecond pure calculation.

### 8. Thresholds are scaled proportionally, not calibrated on a past run

The old per-threat maximum was 16; the new maximum is 10.
The proportional factor is `0.625`.

| setting | old | new |
|---|---|---|
| `DEFAULT_RISK_THRESHOLD` | 250 | 156.25 |
| iteration D `risk_threshold` | 180 | 112.5 |
| iteration D `promotion_risk_threshold` | 4 | 2.5 |

The settings API and the run record use floats.
The comparison stays inclusive.
The severity bands are the standard CVSS bands, not a scaled version of the old buckets.
The iteration D corpus is recorded as evidence of the scoring change. It does not set a threshold.

### 9. The dispatch queue is per-threat risk descending

The queue orders threats by `risk` descending, ties by the store rank and the write order.
It does not order units by their model sum, and it applies no per-unit cap.
The unit model sum remains a run-record field for the budget and the audit.

### 10. Schema v5

`SCHEMA_VERSION` becomes 5.
A v4 document is read raw for prior art and measurement. It is never re-scored.
A v5 document is normalised.

## Reconstructed iteration D corpus

The table below is a first-pass reconstruction, not a re-run.
It maps the old `medium` impact to `high`, applies the new `AT` rule (`AT:N` for every D threat, because the old `AT:P` encoded step count), and uses the class-implied `UI`.
It exists to show the direction and the saturation, not to set a threshold.

| rank | old risk | new score | unit / class |
|---|---|---|---|
| 1 | 12 | 9.9 | `RESTApi:api` / mass assignment |
| 2 | 12 | 9.9 | `ReverseProxy` / BFLA |
| 3 | 4 | 9.5 | `Service:sign-in` / assumed deserialization |
| 4 | 9 | 9.3 | `Service:register` / concurrent duplication |
| 5 | 6 | 9.3 | `Service:jotter-reading` / business logic |
| 6 | 6 | 9.3 | `IdentificationSystem` / session management |
| 7 | 6 | 9.3 | `Service:article-management` / stored XSS |
| 8 | 6 | 9.3 | `AuthenticationMechanism` / session management |
| 9 | 9 | 9.2 | `RESTApi:api` / SQL injection |
| 10 | 9 | 9.2 | `ReverseProxy` / BFLA |
| 11 | 9 | 9.2 | `ReverseProxy` / information disclosure |
| 12 | 6 | 9.2 | `RESTApi:actuator-management` / BFLA |

Fifteen of the 27 threats score at least 9.2 under this reading.
Under the conservative `medium -> low` reading, six score at least 9.2 and the stored XSS falls to 2.3.
The model's impact choice therefore dominates the score. The decision prose must force `VC:H/VI:H` for a stored XSS that executes in another user's session.

The stored XSS moves to rank 7 of 27 and would enter a 12-threat dispatch window.
That is the direct fix for the observed downgrade.
It also depends on the `AT` correction: with the old `AT:P`, the same XSS scores 8.8 and falls to rank 20.

## Considered options

- Keep `likelihood x impact` and only remove confidence: rejected. The likelihood is a free-form summary, the factors do not feed it, and the victim-action and assumed-premise downgrades recur.
- Use CVSS 4.0 only as a report and keep the old risk for dispatch: rejected. Two scores diverge and the operator asked for one.
- Use the CVSS 3.1 exploitability sub-score with CVSS 4.0 values: rejected. `AT` has no v3.1 weight, the `UI` third value has no v3.1 weight, and the result is neither standard.
- Use a detached asynchronous scorer: rejected. It adds a null-score window and a reconciliation gate for a pure calculation.
- Use `high/none` impact: rejected for standard fidelity. The standard has `low`.

## Consequences

- The old `risk` values are not comparable across schema versions.
  The run record drops `risk_weights`, `impact_weights`, and `impact_breakdown`.
  `risk_breakdown` is keyed by the severity band.
- `measure_utm.py` needs a v5 path. The iteration D artifacts stay v4 and are read raw.
- The CVSS 4.0 base score saturates on a corpus that already filters to damage-bearing rows.
  The score is a severity filter, not a fine-grained rank.
  The dispatch cap and the queue are separate policies.
- The stored XSS rises from 6 to 9.3 and enters the top twelve in the reconstructed corpus.
  The result depends on the model choosing `VC:H/VI:H` and `AT:N`, so the tool prose and the prompt must carry those decision nodes.
- The domain-mapped `AC` and `AT` semantics deviate from the standard's wording.
  The persisted vector lets a reader audit the mapping.
  Reports must present the number as a CVSS 4.0 base score over domain-mapped factors, not as a certified CVSS assessment.
- FIRST requires attribution and the vector beside a published score.
  The persisted vector satisfies the second requirement. The tool description and the reports carry the attribution.
