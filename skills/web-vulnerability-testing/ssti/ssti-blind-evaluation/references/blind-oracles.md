# Blind Oracle Signal Shapes

This note details the oracle signals summarised in the blind variant body.
Each shape stays abstract because concrete payload spellings are runtime knowledge-base facts.

## Timing oracle

The timing shape pairs a benign baseline submission with an evaluation-triggering submission that invokes a delay primitive.
The signal is the elapsed-time margin between the two renders measured across repeated trials.
The completion bar is a stable margin that benign jitter never reaches.

## Out-of-band oracle

The callback shape pairs a triggering submission with a unique per-probe marker embedded in an outbound request.
The signal is the arrival of that marker at attacker-operated infrastructure.
The completion bar is marker uniqueness so unrelated egress cannot corroborate the probe.

## Length-differential oracle

The length shape pairs a benign stored value with an evaluation-triggering stored value of similar input size.
The signal is a shift in body length or validator output on a rendering surface without visible computed content.
The completion bar is reproducibility across re-renders with coincidence excluded.
