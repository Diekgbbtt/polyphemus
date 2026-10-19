# Secret Shape Catalogue

This note details the ordered shape catalogue the exposure variant's parse step summarises.
The rows run most specific first, because a generic entropy catch pre-empts every typed shape when it runs first.
A match is a candidate and never a finding: the finding is a credential that converts into authentication.

## The ordering rule

1. An armour-bearing or prefix-bearing shape runs before a context-anchored shape.
2. A context-anchored shape runs before a bare entropy shape.
3. A structured document shape runs before the token shapes its fields contain, because the document names the issuer and the bare token does not.

## Shape rows

| Shape | Structural signature | Issuer family | Severity | Notes |
|---|---|---|---|---|
| Key-armour block | A text block opened and closed by an armour header naming a key algorithm, with a folded base64 body | Key material | Critical | The armour header is the whole signature; a documentation sample is the common false positive |
| Service-account document | A structured document whose type field names a service-account identity and which embeds a private key beside client identity fields | Cloud identity | Critical | The embedded key is the credential; the document frequently answers at a guessable path |
| Key-pair credential | A fixed-length upper-case identifier (four letters then sixteen upper-case alphanumerics) beside a companion secret assignment | Cloud infrastructure | Critical | The identifier alone authenticates nothing, so capture both fields before judging |
| Issuer-prefixed token | A short lower-case literal prefix, a separator, then a fixed-length alphanumeric body | Varies by issuer | High | The prefix table is a runtime fact; an environment marker inside the prefix decides severity, and a test marker drops the row to low |
| Numeric-separated bot token | A short numeric identifier, a separator, then a long alphanumeric body | Messaging bot | High | The numeric half discloses the bot identity, so a dead match still leaks identity |
| Signed-token triplet | Three dot-separated base64url segments whose first two decode to structured JSON | Session artefact | Medium | Presence in served content often means a live session; the shape alone discloses nothing |
| Bearer assignment | An authorization field assigning a bearer value | Auth header | Medium | A header name without an assigned value is not a credential, so the row needs the assignment |
| Basic-auth header | An authorization field assigning an encoded user-and-secret pair | Auth header | Medium | Frequently a monitoring or debug URL rather than a live credential |
| Credentialed URL | A scheme, a userinfo pair carrying a password, and a host | Connection string | Medium | Confirm the host belongs to the target before treating the pair as in scope |
| Signed request URL | A URL whose path carries two or three fixed-length opaque identifiers | Notification service | Medium | Usually a post-only or notify-only grant, which caps the impact |
| Context-anchored secret | A credential noun assigned a long mixed-character literal | Varies by issuer | Medium | The credential noun is the anchor: any token or key noun, a client secret, a password, or a private-key field |
| Context-anchored hexadecimal secret | A secret noun assigned a long hexadecimal literal | Varies by issuer | Medium | The noun decides the verdict; a bare hexadecimal string alone stays noise |
| Encoded holder | A base64 or base32 blob long enough to carry a credential | Varies by issuer | Low | Decode first, then re-run the catalogue over the decoded text |
| High-entropy literal | A standalone literal mixing upper case, lower case, and digits at length | Varies by issuer | Low | The last row; run it only when the others stay clean, and expect noise |

## Context discipline

- Judge the carrier before the shape: a match in a production artifact outranks the same match in a sample block, a documentation page, or a test fixture.
- Judge the audience: a value the surface already serves to an anonymous caller is disclosed, and the scope it grants decides its severity.
- Judge reuse: a value shared between environments means one exposure authenticates several deployments.
- Judge freshness: a content-hashed artifact rotates on every deploy, so a missing location is a new build rather than remediation.

## Runtime facts

The issuer prefix table, the exact body lengths, and the issuer endpoints are runtime knowledge-base facts.
Extend the catalogue by adding prefix rows above the generic ones, and keep the shape classes and the ordering rule stable.
