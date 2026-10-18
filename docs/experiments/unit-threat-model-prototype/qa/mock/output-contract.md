# Output contract - TestImplementationSpecs set (mock v1, 2026-10-17)

One YAML file per loop.
The set is the loop's coverage of the slice it opened.

## Schema

```yaml
loop_id: <string>                     # copied from the payload
unit_id: <string>                     # copied from the payload
class: <string|null>                  # web-vulnerability class (null when class-less)
class_skill: <string|null>            # skill directory loaded (null when absent)
slice:
  source: trust_agreement | dynamic_state_trust
  statement: <string>                 # the slice of the failure-modes space this loop opens (<=500 chars)
discrimination:
  axes_used: [chaining-advanced | tech-misconfiguration | payload-vector, ...]
  boundary: <string>                  # the subset of variables the set discriminates on
  narrow_broad_tradeoff: <string>     # which way you chose and why
specs:                                # one entry per sub-slice; >=1
  - spec_id: <string>                 # <loop_id>-s<N>
    label: <string>                   # short human name
    sub_slice: <string>               # the distinct region this spec owns (<=500 chars)
    class_skill_parametrisation:
      skill: <string|null>
      inputs: <open dict>             # which target facts parametrise the skill
    concretisation: <open dict>       # target-bound: protocol, technology, endpoint, parameter, method, body, headers
    discrimination_axis: chaining-advanced | tech-misconfiguration | payload-vector
    discrimination_note: <string>     # what separates this spec from its nearest sibling (<=500 chars)
    chaining_advanced_note: <string|null>  # required when the axis is chaining-advanced; structural reasoning when the skill lacks entities
    proxy_technique: <string>         # how the failing execution mode is reached (<=500 chars)
    verification_symptoms: [<string>, ...]
    payload_vector_space: <open dict> # method, path, parameter, body, headers as applicable
    assumptions: [<string>, ...]
    rationale: <string>               # why this sub-slice materialises if the fault is implemented (<=500 chars)
    interpretation_guidance: <string> # what present and absent mean; falsifiability (<=700 chars)
checks:
  overlap:
    status: none | present
    notes: <string>                   # overlapping spec pairs and the shared region, or none
  coverage:
    status: exhaustive | partial
    uncovered: [<string>, ...]        # uncovered slice regions (empty when exhaustive)
    notes: <string>
  well_formedness_statement: <string> # one paragraph: no-overlap + exhaustive coverage claim with its basis
degradations: [<string>, ...]         # fail-open notes: missing skill, thin payload, ungrounded assumption (empty when none)
```

## Worked example (fragment, illustrative only - do not copy its domain)

```yaml
loop_id: loop-N
unit_id: Service:example
class: csrf
class_skill: csrf
slice:
  source: trust_agreement
  statement: "The boundary treats a state-changing GET as safe; any crossing participant can mutate queue state without an anti-CSRF expectation."
discrimination:
  axes_used: [payload-vector, tech-misconfiguration]
  boundary: "delivery proxy x endpoint inventory; the vector varies, the failure mode does not"
  narrow_broad_tradeoff: "wide on endpoints (inventory completeness), narrow on delivery (two proven proxies)"
specs:
  - spec_id: loop-N-s1
    label: "cross-site GET via image loader"
    sub_slice: "state-changing GETs reachable from an <img> loader on a foreign origin"
    class_skill_parametrisation:
      skill: csrf
      inputs: {state_changing_get: true, token_expected: false}
    concretisation:
      protocol: http
      endpoint: /queue/clear
      method: GET
    discrimination_axis: payload-vector
    discrimination_note: "separated from loop-N-s2 by the delivery proxy only; both exercise the same missing-token failure"
    chaining_advanced_note: null
    proxy_technique: "foreign-origin page embeds the URL as an image source; the browser issues the GET with ambient credentials"
    verification_symptoms: ["queue state mutated without a same-origin interaction"]
    payload_vector_space: {method: GET, path: /queue/clear, parameter: null, body: null, headers: null}
    assumptions: ["an authenticated session exists in the victim browser"]
    rationale: "no anti-CSRF expectation crosses the boundary; the GET mutates state, so any embedding context completes the attack"
    interpretation_guidance: "symptom-present = queue emptied and the response carries no rejection; symptom-absent = 403/redirect with state unchanged; a WAF-looking block is inconclusive, not absent"
checks:
  overlap:
    status: none
    notes: "s1 and s2 differ on the delivery proxy; sub-slices disjoint"
  coverage:
    status: partial
    uncovered: ["state-changing POSTs on the same boundary - out of this loop's GET-shaped slice"]
    notes: "all GET-shaped mutation endpoints covered"
  well_formedness_statement: "Two specs, disjoint sub-slices, delivery proxy x endpoint inventory; the slice is GET-shaped mutations, covered exhaustively."
degradations: []
```
