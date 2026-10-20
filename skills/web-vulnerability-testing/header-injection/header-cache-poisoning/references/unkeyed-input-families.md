# Unkeyed Input Families

This note details the component families summarised in the variant body.
Each family is a place a value can move the stored body while the cache key stays fixed, which is the whole finding.
Concrete field spellings and extension lists are runtime knowledge-base facts and stay out of this note.

## Component families

| Family | Members | Why the key may miss the member |
|---|---|---|
| Authority and forwarding families | The authority field and each forwarding alias | Link builders read the member while the key covers only the address the caller requested |
| Client-address family | Address and origin claims | Logging and personalization consume the member while the key ignores it |
| Protocol and port family | Protocol version, port, and transport claims | The key is computed before the member is consumed, or from a different member |
| Content-negotiation family | Media type, encoding, and language preferences | The origin varies the body while the key covers the address alone |
| Capability and hint family | Identity, role, device, and correlation hints | The member reaches a template or a decision the key never covered |
| Method-override family | Override carriers and method variance | The cache keys one method's address while the origin answers another |
| Request-shape members | A body on a bodyless method, a fragment, an unkeyed query member | The origin processes bytes the key never included |

## Address-shape members

The address itself is a member family when the cache and the origin normalize it differently.
- Case variation, a trailing dot, and encoded separators move the key and the origin path apart.
- A delimiter append, an encoded percent, a null byte, a fragment, and a dot-segment normalization each read as a distinct address to one side.
- A cacheable suffix on an otherwise dynamic path stores a body the origin produced for a caller.

## Sweep protocol

Probe under a fresh throwaway key so a live victim key is never poisoned during the sweep.
Vary one member per probe, and read the cache-signal values before and after, so each stored entry attributes to exactly one sweep member.
Confirm with a clean second session that replays the victim address with no attack member and records the served body.
Diff the poisoned key against a never-touched control key, so ambient content drift cannot read as attacker influence.

## Boundary

Correctly keyed personalization is the boundary: keyed variation is intended behavior rather than poisoning.
A member that bends only an emitted link, with no store behind it, belongs to `header-host-forward-spoof` rather than here.
The shared-cache keying mechanics belong to the `proxy-techniques` family at its cache step, and this note keeps only the member families and the sweep discipline.
