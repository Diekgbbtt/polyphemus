---
name: sql-injection
description: SQL injection testing covering union, blind, error-based, and ORM bypass techniques
metadata:
  version: 1.0.0
---

# SQL Injection

SQL injection remains one of the most durable and impactful vulnerability classes. Modern exploitation focuses on parser differentials, query-builder edges, document and expression surfaces, out-of-band exfiltration, and subtle blind channels. Treat every concatenation of input into a statement as suspect.

## Attack Surface

**Statement Slots**
- String literals, numeric positions, and identifier slots such as table and column names
- Filter fragments, sort clauses, grouping clauses, and paging clauses
- Batch and bulk endpoints and report generators that embed filters directly

**Integration Paths**
- Query builders, object mappers, and stored procedures
- Search servers, reporting engines, and exporters

**Input Locations**
- Path, query, body, header, and cookie
- Mixed encodings: URL, structured body, document formats, multipart
- Document and array operators exposed through the query layer
- Second-order inputs: stored values that a later query interpolates

## Reconnaissance

### Query-Shape Inference

- Identify the operation shape (read, insert, update, delete) and which clauses are present
- Determine whether input lands in an identifier position or a value position; the escape rules differ
- Note ordering, arity, and paging behavior that reveal the underlying statement before any payload is sent
- Treat authenticated-only surfaces as first-class targets: internal tooling often runs an over-privileged account, and edge controls frequently whitelist authenticated traffic

### Error Fingerprinting

- Send malformed values and read the failure text for parser, type, and constraint detail
- Compare a benign probe with a shaped probe to separate inquiry errors from statement errors
- Record the stable baseline error shape per endpoint so a differential is attributable

### Channel Calibration

- Establish a paired true-and-false differential on the tamest predicate available
- Normalize the response (length, digest, entity tag, presence headers) so templating noise does not mask the signal
- Measure a latency baseline before any gated delay is attempted

## Detection Channels

- Error text carrying type, constraint, or parser detail from a crafted probe.
- Error-text change between a benign probe and a shaped probe, which separates shaping success from failure.
- Paired differential across status, body, length, and presence headers between a true predicate and its false pair.
- Stable per-pair verdict and normalized digest that separate a reachable truth signal from templating noise and random variance.
- Response-time delay over a calibrated baseline, confirmed by repeated samples.
- Delay-baseline record that separates database-induced latency from network and CPU noise.
- Rendered appended rows carrying data from outside the intended query.
- Row-count change between arity probes, which separates wrong column counts from the correct one.
- Coercion error text that separates a misaligned type attempt from an aligned one during alignment.
- Stable metadata echo confirming version, current user, and database name through the established channel.
- Callback receipt at an operated listener carrying an embedded label from the database.
- Per-probe token correlation binding one inbound hit to exactly one outbound request.
- Ordered-output shaping where sort and paging contexts carry the predicate into visible row order.
- Fallback signals where one channel answers in place of another: a rendered row where filtering removes shaping, a content differential where timing stays hidden, and a differential where egress filtering removes callbacks.

## Adversarial Capabilities

SQL injection testing presupposes a query-reaching input, a controllable predicate or payload slot, and a readback channel, and it consumes all three.
- Reach a parameter that flows into a statement, including identifier slots, filter fragments, and sort and paging clauses.
- Infer the statement shape from ordering, arity, and error behavior before payload assembly.
- Read paired true-and-false responses as a boolean oracle, with a normalized digest to remove templating noise.
- Operate a listener for out-of-band egress and mint a unique token per probe.
- Measure latency against a calibrated baseline when no content channel answers.
- Hold a privileged target or an authentication boundary so a bypass converts into data or access.

## Trust Assumptions

The class rests on one agreement: user input reaches the database as a bound value, never as statement text or an identifier.
The agreement holds values to parameter binding, holds identifiers and operators to an application-chosen set, holds the statement grammar to the application's own fragments, and holds database egress to destinations the application intended.
Data and control leak when any clause fails: a quote escapes a literal, a fragment widens the predicate, an identifier is interpolated, or the database reaches an attacker-chosen destination.
Each variant breaks one clause on a different channel: rendering, shaping, truth-differencing, timing, or egress.

## Key Vulnerabilities

### Union-Based Extraction

- Determine column count and types by arity probing, then align types so the appended result renders
- When the union path is filtered, switch to shaping, differential, timing, or egress channels

### Error-Based Extraction

- Failure text shaped by type, constraint, or parser errors carries internals: version, user, database name, and path detail
- Error shaping needs proving first: compare a benign probe with a shaped probe until the differential is stable
- Where shaping is filtered, a rendered row or a union fallback still answers

### Boolean-Blind Extraction

- Branch on single-bit predicates with substring and comparison functions, then extract bit by bit
- Binary search over the character space reduces requests
- Normalize responses and keep a stable per-pair verdict, or templating noise will drown the signal
- Sort and paging contexts carry the predicate into visible order, which is a second differential surface

### Time-Blind Extraction

- Gate delays inside a conditional expression and confirm against a calibrated baseline
- Use short gated delays to reduce noise; a stable repeated-sample verdict separates signal from jitter
- Where a content differential also answers, prefer it over the timing channel

### Out-of-Band Extraction

- Prefer egress channels to bypass strict response paths and minimize noise
- Embed data in name-resolution labels or fetch parameters, and mint a unique token per probe to bind each hit to one request
- Where egress is filtered, fall back to a differential channel

### Database Primitive Families

- Metadata reads: version, current user, and database name through the established channel
- Error shaping: functions and expressions that turn internals into response text
- File reads and writes at the filesystem boundary, where the account holds the privilege and the policy allows it
- Egress primitives through name resolution, fetch-capable extensions, and job interfaces
- Timing primitives gated by the predicate
- Document and operator expressions, including containment and path operators with derived-table and common-table-expression smuggling

### Write and Control Primitives

- Authentication bypass: inject an always-true predicate or a subselect into a login check
- Privilege changes: update role, plan, or feature state where the update path is injectable
- File write and job creation where the account permissions allow, which converts data access into execution

### Query Builders and Object Mappers

- Dangerous fragments: raw filter and sort helpers, and string interpolation into filter, membership, and ordering clauses
- Identifier interpolation: table and column names taken from user input
- Builder-carried identifiers: structured keys used as column aliases, and mapper filters forwarded into expression-shaped operators, reach interpolation through the builder rather than through a value position
- Document operator passthrough: containment and array operators exposed by the mapper with raw fragments
- Parameter mismatch: partial binding where operators or lists remain interpolated

### Uncommon Contexts

- Sort, group, and having contexts with conditional expressions for boolean channels
- Paging clauses: inject into the offset to produce measurable timing or page-shape differences
- Full-text and search helpers with mixed payload shapes
- Document and path functions that generate errors from malformed input

## Advanced Techniques

**Channel Selection and Fallback**
- Pick the quietest reliable channel first and hold the loud ones in reserve: shaping, then differential, then timing, then egress
- When a filter removes one channel, the same predicate answers on another; keep the predicate constant across attempts

**Query-Shape Smuggling**
- Use subselects, derived tables, and common table expressions to hide payload shape where filters block direct clause placement
- Relocate the injection into a nested scope the filter does not cover

**Metadata-First Extraction**
- Establish version, user, and database name first: they decide which primitive family is available
- Jump from metadata to the business-critical tables, and keep lateral noise low

## Bypass Techniques

**Whitespace and Spacing**
- Comment forms as separators, newlines and tabs, and alternate whitespace characters

**Keyword Splitting**
- Inline comments inside keywords, encoded characters, case folding, and quoting variants

**Numeric and Encoding Tricks**
- Scientific notation, signed and unsigned forms, and hexadecimal literals
- Double URL encoding and mixed Unicode normalization

**Clause Relocation**
- Subselects, derived tables, and common table expressions to place the payload outside the filtered fragment

**Filter-Aware Substitution**
- Substitute an equivalent operator or function when the obvious one is filtered
- Expression contexts carry comparisons that the top-level filter rejects

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- SQL injection to authentication bypass, then a second request to a privileged surface
- SQL injection to file write, then retrieval from the served directory
- SQL injection to a job or process primitive where the database account holds it, which reaches execution
- SQL injection to egress primitives, which doubles as internal network reach
- SQL injection to credential and token stores for movement to other systems

## Testing Methodology

1. **Identify the query shape** - Operation type, presence of filter, sort, group, and paging clauses
2. **Determine input influence** - User input in identifiers versus values
3. **Confirm the injection class** - Shaped errors, paired differentials, timing, or egress callbacks
4. **Choose the quietest channel** - Prefer shaping or paired differentials over noisy gated delays
5. **Establish the extraction channel** - Rendered rows if visible, then shaping, bit extraction, timing, or egress
6. **Pivot to metadata** - Version, current user, and database name
7. **Target high-value tables** - Authentication bypass, privilege changes, and filesystem access where feasible
8. **Confirm the effect** - Hold the predicate constant across channels and keep the request set minimal and repeatable

## Variants

- sqli-union-extraction - Append result sets to visible responses, proving column count and type alignment first.
- sqli-error-based-extraction - Read database internals from shaped failure text, including type, constraint, and parser detail.
- sqli-boolean-blind-extraction - Diff paired true and false responses bit by bit when no rows render and no error shows.
- sqli-time-blind-extraction - Measure predicate-driven delays bit by bit when only response latency varies.
- sqli-oast-exfiltration - Correlate database callbacks with per-probe labels when in-band channels stay silent.
- sqli-second-order-injection - Plant a shaped value through a bound or escaped write, then trigger the operation that interpolates the stored text into a statement, including cross-context execution.

## False Positives

- Generic errors unrelated to statement parsing or constraints
- Static response sizes driven by templating rather than predicate truth
- Artificial delays from network or CPU unrelated to the injected expression
- Parameterized statements with no string concatenation, verified by code review
- Paired differentials that vanish once responses are normalized
- Egress hits whose source or timing cannot be bound to the injected primitive

## Pro Tips

1. Pick the quietest reliable channel first; avoid noisy long delays
2. Normalize responses (length, digest, entity tag) to reduce variance when differencing
3. Aim for metadata first, then move directly to business-critical tables
4. When the union path fails, switch to shaping or bit extraction; prefer egress where available
5. Treat query builders as thin wrappers: raw fragments slip through, so audit the raw helpers
6. Use subselects and common table expressions to smuggle expressions when filters block direct placement
7. Exploit document and array operators for side channels where the query layer exposes them
8. Keep payloads portable; maintain per-engine dictionaries of functions and types
9. Document the exact statement shape; defences must match how the statement is constructed

## Summary

SQL injection succeeds where authorization and statement construction drift from assumptions. Bind parameters everywhere, avoid dynamic identifiers, and validate at the exact boundary where user input meets the statement.
