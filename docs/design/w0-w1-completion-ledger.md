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
- Operator gates: B1 (taxonomy grilling), B2 (parent-conformance ruling), D1a (enrichment proposal report), and the final acceptance of the A1 status wording.

## Task table

| ID | Task | Status | Commit | Verification command | Observed output |
|---|---|---|---|---|---|
| A1 | Mark the validated documents accepted | done | `COMMIT-A1` | `grep -rn 'proposed, awaiting operator review' docs/design/skills-variant-boundary.md docs/design/skills-ontology.md` | `NONE` (no stale status) |
| A2 | Fix the stale agnosticism lines | done | `COMMIT-A2` | `grep -rn 'block stays\|left in place and flagged' skills-unspurious/; grep -rn '^## Framework-Specific' skills-unspurious/llm-prompt-injection/` | `NONE`; `NONE` (skill carries no such section) |
| A3 | Boundary reference ubiquitous | done | `COMMIT-A3` | `for f in <skill-concern docs>; do grep -q skills-variant-boundary.md "$f" && echo REF $f || echo MISS $f; done` | all `REF` |
| A4 | Tracked home for the cross-stream doc | done | `COMMIT-A4` | `git ls-files docs/design/skills-system-decomposition.md; grep -rn skills-system-decomposition.md docs/design skills-unspurious` | tracked; 3 citations resolve |
| A5 | Arsenal-gaps ticket(s) | done | `COMMIT-A5` | `gh issue view 303 --json number,state,labels; grep -n 303 skills-unspurious/SCREAMING-REPORT.md` | issue #303 OPEN (enhancement, needs-triage); report links it |
| A6 | Open-item refresh | done | `COMMIT-A6` | `grep -rn 'awaiting review\|awaiting operator review\|for a future ticket' skills-unspurious/ docs/design/skills-*.md` | `NONE` |
| B1 | Round-2 taxonomy map | pending | - | - | - |
| B2 | Parent-conformance decision | pending | - | - | - |
| B3 | `graphql` outlier confirmation | pending | - | - | - |
| B4 | `two-principal-authz` ruling recorded | pending | - | - | - |
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

Command: `grep -rn 'awaiting review\|awaiting operator review\|for a future ticket' skills-unspurious/ docs/design/skills-*.md`

Output:
```
NONE
```

Refreshed the README status/open-items section, the decomposition report's open questions, and the cross-stream status map and audit findings (each finding now carries its closure status).

## Machine-check runs

### After Phase A

Command: `bash skills-unspurious/_completion/verify.sh`

Output:
```
== W0+W1 completion checks (2026-10-03T11:55Z) ==
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
== ALL-CHECKS-PASS ==
exit=0
```

