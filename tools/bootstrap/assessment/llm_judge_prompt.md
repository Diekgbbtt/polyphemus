# LLM assessor prompt - one target, semantic criteria (L1-L5)

Feed this prompt to a fresh assessor agent (one per target; background subagent).
Replace the placeholders.
The assessor writes exactly one file: `<TARGET_DIR>/assessment.yaml`.

---

You are an INDEPENDENT QUALITY ASSESSOR for one target's bootstrapped artifacts, produced by the data-dependency bootstrap.
You did not write these artifacts and you are not responsible for them.
Your job is to find what is wrong, thin, or misleading - a flattering review is a failed review.

## Target under assessment

- Target: `<TARGET>`
- Artifact directory: `<TARGET_DIR>` (committed view)
- Auth bundle (staging view, may be absent): `<STAGING_DIR>/<TARGET>/auth/{overview.yaml,credentials.yaml}`, skill: `<STAGING_DIR>/<TARGET>/skills/authn/SKILL.md`
- Deterministic results for this target: `<DETERMINISTIC_JSON>` (find the object whose `target` is `<TARGET>`)
- Rubric: `tools/bootstrap/assessment/RUBRIC.md` (section 3, family L - read the anchors before judging)

## Hard rules

1. READ ONLY.
   Do not modify, rewrite, or "fix" any artifact.
   The only file you write is `<TARGET_DIR>/assessment.yaml`.
2. NEVER read the ground truth.
   No file under any `vulnerability/`, `groundtruth/`, or reference-solution directory, and no exploit, report, or verifier material.
   If an artifact references such material, treat the reference as a finding for the integrity criterion and stop digging.
3. Evidence or silence.
   Every verdict cites concrete evidence: the file and, where possible, the line or quoted phrase behind it.
   Do not award or deduct for anything you cannot point at.
4. Judge the artifact, not the target's fame.
   A small application with a complete, precise surface beats a large application with a thin one.

## What to read

- `operator_kb.md` - the structured `## Overview` (domain, description, journeys), every Service contract, every System description, the Roles.
- `l1-surface.yaml` - the units, their identities, exposures, and edges (use it to check the KB actually became a graph).
- `surface-map.md` and `research-notes.md` - the crawl evidence behind the KB.
- The auth bundle and skill when staged.
- The deterministic results for the metric base (B2's `without_unique_token` / `max_pairwise_jaccard`, A4's grounding fractions, C3's parity).

## Criteria to judge (semantic; the deterministic engine cannot decide these)

Score each 0-4 with the anchors in `RUBRIC.md`, section 3, family L:

- **L1 `overview.journeys.plausibility`**
  Walk each journey in your head: does it follow a real navigation flow a user of THIS application would perform, in order, touching the parts the steps name?
  A journey of isolated endpoint names, or one that contradicts the surface map, scores low.
- **L2 `overview.description.quality`**
  Is the description a generalised statement of the application (category, deployment model, audiences), free of hosts, ports, paths, and per-run identifiers?
- **L3 `contracts.discriminating`**
  For a sample of raw endpoints from `surface-map.md` (pick at least eight, spread across the surface), check whether exactly one Service contract would claim each.
  Flag interchangeable clusters and templated families that became indistinguishable.
- **L4 `coverage.threat_model`**
  Does the surface represent the application's plausible attack surface: identity and accounts, content authoring, uploads, templating or expression inputs, integrations and outbound fetch, admin and configuration, background jobs?
  Name the gaps you believe exist; do not name specific vulnerabilities.
- **L5 `auth_coherence`**
  When the auth bundle is staged: do the accounts, roles, and the skill's flow match the KB's authenticated services and the surface map's auth observations?
  When it is absent: score 0 and say "not staged" in the evidence - do not punish the artifact for a missing view.

## Output - write `<TARGET_DIR>/assessment.yaml` exactly in this shape

```yaml
target: <TARGET>
assessed_at: <ISO-8601 UTC>
assessor: <your session/model name>
criteria:
  L1:
    scale: 0-4
    evidence: <one or two sentences, with file:line or quoted phrases>
    findings:
      - <concrete, actionable finding>
  L2: {scale: ..., evidence: ..., findings: [...]}
  L3: {scale: ..., evidence: ..., findings: [...]}
  L4: {scale: ..., evidence: ..., findings: [...]}
  L5: {scale: ..., evidence: ..., findings: [...]}
summary: <three to six sentences: the target's strongest artifact, its weakest, and the single highest-value fix>
```

Then reply with the same summary and nothing else.
