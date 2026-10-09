# Assessment workflow node

You reach this node through the `eval_monitor` tool, once a trial's execution
has completed successfully (terminal `complete`, or `stopped` at the hunting
cap) and no `verdicts.yaml` exists yet.
This prompt is the node; the subagent it dispatches has its own role prompt at
`eval/prompts/assessment.md`.

## What happens at this node

The monitor runs the assessor as an **awaited opencode child session** - the
`eval-assessor` role agent, selected by the plugin's native child dispatch -
handing it the trial record, the ground truth, the data root, and the
destination `verdicts.yaml` in the trial directory.
The dispatch is bounded: the child is aborted if it exceeds the wait budget, and
a fatal provider error terminates it non-zero instead of hanging.
The monitor waits for the child's terminal, then verifies the file, so the node
is synchronous.

## What the monitor verifies

Immediately after the child returns, the monitor reads the destination:

- **present and schema-valid** - every row carries the trial record's `eval_sha`
  and `stack_fingerprint`, and every `identified`/`partial` row carries an
  evidence chain whose paths are relative to the data root, begin with the
  `<project_id>/` segment, and resolve on disk - the node is done and the trial
  moves to the diagnosis node in the same tick.
- **absent** - the node is `awaiting`; the monitor re-dispatches within its
  bounded count and budget on a later tick.
- **present but rejected, or absent past the budget** - the node escalates with
  one named failure recorded on the trial record: `empty_file` (no file),
  `schema_invalid` (rejected), or `dispatcher_process` (the child died, whether
  on a launch failure, a timeout, or the provider's own quota).
- **a provider-quota death** - the node backs off for the longer provider window
  instead of hot-looping a new child against the exhausted quota.

## What this node does not do

It does not judge, score, or edit `verdicts.yaml`; the assessment subagent is
the sole writer.
It does not assess a failed run: a trial whose execution is `deferred` never
reaches this node.
It drives the node to a present file or a named escalation, then hands the
trial to the diagnosis node.
