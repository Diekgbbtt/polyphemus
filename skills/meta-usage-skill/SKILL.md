---
name: meta-usage-skill
description: Judge a loaded skill against its stated observables after execution and record reusable improvements through write_skill.
version: '1'
inputs: []
---
# Judging the skill just run

1. Match seen sights against the observable each step states; a step stating none is itself the gap, citing that step.
Observable: each gap cites its step plus seen-versus-stated.
2. Keep defects seen twice or once with their trigger named from the run; leave execution misses and single samples without a trigger unrecorded.
Observable: each kept defect names its step plus recurrence or trigger.
3. Record kept defects through `write_skill`, shaped by `meta-write-skill`.
Observable: the envelope reports `ok`, or the code naming its correction.
Judge once per run; a successful write closes the run, the revised text waits for the next; a failed envelope means correct the write and retry under the same judgement.
