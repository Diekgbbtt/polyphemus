---
name: meta-usage-skill
description: Judge a loaded skill against its stated observables after execution and record reusable improvements through write_skill.
version: '1'
inputs: []
---
# Judging the skill just run

1. Match seen sights against the observable each step states; a step stating none is itself the gap, citing that step.
Observable: each gap cites its step plus seen-versus-stated.
2. Keep skill defects a later run would hit again; leave execution misses on sound steps.
Observable: each kept defect names the step the rerun would hit plus the sight or rerun condition proving it.
3. Record kept defects through `write_skill`, shaped by `meta-write-skill`.
Observable: the envelope reports `ok`, or the code naming its correction.
Judge once per run; a successful write closes the run, the revised text waits for the next.
