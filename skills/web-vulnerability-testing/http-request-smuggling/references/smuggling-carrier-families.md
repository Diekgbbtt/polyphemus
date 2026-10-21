# Smuggling Carrier Families

This note details the carriers a smuggled prefix can ride, which the parent body summarises as topologies.
Each family names its prerequisite, what carries the prefix, and the step that owns the craft.
Version and product suitability tables are runtime knowledge-base facts and never enter a body or this note.

## Carrier families

| Family | Prerequisite | What carries the prefix | Owning step |
|---|---|---|---|
| Raw socket framing | The edge and the origin disagree on the length-versus-encoding pair | Leftover bytes on a persistent origin socket | The parent declaration pair |
| Downgrade mapping | The edge speaks the newer protocol to the client and re-emits the older one to the origin | A framing field injected in the header block that the translation hop maps onto the re-emitted request | `http-request-smuggling-h2-desync` |
| Upgrade and tunnel | The edge validates a framing declaration and the origin re-reads it on an upgraded channel | Bytes riding a connection the edge believes it upgraded | The parent upgrade-based shapes |
| Connection reuse | The edge pools origin sockets across clients | A prefix that survives on a pooled socket and re-shapes every later request on it | The parent reuse-amplification step |
| Cache-eligible response chain | The smuggled prefix lands on a cacheable endpoint | A stored entry produced for the next requester | `header-cache-poisoning`, with the cache mechanics named at the `proxy-techniques` family |
| Binary translation hop | The hop re-encodes the request into a binary protocol of the origin's own design | A request embedded inside the frame's attribute encoding, opaque to the edge controls | `http-request-smuggling-cross-protocol-desync` |

## Capture shapes

A poisoned socket prepends a partial request whose declared length exceeds the sent body, so the origin consumes bytes from the next request.
Aim the prefix at a handler that echoes the whole request, so the next caller's headers and body return in a readable response attributed to the smuggled request.
The collector-gadget shape harvests at scale instead of one request at a time, and it needs a request-echoing handler rather than a blind queue.
Proof lives in the arrival of the marker token in a response to a request that never carried it.

## Discipline

Select the carrier family before the probe, because each family needs a different client capability: raw socket framing needs byte-level control, the downgrade family needs header-block construction, and the translation family needs the binary frame's attribute encoding.
Keep the smuggled prefix short while the carrier is being confirmed, then lengthen only for a capture attempt.
Reach the edge directly, and the origin where a direct path exists, so the two framing views can be compared.
A timing delta alone is parser disagreement; the finding needs the effect to land on a request issued by a different client or session.
