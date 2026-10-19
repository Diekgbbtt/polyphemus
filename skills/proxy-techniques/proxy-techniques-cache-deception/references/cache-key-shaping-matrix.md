# Cache Key Shaping Matrix

This note holds the key-shaping shapes for the shared-cache procedure: what the cache sees, what the origin serves, and the completion bar for each shape.

## Key-Shaping Shapes

| Shape | What the cache sees | What the origin serves | Completion bar |
|---|---|---|---|
| Unkeyed selector | A request whose key omits the selector | A body shaped by the selector | The stored entry carries the selector's effect |
| Normalisation collapse | One key for two spellings | The entry of whichever spelling stored first | The second spelling reading the first spelling's entry |
| Eligibility suffix | A static-looking address tail | A dynamic response for the base resource | The dynamic response stored under the tail's key |
| Extension allowlist gap | An extension outside the eligibility list | A dynamic or authenticated response | The response stored although the eligibility list omitted the extension |
| Forced-miss field | A field the key treats as a distinct input | A freshly fetched response under the shaped key | The shaped response fetched and stored rather than served from an entry |
| Delimiter discrepancy | A key split at one delimiter | A path the origin reads whole, or the reverse | The cache and the origin disagreeing about the resource the key names |
| Error or verdict class | A failure produced from attacker input | A failure stored under a healthy request's key | A later caller reaching a failed response for a working operation |
| Identity omission | A key with no identity binding | A response produced for the requesting identity | A second caller or session reading the entry |

## Key Reading

Identify the shared cache on the path and the fields that decide whether a response is stored, because eligibility and key identity are separate rules.
Enumerate the selectors that shape the body and record which of them the key covers, because the gap is an omission in the key rather than a malformed request.
Treat the key's own coverage declaration as the control to defeat: a key that omits a selector the response varies with is the whole mechanism.
Vary one selector per attempt and re-read the entry each time, so the omission is nameable.

## Eligibility and Reach

Use suffixes and address tails where storage eligibility keys off the address alone, because a static-looking tail can change eligibility without changing the resource.
Where the key's rule matches the address exactly, add a field the key treats as a distinct input to force a miss, so the shaped response is fetched and stored rather than served from an existing entry.
Record the entry's lifetime and age fields, because the storage window bounds the reach and is the report's exposure evidence.
Treat an entry reachable only by the producing caller as a private entry rather than a reach.

## Proof

Baseline a request the cache does not store, so a later stored entry is attributable to the key rather than to an absent cache.
Read the entry back as a second caller or in a second session, because the producing caller's own read proves nothing about the key.
Pair the producing request with the second caller's read, so the omitted selector or binding is named from the pair.
A response that looks stored but is regenerated per request is a recorded negative, confirmed by a changing body.
