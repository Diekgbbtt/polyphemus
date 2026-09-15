---
name: meta-usage-skill
description: Judge a loaded skill against its stated observables after execution and record reusable improvements through write_skill.
version: '1'
inputs: []
---
# Judging a loaded skill

Judge the skill just executed against the observable each step states.

1. Compare the run's seen sights against each stated observable.
Observable: each gap cites its step plus seen-versus-stated.
2. Label each gap a skill defect or an execution miss on a sound step; keep the defects for step 3.
Observable: each kept defect names the step a later run would hit again.
3. Record reusable defects through `write_skill`, shaped by `meta-write-skill`.
Observable: the envelope reports `ok`, or the code naming its correction.
