# Identifier Harvesting

Identifiers are harvested, never guessed: the corpus precedes the swap, and the corpus decides whether a finding is reproducible.
This reference holds the harvest sources, the extraction shapes, the corpus discipline, and the adjudication gate a claim passes before it is filed.
The harvest completes when each principal owns at least one recorded identifier per object type, each with its source surface.

## Harvest Sources

- **List, search, and suggestion surfaces**: the richest seeders, because they return identifiers the caller is entitled to name and sometimes identifiers it is not.
- **Export, import, and report surfaces**: bulk paths that emit whole identifier sets, including archived and scheduled outputs.
- **Notification, message, comment, and activity feeds**: cross-principal surfaces that name objects of other principals.
- **Client bundles, source maps, and lazily loaded chunks**: static material that carries route shapes, field names, and literal identifiers.
- **Serialized page state and static data payloads**: embedded values the initial load never renders.
- **Response metadata and headers**: location, content-disposition, and validator fields that carry an identifier for the object just fetched.
- **Public and analytics surfaces**: activity, share, and tracking endpoints that expose object identifiers without an actor.
- **Logs, exports, and prior history**: identifiers already observed in an earlier engagement phase.
- **Time-derived identifiers**: values guessable within a window, which enter the corpus as candidates rather than as facts.

## Extraction Shapes

- Scrape opaque identifier literals from bundles and static payloads, then de-duplicate before use.
- Grep response bodies for reference-like keys, including nested and related-object fields.
- Follow pagination and cursor handles, because a continuation handle frequently encodes a scope the caller cannot name directly.
- Read embedded related objects in an unrelated response, because a shared representation carries identifiers of objects the caller never requested.
- Collect from the control surface first, so the corpus holds what the application itself returns rather than what a fuzzer produced.

## Corpus Discipline

- One valid identifier per principal per type, recorded with the surface it came from.
- Treat opaque identifiers as untrusted but collectable, because opacity is never a binding.
- Keep the owner's control response beside every foreign attempt.
- Seed the corpus before the swap, so no attempt rests on a guessed value.
- Chain deliberately: an identifier leaked by one surface fuels a second, distinct access, and the two verdicts stay separate rather than merging into one claim.

## The Adjudication Gate

A swap candidate becomes a finding only when all three answers hold.

- **Capability**: what the attacker can do right now, stated as the exact request and the response evidence, not as a class name.
- **Loss**: what the victim loses, mapped to the confidentiality, integrity, or availability of a named object.
- **Reproducibility**: two fresh accounts, the exact request with the victim's identifier, and the recorded response or state change, reproducible from a clean state in minutes.

A candidate that fails any answer is a lead rather than a finding.

## Delegation

- The swap procedure and the reference-form probe table are in this bundle's matrix reference.
- The stored-reference case, where the foreign reference is planted and resolved later, is owned by `idor-second-order-stored-reference`.
- The principal handling behind the corpus and the control pair is owned by `two-principal-authz`.
- The artifact surfaces that carry identifiers are named at the step owned by `stored-artifact-disclosure`.
- The counter or token behind a time-derived identifier is owned by the `crypto-weakness` class.

## False Positives

- An identifier that is public by design, such as a published catalogue entry.
- A guessed identifier that returns a valid object belonging to the caller.
- A continuation handle that resolves only within the caller's own scope.
- An identifier harvested from a surface that already discloses the whole object, so the swap adds no new access.
