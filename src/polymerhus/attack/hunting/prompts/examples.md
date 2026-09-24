# Hunting-agent worked examples: the off-path shapes

Read this section when the run leaves the straight path - on a coverage
re-entry, an INIT rejection, or total blockage. Example 1 (the confirmed
straight path) is above in the main body; these three cover the branches.
Imitate the REASONING SHAPE, never the domain.

### Example 2 - coverage re-entry, then an exec probe

```
GROUND: same pair, but the surface shows a JS-driven state-changing
flow and the KB has not been consulted yet.
[D1]: sufficient knowledge and coverage - answer YES, proceed directly.
DECOMPOSE/GENERATE: H1-H3 as example 1.
[D2]: NOT exhaustive - the candidates only cover server-side token
mechanics; the JS-driven flow suggests client-side token generation,
a specific fault the class also contains. Coverage fails.
RE-ENTRY: QUERY on (fault-x, web-app axis) -> retrieval adds specific
fault (d) "client-side generated token with server-side blind
acceptance", symptoms {token generated in JS, token submitted from a
second endpoint}, techniques {drive the JS flow, intercept the submit
target}, defence {same-origin checks on the submit endpoint}.
Re-DECOMPOSE: (d) enters the set.
GENERATE: H4: token generated client-side, blindly accepted - Supports:
the JS flow matches the retrieved symptom; Conflicts: none; Test:
intercept the form's real submit target, submit without the token.
[D2] now: fixed-point reached.
DISCRIMINATE/VERIFY-CLAIMS/RANK/COMMIT: ROOT = H4 (the JS flow makes
server-side-only hypotheses weakly supported).
SPEC-WRITE: verification symptom "state-changing request accepted from
the intercepted submit target without the client-generated token".
EVALUATE: pod returns {unsuccessful, technical-infeasibility}: the HTTP
tool cannot drive the JS flow; the trail carries the infeasibility
assertion, not a clean symptom-absent.
[D5]: meaningful insight - yes, a tool-reach gap, not a refutation.
Target-knowledge gaps are resolved inside the loop: exec probes the
client-side flow (the form's real submit target, the token source) and
returns a second endpoint carrying no CSRF token. Re-enter
VERIFY-CLAIMS with the probe evidence; RANK/COMMIT unchanged.
EVALUATE (revised dispatch): symptom confirmed.
[D5]: meaningful insight - yes. Close the candidate and move to the
next (or conclude). No verdict derives here - the harness idles; the
probe result is in the trail for the future verdict-consumption graph.
```

### Example 3 - INIT rejection, re-authoring (the one re-authoring pass)

```
Sub-loop: [G] H2 testable. COMMIT/SPEC-WRITE dispatch the spec.
Pod rejects the spec at INIT validation.
INIT validation evidence: "verification_symptoms references an
unobservable surface (the response body is not in the tool registry's
reach for this target); payload_vector_space contains a method the
target does not expose".
Re-author (one pass): decline exactly the failing attributes - narrow
the verification symptom to the observable status-code surface; drop
the unsupported method from the payload vector space; keep everything
that passed.
Re-dispatch: pod accepts at INIT; runs; returns {successful,
symptom-confirmed}.
No verdict derives here: the harness lands the hunt idle. (If the
re-authored spec is rejected again: land with the validation evidence
and close - the hunt does not re-author a third time.)
```

### Example 4 - worst case, graceful degradation

```
GROUND: a hostile pair; one candidate verifiable, its test technically
unfeasible (all paths WAF-blocked).
D1/D2: coverage reached; DISCRIMINATE..RANK order the candidates.
Sub-loop:
  H1: dispatched; every pod variant lands unfeasible or strongly
  blocked; [D5] no meaningful insight in the returned evidence -> close
  H1 with its trail.
  H2: [G] passes; dispatched; clean symptom-absent -> refuted -> close.
  H3: [G] dropped - the distinguishing evidence against H1 was
  disproven by H1's trail, no testable mechanism remains.
All candidates closed, none successful.
CONCLUDE: hunt lands unsuccessful with the attempted hypotheses'
evidence trail; the feedback carries the blocking assertions and why
each hypothesis was unverifiable - never empty.
```
