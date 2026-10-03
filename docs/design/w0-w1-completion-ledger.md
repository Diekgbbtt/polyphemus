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
| A2 | Fix the stale agnosticism lines | pending | - | - | - |
| A3 | Boundary reference ubiquitous | pending | - | - | - |
| A4 | Tracked home for the cross-stream doc | pending | - | - | - |
| A5 | Arsenal-gaps ticket(s) | pending | - | - | - |
| A6 | Open-item refresh | pending | - | - | - |
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

