---
name: xpath-injection
description: XPath expression injection into XML-backed queries. Use when caller text concatenates into a path expression or a predicate; when node-set widening, predicate tautology, or blind string extraction answers as the oracle.
metadata:
  version: 1.0.0
---

# XPath Injection

XPath injection exploits the mismatch between the text an application passes into an XML query and the expression grammar the query engine evaluates.
Caller text that closes a quoted literal supplies its own predicate, and caller text that lands in a node-selection position chooses which branch of the document is traversed.
The class owns predicate bypass, node-set widening, node-name discovery, and blind extraction through string and length functions.

## Attack Surface

- **XML-backed lookups**: authentication flows, search surfaces, catalogues, and configuration reads whose predicate is an expression over a document or a document store.
- **Value position**: caller text interpolated inside a quoted literal in a predicate, where a closing quote ends the literal.
- **Path position**: caller text interpolated into a node name or a path fragment, where the caller chooses the branch instead of the value.
- **Carriers**: form fields, query parameters, structured bodies, and stored values that a later flow resolves through an expression.
- **Out of scope**: a document parsed for entities rather than queried belongs to the xxe class, because no expression grammar evaluates there.

## Reconnaissance

### Backend Confirmation

- **Error fingerprinting**: send a quote or a bracket probe and read failure text for expression-parser naming and syntax complaints.
- **Baseline first**: capture a control response with a valid-looking wrong value, because every later verdict compares against it.
- **Balance note**: the expression language has no comment syntax, so a probe must keep its quotes and brackets balanced; truncation comes from balance, not from a terminator.

### Context Discrimination

- **Context verdict**: decide per input whether the value lands in a value position or in a path position, because the escaping rules differ.
- **Value position**: a closing quote plus a caller predicate is the shape to test first.
- **Path position**: a caller-supplied node name or wildcard is the shape to test first, because a value-position payload usually fails there.

### Probe Grammar and Oracle Setup

- **Predicate pair**: build a true predicate and a false predicate on a known node, and treat the response class change as the oracle.
- **Function oracles**: string length, substring, and node-count functions answer boolean questions about values the response never renders.
- **Node-name probes**: node-name and name-matching predicates enumerate element and attribute names without rendering content.
- **Oracle ladder**: prefer error, then rendered node or count, then the boolean predicate, and keep timing for engines that answer no other way.

## Detection Channels

- **Unbalanced-probe error**: a syntax error for an unbalanced probe where a balanced probe succeeds, which proves the expression is concatenated and parsed.
- **Predicate differential**: a differential between a true predicate and its false pair, which proves predicate control.
- **Impossible success**: an authentication success from a predicate no literal value could satisfy, which proves the credential predicate was neutralised.
- **Node-set widening**: a node-set widening between a single-branch query and a caller-appended union, which proves path control.
- **Cross-branch node or count**: a rendered node or a count change that carries values from outside the intended branch.
- **Character-by-character value**: a value recovered character by character through string-length and substring predicates.
- **Grammar-naming error text**: error text naming the expression grammar or the document store, which narrows the probe set.
- **Per-identity difference**: a per-identity difference in message, status, or timing under one fixed value, which proves an enumeration oracle.

## Adversarial Capabilities

- **Expression injection**: presupposes an input that reaches the expression grammar plus a readable oracle, and it consumes both.
- **Grammar-reaching input**: reach a field whose text lands inside a predicate literal or a node-selection position.
- **Oracle reading**: read syntax errors, status, body markers, counts, and rendered nodes as oracle answers.
- **Balanced composition**: compose probes that keep every quote and bracket balanced, because the language offers no comment to absorb the remainder.
- **Candidate node names**: hold candidate element and attribute names for enumeration and for targeted extraction.
- **Second context**: hold a path-position input as well as a value-position input, because the two contexts accept different payloads.

## Trust Assumptions

- **The agreement**: caller input reaches the expression as a literal inside a predicate the application wrote, never as expression structure or as a node-selection fragment.
- **Held clauses**: the expression grammar carries only application fragments, node names come from the application, the document set stays inside the caller's scope, and the returned node set matches the intended query.
- **The failing clause**: the literal-binding clause. Caller text closes the quoted literal and supplies its own predicate or node set, so the document is traversed with an expression the application did not write.
- **The delta**: the class fails at one of two boundaries, the value literal or the node path, and the balance rule makes every probe syntactically complete.

## Key Vulnerabilities

### Predicate Bypass

- **Literal break-out**: close the quoted literal, append a boolean predicate, and keep the whole expression balanced so the engine parses rather than rejects.
- **Always-true predicate**: a predicate no literal value can falsify makes the credential comparison irrelevant and admits the first matching node.
- **Compound conditions**: the caller's predicate composes with the application's own conditions, so a negated impossible condition is as strong as a tautology.

### Node-Set Widening

- **Union append**: append a second path to the query so the result set carries nodes from a branch the application never intended.
- **Branch selection**: a caller-supplied node name or wildcard in a path position selects the branch directly.
- **Widened reads**: a union that returns whole branches discloses far more than the single node the feature renders.

### Node-Name Discovery

- **Name predicates**: node-name and name-matching predicates enumerate elements and attributes without rendering any content.
- **Count oracles**: node counts answer structural questions about the document before any value is read.
- **Attribute targeting**: attributes are frequently the secret holder, so enumerate attributes before reading values.

### Blind Extraction

- **String functions as oracle**: string length and substring predicates answer one boolean per request about a value the response never renders.
- **Character walk**: recover a value one position at a time, comparing each candidate against the paired predicate.
- **Multi-node verdicts**: extract from several nodes in one sweep by pairing each candidate with its own predicate.
- **Target selection**: recovery tokens, configuration values, and identity attributes answer the same way as credential fields.

### Path-Position Injection

- **Caller-chosen branch**: a value landing in a node-selection position lets the caller choose the document branch the query reads.
- **Wildcard reach**: a wildcard in a path position returns nodes the intended query never selected.
- **Boundary between contexts**: a value-position payload fails in a path position and the reverse, so the context verdict decides the payload set.

## Advanced Techniques

- **Oracle ladder**: prefer error, then count or rendered node, then the boolean predicate, and use timing only where the engine answers nothing else.
- **Union dumping**: widen to a whole branch, then narrow to the smallest node that proves the scope break.
- **Per-node verdicts**: pair each extracted node with its own true and false predicate so one request answers about one node only.
- **Function coverage**: string, length, substring, and count functions cover most extraction needs, so build the oracle from the functions the engine exposes.
- **Extension reach**: where the engine exposes extension functions, an expression may reach files or destinations, which hands the fetch step to the xxe or ssrf class.

## Bypass Techniques

- **Quoting variants**: quote forms that survive a filter yet parse as a literal boundary, including nested and alternate quoting.
- **Assembly**: concatenate string fragments so a denylisted keyword never appears literally in the request.
- **Alternate path syntax**: abbreviated paths, wildcards, and descendant axes reach the same nodes when the obvious path form is filtered.
- **Encoding layers**: an encoding that survives the filter and decodes before the expression parses restores the grammar characters.
- **Predicate substitution**: substitute an equivalent predicate for a filtered function or operator, and build the oracle from what remains reachable.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Authentication to privilege**: a predicate bypass that lands on a privileged account continues into the surface that account controls.
- **Disclosed nodes to credentials**: extracted configuration or identity nodes feed credential discovery and replay flows.
- **Document traversal to secrets**: a widened branch often holds secrets the feature never intended to render.
- **Extension functions to interior reach**: where the engine exposes extension functions, the fetch or read step hands off to the ssrf or xxe class.
- **Recovered tokens to recovery flows**: an extracted recovery token or identifier feeds the flow that accepts it.

## Testing Methodology

Context discrimination runs before probing, because the two positions accept different payloads.
1. **Inventory expression-bound inputs** - list every field whose text reaches a predicate literal or a node-selection position, and the step completes when no unlisted input remains.
2. **Capture the baseline** - record a control response with a valid-looking wrong value, and the step completes when the control carries status, size, and marker values.
3. **Discriminate the context** - decide value position versus path position per input, and the step completes when every input carries a context verdict.
4. **Probe the grammar** - send quote and bracket probes beside balanced controls, and the step completes when every input carries a parse-handling verdict.
5. **Prove predicate control** - pair a true predicate with a false one and record the response class change, and the step completes when the pair separates or a definitive negative is recorded.
6. **Widen or enumerate** - append a union in a path position, or enumerate node and attribute names through name predicates, and the step completes when the scope break or the name set is recorded.
7. **Extract or escalate** - walk values through length and substring predicates, or hand the disclosed nodes to the follow-on flow, and the step completes when the target value or the account context is recorded.

## False Positives

- **Literal reflection**: expression syntax echoed verbatim, which is a markup-shape finding rather than evaluation.
- **Uniform rejection**: a parser that rejects every unbalanced probe and accepts every balanced one, which signals a parameterised query rather than injection.
- **Bound predicates**: a query that binds the caller value, verified by code review or by a quote that changes nothing.
- **Client-side evaluation**: an expression evaluated in a browser over fetched data, whose impact is markup rather than document traversal.
- **Rendering differential**: a count or length change caused by output formatting rather than by the predicate.
- **Unbalanced success**: a syntax error read as a bypass, when only a balanced expression that executes proves control.

## Pro Tips

- **Balance discipline**: keep every probe balanced; the language has no comment to absorb an unclosed quote.
- **Context first**: discriminate the context first, because payloads never transfer between a value position and a path position.
- **Function preference**: prefer length and substring predicates for extraction, and a rendered node or count for the first proof.
- **False-pair pairing**: pair every claim with a false predicate of the same shape, because the failure response is the proof of parsing.
- **Attribute enumeration**: enumerate attributes before values, because attributes are the more frequent secret holder.
- **Widen then narrow**: widen to a whole branch, then narrow to the smallest node that proves the scope break.
- **Known-value control**: use a control node whose value is known, so a predicate that answers on it validates the oracle before any target read.

## Summary

Expression injection is a grammar break at a value literal or at a node path, and the balance rule makes every probe syntactically complete.
Discriminate the context, prove the predicate against a false pair, and read nodes or values only through a reproducible oracle.
