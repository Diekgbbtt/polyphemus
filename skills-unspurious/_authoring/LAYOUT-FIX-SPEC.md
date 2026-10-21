# Layout-fix spec: enumerable sections as identifier records

*Working spec for the layout normalisation of the W0 phase-4 variant skills. Companion to `docs/design/skills-ontology.md` (the section contract) and `SPEC.md` (the authoring contract). The golden reference is the two fixed `ssti` variants.*

## 1. The defect

Some variant skills rendered enumerable sections as flat prose paragraphs.
The source parent skills render those sections as bullet lists.
Prose hides the records: a reader cannot scan them and a parser cannot address them.

## 2. The rule

Every enumerable section body in every variant is a flat bullet list.
Each bullet is one record of the form:

```
- **<identifier>**: <brief content>.
```

## 3. Sections in scope

`## Attack Surface`, `## Reconnaissance`, `## Detection Channels`, `## Adversarial Capabilities`, `## Trust Assumptions`, `## Key Vulnerabilities`, `## Advanced Techniques`, `## Bypass Techniques`, `## Chaining Attacks`, `## False Positives`, `## Pro Tips`, `## Tooling`.

## 4. Sections out of scope (leave byte-identical)

Frontmatter, `# <Title>`, the intro paragraph, `## Testing Methodology` (keeps its numbered steps), `## Summary` (keeps its prose), and every `references/` pointer target.

## 5. The record shape

- A record line reads `- **<identifier>**: <content>.`
- `<identifier>` is a noun phrase in sentence case with no trailing period.
- `<content>` is the predicate and ends with a period.
- One record per line, no blank line between records.
- No nested bullets, no `**group**` headers, and no numbered items inside an in-scope section.
- A `###` subheading may stay as a group label above its records; it is not itself a record.
- Keep a leading word lowercase unless it is a proper term.

## 6. How to derive the identifier

- Declarative source sentence: the identifier is the subject noun phrase, the content is the predicate.
  `Reflection walks enumerate host-runtime classes.` -> `- **Reflection walks**: enumerate host-runtime classes.`
- Imperative source sentence (Reconnaissance, Pro Tips): coin a terse noun-phrase label for the action, the content restates the instruction.
  `Run one arithmetic probe per delimiter family.` -> `- **Delimiter-family probe**: run one arithmetic probe per delimiter family.`
- A `###` subheading already present stays where it is; do not invent one and do not remove one.
  Each sentence under it becomes one record bullet.
- A `**group**` header is removed; fold its meaning into each record's identifier.
- `## Trust Assumptions` yields exactly two records: the agreement, then the failing clause.
- A `See references/...` pointer stays as its own record.

## 7. Preserve

- All substantive content; do not delete a sentence to shorten the section.
- The abstraction rule: no concrete product, version, host, parameter, payload literal, or tool name.
- Positive phrasing and the class's leading words.
- An abstract code fence stays immediately after the record it belongs to, indented two spaces so it sits inside the list item.
- The exact section set and order.
- No em dashes; use a plain dash.

## 8. Golden reference

Read these two fixed files and match their shape exactly:

- `skills-unspurious/ssti/ssti-reflected-evaluation/SKILL.md`
- `skills-unspurious/ssti/ssti-blind-evaluation/SKILL.md`

## 9. Verify before returning

- Every non-heading, non-fence, non-indented line of every in-scope body matches `^- \*\*[^*]+\*\*: .+\.$`.
- No `^[0-9]+\.` line remains inside an in-scope section.
- A `###` line is kept only where the source already had it; no new one is introduced.
- `git diff -- <file>` shows changes only inside in-scope sections.
- No em dash in the file.
