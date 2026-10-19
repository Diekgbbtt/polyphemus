# Batching Carriers

This note holds the carrier catalogue for the attempt-batching procedure: what each carrier is, what the limiter counts, what the backend iterates, and the check that shows the envelope was expanded.

## Carrier Catalogue

| Carrier | Shape | What the limiter counts | What the backend iterates | Acceptance check |
|---|---|---|---|---|
| Array body | One member whose value is a list | The request, once | Each element of the list in sequence | A per-item verdict or a response whose shape grows with the item count |
| Alias set | One operation envelope repeating one field under distinct names | The request, once | Every aliased repetition of the operation | A response carrying one verdict per alias |
| Batch envelope | Inner operations inside a structured envelope | The envelope, once | Each inner operation the envelope carries | Inner operations executed while the outer shape was the only one parsed |
| Fat request | A body carried on a verb the limiter treats as one read | The request, once | The parameters the backend still consumes | The verb's handler acting on the carried parameters |
| Nested or duplicate shape | A member the key counts once while the backend expands it | The envelope, once | Every nested item the backend unfolds | A per-item effect beside a single counted request |

## Counting-Unit Arithmetic

The amplification is the item count per counted request, so state it as a number beside the single-operation threshold.
Prefer the carrier with the highest accepted item count, because the amplification is the item count itself.
A carrier the backend expands into expensive per-item work is an amplification surface, not merely a brute enabler, so record the per-item cost beside the count.

## Guard Parity

Compare what each layer counts and what each layer parses: a carrier can pass a rate limiter and a request-shape filter at once when both inspect the outer shape only.
The inspecting layer's own verdict never covering an inner operation is the guard-parity signal, and it localises which layer the carrier escaped.
Name the class that owns the envelope where the carrier is that class's own construct, rather than restating its parsing here.

## Proof Discipline

Keep every item distinguishable, so each per-item verdict is attributable to its own input.
Pair the admitted envelope with the same effect sent as separate requests and refused, because an unrefused baseline proves nothing about the counting unit.
Read the response per item rather than as one verdict, because an envelope that answers once with no per-item verdict proves nothing about iteration.
A backend that rejects or ignores a multi-item payload across every carrier is a recorded negative, and the search moves to the next carrier.
