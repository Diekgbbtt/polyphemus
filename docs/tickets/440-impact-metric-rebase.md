# 440 - Impact metric rebase

**What to build:** Replace the class-based green gate with the impact metric. The measurement reads the impact assessment and the CIA vector. A row with all-none CIA values is red. A row with any non-none CIA value is green. A placeholder is red. The class-binding rate stays a diagnostic.

**Blocked by:** 436.

**Status:** done

**Seams:** `eval/measure_utm.py`, `eval/prompts/measure.md`, `docs/experiments/EXPERIMENT-RESULTS-TEMPLATE.md`

## Context

The spec is `docs/design/impact-assessment-system-spec.md` section 9.

The measurement reports:

- `impact_rows`: every impact-assessment row.
- `threats`: rows with `disposition=threat`.
- `placeholders`: rows with `disposition=placeholder`.
- `red`: rows with all CIA values none.
- `green`: rows with any CIA value not none.
- `green_share`: green / impact_rows.
- `threat_share`: threats / impact_rows.
- `placeholder_share`: placeholders / impact_rows.
- The CIA distribution per metric and level.
- The precursor count and the prior-art reuse count.
- The class-binding rate as a diagnostic.

The measurement reads the v3 model. A v2 model remains readable: the `loop-*.yaml` glob is supported, and the CIA vector is read from the legacy `impact` record. The v2 result is reported as a legacy recomputation, not as a v3 result.

The class-based green gate is retired. The report may show the old figure beside the new one, marked superseded.

## Acceptance criteria

- [ ] The measurement reads the v3 `impact_assessment` and the CIA vector.
- [ ] The measurement reports the red/green share, the threat share, the placeholder share, and the CIA distribution.
- [ ] The measurement reads the v2 `loop-*.yaml` and reports the legacy recomputation separately.
- [ ] The class-binding rate remains a diagnostic.
- [ ] The class-based green gate is not a pass/fail gate.
- [ ] The results template carries the new metric.

## Verification

- `tests/eval/test_measure_utm.py`
- A replay of the iteration B `metrics.yaml` with the v2 read.
- A v3 fixture with one threat and one placeholder.
