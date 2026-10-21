# Deserialization Safe-Oracle Workflow

This note details the oracle classes and the proof discipline behind the safe-oracle step of the parent body.
The workflow holds one rule above every technique: no effect-bearing payload is sent before an oracle has confirmed that attacker bytes reach the decoder.

## Oracle classes

- **Name-resolution-only**: the decode triggers an outbound name lookup and nothing else, so the receipt proves rehydration with no code execution and no response reading.
- **Callback**: the decode triggers an outbound fetch to attacker-operated infrastructure carrying a unique per-probe marker.
- **Delay**: the decode invokes a bounded delay primitive, so the signal is an elapsed-time margin against a benign baseline measured across repeated trials.
- **Local differential**: the decode changes an observable response class, such as a resolution error against a parse error, with no outbound channel needed.

## Selection order

1. Prefer the name-resolution-only class where any egress is possible, because it is the cheapest liveness proof.
2. Fall back to the callback class where a listener can be operated and the target can fetch.
3. Fall back to the delay class where egress is filtered and timing is stable enough for a margin.
4. Use the local differential only to orient, because an error-class change alone proves malformed bytes rather than live resolution.

## The gate discipline

- Gate every effect-bearing payload behind the oracle, and treat an oracle signal as the permission to continue rather than as the finding.
- With no oracle signal, stop and re-fingerprint the family instead of escalating; an escalation without liveness burns the sink and produces unattributable noise.
- Send the oracle through the same locus and the same encoding chain the effect payload would use, so the proof transfers.
- Keep one oracle attempt per locus and per encoding, so a negative narrows the sink rather than leaving it ambiguous.

## Attribution

- Embed a unique marker per probe, per locus, and per attempt, so a receipt binds to exactly one submission.
- Correlate plant, trigger, and receipt by time and by marker when the decode happens in a later job.
- Repeat each positive before claiming it; a receipt that also fires for a benign submission marks shared egress rather than the decode.

## Bounded-effect proof

- After liveness, choose the least destructive effect that still demonstrates control: a reversible read or a benign computation over a full command.
- Record the bound beside the payload, so a later reviewer sees why the proof stopped where it did.
- Stop at the first confirmation; a second effect adds risk without adding evidence.
- Hand the confirmed execution to the consuming class rather than escalating inside this class.

## False positives

- A callback fired by a plain parse, a proxy probe, or a scanner rather than by the decoder.
- Shared egress infrastructure that fires for unrelated traffic.
- A timing shift caused by load rather than by the invoked delay.
- An error-class change on a request that never reached the decoder.
- A single unreproduced receipt, which is chatter until a second run repeats it.
