# Tier Route Inventory

This note holds the sibling-route and version inventory behind the version-consistency check: the route families that reach one operation, the chain each carries, and the behavioural regression the pair is read for.
It belongs to the proxy family because an older version, an alternate host family, or a legacy alias is a second carrier that reaches the same operation.

## The Route Families

| Route family | Why it exists | Chain it often carries | What the pair is read for |
|---|---|---|---|
| Current versioned route | The enforced path to the operation | The current chain | The reference verdict |
| Older version of the same operation | Kept for older clients | The chain as wired when that version shipped | A weaker or missing authentication requirement, validation, or accounting |
| Deprecated or legacy path alias | Kept for redirects or compatibility | Often no current chain | The operation reachable with no rule at all |
| Alternate host family | A device, mobile, or regional host | A separate enforcement wiring | Rules that cover one host family only |
| Internal-shaped or debug-shaped sibling path | A management or diagnostic route | A trusted-network assumption | The route reachable from outside the trusted network |
| Sibling verb on one route | A handler that answers more than one verb | A verb-scoped rule | The same handler answering an unenforced verb |
| Path spelling the rule does not match | Router normalisation | The current chain, addressed differently | The protected path reached through an unmatched spelling |
| Direct core entry | A route the front tier hides | No front-tier verdict | The operation answered without the front tier's decision |

## The Version Consistency Check

Pair the older and the current version of one operation with one identical input, and record both verdicts.
Diff the behavioural properties rather than the text: the authentication requirement, the validation applied, the accounting observed, and the permit enforced.
A behavioural difference between two versions of one operation is the finding, because the current control set was assumed to apply to every reachable version.
The finding is a regression rather than a disclosure, so state the property that changed and the version pair that carries it.

## Discovery

A specification or documentation surface that lists an older version names the route family before any fuzzing.
A client bundle or a mobile build that names an older route, an alternate host, or a legacy alias is the same inventory from the client side.
A route table, an error message, or a redirect that names a version is the inventory from the server side.
Enumerate the host families beside the path families, because the enforcement wiring often diverges by host rather than by version.

## Proof and Consumption

Record the paired verdicts: the refused current route beside the accepted older route, or the enforced current property beside the weaker older one.
A sibling route that refuses the same input across the inventory is a recorded negative rather than a dead end.
Name the class that owns the effect at its own step, because the version gap is the carrier and the class owns the consequence.
The route inventory itself is reconnaissance evidence for the class, not a finding on its own.
