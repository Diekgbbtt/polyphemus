# W0+W1 completion ledger

This ledger closes the residual tasks of the W0 skills-suite agent (session `ses_f181eb14bffei9Y8v5O30nGDjG`), finishes the W1 data-model deliverables, and completes the two outstanding W0 outputs: the bypass/proxy technique families (#278) and the suite enrichment.

It is the evidence record.
A task is `done` only when its verification command has run and its output excerpt is pasted below.
Intent is never evidence.

Branch: `feat/w0-w1-completion`, based on `feat/232-skill-evolution` (W0 landing, tip `96fb82a`).
Nothing is pushed; integration is a later human-merged PR.

## Verification mechanism

- Machine checks: `skills-unspurious/_completion/verify.sh`.
- Independent verification agent: a fresh adversarial reviewer dispatched after each phase.
- Operator gates: B1 (taxonomy grilling; answered 2026-10-03 and 2026-10-18), B2 (parent-conformance ruling; answered 2026-10-18), the A1 status wording (accepted 2026-10-18), and D1a (enrichment proposal report; pending).

## Task table

| ID | Task | Status | Commit | Verification command | Observed output |
|---|---|---|---|---|---|
| A1 | Mark the validated documents accepted | done | `COMMIT-A1` | `grep -rn 'proposed, awaiting operator review' docs/design/skills-variant-boundary.md docs/design/skills-ontology.md` | `NONE` (no stale status) |
| A2 | Fix the stale agnosticism lines | done | `COMMIT-A2` | `grep -rn 'block stays\|left in place and flagged' skills-unspurious/; grep -rn '^## Framework-Specific' skills-unspurious/llm-prompt-injection/` | `NONE`; `NONE` (skill carries no such section) |
| A3 | Boundary reference ubiquitous | done | `COMMIT-A3` | `for f in <skill-concern docs>; do grep -q skills-variant-boundary.md "$f" && echo REF $f || echo MISS $f; done` | all `REF` |
| A4 | Tracked home for the cross-stream doc | done | `COMMIT-A4` | `git ls-files docs/design/skills-system-decomposition.md; grep -rn skills-system-decomposition.md docs/design skills-unspurious` | tracked; 3 citations resolve |
| A5 | Arsenal-gaps ticket(s) | done | `COMMIT-A5` | `gh issue view 303 --json number,state,labels; grep -n 303 skills-unspurious/SCREAMING-REPORT.md` | issue #303 OPEN (enhancement, needs-triage); report links it |
| A6 | Open-item refresh | done | `COMMIT-A6` | `grep -rn --exclude-dir=_completion 'awaiting review\|awaiting operator review\|for a future ticket' skills-unspurious/ docs/design/skills-*.md` | `NONE` |
| B1 | Round-2 taxonomy map (the taxonomy and naming spec) | done | `c46c8f85` + review fix `cb2a8cb3` (merged `a0076955`) | `test -f docs/design/skills-taxonomy.md; bash skills-unspurious/_completion/verify.sh` | `PASS taxonomy document exists`; spec authored from `skills-taxonomy-decisions.md`; debt issue #372 filed |
| B2 | Parent-conformance ruling executed (the 30-parent conform pass) | done | six batches `251eca5e`..`fa4d2e3e` + review fix `ea68d9b4` (merged `2d82ab05`) | structural sweep over the 30 parents; `bash skills-unspurious/_completion/verify.sh` | 30/30 carry the two new sections; 101/101 variant lines; `NO-FAILURES` |
| B3 | `graphql` outlier confirmation | done | recorded in `skills-taxonomy-decisions.md` (D-T8) | `grep -n 'D-T8' docs/design/skills-taxonomy-decisions.md docs/design/skills-taxonomy.md` | confirmation recorded; `graphql` conformed with no `## Variants` section |
| B4 | `two-principal-authz` ruling recorded | done | recorded in `skills-taxonomy-decisions.md` (D-T6) | `grep -n 'D-T6' docs/design/skills-taxonomy-decisions.md` | the cross-cutting ruling recorded; conformed without a `## Variants` section |
| C1 | Bypass/proxy families (#278) | pending | - | - | - |
| C2 | Cross-reference wiring | pending | - | - | - |
| D1a | Enrichment proposal report | pending | - | - | - |
| D1b | Surgical enrichment | pending | - | - | - |
| D1c | References/scripts pass | pending | - | - | - |

## Phase A evidence

### A1 - validated status lines

Command: `grep -rn 'proposed, awaiting operator review' docs/design/skills-variant-boundary.md docs/design/skills-ontology.md`

Output:
```
NONE
```

Command: `grep -n 'ses_f181eb14bffei9Y8v5O30nGDjG' docs/design/skills-variant-boundary.md docs/design/skills-ontology.md skills-unspurious/_analysis/LEDGER.md skills-unspurious/_authoring/LEDGER.md`

Output (4 files, validation cited):
```
docs/design/skills-variant-boundary.md:3:*Status: validated by the operator in session `ses_f181eb14bffei9Y8v5O30nGDjG` (2026-09-28, "boundary and skills analysis validated. We can move on to the effective skill writing") ...
docs/design/skills-ontology.md:3:*Status: validated by the operator in session `ses_f181eb14bffei9Y8v5O30nGDjG` (2026-09-28), including the corrections that trust assumptions are the generative layer, that detection channels are multicast per variant, and that Tooling stays. ...
skills-unspurious/_analysis/LEDGER.md:7:*The operator validated the boundary and all 29 analyses in session `ses_f181eb14bffei9Y8v5O30nGDjG` (2026-09-28); the boundary status line now records that validation.*
skills-unspurious/_authoring/LEDGER.md:9:*The authoring contract is the operator-validated ontology ...
```

### A2 - stale agnosticism lines

Command: `grep -rn 'block stays\|left in place and flagged' skills-unspurious/`

Output:
```
NONE
```

Command: `grep -rn '^## Framework-Specific' skills-unspurious/llm-prompt-injection/`

Output:
```
NONE
```

Corrected lines (4, including the correction note): `grep -rn 'dropped with every non-RDF section in `fc90ad3`' skills-unspurious/` returns `INVENTORY.md:85`, `SCREAMING-REPORT.md` (note + batch E), `_migration/reports/batch-E.md:18`.

### A3 - boundary reference ubiquitous

Command: sweep every skill-concern document for `skills-variant-boundary.md`.

Output (all references present):
```
REF   docs/design/skills-ontology.md
REF   docs/design/skills-typed-surface-spec.md
REF   skills-unspurious/README.md
REF   skills-unspurious/INVENTORY.md
REF   skills-unspurious/SCREAMING-REPORT.md
REF   skills-unspurious/DECOMPOSITION-REPORT.md
REF   skills-unspurious/_analysis/SPEC.md
REF   skills-unspurious/_authoring/SPEC.md
REF   skills-unspurious/_analysis/LEDGER.md
REF   skills-unspurious/_authoring/LEDGER.md
REF   docs/design/w0-w1-completion-ledger.md
```

### A4 - tracked home for the cross-stream doc

Command: `git ls-files docs/design/skills-system-decomposition.md`

Output:
```
docs/design/skills-system-decomposition.md
```

Command: `grep -rn 'skills-system-decomposition.md' docs/design/ skills-unspurious/` (excluding the doc itself)

Output (3 citations, all now resolve to a tracked path):
```
docs/design/skills-variant-boundary.md:144:The **RDF notions** (`docs/design/skills-system-decomposition.md`) are the skill's sections; ...
docs/design/skills-ontology.md:13:- The **RDF notions** (the ordered skill sections) are in `docs/design/skills-system-decomposition.md`, component C2 and its provisional glossary.
skills-unspurious/_analysis/SPEC.md:104:RDF notions (from `docs/design/skills-system-decomposition.md`): ...
```

### A5 - arsenal-gaps ticket

Command: `gh issue view 303 --json number,title,labels,state`

Output:
```
{"labels":["enhancement","needs-triage"],"number":303,"state":"OPEN","title":"Kali arsenal gaps from the skills-suite de-spuriation (seven blind/automation capabilities)"}
```

Command: `grep -n 303 skills-unspurious/SCREAMING-REPORT.md`

Output:
```
42:## 3. Arsenal gaps discovered (filed as #303)
44:... The seven gaps below are filed as [issue #303](https://github.com/Diekgbbtt/polyphemus/issues/303) (`enhancement`, `needs-triage`):
```

### A6 - open-item refresh

Command: `grep -rn --exclude-dir=_completion 'awaiting review\|awaiting operator review\|for a future ticket' skills-unspurious/ docs/design/skills-*.md`

Output:
```
NONE
```

The checker's own pattern strings in `skills-unspurious/_completion/verify.sh` are excluded; they are grep expressions, not stale claims.

Refreshed the README status/open-items section, the decomposition report's open questions, and the cross-stream status map and audit findings (each finding now carries its closure status).

### Phase B evidence

- B1: `docs/design/skills-taxonomy.md` authored from the decision record (D-T1..D-T9); issue #372 filed for the 70 grandfathered leaves; `verify.sh` check 6 flips to PASS.
- B2: the 30 level-1 parents conformed to D-T7/D-T8/D-T9 in six batches; structural sweep: 30/30 carry `## Adversarial Capabilities` and `## Trust Assumptions`, 30/30 `name` == directory and `metadata.version: 1.0.0`, `## Variants` holds exactly one line per child, 101 lines total, absent only on `graphql` and `two-principal-authz`.
- B3/B4: recorded in `docs/design/skills-taxonomy-decisions.md` (D-T8, D-T6).
- Independent adversarial review (one round, W0+W1 residual): the W0 branch returned CLEAR (minor findings); the W1 branch returned BLOCKED on a stale README status line. The fix pass applied: the README contradiction, one line-style split in the spec, one shared capability line rephrased, and the parent descriptions abstracted of technology literals (`ssti`, `insecure-deserialization`, `nosql-injection`, `graphql`, `prototype-pollution`).
- Deferred by the review to W7 (recorded in the decomposition map): the suite-wide writing harmonisation (per-step completion criteria, negation phrasing).

## Machine-check runs

### After Phase A

Command: `bash skills-unspurious/_completion/verify.sh`

Output:
```
== W0+W1 completion checks (2026-10-03T11:57Z) ==
PASS  no stale 'awaiting operator review' in boundary/ontology
PASS  stale agnosticism lines gone; llm-prompt-injection carries no Framework-Specific
PASS  skills-ontology.md references the boundary
PASS  cross-stream doc tracked; citations present
PASS  arsenal ticket #303 exists and is linked from SCREAMING-REPORT
PENDING  taxonomy document (B1)
PENDING  defence-bypass / proxy-techniques families (C1)
PASS  101 child SKILL.md present (found 101)
PASS  every child frontmatter name equals its directory
PASS  no em dashes in authored Markdown
== NO-FAILURES (2 pending) ==
exit=0
```

### After Phase B

Command: `bash skills-unspurious/_completion/verify.sh`

Output:
```
== W0+W1 completion checks (2026-10-18T15:17Z) ==
PASS  no stale 'awaiting operator review' in boundary/ontology
PASS  stale agnosticism lines gone; llm-prompt-injection carries no Framework-Specific
PASS  skills-ontology.md references the boundary
PASS  cross-stream doc tracked; citations present
PASS  arsenal ticket #303 exists and is linked from SCREAMING-REPORT
PASS  taxonomy document exists
PENDING  defence-bypass / proxy-techniques families (C1)
PASS  101 child SKILL.md present (found 101)
PASS  every child frontmatter name equals its directory
PASS  no em dashes in authored Markdown
== NO-FAILURES (1 pending) ==
```

## Independent verification

### Phase A

Adversarial independent reviewer (general agent) re-derived every claim from the branch, not the ledger.
Verdict: A1 PASS, A2 PASS, A3 PASS, A4 PASS, A5 PASS, A6 PASS; cross-cutting checks PASS (101 children, `name` == directory, no em dashes, no out-of-scope changes in `96fb82a..HEAD`).
Three minor discrepancies were raised and fixed in commit `COMMIT-REVIEW-A`: the phase summary line now reports pending items instead of "ALL-CHECKS-PASS"; the A6 evidence command excludes the checker's own pattern strings; audit finding 3 is past-tense.

### Phase B

One adversarial independent reviewer re-derived both branches from the repository, never from the reports. Verdicts: the W0 branch CLEAR (minor judgement findings only); the W1 branch BLOCKED on the stale README parent-conformance status line. The blocker and the actionable minor findings were fixed once (`cb2a8cb3`, `ea68d9b4`); the two writing-unevenness findings were deferred to W7 and recorded in the decomposition map.

