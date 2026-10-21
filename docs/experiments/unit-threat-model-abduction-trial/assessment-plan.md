# T1-TBSG assessment plan (pre-registered)

*Status: pre-registered 2026-10-18, BEFORE the treatment run and BEFORE any comparison data existed. Purpose: fix the criteria, the instruments, the blind protocol, the confounds, and the decision rules in advance, so the assessment cannot be steered by the outcome. Any deviation after the fact must be recorded in the report's appendix with its reason.*

## 1. Experiment summary

- **Unit under test**: `Service:model-download` on the comfyui live target (ComfyUI + Manager V3.37, benchmark patches inserted).
- **Control**: the T1 baseline model, produced 2026-10-15 by the trial-modeller subagent (`docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/threat-model-Service-model-download.yaml`, session `ses_ebe86bcf1ffe7QLa1dwK0yp3zp`).
- **Treatment**: the `t1-tbsg` run, produced by a fresh subagent with the boundary-abduction run book (`input.md`, `typed-surface.md` in this directory) on the redeployed target.
- **Design type**: single-unit retrospective-control comparison (n=1 per arm, non-randomised, no repeated runs). Every result is descriptive; no significance testing is possible or claimed.

## 2. Hypothesis and falsifiers

- **Hypothesis (H1)**: the boundary-abduction discipline improves the quality of the trust boundaries and the trust assumptions (exhaustiveness, sophistication, well-formedness, depth precision) at an acceptable token cost, compared with the inductive baseline, on this unit.
- **Null (H0)**: no material quality difference; any cost increase is not justified.
- **Falsifiers (pre-listed disconfirming outcomes)**:
  1. loss of a ground-truth anchor region (any element of the comfyui-006 chain or the comfyui-005 carrier direction absent from the treatment model);
  2. material loss of baseline-assumption regions (retention < 90%);
  3. fewer sophisticated assumptions or lower depth scores under the blind rubric;
  4. more duplicates/overlaps (beyond one extra pair) or orphan assumptions;
  5. generated-token inflation above 2x with no quality gain.
  Any one of 1, 2, or 4-without-compensating-gain falsifies H1 in favour of H0 or an iterate verdict.

## 3. Criteria and instruments

### 3.1 Exhaustiveness

- **Anchor set (fixed now)**:
  - GT-A: the comfyui-006 chain as reconstructed by the benchmark: `install_model` accepts a `.safetensors` name plus an arbitrary URL; `queue/start` executes the fetch; the outbound fetch reaches an attacker-chosen destination. Covered means: a boundary record with the URL/destination artifact, an assumption on the destination/fetch trust, an SSRF-class vulnerability, and a surviving loop.
  - GT-B: the comfyui-005 carrier direction (arbitrary channel URL written via `channel_url_list?value=`, later consumed by the catalog render). Covered means: at least one boundary/assumption region naming the channel write or the consumed channel content as attacker-influenced. (The baseline dropped this direction erroneously; its absence in the treatment is not itself a regression, but its presence is positive evidence.)
  - Retention set: the baseline model's assumption regions (A1..A15 and any dropped directions recorded in place).
- **Measurement**: mechanical mapping of each anchor and each baseline assumption to treatment assumptions (region-level, not wording-level); counts and percentages. New-only regions are listed and plausibility-judged blind (they have no ground truth and are flagged as such).

### 3.2 Sophistication

- **Tier scale (fixed now, synthetic anchors)**:
  - T0 trivial: generic boilerplate that would apply to almost any web application without system knowledge (for example "input may be malformed", "no rate limiting").
  - T1 standard: system-specific but a common recognised pattern requiring only surface knowledge (for example "state-changing operation reachable without authentication").
  - T2 sophisticated: requires understanding of this system's mechanism; names a specific check-use divergence, guard-invariant mismatch, identity binding, or interpretation differential (for example a non-atomic check-then-commit, a stale-cache read, a status field with two meanings).
- **Measurement**: blind per-assumption tier assignment; metrics: T2 share, mean tier, tier distribution; plus the count of assumptions the assessor marks "cannot judge".

### 3.3 Well-formedness

- **Duplicates**: two assumptions with the same region and near-identical statement (mechanical near-duplicate detection by normalised token overlap, confirmed by the assessor).
- **Overlaps**: pairs whose regions intersect without distinct faults or dimensions (assessor judgement on the blind corpus).
- **Orphans and broken references**: assumptions with no resolvable boundary/fault reference (mechanical); treatment `boundary_ref` resolution rate (mechanical; treatment-only, reported as supplementary).
- **Metrics**: duplicate pairs, overlap pairs, orphans; baseline as the reference point.

### 3.4 Depth precision

- **Per-assumption score 0-3 (fixed now)**, blind: +1 names the specific boundary/interface/transition or mechanism; +1 names the specific attribute, state, or check involved; +1 states the concrete failure mechanism (what goes wrong when).
- **Metrics**: mean, distribution, and the per-item table.

### 3.5 Token tax

- **Primary**: session token totals from the opencode session store for both sessions: input, output, reasoning, cache read, cache write, total, cost. "Generated tokens" = output + reasoning.
- **Secondary**: artefact sizes (model YAML bytes; trace bytes), probe commands used, wallclock.
- **Known caveat**: the baseline ran on `opencode/deepseek-v4.1-flash-free#max`; the treatment runs on `opencode-go/deepseek-v4.1-flash#max` (same model family, different provider tier, after the free tier's rate limits). Flagged as a parity deviation.

## 4. Blind protocol

1. After the run, render both models into a **neutral comparative corpus**: for each model, the boundary statements (interface agreements, trust agreements, transitions normalised to trigger + enforced checks + relied-on requirements) and the assumption statements with their fault names and vulnerabilities. Strip treatment-only field names; keep all semantic content common to both. Two files: `blind/model-a.md`, `blind/model-b.md`; assignment recorded in the report only.
2. Dispatch an independent **assessor subagent** (fresh context) with: the corpus files, this rubric, the GT anchor definitions, and the instruction to read the critical-thinking skill at `/Users/diekgbbtt/.config/opencode/skills/critical-thinking-logical-reasoning/SKILL.md` and apply it. The assessor is told: the two models are anonymous variants of the same unit produced under different processes; do not attempt to identify them; do not read any other file; score every assumption; flag "cannot judge" where the evidence does not suffice; actively look for disconfirming evidence for any quality claim.
3. The assessor returns per-assumption scores and per-criterion summaries before any unblinding.
4. Unblind, then run the mechanical checks (mapping, duplicates, orphans, tokens) that were defined above.
5. Supplementary non-blind structural review: the treatment-only fields (`establishes`/`requires` inventories, `boundary_ref` resolution, dimension assignment) are inspected openly and reported as lower-trust evidence, since they cannot be blinded.

## 5. Confounds and threats to validity (pre-listed)

1. **n=1, single unit, no repetition** - no variance estimate; model-run stochasticity can dominate. Reported as the primary limitation.
2. **Retrospective control** - the baseline ran under its own conditions (2026-10-15 target instance); the treatment runs on a redeployed instance of the same image (id verified unchanged, build 2026-10-02), fresh seed state. Time-of-run drift flagged.
3. **Model parity** - free-tier versus paid-tier endpoint of the same model family (section 3.5).
4. **Experimenter bias** - the same session authored the treatment prompt and this plan. Mitigations: pre-registration, blind assessor, mechanical checks, pre-listed falsifiers. Residual bias acknowledged.
5. **Prompt-length effect** - the treatment run book is longer; any quality gain could come from more instructions or attention, not from the reasoning model specifically. The report states this explicitly.
6. **Target-state effects** - the redeployed target is freshly seeded; the baseline's target had boot-time caches in the same seeded state. Probe budget held equal (60).
7. **Probe-campaign differences** - different probes will be run; a quality difference may reflect probe luck, not reasoning discipline. Mitigated by scoring the model content (not the probe count) and by reading the treatment trace.
8. **Assessment subjectivity** - one assessor; its own biases. Mitigation: the rubric, "cannot judge" flags, and my own adversarial cross-check of every assessor claim quoted in the report.

## 6. Decision rules (pre-registered)

- **ADOPT** (recommend the boundary-abduction model for the production design) if: all GT anchors covered; baseline-region retention >= 90%; (T2 share or mean depth materially better, or equal quality with strictly better well-formedness); duplicates/overlaps no worse than baseline + 1 pair; no orphans; generated-token ratio <= 2.0x.
- **ITERATE** if: mixed quality (gains in some criteria, losses in others) or a fixable well-formedness regression, or token ratio in (2.0x, 3.0x] with quality gains.
- **REJECT** if: any GT anchor lost; or retention < 80%; or duplicates/overlaps roughly double without compensating gains; or token ratio > 3.0x without quality gain.
- **INCONCLUSIVE** if the treatment run fails mechanically (target unreachable for the whole run, provider outage). One rerun is allowed before concluding; a second failure concludes INCONCLUSIVE.

## 7. Report format

The report follows the `measure-experiment-results` template (`/Users/diekgbbtt/.config/opencode/skills/measure-experiment-results/references/TEMPLATE.md`), adapted honestly for a single-unit comparison: no p-values, no confidence intervals, no segment analysis in the statistical sense; instead the control/treatment tables carry the raw values, and the limitations section carries the n=1 caveats. The report is filed at `docs/experiments/unit-threat-model-abduction-eval.md`. The decision (adopt/iterate/reject) and the residual open questions (for the next grilling round) close the report.
