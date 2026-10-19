---
name: xxe-local-dtd-error-exfiltration
description: Zero-egress XXE exfiltration through a definition document already installed on the host. Use when remote fetch stays closed but a local definition document is still processed; when the parse-error path interpolates a read value back to the caller.
metadata:
  version: 1.0.0
---

# Local-Definition Error Exfiltration

When remote resolution is closed but the parser still processes a definition document already installed on the host, the disclosure rides the error path instead of the network.
This variant references an installed definition document, redefines one of its declared entities with a caller-supplied body, and forces a read value into a parse-error message with zero egress.
The exfiltration goal is file content returned to the caller through the error channel, with no callback and no outbound request.

## Attack Surface

- **Applicability**: centers on a consumer that honours a document type declaration and resolves local references while remote fetch stays closed.
- **Installed definitions**: a definition document shipped by the operating system, the application install tree, or a container layer, reachable by path from the parser.
- **Error channel**: an error path that returns text to the caller, or writes it where the caller can read it, including derived artifacts and logs.
- **Carriers**: the same carriers as the class: request bodies, uploads, multipart parts, and embedded document segments that a later job parses.
- **Out of scope**: a consumer whose remote fetch is open belongs to the callback variant, because its channel is a receipt rather than error text.

## Reconnaissance

### Local Definition Inventory

- **Path families**: enumerate installed definition documents by family: system grammar directories, application install trees, converter resources, and container image layers.
- **Reachability probe**: reference each candidate as an external subset and record whether it resolves, because an unreachable path produces the same silence as a hardened parser.
- **Candidate record**: keep one candidate path per attempt so an error-class change attributes to one definition document.

### Declaration and Local-Resolution Probes

- **Declaration acceptance**: confirm that a declaration block is honoured at all before composing any redefinition.
- **Local resolution**: confirm that a local reference resolves, because this variant needs the filesystem open even while the network stays closed.
- **Inline pre-flight**: declare an internal entity, reference it, and confirm expansion; when a harmless internal entity does not expand, no local resolution will follow.

### Error-Channel Calibration

- **Error reach**: confirm that a parse failure returns text to the caller, or lands in an artifact or log the caller can read.
- **Interpolation check**: send a reference to a deliberately absent path and read the error text, because the variant needs an error class that quotes the reference it failed to resolve.
- **Egress confirmation**: verify that no outbound request leaves the host, which is what separates this variant from the callback channel.

## Detection Channels

- Error text carrying a fragment of the read file rather than of the submitted document.
- An error-class change that proves the redefined entity resolved where the original definition was inert.
- An error naming a destination built from file content, where the destination itself is the disclosure.
- A difference between the pre-flight document and the redefinition document, which isolates the redefinition as the cause.
- A derived artifact or log entry carrying the interpolated fragment when the response channel stays closed.
- Absent egress across the attempt, which confirms the disclosure came from the error path rather than from a callback.

## Adversarial Capabilities

Local-definition exfiltration presupposes a declaration-accepting consumer plus a reachable installed definition document, and it consumes both.
- **Submit a declaration block**: send a document whose external subset names an installed definition document.
- **Know a definition path**: discover at least one definition document on the host through the path families above.
- **Compose a redefinition**: override an entity the installed document itself declares, so the trusted document carries the caller body.
- **Read the error channel**: recover the interpolated text from the response, an artifact, or a log.
- **Operate with zero egress**: run the whole procedure without a callback host, because no outbound request is available or wanted.

## Trust Assumptions

- **The agreement**: a caller document supplies no definitions of its own, and an installed definition document is trusted because the application placed it there.
- **Held clauses**: declarations stay application-chosen, installed definitions stay unreachable as caller-controlled content, and resolution failures never quote content the application did not supply.
- **The failing clause**: the local-definition clause. The parser resolves a caller-named definition from the filesystem, so an entity inside a trusted document is redefined by the caller and the error path interpolates the read value.
- **The delta**: the callback variant breaks the external-resolution clause over the network; this variant breaks the local-definition clause with no egress at all, so the two never share a channel.

## Key Vulnerabilities

### Local-Definition Repurposing

- **Trusted hook**: reference an installed definition document and redefine one of its declared entities, because the trusted document's own entity names are the hook the parser already accepts.
- **Caller body**: the redefinition body declares further entities, so the caller supplies grammar the installed document never contained.
- **No network needed**: the whole chain resolves on the filesystem, so a closed network does not close the technique.

### Error-Channel Construction

- **Failing destination**: declare a reference whose destination embeds the read value, because the resolution failure then quotes the value in the error text.
- **Nested indirection**: build the value through one entity and embed it in the destination through a second, so a single parse produces the disclosure.
- **Window discipline**: read the value in ordered windows when the error text is truncated, one window per attempt.

### Definition Enumeration

- **Family sweep**: walk the installed definition families until one resolves, because installed paths differ per image and per install layout.
- **Application grammars**: application install trees and converter resources are as valid a hook as system grammar directories.
- **Layered images**: container layers carry their own definition documents, so an image change reopens the candidate set.

## Advanced Techniques

- **Multi-step redefinition**: an entity that builds an entity that builds the failing reference, which reaches values a single nesting level cannot express.
- **Error-class selection**: prefer a failure class that quotes the destination, such as an unresolvable reference or a malformed grammar, over a class that reports only a line number.
- **Split-window reads**: read one offset window per attempt and reassemble locally when the error text caps its length.
- **Zero-egress proof**: record the absence of outbound traffic alongside the error text, so the finding carries its own channel evidence.

## Bypass Techniques

- **Alternate definition hooks**: when the first installed definition document is absent or refuses redefinition, walk the other installed families before abandoning the technique.
- **Nested subset placement**: reach the same hook through an internal or nested subset form when the external placement is filtered.
- **Encoding variants**: declaration encodings and newline shapes that a text filter misses while the parser still accepts them.
- **Truncation workaround**: split the read into windows when the error channel truncates a long value.
- **Chain scope**: the whole bypass stays inside the local filesystem, so it never depends on a network control.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Configuration to credentials**: a disclosed configuration file names credential and key material, which continues into credential discovery.
- **Disclosed paths to further reads**: a disclosed path names further reachable content, which hands the step to the path-traversal class.
- **Interior destinations**: a disclosed value that names an interior service hands the fetch step to the ssrf class.
- **Derived artifact reuse**: content disclosed into a generated document or log persists after the request, which widens the read window.

## Testing Methodology

Calibration runs first, because a redefinition without a reachable error channel discloses nothing.
1. **Inventory consumers** - list every consumer that accepts a declaration block with its carrier, and the step completes when no unlisted consumer remains.
2. **Confirm declaration and local resolution** - probe declaration acceptance and a local reference per consumer, and the step completes when every consumer carries a resolves or inert verdict.
3. **Calibrate the error channel** - send an absent-path reference and record which error classes quote the reference, and the step completes when at least one quoting class or a definitive negative is recorded.
4. **Enumerate installed definitions** - walk the definition path families until one resolves, and the step completes when a reachable definition document or a recorded absence is established.
5. **Compose the redefinition** - override a declared entity so the read value lands in the failing destination, and the step completes when the error text carries a fragment of a known file.
6. **Read the target** - repeat with the target file and ordered windows where needed, and the step completes when the target value is recovered or a definitive negative is recorded.
7. **Prove zero egress** - record the absence of outbound traffic across the attempt, and the step completes when the channel is attributed to the error path alone.

## False Positives

- **Literal reflection**: an error that echoes the submitted document's own text rather than content read from a file.
- **Unprocessed definition**: a path that is absent or an entity that never resolves, confirmed by no error-class change between the pre-flight and the redefinition document.
- **Path without content**: an error that names a path but carries no file content, which discloses nothing beyond the path the caller supplied.
- **Egress present**: an outbound request observed during the attempt, which places the finding in the callback variant rather than here.
- **Parser-generated noise**: error text assembled from parser internals with no relation to the referenced value.

## Pro Tips

1. Pre-flight with a harmless internal entity; it is the cheapest gate on the whole technique.
2. Keep the redefinition minimal so each error is attributable to exactly one read.
3. Read one offset window per attempt; long values rarely survive the error path intact.
4. Enumerate installed definition documents before composing anything, because the hook decides the whole chain.
5. Confirm zero egress explicitly, because the channel is the finding here.
6. Prefer an error class that quotes the destination over one that reports only a line number.
7. Re-enumerate the definition documents after an image or application upgrade; the installed set changes with the build.

## Summary

A parser that still processes an installed definition document discloses file content through its error path with no network at all.
Reference the installed document, redefine one of its entities, force the read value into a failing destination, and read the error text.
