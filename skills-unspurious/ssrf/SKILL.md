---
name: ssrf
description: SSRF testing for cloud metadata access, internal service discovery, and protocol smuggling
metadata:
  version: 1.0.0
---

# SSRF

Server-side request forgery lets the server reach networks and services the caller cannot: metadata and credential services, internal control planes, service plumbing, and non-HTTP protocol handlers turn one steered fetch into credentials, lateral position, and sometimes execution. Steer the fetch quietly, prove reach with the smallest effect, and treat every caller-influenced destination as untrusted until the connection target is proven inside the intended set.

## Attack Surface

**Fetch Sinks**
- **Fetching components**: outbound fetchers, previewers, importers, exporters, webhook testers, and link expanders that take a destination from the caller.
- **Protocol-translating services**: document and media renderers, archive expanders, validators, and converters that fetch on behalf of another format.
- **Renderer and headless-browser sinks**: renderer and headless-browser sinks execute caller-authored markup, so the caller supplies code rather than a destination; the renderer then fetches, reads interior content, and can exfiltrate it out of band, which stays an aspect inside this class rather than a variant of its own.

**Indirect Carriers**
- **Stored links**: profiles, avatars, signatures, and notification targets rendered or fetched later.
- **Document and media content**: document and media content that triggers a fetch during processing.
- **Application-resolved inputs**: feed, calendar, import, and package-reference inputs the application resolves itself.

**Less Obvious**
- **Schema-layer resolvers**: schema-layer resolvers that fetch by argument.
- **Tool-mediated fetches**: a model-driven fetch or browse tool consumes an instruction and reaches an interior destination, which composes with the `llm-prompt-injection` class rather than restating it here.
- **Background workers**: background crawlers, queue workers, and sync jobs that consume attacker-influenced references.
- **Service-to-service hops**: through relays, gateways, and sidecars that forward caller-supplied destinations.

## Reconnaissance

### Surface Map

- **Input enumeration**: enumerate every input the application resolves - direct destination parameters, embedded links, stored references, and derived values.
- **Carrier-to-fetcher mapping**: note which carrier reaches which fetcher, and whether the value is resolved immediately or by a later job.
- **Indirect path recording**: record indirect paths where the caller names a resource and the application builds the destination.

### Capability Probes

- **Destination carriers**: which parameters, headers, and stored fields reach a fetcher at all.
- **Handler support**: which schemes resolve, which are refused, and whether the refusal is uniform.
- **Redirect following**: single-hop, multi-hop, and scheme switches across the chain.
- **Request shaping**: whether the sink lets the caller influence the method, headers, or body of its own request.
- **Parse behaviour**: the canonical form the validation side reads versus the form the fetch side resolves.
- **Read settlement**: fetch a known external body first and check whether the upstream body returns, so blind versus full-read is settled before severity is assigned.

### Oracle Setup

- **Token minting**: mint a unique token per probe and confirm listener infrastructure receives arrivals before sending any effect payload.
- **Per-parameter attribution**: attribute per parameter - one fresh token per candidate field, one request each, and a negative control, so an unvisited field is recorded as evidence rather than assumed silent.
- **Response-time baseline**: measure a response-time baseline and record length and validator values for a control destination.
- **Error-class calibration**: calibrate error classes against known-open and known-closed control points so a differential is attributable.

## Detection Channels

- **Direct response content**: direct response content from an internal destination, which decides the finding when the body carries interior-only material.
- **Callback receipt**: a callback receipt at operated infrastructure carrying the per-probe token, which proves egress even when the response carries nothing.
- **Response-length and validator differences**: between a reachable and an unreachable destination, which infer reach behind a masked body.
- **Timing differences**: over a calibrated baseline between open and filtered destinations, which separate a live port from a closed one.
- **Error-class differences**: on interior addresses, which confirm a connection attempt reached a network service rather than being refused at the parser.
- **Timeout-search port mapping**: where repeated gated requests split reachable from filtered ports without payload noise.
- **Redirect chain landing**: a redirect chain that lands outside the originally approved destination set, which proves the check was applied before the hop.
- **Handler-specific behaviour**: on a non-HTTP scheme, which confirms protocol translation reached the target service.
- **Gated destination read**: a gated destination read that succeeds only after the sink performs the preceding token fetch, which proves the caller shaped the request.
- **Interior-only content**: surfaced in a derived document, render, or log, which proves the fetch reached interior material.
- **Uniform errors**: across every destination and handler, which read as a closed network rather than a confirmed negative.

## Adversarial Capabilities

- **Testing prerequisites**: a fetch sink that consumes caller-influenced destinations, an egress oracle, and control of a reachable resource, which the class consumes.
- **Carrier supply**: supply a destination through every carrier the sink accepts - direct parameters, embedded links, document contents, and stored values.
- **Callback operation**: operate callback infrastructure and mint one token per probe to bind each inbound hit to one request.
- **Differential reading**: read differentials (length, validator, timing, error class) when the response carries no body.
- **Request-shape influence**: influence the sink's request shape where the interface allows it, including method selection and header control.
- **Redirector hosting**: host a redirector or served resource under attacker control to decide where the approval is applied.
- **Interior reach mapping**: map interior reach with tight timeouts, repeated samples, and minimal destinations.

## Trust Assumptions

- **The agreement**: a fetch sink reaches only the destinations, schemes, and request shapes the application intends, and the answer it returns reflects what the fetch actually reached.
- **Held conditions**: the agreement holds the checked address to the connected address, holds every redirect hop to the same check, holds the handler family to the schemes the application needs, and holds method and headers to application-chosen values.
- **The failing clause**: interior position leaks when a clause fails - the approval covers one canonical form while the client connects to another, a later hop leaves the checked set, an alternate handler translates the request, or caller input shapes a gated read.
- **Variant clauses**: each variant breaks one clause - the canonical-address clause, the hop clause, the scheme clause, or the request-shaping clause.

## Key Vulnerabilities

### Interior Address Reach

- **Interior address families**: loopback, private, and link-local address families plus IPv6 and mapped forms, sent through every notation the parser accepts.
- **Scheme-less and relative forms**: that the fetcher completes against an interior base.
- **Resolution-after-approval**: hostname forms whose resolution the fetcher performs after the validation side has approved a different canonical value, where the proxy-techniques family owns the rebinding step and this class records only the reach verdict.
- **Parse-changing shapes**: userinfo, fragment, trailing-dot, and case shapes that change the parse between the check and the connection, with the parse comparison owned by the proxy-techniques family at its destination-parser step.

### Scheme Translation

- **Raw text protocol handlers**: non-HTTP handlers that speak raw text protocols reach data stores and job interfaces; craft the target service's own grammar and multi-line payloads.
- **Wrapper handlers**: read local files and apply transforms when the fetch library honours them.
- **Alternate handlers**: with the same reach substitute when the primary family is disabled.
- **Local-read pivot**: where remote handlers are refused, pivot to a local read through the wrapper family.

### Redirect and Parser Differentials

- **Approval-before-hop**: an approval applied before redirect following lets a controlled hop land on an interior destination.
- **Trusted redirector**: a registered interior component that returns a redirect with elevated credentials makes the aggregation layer itself fetch the interior target, so the trusted redirector rather than the caller becomes the fetcher.
- **Validation-versus-fetch disagreement**: validation and fetch sides disagreeing on scheme, host, port, path, or encoding.
- **Front-end parsing differences**: front-end and client-library parsing differences that open a connection the front end never approved.
- **Proxy-techniques pointer**: redirect chains and destination parse differentials are the proxy-techniques family's steps; name it at the hop and record only the reach verdict here.

### Gated Destinations

- **Shaped requests**: some high-value destinations answer only when the request is shaped - a specific method, a required header, or a preceding token fetch.
- **Two-step reads**: fetch a token from one interior endpoint, then present it to the credential endpoint.
- **Flavour and version gates**: decide which shape the destination accepts; confirm the gate before assembling the sequence.

### High-Value Targets

- **Credential and control services**: metadata and instance credential services, control planes, orchestrators, and admin interfaces.
- **Interior data stores**: interior data stores, queues, and process managers reachable through raw protocols, where a fetch converts into control.
- **Discovery endpoints**: service discovery and status endpoints that enumerate further interior destinations.
- **Exported documents**: exported or generated documents that carry interior content back through a channel the application trusts.

### Blind Mapping

- **Port state inference**: port state inferred from timeout search, response size, and error class - reachable and filtered split without content.
- **Recorded absence**: a recorded absence with no differential remains a negative result rather than proof of no egress.
- **Sample repetition**: repeated samples over a fresh baseline separate reachability from load noise.

## Advanced Techniques

**Quiet Oracle Discipline**
- **Smallest answering request**: callback first, then differentials, then timeout search; send the smallest request that answers the question.
- **Listener confirmation**: confirm listener infrastructure itself before any probe, so a missing callback means blocked egress rather than a broken receiver.

**Chain Depth Control**
- **Hop control**: control both the approved destination and the next hop when redirects are followed, with the chain mechanics owned by the proxy-techniques family at its redirect step.
- **Protocol switches**: through a redirect test where the handler policy is actually applied.

**Timing Discipline**
- **Tight budgets**: tight connect and read timeouts with repeated samples; a fresh baseline before each measurement window.

## Bypass Techniques

**Address Encoding**
- **Notation variants**: decimal, octal, and hexadecimal notations, IPv6 and mapped forms, and mixed notation the parser accepts.
- **Wrapped and encoded destinations**: a blob carried in the path or a double-encoded host reaches the fetch after the filter's decode passes, and the number of decode passes before the fetch is the bug.
- **Parser-confusion address shapes**: a userinfo split, a fragment before the host, an encoded separator, and a backslash before the host move the parse between the check and the connection.
- **Edge-versus-origin path confusion**: the edge and the origin normalise the path differently, so the approved address and the fetched path diverge, with the comparison owned by the proxy-techniques family at its destination-parser step.

- **Address notation families**: see `references/address-notation-bypass.md` for the notation families with the check each one defeats.

**Relay Mechanics**
- **Relay ownership**: short-lived resolution, redirect chains, and destination parse differentials are generic relay steps, and the proxy-techniques family owns them; name it at the hop rather than restating the mechanics here.

**Carrier Switching**
- **Carrier switching**: move the same destination between direct parameters, stored fields, embedded links, and derived values until one reaches the fetcher unfiltered.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Credential services**: SSRF to credential services, then cloud API position - list, read, and store in the target account.
- **Interior data store**: SSRF to an interior data store or process manager through a raw protocol, which converts the fetch into control.
- **Orchestrator**: SSRF to an orchestrator or control plane, then lateral movement through tokens and workload interfaces.
- **Compounding reach**: SSRF to interior services that themselves fetch, which compounds reach without new input.
- **Relay and gateway hops**: at relay and gateway hops that forward caller destinations, the proxy-techniques family owns the mechanics; name it rather than restating it here.
- **Schema-layer resolvers**: at schema-layer resolvers that fetch by argument, the graphql class owns the step; compose with it rather than restating resolver mechanics.

## Testing Methodology

1. **Inventory surfaces** - Every caller-influenced destination across request, stored, derived, and background carriers
2. **Establish the oracle** - Callback infrastructure first, with one fresh token per candidate parameter plus a negative control and listener preflight
3. **Interior addressing** - Loopback, private, link-local, and mapped address families plus hostname resolution
4. **Handler variation** - Non-HTTP schemes where the sink supports them, or the recorded absence of each
5. **Parser differentials** - Front-end approval versus fetch-side canonical form, with the comparison owned by the proxy-techniques family at its destination-parser step
6. **Redirect behaviour** - Single-hop, multi-hop, and protocol switches, with both hops under control and the chain owned by the proxy-techniques family at its redirect step
7. **Request shaping** - Method, header, and two-step sequences the sink allows
8. **High-value targeting** - Credential paths, control planes, and interior data stores, one minimal read each
9. **Confirm the effect** - Every claim carries a callback, differential, or disclosed-content verdict

## Variants

- no-response-egress-inference - Infer reachability through timing, size, and error-class differences plus timeout port mapping when the response carries no readable body.
- scheme-translated-command-execution - Translate fetches into raw non-HTTP protocol grammar and wrapper-aware local reads, scoped to a direct response oracle.
- header-gated-cloud-credential-read - Sequence a token fetch before an authenticated gated read, pairing the required method and headers, scoped to a direct response oracle.

## False Positives

- **Client-side fetches**: client-side fetches only, where no server request occurs.
- **Strict allowlists**: applied at the connection target with resolution pinned and redirects disabled.
- **Simulators and mocks**: returning canned responses without real egress.
- **Blocked egress**: showing uniform errors across every destination and handler.
- **Client-sourced callbacks**: callbacks whose source is the tester's own client rather than the target's egress path.
- **Parser-driven responses**: static responses driven by the parser rather than by a live connection attempt.
- **Echoed destination**: a destination echoed back inside an error, help, or validation string, which proves formatting rather than a fetch and is the most common mis-report.

## Pro Tips

- **Callbacks first**: prefer callbacks first, then iterate on addressing and handlers; a differential is second best, a body is rare.
- **Address families**: test address families and notation variants; filters often normalise only the obvious forms.
- **Client-library comparison**: client libraries differ in redirect, decoding, and handler behaviour; compare the same sink across services and jobs.
- **Redirect leverage**: redirects are leverage - control both the approved hop and the next one.
- **Gated destinations**: gated destinations need request shaping; verify the sink can set the method and headers before assuming a negative.
- **Tiny destinations**: use tiny destinations and tight timeouts to map reach with minimal noise.
- **Masked responses**: when responses are masked, prefer length, validator, and error-class differences over content.
- **Quick chaining**: chain quickly to a durable, harmless proof and stop at the narrowest demonstration.

## Summary

Any feature that fetches remote content on behalf of a caller is a potential tunnel into interior networks and control planes. Bind scheme, host, port, method, and headers explicitly at every hop, and re-check each hop against the canonical form the connection actually uses.
