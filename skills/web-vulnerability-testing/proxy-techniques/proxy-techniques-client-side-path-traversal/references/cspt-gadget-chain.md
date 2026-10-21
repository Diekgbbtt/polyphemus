# Client-Side Path Traversal Gadget Chain

This note holds the worked chain behind the client-request-construction procedure: the depth arithmetic, the gadget endpoint kinds, the client's own follower, and the response consumption that completes the chain.

## The Chain

A client builds a request path by concatenating a caller-influenced value into the path component rather than the query, and completes it against its own base.
Traversal depth is arithmetic: the segments above the value minus the upward segments yields the arriving depth.
The traversed request reaches a gadget endpoint on the same origin, the client's own follower carries it onward, and the response the page renders is the attacker's.
Keep the traversal and the follow as one chain, because the traversal alone reaches an endpoint the page still treats as its own.

## Depth Arithmetic

| Input | Computation | What it decides |
|---|---|---|
| Segments above the value | Counted from the constructed path | How many upward segments reach the root |
| Upward segments in the value | Counted from the traversal | The arriving depth |
| Checker depth | The checker's own count after its decode | Whether padding is needed to keep the checker non-negative |
| Client depth | The client's count after its decode | Where the request actually arrives |

Confirm the value lands in the path component first, because the same value in the query string changes nothing.
Select the encoding depth that keeps the checker's count non-negative while the client's count leaves it, and name the encoding differential at that step.

## Gadget Endpoint Kinds

A redirecting endpoint whose destination is caller-influenced is the first gadget kind, and the client follows it because its follower is not the caller's to control.
A reflecting endpoint whose response the page consumes is the second gadget kind, because the arrival's answer is what the page renders.
A redirecting gadget and a reflecting gadget can be the same endpoint read at two steps, and the chain names the redirect-carry mechanism at the follower step.
A traversed path that reaches only static resources with no caller-influenced destination or response is not a gadget, and the search moves on.

## Response Consumption

The response the client receives is the attacker's, and what the page does with it decides the consequence: a markup insertion, an evaluation, or a state binding.
A relocated request whose answer is discarded proves nothing, so confirm the consumption before claiming the chain.
Hand the consumed response to the class that owns its consequence, and stop at the chain's enabling step rather than restating the class's procedure.

## Proof

Count the depth before crafting, because the traversal is arithmetic rather than a payload.
Confirm the arrival endpoint differs from the intended one, then confirm the follower carried the request to an operated target.
Read the client's encoding and follow behaviour, because both decide whether the traversal survives the request.
