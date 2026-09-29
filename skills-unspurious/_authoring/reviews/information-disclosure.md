# Review: information-disclosure variants

## Verdict table

| Variant | Verdict | Criteria failed |
|---|---|---|
| error-verbosity-disclosure | PASS | none |
| stored-artifact-disclosure | PASS | none |
| differential-oracle-disclosure | PASS | none |

## Per-variant criterion notes

All three variants satisfy all 10 criteria in SPEC.md section 8.
No FAIL entries, so no section, line-quote, or minimal-fix rows are owed.

Summary of checks per variant:

- Criterion 1: directory is `skills-unspurious/information-disclosure/<variant>/SKILL.md` with the exact analysis section 11 name.
- Criterion 2: frontmatter `name` equals the variant directory, `description` front-loads the variant leading word with three distinct per-branch triggers and no synonym restatement, `metadata.version` is `1.0.0`.
- Criterion 3: every ubiquitous section is present (`Attack Surface`, `Detection Channels`, `Adversarial Capabilities`, `Trust Assumptions`, `Key Vulnerabilities`, `Testing Methodology`, `False Positives`, `Pro Tips`, `Summary`).
- `Reconnaissance` and `Chaining Attacks` are kept, which is correct for this class (the class seeks surfaces and composition matters per the analysis section 3 chaining notion).
- `Bypass Techniques` is absent in all three, which is correct (the analysis section 3 marks defence-bypass as aspect-only, and the ontology matrix marks bypass genuinely absent for this class).
- No `references/` directories exist, which is correct (scripted tests are marked absent for this class).
- Criterion 4: each `Trust Assumptions` states the shared agreement with a variant-specific failing clause (generic-output clause versus unreachable-deployable clause versus agreement-of-indistinguishables clause), varying only at the failing clause as SPEC.md section 5 licenses.
- Criterion 5: each `Adversarial Capabilities` is authored from capability rows and reconnaissance probes, not stubbed.
- Criterion 6: each `Detection Channels` holds only the entries live for its own bent step plus an explicit sibling-exclusion sentence, not a parent copy.
- Criterion 7: each bent step from analysis section 11 is named with an explicit delta over its parent step (P3 versus P4 versus P2).
- Criterion 8: no concrete product, version, host, parameter, payload-literal, or tool-name leak; header and method vocabulary stays abstract (`header-only`, `validators`, `keying signals`); the only skill names are the licensed cross-references (`graphql`, `two-principal-authz`, authorization skills).
- Criterion 9: style obeys writing-great-skills (live sentences, leading channel vocabulary, positive phrasing, no cross-section duplication).
- Criterion 10: no em dashes anywhere; free prose is one full sentence per line (numbered methodology steps carry action plus completion criterion per step by design).

## Parent non-standard material folding

The parent's `Triage Rubric` severity levels were folded sensibly rather than dropped: Critical and High chains live in each variant's `Chaining Attacks` narrowed to that variant (verbosity carries paths-to-file-access and versions-to-flaws; artifact carries secrets-to-control, schemas-to-authorization-bypass, and bundles-to-hidden-routes; oracle carries existence-to-targeting, cross-session serving to boundary crossing, and channel extras to hidden operations), while Low and exclusion predicates live in each variant's `False Positives`.
All four parent `Exploitation Chains` (credential extraction, version to CVE, path disclosure to LFI, schema to auth bypass) appear across the set, each narrowed to the variant it belongs to.
No chain was dropped without trace.

## Sibling variance

The three siblings share one trust-agreement body and vary only at the failing clause plus the moment clause (`renders a failure` versus `answers a fetch` versus `answers the second request`), which is the licensed micro-verbatim variation.
