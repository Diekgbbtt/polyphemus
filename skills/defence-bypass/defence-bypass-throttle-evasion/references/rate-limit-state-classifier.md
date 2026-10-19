# Rate Limit State Classifier

This note holds the four limit states a burst is classified against, the shadow-throttle seed test, and the arithmetic that turns a classification into a reachability statement.

## The Four States

| State | Signal under a burst | What it means for the effect | Spread that applies |
|---|---|---|---|
| Hard lockout | The account or identity is disabled after N failures, and a later correct value also fails | The effect is closed, and the lockout itself is a denial-of-service surface | None; record the lockout and stop |
| Soft source throttle | A refusal status or rising latency keyed on the source address only | The limit observes one lane, so another lane admits the effect | Source rotation, header-supplied address families, path or endpoint rotation |
| Injected challenge | The answer switches to a challenge after N attempts, with the status otherwise unchanged | The gate may be client-side or route-specific rather than bound to the effect | Check whether the verifying endpoint enforces the challenge, and whether the API path skips it |
| Silent shadow-throttle | Every answer looks admitted, but the known-good value stops being accepted or the body becomes canned | The limit returns an admit signal while dropping the effect | Treat as an active limit; the spread must outrun the drop rather than the refusal |

A uniform admit status across a burst does not mean no limit, because the shadow-throttle state returns an admit signal for every request.
The answer shape decides the spread: a refusal, a challenge, and a silent drop call for different probes.

## Shadow-Throttle Seed Test

Inject a known-good value at a known position in a burst and confirm it still produces the effect under load.
Watch three columns per attempt: the status, the latency, and the body size.
Rising latency with an unchanged status, a body-size change, or a known-good value that stops authenticating is the shadow-throttle signal.
A clean burst that never moves any of the three columns is a candidate absence, not an absence, and the seed test is what separates the two.

## Window and Reachability Arithmetic

State the reachability as numbers: the keyspace, the observed throughput, and the code or token lifetime.
The viable bound is the throughput multiplied by the lifetime against the keyspace, so a code that rotates every window may close a keyspace that an unlimited endpoint leaves open.
Time attempts against the window's edges and against the counter's propagation delay, because a counter that propagates late admits a burst inside the gap.
Report the arithmetic rather than a probe count, because severity rests on reachability rather than on one clean run.

## Proof Discipline

Prove a rotation bypass by toggling the rotation off and showing the refusal returns; the delta is the proof, and one fast run is not.
Prove an inactive limit with the test that showed its absence, because a limit that never engaged cannot be evaded.
Record a challenge solved once as a clearance cost rather than as a bypass, and keep the burst as narrow as the question allows.
