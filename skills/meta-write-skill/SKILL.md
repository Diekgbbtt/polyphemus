---
name: meta-write-skill
description: Extend or correct a project skill from run experience through write_skill when a run exposed missing target detail or contradicted content.
version: '1'
inputs: []
---
# Extending a project skill from run experience

Extend the already-existing skill the run just exercised: add the specific target detail it lacked, prune the content the run contradicted.
Work the steps in order; each ends with its checkable observable.
Whether a run warrants a revision is assessed in meta-usage-skill; this skill carries the revision procedure alone.

1. Name the divergence: match the run's seen sights against the observable each step states; keep the gap a later run would hit again.
Observable: each kept gap cites its step plus seen-versus-stated.
2. Extend the procedure with the missing specific detail; prune each contradicted line and write what the run showed.
Observable: every step pairs its action with a checkable sight.
3. Hold bulky target detail (endpoint snapshots, header dumps, role matrices) in `references/<name>`; carry a context pointer naming the file in SKILL.md.
Observable: SKILL.md reads as procedure alone; each bulky claim resolves through its pointer.
4. Rewrite through `write_skill`: `procedure` rewrites the whole SKILL.md, `references/<name>` writes one reference file for one safe file stem; one whole file per call, written atomically.
Frontmatter carries `name` matching the bundle directory plus non-empty `description` and `version`; the revision block carries `base_version`, the new `revision`, run provenance, and the `source_note_ids` the revision draws on.
Observable: the envelope reports `ok` for the intended skill and target; `skill_invalid` names the frontmatter correction, `skill_target` the target correction, `store_unavailable` the retry.
