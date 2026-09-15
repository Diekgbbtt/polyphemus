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

1. Take the kept defects meta-usage-skill recorded: confirm citation shape only (step plus seen-versus-stated present); return a gap failing the shape to the judge unrevised - the judge's verdict stands.
Observable: each confirmed gap cites its step plus seen-versus-stated; with zero kept defects skip write_skill entirely.
2. Extend the procedure with the missing specific detail; prune each contradicted or stale line and write what the run showed, holding additions to the rerun-relevant.
Observable: every procedural step pairs its action with a sight naming the step, the seen value, and the stated value; reference-shaped content resolves through its pointer instead.
3. Hold bulky target detail (endpoint snapshots, header dumps, role matrices) in `references/<name>`; carry a context pointer naming the file in SKILL.md.
Observable: SKILL.md reads as procedure alone; each bulky claim resolves through its pointer.
4. Rewrite through `write_skill`: `procedure` rewrites the whole SKILL.md, `references/<name>` writes one reference file for one safe file stem; one whole file per call, written atomically.
Frontmatter carries `name` matching the bundle directory plus non-empty `description` and `version` plus an `inputs` list; the revision block carries `base_version` with the new `revision`, run provenance, and the `source_note_ids` the revision draws on, with empty `source_note_ids` legal and `base_version`/`revision` reader convention; the store checks only frontmatter `name`/`description`/`version`/`inputs`.
Observable: the envelope reports `ok` for the intended skill and target; `skill_invalid` names the frontmatter correction, `skill_target` the target correction, `store_unavailable` the retry.
