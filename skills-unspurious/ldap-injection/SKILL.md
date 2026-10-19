---
name: ldap-injection
description: LDAP filter and name injection against directory-backed authentication and search. Use when caller text concatenates into a directory filter or a distinguished name; when a bind result, result count, or attribute read answers as the oracle.
metadata:
  version: 1.0.0
---

# LDAP Injection

Directory injection exploits the mismatch between the text an application passes into a directory query and the grammar the directory evaluates.
The same value can land in a filter clause or in a distinguished name, and the two contexts carry different metacharacters and different escape rules.
The class owns authentication bypass, blind attribute extraction, directory enumeration, and out-of-band confirmation through a caller-controlled referral.

## Attack Surface

- **Authentication acceptors**: login, single sign-on, and intranet panels whose credential check resolves through a directory bind or search.
- **Search surfaces**: people and colleague search, org charts, address books, group membership lookups, and import or export over directory data.
- **Filter context**: caller text interpolated inside a filter clause the application composed, where the grammar operators are live.
- **Name context**: caller text interpolated into a distinguished name, where the separators and assignment characters are live instead.
- **Carriers**: form fields, structured bodies, query parameters, and any filter text a client can influence.

## Reconnaissance

### Backend Confirmation

- **Error fingerprinting**: send malformed values and read failure text for directory-layer naming, filter-syntax complaints, and bind-failure codes.
- **Baseline first**: capture a control response with a valid-looking wrong secret, because every later verdict compares against it.
- **Unbalanced probe**: send one unbalanced group bracket; a syntax error or status change against the baseline is the cleanest tell that the filter is concatenated.

### Context Discrimination

- **Context verdict**: decide per input whether the value lands inside a filter clause or inside a name, because the metacharacters do not transfer between them.
- **Filter context**: the wildcard, the group brackets, the escape character, and the terminator are the live metacharacter roles.
- **Name context**: the name separators and the assignment character are live instead, and the wildcard loses its meaning.

### Metacharacter and Oracle Probes

- **Role-per-probe**: test one metacharacter role per attempt, raw against escaped, and record the grammar verdict for each.
- **Operator logic**: the grammar is prefix notation, so the operator precedes its clauses and every clause is bracketed; a probe must leave the total bracket count balanced to parse.
- **Oracle ladder**: establish status, body marker, and result count before timing, and keep an out-of-band channel for otherwise-blind cases.
- **Enumeration control**: compare each wildcard prefix against an unlikely control prefix, because a count that never moves proves nothing.

## Detection Channels

- A syntax error for an unbalanced bracket where a balanced probe succeeds, which proves the filter is concatenated and parsed.
- A differential between an always-true predicate and its always-false pair, which proves predicate control.
- An authentication success from a filter that no literal value could satisfy, which proves the credential clause was neutralised.
- A result count or result-set change per prefix against a control prefix, which proves wildcard enumeration.
- Error text naming the filter grammar or the directory layer, which narrows the probe set.
- A returned attribute value recovered character by character through a boolean oracle.
- A per-identity difference in message, status, or timing under one fixed secret, which proves an enumeration oracle.
- An out-of-band name-resolution or directory hit from a caller-supplied referral, which proves server-side reach with zero ambiguity.

## Adversarial Capabilities

Directory injection presupposes an input that reaches the directory grammar plus a readable oracle, and it consumes both.
- **Grammar-reaching input**: reach a field whose text lands inside a filter clause or a distinguished name.
- **Oracle reading**: read syntax errors, status, body markers, counts, and timing as oracle answers.
- **Candidate identities**: hold a candidate list of directory identities for enumeration and for bypass targeting.
- **Out-of-band listener**: operate a listener so a caller-supplied referral confirms reach when every in-band channel is masked.
- **Bind context**: hold directory credentials or a privileged session only where white-box validation of the inferred filter is wanted.

## Trust Assumptions

- **The agreement**: caller input reaches the directory as a value inside a filter or a name the application composed, never as grammar or as a name component.
- **Held clauses**: the filter grammar carries only application fragments, the name context carries only application-chosen components, the bind checks the credential the caller presented, and result sets stay inside the caller's scope.
- **The failing clause**: the interpolation clause. Caller text closes the enclosing clause and supplies its own operator or name component, so the directory evaluates a query the application did not write.
- **The delta**: the class fails where text and grammar share one channel, so an escaping gap at either the filter or the name boundary is enough.

## Key Vulnerabilities

### Filter-Context Injection

- **Clause break-out**: close the enclosing clause, supply a caller operator, and leave the bracket count balanced so the directory parses rather than rejects.
- **Always-true predicates**: a predicate no literal value can falsify makes the credential clause irrelevant and admits the first matching entry.
- **Clause neutralisation**: a terminator or a trailing always-true group removes the password comparison from the evaluated filter.
- **Compound logic**: the operator set composes caller logic with the application's own clauses, so a negated impossible clause is as strong as an always-true one.

### Name-Context Injection

- **Separator semantics**: in a name, the separators and the assignment character build additional name components, so the caller chooses which entry the bind resolves.
- **Wildcard loss**: the wildcard carries no meaning in a name, so a filter-context payload usually fails here; test the context first.
- **Component injection**: an injected component changes the entry the search or bind resolves, which reaches authentication bypass and directory traversal within the tree.

### Blind Attribute Extraction

- **Paired oracle**: build a known-true filter and a known-false filter on a readable attribute, and treat the response class, not the raw size, as the oracle.
- **Character walk**: extend a recovered prefix one character at a time, testing each candidate against the paired oracle.
- **Repetition discipline**: repeat each positive three times and re-check the false control between rounds, because length jitter from the probe character itself is the first false positive.
- **Target selection**: recovery tokens, group memberships, and identity attributes answer the same way as credential fields.

### Directory Enumeration

- **Prefix walk**: wildcard prefixes over identity and group attributes, judged against a control prefix that should match nothing.
- **Group targeting**: membership attributes narrow the candidate set to privileged groups for later targeting.
- **Descriptive attributes**: directory attributes that administrators misuse for notes are a frequent plaintext credential holder.

### Referral and Out-of-Band Reach

- **Caller-supplied referral**: where the directory follows a referral the caller can influence, the resolution itself becomes an out-of-band confirmation.
- **Zero-ambiguity proof**: treat a listener hit from a referral as the strongest confirmation of a blind case.

### Credential-Attribute Discipline

- **Readable credential attribute**: some directory services expose a credential attribute that a search can read, and its format decides whether offline cracking follows.
- **Write-only credential attribute**: other directory services keep the credential attribute write-only, so no search returns it; never claim a credential read from such a directory.
- **Claim rule**: name the directory family before claiming a credential read, and prefer enumeration or bypass when the credential attribute is write-only.

## Advanced Techniques

- **Oracle ladder**: prefer status, then body marker, then result count, then timing, and keep the out-of-band referral for cases where every in-band channel is masked.
- **Balancing arithmetic**: count the group brackets of the presumed full filter, not of the payload alone, because the application appends its own closing clauses.
- **Multi-round extraction**: keep the false control live across rounds so a control that starts refusing every request is detected as a filter rather than read as a match.
- **Context transfer test**: replay a confirmed filter-context payload in a name context and the reverse, because a working payload in one context proves nothing about the other.
- **Control-shape negatives**: every bypass claim carries a same-shape false control that returns the failure response.

## Bypass Techniques

- **Escaping gaps**: a value escaped for one context and interpolated into the other carries its metacharacters through untouched.
- **Encoding layers**: an encoding that survives the escape step and decodes before the directory parses the query restores the live metacharacters.
- **Operator alternatives**: substitute an equivalent predicate for a filtered operator, and compose caller logic from the operators the filter leaves reachable.
- **Nested clause placement**: place the caller clause deeper in the compound filter where the filter stage inspects only the outer level.
- **Case and spacing variants**: spelling and spacing changes that compare unequal to a blocklist yet parse identically.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Authentication to privilege**: a bypass that lands on a privileged directory entry continues into the console or single sign-on surface that entry controls.
- **Enumeration to replay**: enumerated identities feed credential replay and spray flows, and the throttle step belongs to the defence-bypass family.
- **Group mapping to targeting**: privileged group membership narrows the candidate set for targeted testing.
- **Credential attribute to offline cracking**: a readable credential attribute continues offline, outside the live surface.
- **Referral to interior reach**: a referral the directory resolves hands the fetch step to the ssrf class.
- **Attribute read to account recovery**: a recovered recovery token or identity attribute feeds the recovery flow that accepts it.

## Testing Methodology

Confirmation runs before enumeration, because a grammar verdict without a control is only noise.
1. **Inventory directory-bound inputs** - list every field whose text reaches a filter clause or a distinguished name, and the step completes when no unlisted input remains.
2. **Capture the baseline** - record a control response with a valid-looking wrong secret, and the step completes when the control carries status, size, and marker values.
3. **Discriminate the context** - decide filter context versus name context per input, and the step completes when every input carries a context verdict.
4. **Probe the metacharacter roles** - test one role per attempt, raw against escaped, and the step completes when every input carries a per-role grammar verdict.
5. **Prove predicate control** - pair an always-true predicate with an always-false one and record the response class change, and the step completes when the pair separates or a definitive negative is recorded.
6. **Confirm bypass or enumeration** - land the bypass on a real authenticated context, or enumerate identities against a control prefix, and the step completes when the finding carries a reproducible verdict rather than a syntax error.
7. **Extract or escalate** - walk attribute values character by character, or hand the enumerated identities to the follow-on flow, and the step completes when the target value or identity set is recorded.

## False Positives

- **Broken endpoint**: a syntax error on every input, including the balanced control, which signals a broken filter rather than an injection point.
- **Open endpoint**: both the true class and the false class succeeding, which signals an endpoint that fell open rather than predicate control.
- **Jitter as oracle**: a size difference that tracks the probe character rather than the predicate, which disappears under repeated samples.
- **Flat enumeration**: a count that never moves between prefixes and the control prefix, which proves the directory does not leak through wildcards.
- **Write-only credential claim**: a credential read claimed from a directory that never returns the credential attribute.
- **Unbalanced success**: a filter-syntax error read as a bypass, when only a balanced filter that executes proves control.

## Pro Tips

1. Capture the control response first; every later verdict is a comparison against it.
2. Balance the presumed full filter, not the payload alone, because the application appends its own clauses.
3. Test both interpolation contexts early; payloads never transfer between a filter and a name.
4. Prefer a result-count or body-marker oracle over raw response size, which jitters.
5. Keep a same-shape false control beside every claim, because the failure response is the proof of parsing.
6. Validate a recovered value by using it, not by its shape.
7. Keep the referral channel for blind cases; a listener hit removes the ambiguity that length inference leaves.
8. Name the directory family before claiming a credential read; a write-only credential attribute yields nothing.

## Summary

Directory injection is a grammar break at either the filter boundary or the name boundary, and the two contexts never share a payload.
Confirm the context, balance the full query, prove control against a false control, and read attribute values or enumerated identities only through a reproducible oracle.
