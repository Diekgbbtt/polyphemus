# Diagnosis workflow node

You reach this node through the `eval_monitor` tool, once a trial is `assessed`
and at least one verdict is `missed` or `partial` and no `diagnoses.yaml`
exists yet.
This prompt is the node; the subagent it dispatches has its own role prompt at
`eval/prompts/diagnoser.md`.

## What happens at this node

The monitor computes the required vulns - the ids of every `missed` and
`partial` verdict - and dispatches the diagnoser subagent once, handing it the
role prompt, the trial record, the verdicts, the ground truth, the data root,
the destination `diagnoses.yaml`, and the comma-separated vuln ids the dispatch
must cover.
The dispatch is fire-and-forget: the monitor does not block waiting for the
subagent.

A trial whose every verdict is `identified` requires no diagnosis and never
reaches this node: it is `complete` straight from the assessment node.

## What the tick verifies

On each later tick the monitor reads the destination:

- **present, schema-valid, and paired** - one entry per `missed`/`partial`
  verdict, each carrying the trial record's `eval_sha` and `stack_fingerprint`,
  and exactly one of `closest_issue` or `proposed_issue` - the node is done and
  the trial is `complete`.
- **absent** - the node is `awaiting`; the monitor re-dispatches within its
  bounded count and budget.
- **present but rejected, unpaired, or absent past the budget** - the node
  escalates with one named failure recorded on the trial record: `empty_file`
  (no file), `schema_invalid` (rejected), `unpaired` (a `missed`/`partial`
  verdict with no entry), or `dispatcher_process` (the launch raised).

## What this node does not do

It does not root-cause or edit `diagnoses.yaml`; the diagnoser subagent is the
sole writer.
It never files an issue; the subagent may only record a `proposed_issue` in the
file.
It drives the node to a present, paired file or a named escalation, then the
trial is `complete`.
