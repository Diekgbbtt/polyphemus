---
name: meta-write-skill
description: Write project skill bundles through write_skill - authoring rules for recording a reusable procedure, and for offloading bulky target material into references.
version: '1'
inputs: []
---

# Writing a project skill

A project skill bundle is the project-owned procedure directory `data/<project_id>/skills/<skill>/`: `SKILL.md` holds the procedure, `references/` holds bulky target material, `scripts/` and `assets/` hold runnable and static support.
Every change reaches the bundle through `write_skill`, one whole file per call, written atomically; the bundle appears on first write.
Follow the steps in order; each ends with the observable showing it worked.

## 1. Shape the procedure as ordered steps ending in observables

Write what the executor does, in order.
Close every step with its expected observable: the concrete sight (output line, file, envelope field) showing the step worked, so an executor comparing stated against seen recognizes divergence.
Observable: every step pairs its action with a checkable sight.

## 2. Open SKILL.md with frontmatter and a revision block

Frontmatter carries `name` matching the bundle directory, a non-empty `description` of what the skill is plus when it fires, and `version`.
The revision block carries `base_version`, the new `revision`, run provenance, and the `source_note_ids` of the notes the revision draws on, recorded as provenance for later debugging.
Observable: a frontmatter check confirms name, description, and version; the revision block cites its base and its sources.

## 3. Hold bulky material in references behind a pointer

Record endpoint snapshots, header dumps, role matrices, and similar bulky target material in `references/<name>`; keep the procedure compact and carry a context pointer naming the reference file.
Observable: SKILL.md reads as procedure alone; each bulky claim resolves through a pointer.

## 4. Write through the write_skill targets

Call `write_skill` with `procedure` to rewrite the whole SKILL.md, or with `references/<name>` to write one reference file.
Address the skills bound to you; the tool answers any other skill with a `skill_read_only` envelope. The shared `skills/` catalogue is read ground for a live run; project bundles are write ground.
Keep credentials in the auth store; skill bodies carry procedure alone. Shape content within the size caps and valid frontmatter; every outcome arrives as an in-band coded envelope (`ok` with skill and target, or `skill_invalid`, `secret_refused`, `size_exceeded`, `skill_target`, `store_unavailable`), and each code names its correction.
Observable: the envelope reports `ok` for the intended skill and target.
