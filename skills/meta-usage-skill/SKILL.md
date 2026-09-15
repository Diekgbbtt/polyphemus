---
name: meta-usage-skill
description: Judge a loaded skill against its stated observables after execution and record reusable improvements through write_skill.
version: '1'
inputs: []
---
# Judging the skill just run

1. Match seen sights against the observable each step states.
Observable: each gap cites its step plus seen-versus-stated.
2. Keep skill defects a later run would hit again; leave execution misses on sound steps.
Observable: each kept defect names the step the rerun would hit.
3. Record kept defects through `write_skill`, shaped by `meta-write-skill`.
Observable: the envelope reports `ok`, or the code naming its correction.
