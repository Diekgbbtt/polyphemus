# Forwarded and Authority Field Families

This note details the field families summarised in the parent body.
Each family is described by the consumer a forged value bends, so one probe reads one verdict per family.
Concrete field spellings are runtime knowledge-base facts and stay out of this note.

## Family map

| Family | What the value claims | The consumer it bends | The read-out |
|---|---|---|---|
| Authority field | The destination the request is addressed to | Link builders, access decisions, cache keys, upstream selection | An emitted link, a decision flip, a stored entry, or a chosen upstream |
| Authority aliases | The same destination claim under a forwarding name | Link builders that prefer an alias over the authority field | An emitted link that differs from the authority field |
| Client-address family | The origin address the request arrived from | Address allowlists, rate limiters, audit trails | A decision flip against a restricted endpoint |
| Transport and scheme family | The protocol and encryption the request used | Secure-transport gates, redirect policy | A gate flip on an endpoint that demands the claimed transport |
| Protocol and port family | The port and protocol the request claims | Allowlists keyed on port or protocol | A gate flip or a redirect whose target differs |
| Rewrite and override family | The routed path or method the request claims | Routers and dispatchers consulted after the authorization check | A guarded path or method served while the direct request stays refused |
| Capability and hint family | Identity, role, or preference hints | Personalization and authorization hints | A content change or a decision change |

## Layer handoffs

The authority field, its aliases, and the rewrite family act at different layers, and two of them never compose.
A routing-shaped authority result escalates to the `ssrf` class at the interior-body read, and a rewrite-shaped result belongs to `header-method-override` even when both arrive in one request.
The forwarding family stays informational here: no protocol guarantee says which layer set the value, so any trust past the boundary the application controls is a finding.
The layer rule and the per-layer confirmation are detailed by the `proxy-techniques` family at its relay and forwarding step, so this note keeps the per-family consumer map and the probe discipline.

## Probe discipline

Send the authority field and one alias with swapped values, so the winning source reads from the diff rather than from a single forgery.
Spray one alias per probe against the guarded endpoints, with one clean negative control per alias, so a decision delta attributes to the alias that caused it.
Read the discovery-document oracle as a second link-generating consumer: a republished issuer or endpoint address proves the document consumed the forgery.
Record the virtual-host read-out per forged value, namely a status or size delta that names the default host and the interior hosts behind the edge.

## Reading the result

Reflection is not consumption: a value echoed into a log or an error string proves formatting, not trust.
The finding needs a consumer, so each positive carries the emitted link, the decision flip, or the stored entry that the forgery bent.
Emitted links are validated when the destination stays on the application host across every forged submission, which reads as an allowlist rather than a gap.
