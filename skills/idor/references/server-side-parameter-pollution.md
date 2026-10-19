# Server-Side Parameter Pollution Note

This note records the authorization consequence of the server-side parameter-pollution case, where the server interpolates a caller-supplied value into a backend URL and the value therefore decides which backend resource or field the request reaches.
The mechanism, the notation family, and the reader differential are owned by `proxy-techniques-url-parser-differential`; only the consequence, the terminal proof, and the delegation map live here.
The note applies when a lookup, reset, or profile endpoint appears to call a backend API on the caller's behalf, and the caller's value lands in that call's path or query.

## The Shape

- A frontend form or endpoint calls a server-side API on the caller's behalf: password reset, account lookup, profile fetch, product lookup, stock check, search.
- The server interpolates the caller's value into a backend URL path segment or query string rather than validating it as text, so the destination is chosen by the server and the caller moves the request inside the server's own URL.
- The bug is neither client-side query pollution nor an arbitrary-destination fetch: the caller cannot name a destination, only reshape the one the server already holds.

## The Authorization Consequence

- The caller reaches a backend resource or a field they cannot name, which is why this note sits with the object-level class rather than with the parser mechanics.
- The strongest proof is a sensitive field belonging to another principal, such as a reset token or a contact value, redeemed through the normal application flow to a terminal state change.
- Record the terminal state change and the class that owns it: the reset flow belongs to `account-recovery`, the token forgery belongs to `authentication-jwt`, and the access verdict stays here.
- Routing feedback is a lead rather than a finding: stop at the narrowest proof that shows the caller reached a resource or field outside their scope.

## Delegation

- The server-side URL builder as a second reader, the notation family, the probe order, and the parse-differential matrix are owned by `proxy-techniques-url-parser-differential`.
- Duplicate-member precedence and the decision a duplicate reaches are owned by `defence-bypass-parser-confusion` and `http-parameter-pollution`.
- An arbitrary destination the server fetches on the caller's behalf is owned by `ssrf`.
- The reset or recovery flow steps are owned by `account-recovery`.
- The front tier that rewrites a request before the application sees it is named at the step owned by `proxy-techniques-relay-forwarding`.

## False Positives

- A client-side-only echo where the value never reaches a server-side call.
- A route error that names a path but changes no effect and reaches no foreign resource.
- A value validated as text and never interpolated, confirmed by uniform behaviour across every structural element.
- A response-shape change with no authorization consequence, which is an information-disclosure lead rather than an access finding.
