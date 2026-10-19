---
name: nosql-query-language-injection
description: Query-string breaking escaping quoted literals into graph, search, and ledger query grammars. Use when input concatenates into graph clauses or search strings or ledger statements; when wildcard and field metacharacters widen matches; when clause chaining needs proving.
metadata:
  version: 1.0.0
---

# Query Language Injection

Some stores parse user input inside concatenated query strings, so crafted text escapes its literal and becomes query grammar.
This variant breaks string literals across graph, search-index, wide-column, and ledger query shapes and confirms each break through match widening.
The breaking goal is filter escape plus clause control without any operator or script primitive.

## Attack Surface

Applicability centers on a query path whose string concatenation places user text inside a parsed query statement.
User input arrives as a value inside a graph pattern clause or a search-index query string or a wide-column statement or a ledger-style select statement.
The driver offers bound parameters that the code path skips, so raw text reaches the parser.
Operator-object and script-body and pipeline-stage and command-frame sinks stay outside this variant and belong to their own siblings.

## Reconnaissance

Reconnaissance fingerprints the grammar before any breaking work, because each query shape needs its own metacharacters.
Inventory every endpoint whose input flows into concatenated graph, search, wide-column, or ledger statements, and the step completes when each candidate sink carries a named grammar.
Submit quote and metacharacter probes and record parser error text versus silent acceptance, and the step completes when every sink carries a quote-handling verdict.
Enumerate index names, field names, and label vocabularies through listing and mapping reads, and the step completes when each sink carries a grammar vocabulary or a recorded absence.

## Detection Channels

Grammar breaks confirm this variant, so only the entries below are live here.
- Parser error and syntax text after quote and metacharacter probes.
- Hit-count or content widening between a literal control and a metacharacter attempt.
- Index and mapping listing content revealing fields and labels for the next fragment.
- Boolean response, status, or redirect difference between a chained clause and its inert pair.
- External-fetch callback where a procedure surface reaches an attacker-observed location.

## Adversarial Capabilities

Breaking work presupposes anonymous request ability plus hit observation, and it consumes both.
- Send quote breaks and comment closers to each sink and compare parser handling.
- Wield wildcard and field-selector and existence metacharacters against search-index strings.
- Chain union-style and filter-style clauses against graph and ledger and wide-column statements.
- Hold an attacker-observed location only where a procedure surface supports external fetch.
- Invoke the `ssrf` skill at the external-fetch step rather than restating its procedure.

## Trust Assumptions

The feature trusts user input to arrive as plain data values inside declared field shapes from request through filter construction to execution.
The agreement holds filter shape closed to declared fields, keeps interpreter primitives unreachable, keeps stage and collection selection server-side, keeps script bodies server-authored, keeps query strings literal-bound, keeps command frames single, and keeps stored records plus store internals unexposed.
Query answers expose only matched application records, and no predicate truth or store content leaks beyond the intended view.
This variant breaks the literal-binding clause because input text breaks out of the quoted literal into query grammar, so crafted fragments widen the match or chain new clauses.

## Key Vulnerabilities

### Literal Escape and Clause Chaining

Submit quote closers plus boolean fragments plus comment closers where the sink expects a single literal, because the parser then reads the fragment as live grammar.
Pair each chained clause with its inert control and treat a consistent class change as proof of grammar control.
The parent store step lists graph and ledger and wide-column surfaces without describing quote breaking, so this variant owns the escape procedure.
```text
<VALUE>' <BOOLEAN-FRAGMENT> '<COMMENT-CLOSER>
<VALUE>'} <CHAINED-CLAUSE> <COMMENT-CLOSER>
```

### Search-String Widening

Submit wildcard and field-selector and existence metacharacters to search-index query strings, because the index parser evaluates them as match directives rather than literal text.
Walk from a match-all wildcard to field-scoped selectors to existence probes, and record each widening step.
The parent store step omits search metacharacters, so this variant owns the widening procedure.
```text
<WILDCARD>
<FIELD><SELECTOR><VALUE>
<EXISTENCE-OPERATOR>:<FIELD>
```

### String-Context Breakout

Where the application concatenates input into a script-expression string instead of accepting an operator object, the break is a literal break inside that string.
Fuzz the quote and metacharacter set first, then close the literal with an always-true fragment and confirm through a boolean differential.
Extract through the same boolean oracle character by character, because the string context answers per predicate rather than per record.
The parent grammar step lists query grammars without describing a script-string literal, so this variant owns the string-context break; hand the step to the script sibling when the value becomes an executable body rather than a literal.

### Graph Clause Control

Submit pattern breaks plus union-style appends to graph query text, because concatenated patterns merge the fragment into the executed traversal.
Verify control through record markers outside the intended pattern rather than bulk traversal reads.
The parent store step lists graph concatenation without describing pattern breaks, so this variant owns the graph procedure.

### Procedure-Surface Abuse

Exercise database procedure calls reachable through the broken query only for fetch-then-read sequencing, because external fetch plus dynamic execution extend the break beyond record reads.
Invoke the `ssrf` skill at the external-fetch step and the operator sibling nowhere, since no operator primitive participates here.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no encoding difference changes the literal-breaking step itself.
- Comment closers plus spacing swaps reach the parser past naive quote filters.
- Case folding plus keyword splitting reach the parser past naive keyword blocklists.
- Percent-encoded plus double-encoded quotes reach the parser past filters that match only literal quote bytes.
- Filter-clause alternatives reach the parser past single-keyword stripping.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Breaks chain forward into reads because one widened match without a follow-up read is only a probe.
- Pivot from a match-all wildcard to index and mapping reads for field vocabularies.
- Pivot from field vocabularies to scoped selectors that confirm targeted extraction.
- Pivot from clause control to neighboring labels and collections for the smallest confirming read.
- Pivot from external fetch to the `ssrf` procedure and stop at the callback that proves egress.
- Stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Breaking work runs grammar mapping first and clause control second, because no fragment proves anything until its metacharacters are known live.
The first bent step is the S9 store step query-language sub-value, namely quote-breaking grammar plus search-metacharacter widening plus graph and ledger and wide-column clause oracles.
The delta over the parent is the escape procedure plus the widening ladder plus the per-grammar oracle mapping that S9 lists without describing.
1. **Inventory string sinks** - list every endpoint concatenating input into graph, search, wide-column, or ledger statements, and the step completes when no unlisted sink remains.
2. **Fingerprint grammars** - submit quote and metacharacter probes and record parser handling, and the step completes when every sink carries a quote-handling verdict.
3. **Read vocabularies** - enumerate indexes, mappings, labels, and fields through listing reads, and the step completes when each sink carries a vocabulary or a recorded absence.
4. **Break literals** - submit quote closers with boolean fragments beside inert controls, and the step completes when each sink shows grammar control or a recorded negative.
5. **Widen search strings** - walk wildcard to field-selector to existence probes, and the step completes when each search sink shows widening or a recorded negative.
6. **Chain graph clauses** - submit pattern breaks plus union-style appends, and the step completes when each graph sink shows clause control or a recorded negative.
7. **Abuse procedure surfaces** - exercise fetch-then-read sequencing where procedures are reachable, and the step completes when each surface shows extended control or a recorded negative.

## False Positives

Stop when text answers as inert literals, because bound values without grammar effect are safe.
- Bound parameters that keep user text inside literals regardless of metacharacters, verified by code review.
- Uniform hit counts across literal controls and metacharacter attempts, which carry no widening information.
- Parser errors from malformed test vocabularies rather than from grammar control.
- Sandboxed search profiles that strip metacharacters before index parsing.

## Pro Tips

Breaking rewards grammar patience plus vocabulary reads plus small chains.
1. Fingerprint quote handling per grammar because metacharacters never transfer across query shapes.
2. Read index and mapping vocabularies before chaining so each fragment names live fields.
3. Walk the widening ladder from match-all to scoped selectors so each step confirms the next.
4. Verify graph control with one out-of-pattern marker rather than bulk traversal reads.
5. Invoke the `ssrf` skill at external-fetch steps instead of duplicating its procedure.

## Summary

A concatenated query path that parses input as grammar answers crafted fragments.
Literal escape proves the break, metacharacter widening maps the reach, and the smallest follow-up read confirms each clause.
