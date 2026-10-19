---
name: sqli-second-order-injection
description: Second-order SQL injection through a stored value that a later operation interpolates into a statement. Use when writes bind or escape while reads re-interpolate stored text; when a plant stays inert at the door and fires at a later operation or in another identity's context.
metadata:
  version: 1.0.0
---

# Second-Order SQL Injection

Second-order injection separates the write from the execution: a shaped value enters through a bound or escaped write and stays inert, then a later operation re-interpolates the stored text into a statement and executes it.
The load-bearing move is the storage-to-trigger pairing, because the plant answers no first-order oracle at the door and only the trigger operation carries the effect.
Treat every stored value that a read path reuses as statement text until the trigger proves otherwise.

## Attack Surface

- **Applicability**: centers on a write that persists caller text beside a later operation that interpolates that stored text into a statement.
- **Inert at the write**: the storage path binds or escapes the value, so the shaped text survives as data and executes only at the trigger.
- **Stored carriers**: profile fields, registration fields, display names, handles, addresses, labels, stored preferences, review bodies, and uploaded metadata that persists.
- **Trigger consumers**: listings, exports, reports, notifications, identifier lookups, and credential plus address change flows that resolve a stored value into a statement.
- **Cross-context shape**: the trigger often runs under a different and more privileged identity than the one that stored the value.
- **Out of scope**: a value that is only re-displayed without reaching a statement stays in the first-order variants, because no interpolation occurs.

## Reconnaissance

### Storage-Point Inventory

- **Persistent writes**: list every write that stores caller text, per field, and record whether the path binds or escapes the value.
- **Round-trip check**: write a benign marker and read the field back, because a value that does not survive storage cannot reach a later statement.
- **Survivability record**: note truncation, case folding, and normalisation rules that shape what the trigger will later interpolate.

### Trigger-Point Inventory

- **Read inventory**: list every read that reuses stored text inside a statement, including listings, exports, reports, notifications, and identifier resolution.
- **Binding verdict**: mark each read as interpolating or binding, because only an interpolating read is a trigger candidate.
- **Deferred operations**: note scheduled jobs, asynchronous exports, and queued flows, because their effect never appears in the storing session.

### Pairing and Marker Tracing

- **Pair mapping**: map each storage point to its candidate trigger operations, and record a trigger for every persisted field or a recorded absence.
- **Marker sweep**: plant one unique marker per storage point, then sweep the trigger inventory and search responses plus error text for the marker.
- **Attribution**: keep one marker per pair so a deferred effect names exactly one storage-to-trigger pair.

## Detection Channels

- A statement error at the trigger that quotes the stored value or names a clause the write never contained.
- A differential at the trigger between two stored values that differ in one fragment only.
- An effect that appears only after the plant and correlates with the trigger operation rather than with the write.
- A callback receipt at a later operation carrying data only the stored value could have produced.
- A state change on the record the trigger acts on, where the stored value redirected the statement's target.
- An identity delta where one principal's stored value changes another principal's outcome.

## Adversarial Capabilities

Second-order work presupposes a persistent write plus a reachable trigger, and it consumes both.
- **Persistent write**: hold the ability to store caller text in at least one field the application later reuses.
- **Trigger reach**: invoke the operation that interpolates the stored text, from the same or from another identity.
- **Tracking across operations**: keep the plant and the trigger attributable through one marker per pair.
- **Effect observation**: read the trigger's response, error text, or deferred effect as the oracle.
- **Second principal**: hold a privileged or peer identity where the trigger runs in a context the storer does not control.

## Trust Assumptions

- **The agreement**: text that passed validation at the write boundary is safe to interpolate when read back, because the storage layer is trusted and the value was already checked.
- **Held clauses**: stored text stays a validated literal, the read path applies the same binding as the write path, the stored value keeps the shape the write accepted, and the trigger statement carries only application-composed fragments.
- **The failing clause**: the stored-data clause. The check applied at the write is not applied where the value is interpolated, so text the write accepted as data becomes statement text at the trigger.
- **The delta**: the parent holds every input to a bound value at the door; this variant holds a stored value to the binding at the read, which the write's own success cannot prove.

## Key Vulnerabilities

### Storage-to-Trigger Pairing

- **Plant then trigger**: store a shaped value through an ordinary write, then invoke the operation that interpolates it, because the value is inert until the trigger statement executes it.
- **Pair as one unit**: a stored value without a trigger proves nothing, and a trigger without a stored value carries no payload.
- **Completion criterion**: the pair is confirmed only when the trigger shows an effect the marker baseline did not.

### Storage-Point Shapes

- **Reused free text**: fields that persist free text and are later reused as an identifier, a filter fragment, or a clause, including names, handles, addresses, labels, and stored preferences.
- **Resolved identifiers**: a stored identifier looked up during a credential or address change, and a stored preference read by a report or export builder.
- **Metadata carriers**: uploaded file metadata and imported records that persist text a later job reuses.

### Trigger Consumers

- **Iterating readers**: listings, exports, and report builders that iterate stored values inside one statement.
- **Resolving flows**: notification, credential-change, and account flows that resolve a stored value into an update.
- **Administrative reads**: views that render stored values through a second query path with weaker binding than the write path.

### Cross-Context Execution

- **Stored by one, executed by another**: a value stored by one identity and interpolated in another identity's operation reaches data and privilege the storer never held.
- **Trigger privilege decides reach**: an administrative trigger executes the stored statement with administrative privilege.
- **Attribution rule**: confirm the reach through the stored value rather than through the trigger identity's own permissions.

### Deferred Window

- **Unpredictable timing**: the trigger may fire long after the plant, so the two operations are not adjacent in the request log.
- **Persistent payload**: the stored value survives the window and re-executes on each later trigger.
- **Window discipline**: correlate the effect with the plant through the marker rather than through elapsed time.

## Advanced Techniques

- **Blind second-order**: the write answers no oracle, so build the differential at the trigger, where the parent channel families apply unchanged.
- **Channel reuse at the trigger**: error, rendered rows, boolean, timing, and egress all answer at the trigger statement; keep the predicate constant across attempts.
- **Plant breadth**: plant one distinguishing token per storage point, then sweep the trigger inventory so each effect attributes to one pair.
- **Cross-principal mapping**: store under a low-privilege identity and trigger under a privileged one, which separates the interpolation gap from an authorization gap.

## Bypass Techniques

- **Write-boundary validation**: escaping applied at the write is defeated at the trigger when the read path re-interpolates the stored text into a different statement shape, such as an identifier position or a dynamic clause.
- **Boundary drift**: a check applied at one boundary only; the trigger context usually carries less filtering than the front door.
- **Encoding between the boundaries**: a layer that decodes between the write and the trigger restores the shaped text after the write-time filter.
- **Stored-form shaping**: length, truncation, and normalisation rules at the write decide which fragments survive; shape the plant to survive them.
- **Defeat scope**: the bypass belongs to the trigger context, so record the filter chain of the trigger rather than of the write.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Ownership and credential change**: a stored value that reaches an update or delete changes ownership or credentials, which continues into authorization and account testing.
- **Privileged read**: a stored value that reaches a privileged read returns data the storer could not request directly.
- **File and job primitives**: where the trigger's account holds them, the stored statement reaches write and execution.
- **Interior position**: a trigger that reaches egress primitives doubles as internal network reach.
- **Authorization hand-off**: where the trigger identity's own context is the weakness rather than the statement, hand the step to the two-principal-authz methodology.

## Testing Methodology

Pairing runs before shaping, because a payload without a trigger proves nothing.
1. **Inventory storage points** - list every write that persists caller text with its field and its binding behaviour, and the step completes when no unlisted persistent write remains.
2. **Inventory trigger points** - list every read that reuses stored text inside a statement, and the step completes when each read carries an interpolates-or-binds verdict.
3. **Pair the points** - map each storage point to its candidate trigger operations, and the step completes when every persisted field names a candidate trigger or a recorded absence.
4. **Plant a marker** - write a benign unique marker through each candidate storage point and confirm it reaches a statement at the trigger, and the step completes when every pair carries a reaches-a-statement or inert verdict.
5. **Trigger a shaped value** - store the shaped value, invoke the trigger, and compare against the marker baseline, and the step completes when the trigger shows a statement effect or a recorded negative.
6. **Confirm cross-context reach** - repeat the pair under a second principal where a privileged trigger exists, and the step completes when the effect attributes to the stored value rather than to the identity.
7. **Extract through the trigger** - apply the parent channel ladder at the trigger statement, and the step completes when the target values are read or a definitive negative is recorded.

## False Positives

- **Display only**: a stored value that is re-displayed and never reaches a statement, confirmed by the absence of a statement error and of a query-shaped differential.
- **Bound reads**: a read path that binds the stored value, verified by code review or by a stored quote that changes nothing.
- **Rendering differential**: a trigger difference caused by formatting or normalisation of the stored text rather than by statement parsing.
- **Non-round-trip values**: text transformed, truncated, or stripped at the write, so the shaped fragment never survives to the trigger.
- **Foreign error source**: an error that quotes the stored value from an unrelated validation layer rather than from the statement parser.
- **Unreproducible effect**: a single deferred effect with no reproducible pair, which is noise rather than a second-order finding.

## Pro Tips

1. Map the pair before shaping anything, because the write and the trigger are two halves of one finding.
2. Plant one unique marker per storage point so a deferred effect attributes to exactly one pair.
3. Test the trigger under a second principal; cross-context execution is the strongest form of this variant.
4. Expect less filtering at the trigger, because the read path trusts the store.
5. Keep the plant minimal so the write's own validation accepts it.
6. Record both halves in the finding, because the remediation has a write side and a read side.
7. Re-run the trigger inventory after each deployment; a new report or export adds a new trigger.

## Summary

Second-order injection turns a stored value into statement text at a later operation, which no single-request procedure can describe.
Pair each storage point with its trigger, confirm the interpolation with a marker, and prove the reach at the trigger rather than at the door.
