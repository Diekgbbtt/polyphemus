---
name: nosql-operator-injection
description: Operator-predicate injection embedding query operators in filter input to bypass checks and extract fields. Use when login or filter endpoints accept structured objects; when boolean response differentials answer predicate truth; when character-by-character field extraction needs proving.
metadata:
  version: 1.0.0
---

# Operator Injection

Some filter paths parse user input straight into query objects, so crafted keys reach the interpreter as predicate operators.
This variant builds operator predicates that bypass value checks and walks sensitive fields out through response differentials.
The extraction goal is unauthorized access plus field values rebuilt from boolean oracles without any direct output channel.

## Attack Surface

- **Applicability**: centers on a filter path whose input envelope reaches query construction as a structured object.
- **Input forms**: user input arrives as a parsed body object or as bracket-notation fields coerced into nested objects or as encoded structured text in query strings, headers, or cookies.
- **Filter sink**: the filter sink hands that object to a find-style lookup with operator keys live and string casting absent.
- **Store product**: store product rides inside this variant only as payload spelling because renaming a store never changes the predicate-building procedure.

## Reconnaissance

- **Reconnaissance scope**: maps envelopes plus error behavior before any predicate work, because each envelope needs its own operator spelling.
- **Sink inventory**: inventory every endpoint that accepts structured bodies plus bracket-notation forms plus encoded structured text, and the step completes when each candidate sink carries a named envelope.
- **Malformed-probe pass**: submit malformed operator objects and bracket probes and record driver error text versus silent filtering, and the step completes when every sink carries an error-or-silent verdict.
- **Pass-through probe**: submit a neutral operator predicate beside a plain value and record whether operators pass through to the store, and the step completes when pass-through is proven or refuted per sink.

## Detection Channels

- **Pass-through predicates**: confirm this variant.
- **Driver error text**: names collections, fields, or cast failures after malformed operator objects.
- **Boolean differential**: boolean response, status, or redirect difference appears between a true predicate and its false pair.
- **Impossible success**: login or filter success comes from an operator predicate that no literal value could satisfy.
- **Progressive narrowing**: progressive match narrowing appears across iterated pattern prefixes during character-by-character extraction.

## Adversarial Capabilities

- **Predicate work**: presupposes anonymous request ability plus response observation, and it consumes both.
- **Envelope comparison**: send structured objects and bracket-notation forms to the same sink and compare handling.
- **Predicate pairing**: hold paired true-versus-false predicates and normalize each response before comparing.
- **Prefix iteration**: iterate pattern prefixes with binary search over the value alphabet.
- **Privileged session**: hold an authenticated low-privilege session only where the sink requires privilege before filtering.

## Trust Assumptions

- **The agreement**: the feature trusts user input to arrive as plain data values inside declared field shapes from request through filter construction to execution, the agreement holds filter shape closed to declared fields and keeps interpreter primitives unreachable, stage and collection selection server-side, script bodies server-authored, query strings literal-bound, command frames single, and stored records plus store internals unexposed, and query answers expose only matched application records while no predicate truth or store content leaks beyond the intended view.
- **The failing clause**: this variant breaks the operator-shape clause because input keys reach the filter interpreter as predicate operators, so crafted predicates match records the caller was never granted.

## Key Vulnerabilities

### Operator-Predicate Bypass

- **Operator placement**: submit inequality and comparison and membership operators where the sink expects literal values, because a live interpreter evaluates the operator instead of comparing the literal.
- **Negation pairing**: pair each predicate with its exact negation and treat a consistent class change as proof of interpretation.
- **Paired-predicate procedure**: the parent login step names operator injection without stating true-versus-false pairing, so this variant owns the paired-predicate procedure.
  ```text
  {"<FIELD>": {"<OPERATOR>": <VALUE>}}
  <FIELD>[<OPERATOR>]=<VALUE>
  ```

### Pattern-Prefix Extraction

- **Prefix walk**: walk each sensitive field by extending a pattern prefix one alphabet step at a time, because a boolean oracle answers one prefix per request.
- **Alphabet halving**: halve the alphabet with range comparisons to reach each character in logarithmic requests rather than linear guessing.
- **Search procedure**: the parent blind step names character iteration without stating range halving, so this variant owns the search procedure.
  ```text
  {"<FIELD>": {"<PATTERN-OPERATOR>": "^<PREFIX>"}}
  ```

### Selector-Shape Parity

- **Selector carry-over**: carry the same operator objects into selector-style find endpoints on sibling document stores, because identical selector grammars answer identical predicates.
- **Parity treatment**: treat each reachable selector sink as another instance of the same predicate procedure rather than a new technique.
- **Parity procedure**: the parent store list names selector surfaces without stating the shared grammar, so this variant owns the parity procedure.

## Bypass Techniques

- **Bypass forms**: stay aspects inside this variant because no encoding difference changes the predicate-building step itself.
- **Alternative operators**: alternative operators plus negation wrappers reach the interpreter past single-operator blocklists.
- **Expression-context comparisons**: expression-context comparisons reach the interpreter past top-level operator stripping.
- **Dotted-key shapes**: dotted-key versus nested-object shapes reach the interpreter past sanitizers that strip only one form.
- **Wrapping variants**: array-wrapped versus object-wrapped operators reach the parser past shape checks that assume one wrapping.
- **Encoded brackets**: percent-encoded plus double-encoded brackets reach the parser past filters that match only literal bracket text.
- **Case folding**: case-folding pattern options widen matches past case-sensitive comparisons.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Predicates**: chain forward into reads because one bypass without a follow-up read is only a probe.
- **Access pivot**: pivot from a bypassed login to privileged record or user-list fetches for a reversible access proof.
- **Field pivot**: pivot from pattern-prefix extraction to token, reset-code, or key fields for the smallest confirming read.
- **Error-text pivot**: pivot from error text to collection and field names that sharpen the next predicate.
- **Stop condition**: stop each chain at the smallest read or reversible proof that confirms the architectural risk.

## Testing Methodology

Predicate work runs envelope mapping first and extraction second, because no operator proves anything until its delivery shape is known.
The first bent step is S4 Attempt operator injection, namely operator-predicate construction plus boolean-oracle confirmation plus iterative pattern extraction.
The delta over the parent is the paired-truth procedure plus the alphabet-halving search plus the envelope-parity mapping that S4 through S6 name without specifying.
1. **Inventory sinks** - list every login, search, filter, and lookup endpoint with its envelope, and the step completes when no unlisted sink remains.
2. **Classify envelopes** - name the structured-object versus bracket-notation versus encoded-text form per input, and the step completes when every input carries one envelope class.
3. **Probe errors** - submit malformed operator objects and record error text versus silent filtering, and the step completes when every sink carries an error-or-silent verdict.
4. **Prove pass-through** - submit neutral operator predicates beside literal controls, and the step completes when each sink shows interpretation or a recorded negative.
5. **Calibrate the oracle** - submit true-versus-false predicate pairs and record the stable difference class, and the step completes when every live sink carries a differential or a ruled-uniform verdict.
6. **Bypass value checks** - submit inequality, comparison, and membership predicates against authentication and filter logic, and the step completes when each check shows bypass or a recorded negative.
7. **Extract by prefix search** - halve each character range with pattern predicates until one value remains, and the step completes when every requested field carries one confirmed value or a definitive negative.

## False Positives

- **Stop condition**: stop when predicates answer as inert data, because literal handling without interpretation is safe.
- **Strict-mode casting**: strict-mode casting stringifies operator objects before query construction, verified by code review.
- **Operator-key stripping**: operator-key stripping removes crafted keys before they reach the driver.
- **Uniform responses**: uniform responses across true-versus-false pairs carry no oracle information.
- **Validation errors**: response differences come from validation errors rather than from predicate truth.

## Pro Tips

- **Predicates**: reward envelope coverage plus calibration plus narrow alphabets.
- **Envelope coverage**: try structured objects and bracket-notation forms against every sink because middleware handles them differently.
- **Calibration first**: calibrate the true-versus-false differential before extracting anything.
- **Field targeting**: target token and reset-code and key fields with prefix search, not only credential fields.
- **Range halving**: halve each character range so extraction costs logarithmic requests per character.
- **Inconclusive logging**: record inconclusive pairs as inconclusive rather than negative so later runs revisit them.

## Summary

A filter path that interprets input keys as operators answers crafted predicates.
Paired predicates prove the interpretation, prefix search rebuilds each value, and the smallest follow-up read confirms the access.
