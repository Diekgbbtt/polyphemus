# Redirect Bypass Table

This note holds the destination-validation bypass family: the shape, what the approving side reads, what the following side connects to, and the follower kind the shape applies to.

## Destination Shapes

| Shape | What the approver reads | What the follower connects to | Follower kind |
|---|---|---|---|
| Userinfo separator | The approved host before the separator | The host after the separator | Server-side location, client navigation, library follow |
| Protocol-relative form | A relative destination | A destination on the current scheme | Client navigation and library follow |
| Backslash or mixed separator | A path-shaped value | A host boundary, because the follower normalises the separator | Server-side location and library follow |
| Encoded separator, single or double | An encoded path fragment | A separator after the follower's decode | Any follower that decodes before resolving |
| Null or control-character terminator | The approved host at full length | The attacker host after truncation | Any follower that truncates on the character |
| Fragment terminator | The approved host, with the remainder as a fragment | The attacker host, because the fragment is stripped before the connection | Any follower that resolves before stripping the fragment |
| Trailing dot or case variant | A look-alike of the approved host | A distinct host that resolves the same or different | Any follower that folds the notation |
| Look-alike host family | The approved host as a prefix or suffix | The attacker's registerable host | Any follower |
| Whitespace terminator | The approved host followed by whitespace | The attacker host after the follower trims | Any follower that trims before resolving |
| Scheme swap | A destination under an approved scheme | A destination under a script or document scheme | Client navigation and library follow |
| Duplicate destination member | One occurrence by its own precedence | The other occurrence by its precedence | Any follower that reads a different occurrence than the approver |

## Continuation Values

A post-action, logout, or callback continuation is a destination value with a rule of its own, and that rule is often weaker than the primary destination check.
Enumerate every continuation the flow carries, because the continuation is where the approval's coverage is thinnest.
A continuation that is followed after the primary check carries the arrival past the check without touching the destination it evaluated.

## Follower Kinds

A server-side location header is a follower the caller can inspect, and its destination is the value the approver read.
A client-side navigation sink fed by a URL source is a follower that emits no server-side location at all, so the chain's arrival is visible only in the browser.
A client library that follows a redirect by default is a follower the caller does not control, so the follow happens where no location header is available to inspect.
Treat a follower that re-validates each hop as a recorded negative rather than a dead end, and look for the follower that does not.

## Proof

Record the chain in full: each hop's destination, its verdict, and whether the next hop was checked.
Pair the refused destination with the arrived chain, so the hop that carried the approval past its destination is named from the pair.
A response body that names a destination without following it is not an arrival, and a simulator that answers every hop without a real follow proves nothing.
