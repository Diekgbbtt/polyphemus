# Review: prototype-pollution

## Verdicts

| variant | verdict | criteria failed |
|---|---|---|
| prototype-pollution-client-side | PASS | none |
| prototype-pollution-server-side | PASS | none |

## Criterion walkthrough

### 1. Directory path and exact variant name

Both variants live at `skills-unspurious/prototype-pollution/<variant>/SKILL.md` with the exact names from the analysis section 9 and section 11.
PASS for both.

### 2. Valid frontmatter

Both carry `name` equal to the variant directory, a non-empty `description` front-loaded with the variant leading word, three distinct per-branch triggers with no synonym restatement, and `metadata.version: 1.0.0`.
Client triggers cover routing or rendering derivation, privilege-flag defaults, and catalog-backed sink proof.
Server triggers cover template or process-sink merges, inventory-gated assembly, and background-job merges.
PASS for both.

### 3. Ubiquitous sections present, omissions genuinely absent

Both hold all nine ubiquitous sections: Attack Surface, Detection Channels, Adversarial Capabilities, Trust Assumptions, Key Vulnerabilities, Testing Methodology, False Positives, Pro Tips, Summary.
Both keep Bypass Techniques and Tooling from the parent.
Reconnaissance, Advanced Techniques, and Chaining Attacks are omitted where the parent carries no such section, and `references/` is omitted where the analysis section 3 records no scripted tests for this class.
The ontology matrix absent column (proxy, anti-patterns, scripted tests) is honoured.
PASS for both.

### 4. Trust Assumptions variant-specific failing clause

Shared agreement body with a micro-verbatim failing clause, as SPEC section 5 licenses.
Client fails "at the browser consumer, where a routing, auth-state, or rendering consumer reads an attacker-named prototype property as its own configuration".
Server fails "at the server merge sink, where a recursive merge applies attacker-named keys to a shared prototype feeding template or process-spawning sinks".
Neither restates the other.
PASS for both.

### 5. Adversarial Capabilities authored

Both author four capability entries from scratch (structured input, session or oracle reading, catalog or inventory use, isolated or staged markers).
No stubs.
PASS for both.

### 6. Detection Channels live entries only

Client keeps unrelated-read proof plus routing, auth-interface, and rendering shifts.
Server keeps follow-up reads, response deltas, template-output shifts, and out-of-band execution proof.
Neither copies a parent list (the parent ships no Detection Channels section).
PASS for both.

### 7. Bent step present with visible delta

Client names "the catalog-driven client-sink proof" with delta "gadget-catalog consultation plus per-library sink driving to behavioral proof".
Server names "the inventory-driven gadget-chain assembly" with delta "white-box module enumeration plus version-gated chain assembly plus server-execution proof".
Both match analysis section 9 and section 11.
PASS for both.

### 8. No concrete reference leak

Automated scan finds no product, version, host, parameter, payload-literal, or tool-name literals in either variant.
Parent concretes (library names, parser names, gadget-body key names, canary literal, fuzzer names) are abstracted out.
The `nosql-injection` mention at the server bypass step is the sanctioned cross-skill pointer from analysis section 11, not a leak.
PASS for both.

### 9. writing-great-skills style

Both use bold leading words per step and section, keep single-source meanings with no cross-section duplication, phrase positively with the block-listing guardrails paired to positive alternatives, and end steps on checkable completion criteria.
PASS for both.

### 10. No em dashes, one sentence per line

Automated scan finds no em or en dashes in either file.
Every authored prose line carries exactly one full sentence (numbered-step prefixes excluded as labels, code fences excluded as payload shapes).
PASS for both.

## Operator payload-shape requirement

Both variants retain abstract payload shapes with placeholders ubiquitously in Key Vulnerabilities, as required for this class.
Direct wrappers, two-level wrappers, and query-nested forms use `<PROTO-KEY>`, `<CTOR-KEY>`, `<PROTO-NAME>`, `<CANARY>`, and `<MARKER>` placeholders.
Array-index, lookalike, process-control-body, and template-engine-body forms are described abstractly with no concrete literals.
Both are abstract restatements of the parent payload blocks, never concrete literals.
PASS for both.

## FAIL detail

None.
No section, criterion number, quoted line, or fix applies.
