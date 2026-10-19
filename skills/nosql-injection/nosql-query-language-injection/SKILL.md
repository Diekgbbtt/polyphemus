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

- **Applicability**: centers on a query path whose string concatenation places user text inside a parsed query statement.
- **Input forms**: user input arrives as a value inside a graph pattern clause or a search-index query string or a wide-column statement or a ledger-style select statement.
- **Bound parameters**: the driver offers bound parameters that the code path skips, so raw text reaches the parser.
- **Excluded sinks**: operator-object and script-body and pipeline-stage and command-frame sinks stay outside this variant and belong to their own siblings.

## Reconnaissance

- **Reconnaissance scope**: fingerprints the grammar before any breaking work, because each query shape needs its own metacharacters.
- **Sink inventory**: inventory every endpoint whose input flows into concatenated graph, search, wide-column, or ledger statements, and the step completes when each candidate sink carries a named grammar.
- **Quote probe**: submit quote and metacharacter probes and record parser error text versus silent acceptance, and the step completes when every sink carries a quote-handling verdict.
- **Vocabulary enumeration**: enumerate index names, field names, and label vocabularies through listing and mapping reads, and the step completes when each sink carries a grammar vocabulary or a recorded absence.

## Detection Channels

- **Grammar breaks**: confirm this variant.
- **Parser error text**: parser error and syntax text appears after quote and metacharacter probes.
- **Widening differential**: hit-count or content widening appears between a literal control and a metacharacter attempt.
- **Vocabulary disclosure**: index and mapping listing content reveals fields and labels for the next fragment.
- **Clause differential**: boolean response, status, or redirect difference appears between a chained clause and its inert pair.
- **External-fetch callback**: an external-fetch callback fires where a procedure surface reaches an attacker-observed location.

## Adversarial Capabilities

- **Breaking work**: presupposes anonymous request ability plus hit observation, and it consumes both.
- **Quote-break sending**: send quote breaks and comment closers to each sink and compare parser handling.
- **Metacharacter wielding**: wield wildcard and field-selector and existence metacharacters against search-index strings.
- **Clause chaining**: chain union-style and filter-style clauses against graph and ledger and wide-column statements.
- **Callback location**: hold an attacker-observed location only where a procedure surface supports external fetch.
- **Sibling invocation**: invoke the `ssrf` skill at the external-fetch step rather than restating its procedure.

## Trust Assumptions

- **The agreement**: the feature trusts user input to arrive as plain data values inside declared field shapes from request through filter construction to execution, the agreement holds filter shape closed to declared fields and keeps interpreter primitives unreachable, stage and collection selection server-side, script bodies server-authored, query strings literal-bound, command frames single, and stored records plus store internals unexposed, and query answers expose only matched application records while no predicate truth or store content leaks beyond the intended view.
- **The failing clause**: this variant breaks the literal-binding clause because input text breaks out of the quoted literal into query grammar, so crafted fragments widen the match or chain new clauses.

## Key Vulnerabilities

### Literal Escape and Clause Chaining

- **Quote-closer placement**: submit quote closers plus boolean fragments plus comment closers where the sink expects a single literal, because the parser then reads the fragment as live grammar.
- **Control pairing**: pair each chained clause with its inert control and treat a consistent class change as proof of grammar control.
- **Escape procedure**: the parent store step lists graph and ledger and wide-column surfaces without describing quote breaking, so this variant owns the escape procedure.
  ```text
  <VALUE>' <BOOLEAN-FRAGMENT> '<COMMENT-CLOSER>
  <VALUE>'} <CHAINED-CLAUSE> <COMMENT-CLOSER>
  ```

### Search-String Widening

- **Metacharacter submission**: submit wildcard and field-selector and existence metacharacters to search-index query strings, because the index parser evaluates them as match directives rather than literal text.
- **Widening walk**: walk from a match-all wildcard to field-scoped selectors to existence probes, and record each widening step.
- **Widening procedure**: the parent store step omits search metacharacters, so this variant owns the widening procedure.
  ```text
  <WILDCARD>
  <FIELD><SELECTOR><VALUE>
  <EXISTENCE-OPERATOR>:<FIELD>
  ```

### String-Context Breakout

- **Literal break**: where the application concatenates input into a script-expression string instead of accepting an operator object, the break is a literal break inside that string.
- **Quote fuzzing**: fuzz the quote and metacharacter set first, then close the literal with an always-true fragment and confirm through a boolean differential.
- **Boolean extraction**: extract through the same boolean oracle character by character, because the string context answers per predicate rather than per record.
- **String-context ownership**: the parent grammar step lists query grammars without describing a script-string literal, so this variant owns the string-context break; hand the step to the script sibling when the value becomes an executable body rather than a literal.

### Graph Clause Control

- **Pattern-break submission**: submit pattern breaks plus union-style appends to graph query text, because concatenated patterns merge the fragment into the executed traversal.
- **Marker verification**: verify control through record markers outside the intended pattern rather than bulk traversal reads.
- **Graph procedure**: the parent store step lists graph concatenation without describing pattern breaks, so this variant owns the graph procedure.

### Procedure-Surface Abuse

- **Procedure-call exercise**: exercise database procedure calls reachable through the broken query only for fetch-then-read sequencing, because external fetch plus dynamic execution extend the break beyond record reads.
- **Sibling routing**: invoke the `ssrf` skill at the external-fetch step and the operator sibling nowhere, since no operator primitive participates here.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding difference changes the literal-breaking step itself.
- **Comment closers**: comment closers plus spacing swaps reach the parser past naive quote filters.
- **Case folding**: case folding plus keyword splitting reach the parser past naive keyword blocklists.
- **Encoded quotes**: percent-encoded plus double-encoded quotes reach the parser past filters that match only literal quote bytes.
- **Filter-clause alternatives**: filter-clause alternatives reach the parser past single-keyword stripping.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Breaks**: chain forward into reads because one widened match without a follow-up read is only a probe.
- **Vocabulary pivot**: pivot from a match-all wildcard to index and mapping reads for field vocabularies.
- **Selector pivot**: pivot from field vocabularies to scoped selectors that confirm targeted extraction.
- **Label pivot**: pivot from clause control to neighboring labels and collections for the smallest confirming read.
- **External-fetch pivot**: pivot from external fetch to the `ssrf` procedure and stop at the callback that proves egress.
- **Stop condition**: stop each chain at the smallest read or reversible proof that confirms the architectural risk.

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

- **Stop condition**: stop when text answers as inert literals, because bound values without grammar effect are safe.
- **Bound parameters**: bound parameters keep user text inside literals regardless of metacharacters, verified by code review.
- **Uniform hit counts**: uniform hit counts across literal controls and metacharacter attempts carry no widening information.
- **Parser errors**: parser errors come from malformed test vocabularies rather than from grammar control.
- **Sandboxed profiles**: sandboxed search profiles strip metacharacters before index parsing.

## Pro Tips

- **Breaking**: rewards grammar patience plus vocabulary reads plus small chains.
- **Per-grammar fingerprinting**: fingerprint quote handling per grammar because metacharacters never transfer across query shapes.
- **Vocabulary reading**: read index and mapping vocabularies before chaining so each fragment names live fields.
- **Widening ladder**: walk the widening ladder from match-all to scoped selectors so each step confirms the next.
- **Out-of-pattern marker**: verify graph control with one out-of-pattern marker rather than bulk traversal reads.
- **Sibling invocation**: invoke the `ssrf` skill at external-fetch steps instead of duplicating its procedure.

## Summary

A concatenated query path that parses input as grammar answers crafted fragments.
Literal escape proves the break, metacharacter widening maps the reach, and the smallest follow-up read confirms each clause.
