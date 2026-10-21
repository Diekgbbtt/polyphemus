# Permit Enumeration Matrix

This note holds the route inventory across permit kinds: what each permit enumerates, the omitted-route family that reaches the withheld capability, and the completion bar for each.

## Permit Kinds

| Permit kind | Unit it enumerates | Omitted-route family | Completion bar |
|---|---|---|---|
| Directive or source list | Origins, constructs, and inline allowances | An allowed origin that serves a callback or gadget, an allowed construct that combines into the withheld effect | The withheld effect occurs inside the permit's own confinement |
| Origin list | Origins whose scripts may read a response | A reflected origin, a null-origin value, a pattern that matches a look-alike, a trusted host the attacker can occupy | The cross-origin read returns the credentialed body |
| Path list | Paths that carry the protected rule | A path spelling the rule does not match while the router still resolves it | The protected effect occurs through the unlisted spelling |
| Method list | Verbs the rule covers | A sibling verb that reaches the same handler | The same handler answers the unlisted verb |
| Token check | A value's presence, shape, or binding | A request with the member absent, a permissively formatted value, a value bound to nothing | The operation completes without a value the check could validate |
| Sanitiser list | Elements, attributes, and namespaces | A combination of individually allowed entries, a context or namespace switch the model misses | The withheld effect is reached through the allowed set |
| Confinement claim | Primitives the restriction removes | A substitute primitive, wrapper, or delegate with the same reach | The substitute reaches the withheld capability |
| Delegate or converter policy | Delegates and converters that may run | An unlisted delegate that reaches the same operation | The operation occurs through the unlisted delegate |

## Reading the Permit

Read the permit's own text first: which units it lists, which it omits, and which of its entries are broader than the author intended.
Record the capability the permit withholds and enumerate every route to it that the list does not name, because the gap is the omission rather than a malformed request.
Probe the enforcement boundary separately from the declaration, because a claim of restriction is not evidence of restriction.
Baseline a route the permit plainly forbids, so a later pass is attributable to the omission rather than to an absent control.

## Pattern-Level Routes

Where the permit is a list of origins or paths, test the pattern rather than its intent: a missing separator, a missing end anchor, an unescaped separator, and a prefix-only match each admit a value the author did not mean to list.
A permit that validates only when its member is present, or that matches a prefix of the value rather than the whole value, is the same enumeration gap at the token kind.
Where the permit's own text is attacker-influenced, a reflected value can add an entry the author never wrote, which admits a route outside the enumeration entirely.

## Completion

Prefer the route the permit itself admits, because it needs no second bypass behind it.
Confirm at the sink, because a permitted request is not the effect.
Pair the refused forbidden route with the permitted unlisted route, so the omitted route is named from the pair.
