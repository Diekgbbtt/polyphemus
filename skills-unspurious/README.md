# skills-unspurious - the W0-W7 stream records

The well-formed web-vulnerability-testing suite that this stream produced now lives at the live catalogue root `skills/` (the mount replacement).
Its 41 group directories (38 classes plus the R7 cross-cutting group `two-principal-authz`, never counted among the classes, and the `defence-bypass` and `proxy-techniques` families; 165 skills) sit there beside the product skills, and the loader serves them through the live-root `SkillCatalogue`.

This directory keeps the stream records only:

- `_analysis/` - the per-class variant-decomposition analyses (the argued decomposition) and their reviews, plus `SPEC.md` and `LEDGER.md`.
- `_authoring/` - the authoring contract (`SPEC.md`), the `WRITER.md` and `REVIEWER.md` personas, the phase-4 `LEDGER.md`, the reviews, and `LAYOUT-FIX-SPEC.md` (the reference layout restored by #388).
- `_completion/verify.sh` - the suite-scoped machine checks; they target the suite's 41 group directories under `skills/` and never scan the non-suite live-root skills.
- `_migration/` - the extracted high-value-target and bypass/proxy material, and the per-batch de-spuriation reports.
- `INVENTORY.md` - the KEEP / DISCARD / BORDERLINE classification with a rationale per source directory.
- `DECOMPOSITION-REPORT.md` - the decomposition record: the variant analyses, the authoring batches, and their reviews.
- `SCREAMING-REPORT.md` - the de-spuriation record: what was removed, adapted, extracted, and the arsenal gaps.

Start with the live-root README (`skills/README.md`) for the suite's layout, taxonomy, loader contract, and checks.
The authorities stay `docs/design/skills-variant-boundary.md`, `docs/design/skills-ontology.md`, and `docs/design/skills-taxonomy.md`.
