# CORS Misconfiguration

This note holds the cross-origin read permit: what it enumerates, the omission routes that reach a credentialed read, and the browser proof the effect requires.
It is the reference for the cross-origin read permit, classified like every other permit under the family's allowance-gap procedure.

## The Permit and the Read Model

The browser's same-origin read model withholds a response body from a script whose origin differs from the response's origin, and the read permit names the origins that may read it.
The permit is a pair: a field naming the origin allowed to read, and a field declaring whether credentials may accompany the read.
A credentialed read requires the permit to name the requesting origin exactly and to allow credentials, because a wildcard permit never exposes a credentialed body to a script.
The effect is browser-enforced, so the read is proven in a browser rather than from a raw client that does not enforce the model.

## Omission Routes

| Route | What the permit reads | What the browser does | When it applies |
|---|---|---|---|
| Arbitrary origin reflection | The requesting origin, echoed back | Allows the read, because the permit named the attacker origin | The server reflects the request origin without validation |
| Null-origin value | A null origin, emitted by a sandboxed or local document | Allows the read under the null value | The permit admits the null origin with credentials |
| Pattern look-alike | A value that matches a prefix, suffix, or unanchored expression | Allows the read under the attacker's registerable origin | The permit's pattern lacks a separator or an anchor |
| Unescaped separator in the pattern | A value matching any character where a separator was meant | Allows a look-alike origin | The pattern treats the separator as a wildcard |
| Cleartext sibling origin | A cleartext origin for the same host | Allows the read when a network attacker occupies that origin | The permit admits cleartext origins without transport enforcement |
| Occupied trusted host | A trusted host the attacker can serve from | Allows the read under a genuinely trusted origin | A trusted subdomain is takeover-able or carries its own injection flaw |
| Special-character origin spelling | An origin value with browser-emitted special characters | Allows the read if the permit's parser treats the characters as letters | The permit's validation runs before the browser's own origin emission |

## Preflight and Method Reach

The preflight declaration enumerates the methods and headers a cross-origin request may use, and the browser sends the real request only when the preflight authorises it.
A preflight that reflects whatever method or header it is asked for authorises state-changing verbs and custom headers the page would otherwise be unable to issue.
The preflight cache lifetime extends the window in which a permissive decision survives a policy change, so read it beside the live request.
Test the real request as well as the preflight, because a permissive preflight beside a restrictive real request, or the reverse, changes what the permit actually allows.

## The Browser Proof

Prove the read in a browser: a cross-origin fetch with credentials that returns the credentialed body to the attacker origin.
A raw client that shows the permit field reflected is not proof, because a raw client does not enforce the read model.
A wildcard permit without credentials is not a credentialed read, and a credential declaration alone proves nothing unless the permit names the attacker's origin and the body is readable.
Where the response reflects nothing, confirm the read out of band with a marker unique to the attempt.

## Consumption

Hand the read to the class that owns the disclosed value: a proof-of-intent value read cross-origin turns a protected operation into a cross-site request, and a session-bound body turns into a disclosure.
The permit gap itself is the family's finding; the value the read exposes belongs to the consuming class's procedure.
