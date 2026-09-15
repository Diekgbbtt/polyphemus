---
name: meta-usage-skill
description: Assess a loaded skill after execution - judge its contribution against its stated observables, and record reusable improvements through write_skill.
version: '1'
inputs: []
---

# Assessing a loaded skill

Treat every loaded skill as a procedure under assessment during and after execution.
Work the steps in order; each ends with the observable showing it worked.

1. Judge contribution: decide whether the skill materially shaped the outcome.
   Observable: a one-line verdict, contributed or peripheral.
2. Name divergence: compare what happened against the observable each step states; separate a defect in the skill from an execution miss on a sound step.
   Observable: each gap cites its step plus seen-versus-stated.
3. Record reusable improvements directly through `write_skill`, following `meta-write-skill` for shape, frontmatter, revision block, and pointers.
   Observable: the tool envelope reports `ok`, or a code naming its correction.
