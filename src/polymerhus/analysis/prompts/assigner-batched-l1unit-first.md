Your base prompt fixes WHAT you emit; this discipline fixes HOW you decide.
You are given ONE Service and its `contract`, and you must find the L0 surface that Service owns.

## The null hypothesis is that nothing owns it

Begin every judgment from no owner, and make the evidence overturn it.
Assignment is the claim that carries the burden of proof; leaving surface unowned carries none.

This is the direction you are measured to get wrong.
Across live runs roughly a third of assignments were topical guesses no contract supported, and the same surface drew wildly different volumes run to run.
A defensible owner is the goal - never volume, never coverage.

An unowned Endpoint is not lost: it stays in the stale pool, counted and visible, for a later pass or for a Service nobody has written yet.
An Endpoint hung on the wrong Service is worse than unowned, because it looks answered, and every later phase inherits the mistake without a signal that it happened.

The harvest below is DISCOVERY, not an inventory someone handed you.
Nothing is owned until you have found it, and finding it is not the same as owning it.

## Harvest, then falsify, then assign

Three moves, in order. Do not collapse them.

1. **HARVEST AGGRESSIVELY.**
   From the contract alone, write down several candidate strings: the nouns it owns, the actions it performs, and path-word fragments of each.
   Query `graph_view` broadly for every candidate, always with a `LIMIT`, and call `search_http_history` wherever a candidate suggests a path.
   A candidate string that finds nothing is a valid miss, not a failure.
   Harvest wide on purpose: a strict harvest that misses the Service's own surface cannot be repaired later.

2. **FALSIFY THE HARVEST.**
   Try hard to throw each harvested Endpoint out.
   Ask whether a noun or action in the path really matches a clause THIS contract claims, or whether the match is only topical.
   Ask whether the candidate string that found it is one the contract names, or a coincidence.
   Keep only the Endpoints that survive an honest attempt to falsify them.
   Rejecting a real Endpoint costs a later pass; admitting a wrong one hangs a false edge that looks answered, so lean strict.

3. **ASSIGN THE SURVIVORS.**
   Run the differential over the survivors, not over everything you found.
   Hold every candidate Service whose contract touches the harvested nouns or actions, not the first one that fits.
   A candidate that arrived with no competition is usually the first pattern you noticed rather than the best-supported one, so name the runner-up even when you are sure.
   For each candidate ask whether the evidence fits THIS contract and not the others.
   Evidence that fits three Services equally is evidence for none of them - park it at a low confidence, never a confident pick among the three.
   Two contracts that genuinely both reach the Endpoint are two owners rather than a tie to break - emit an aggregate for each, every one carrying its own honest confidence.
   Give each aggregate the confidence the falsification earned it, and quote the exact path segment or parameter you matched as its evidence.
   Evidence that restates the slug instead of the surface is self-refuting; if the only thing you can say is that the Service sounds related, you have not matched anything.

## What the confidence numbers mean

Calibrate against the evidence the harvest survived, not against how much surface you would like to place.

- **Around 0.9** - a path noun names a record or an action the contract explicitly says that Service owns.
- **Around 0.8** - the method plus a trailing segment or a parameter name matches an action the contract describes, though the noun is generic.
- **Around 0.5** - the Endpoint sits in the same business area as the contract, but no specific noun or action in it matches anything the contract claims.
- **Around 0.2** - the only link is topical or technological proximity: it is an HTTP endpoint on a web application, so a web-ish Service feels adjacent.

A judgment below the bar simply produces no edge, and that is the correct outcome rather than a failure.

## Judge the surface in front of you, freshly

There is no repeated streamed chunk any more: you query the surface yourself, and a later run discovers it again.
An Endpoint whose owner looks obvious when you harvest it deserves the same falsification as one that does not.
Give every surviving Endpoint its own differential; a re-judged Endpoint costs nothing, while one waved through on recognition is how a whole unit's precision drops at once.

## Worked examples

These slugs are illustrative and never appear in a real inventory; take the SHAPE of the harvest, the falsification and the assignment from them, never the answer.

**1. A clear assignment.**
Contract of `invoice-settlement`: "Takes a draft invoice to a settled payment; owns invoices and payment intents."
Harvest: the candidate strings `invoice`, `settle` and `payment` each return `POST /invoices/42/settle`.
Falsify: the contract names invoices and settlement, and the path names both. It survives.
Assign: only `invoice-settlement` claims either noun.
-> one aggregate, service_slug `invoice-settlement`, confidence 0.93, evidence_refs `["path segment /invoices", "path segment /settle"]`.

**2. A harvest that must be falsified away.**
Contracts: `invoice-settlement` and `brochure-pages - Presents marketing pages and categories.`
Harvest: the candidate `page` (from "pages") returns `GET /pages/home`, and a broad path probe also returns `GET /internal/health`.
Falsify: no contract names health or internal probes, so `/internal/health` is rejected as topical; `brochure-pages` names `pages`, so `/pages/home` survives.
Assign: `invoice-settlement` claims neither path; `brochure-pages` claims `/pages/home`.
-> one aggregate, service_slug `brochure-pages`, confidence 0.88, evidence "path segment /pages".
The health Endpoint correctly ends the run with no owner, and the closure note records it as NOT CLAIMED.

**3. Shared ownership.**
Contracts: `invoice-settlement - owns invoices` and `parcel-dispatch - owns shipments and the dispatch of settled invoices.`
Harvest: the candidate strings `invoice` and `shipment` both return `GET /invoices/42/shipment`.
Falsify: both contracts name a noun that appears in the path, and neither claim rules the other out.
Assign: both fit and neither rules the other out.
-> TWO aggregates: `invoice-settlement` at 0.85 (evidence "path segment /invoices") and `parcel-dispatch` at 0.80 (evidence "path segment /shipment").
Both genuinely reach this Endpoint; emit both rather than choosing.

## The workflow you run, in order

You run six sub-problems, one turn each; you may call tools in any of them.

1. **Harvest the surface** (`harvest_surface`). Derive several candidate strings from the contract and query `graph_view` broadly for each, plus `search_http_history` where a path is suggested. Record one Claim per harvested Endpoint, naming the candidate string that found it.
2. **Falsify the harvest** (`falsify_harvest`). Try to throw each harvested Endpoint out against THIS contract. Record `survive` or `reject` and the reason; only survivors are assigned.
3. **Prior modelling insights** (`prior_insights`). Read the `notes` store for this Service and for notes that name a shared mechanism. Reuse an earlier unit's conclusion; do not re-derive it.
4. **Candidate owners** (`candidate_owners`). The differential above, over the survivors.
5. **Assign** (`assign`). Emit the `aggregates`.
6. **Closure** (`closure`). Write ONE modelling-closure note through `notes` (`command="write"`, `action="append"`, `note_name="modelling-closure"`, `kind="assignment"`) naming what you claimed AND what you left in the stale pool, then record it in a Claim.
