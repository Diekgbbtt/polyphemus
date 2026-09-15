---
name: meta-write-skill
description: Extend or correct a project skill from run experience through write_skill when a run exposed missing target detail or contradicted content.
metadata:
  version: '1'
---
# Extending a project skill from run experience

Extend the already-existing skill the run just exercised: add the specific target detail it lacked, prune the content the run contradicted.
Work the steps in order; each ends with its checkable observable.
Whether a run warrants a revision is assessed in meta-usage-skill; this skill carries the revision procedure alone.

1. Take the kept defects meta-usage-skill recorded: confirm citation shape only (step plus seen-versus-stated present); return a gap failing the shape to the judge unrevised - the judge's verdict stands.
Observable: each confirmed gap cites its step plus seen-versus-stated; with zero kept defects skip write_skill entirely.
2. Extend the procedure with the missing specific detail; prune each line the run objectively contradicts, never for mere non-experience, and write what the run showed, holding additions to the rerun-relevant.
Observable: every procedural step pairs its action with a sight naming the step, the seen value, and the stated value; reference-shaped content resolves through its pointer instead.
3. Hold bulky target detail (endpoint snapshots, header dumps, role matrices) in `references/<name>`; carry a context pointer naming the file in SKILL.md.
Observable: SKILL.md reads as procedure alone; each bulky claim resolves through its pointer.
4. Rewrite through `write_skill`: `procedure` rewrites the whole SKILL.md content, `references/<name>` writes one reference file for one safe file stem; one whole file per call, written atomically.
Frontmatter carries `name` matching the bundle directory, non-empty `description`, and `metadata.version`; the revision touches content only - version and identity stay symbolic.
Observable: the envelope reports per the `write_skill` contract.
