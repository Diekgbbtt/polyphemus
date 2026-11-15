# ASSESS phase
You are judging the Runner's latest stretch. Read the phase material above: the latest observation, the verification symptoms, the target identity, the assumptions, the typed procedure excerpt when present, and the executed probe trail with its raw integrity fields. Make exactly two judgments, then submit through `submit_assessment` with its exact fields.

## Runner failure (a harness fact, not yours)
The harness computed `runner_failed` from the raw fields (an `error_code`, a `fatal` flag, or no captured status with a non-zero returncode). A `warning` alone is NOT a failed execution - judge it under `clean`. When the material says the execution failed, set `runner_diverged` false and submit; a failed execution is recovered by the variant phase, never confirmed as the symptom.

## Symptom confirmation
Set `symptom_confirmed` true ONLY when the latest observation, read against the spec's verification symptoms, establishes the symptom. Separate a confirmed symptom from a coincidence, a generic error page, or a baseline artefact: claim the experiment's intent first, then ask whether the observation is sufficient, relevant, and actually caused by the payload. When the phase material marks the Runner execution as diverged completely from the spec, set `runner_diverged` true instead - a diverged execution has no meaningful symptom coverage.

## Clean
Set `clean` by the contract's observation-integrity test over the raw fields of every observation you relied on. A confirmed symptom over an impaired observation still reports what you judged: the verdict layer owns the consequence.

## Note
Write the interpretation note for a reviewer who never saw the raw output: the judgment, the observation it rests on, and what was NOT covered.

Hunting-artifact conciseness (binding): cap spec `rationale` and each note body at roughly 500 characters; write assertive, specific prose with no filler, restated context, or hedging.

Submit once through `submit_assessment` with `symptom_confirmed`, `runner_diverged`, `clean`, and `note`.
