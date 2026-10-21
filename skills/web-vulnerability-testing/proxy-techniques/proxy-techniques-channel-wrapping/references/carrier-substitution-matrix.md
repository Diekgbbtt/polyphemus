# Carrier Substitution Matrix

This note holds the carrier family table for the channel-wrapping procedure: the carrier, the guard that watches the primary carrier, and the parity check that shows the sibling escapes it.

## The Carrier Family

| Carrier | What it substitutes | Guard that watches the primary | Parity check |
|---|---|---|---|
| Content type or serialisation | The declared and consumed representation of one body | A check bound to one content type | The same operation accepted under a sibling type |
| Verb | The declared method of one route | A rule scoped to one verb | The same handler answering a sibling verb |
| Protocol version or framing | The version and framing the request is read under | An inspecting layer that parses one version only | The origin parsing a shape the inspector stopped reading |
| Transport or persistent channel | The request-response carrier | A per-request guard and its accounting | The operation travelling while neither the check nor the counter fires |
| Endpoint or alternate route | The route to one operation | A route-scoped rule | A sibling route reaching the operation with no check |
| Session or device | The identity binding of one principal | A binding assumed constant across channels | A captured request re-presented in a second session or device |
| Value location | The position the guard inspects | A check bound to the body or one field | The sink reading a location the guard does not parse |
| Batch envelope | The counted request | A per-request limiter and a shape filter | Inner operations reaching the backend unexamined |

## Parity Procedure

Enumerate every carrier that reaches the effect before crafting, and record the guard each one passes through.
Baseline the primary carrier, so a later pass on a sibling is attributable to the carrier rather than to a class-specific gap.
Send one identical operation per sibling carrier, because a changed operation invalidates the comparison between carriers.
Prefer the carrier whose check is absent rather than weaker, since the effect then needs no second bypass behind it.
A carrier the guard does watch, where the operation passed for a class-specific reason, is not a wrap.

## Capture and Re-presentation

Observe the request at a position where its exact shape is visible, then re-present it byte-identical apart from one changed member.
Change one binding element per attempt: the carrier, the session, or the device.
Treat a capture position inside the tester's own client as a client-side artifact rather than a channel.
A signed message replayed inside its validity window or in a second session proves the signature is bound neither to the principal nor to the freshness window.

## Accounting Reset

A carrier that resets the accounting is a counted-dimension gap as well as a carrier substitution, because the limit watches the primary carrier's requests.
Name the throttle-evasion mechanism at that step, and name the attempt-batching mechanism where the carrier is an envelope the limiter counts once.
