---
name: email-header-injection
description: Outbound mail message injection where a user-supplied value is composed into mail headers or a mail command channel, covering recipient injection, sender and reply-path spoofing, body and structure override, and command-channel reach.
metadata:
  version: 1.0.0
---

# Email Header Injection

A feature that sends mail on a user's behalf composes a message from input the user supplies, and the mail composition step trusts every value to stay a value.
The header block, the body, and the mail command channel are separated by line-break and field-boundary rules rather than by the HTTP framing contract, so a value that carries a line break or a command token crosses from data into message structure.
The goal is a message the application's own template never described: an extra recipient, a spoofed sender, an overridden body, or a command the transport executes.

## Attack Surface

- **Applicability**: centers on any feature that builds and sends a message from user input, including contact, share, invite, notification, recovery, and support flows.
- **Header-reaching inputs**: the recipient field, the sender and display-name field, the reply-path field, the subject, and any address-list field the flow accepts.
- **Composition paths**: a mail library, a template renderer, a message queue, or a direct command channel to a mail transport; each decodes and re-encodes the value at a different point.
- **Structure boundary**: the boundary between header fields, between the header block and the body, and between body parts is the injection target.
- **Out-of-scope transport**: response-header injection on the web response belongs to the `header-injection` class; this class owns the outbound mail message only.
- **Delivery reach**: the attacker's own reachable mailbox is the observation point, because the effect is read from what the target sends.

## Reconnaissance

### Feature and Field Inventory

- **Feature inventory**: enumerate every feature that triggers an outbound message and record which user inputs reach a message field.
- **Composition-path recording**: record the composition path per feature, which component assembles the message, and whether it writes the value into a header, a body, or a command line.
- **Delivery baseline**: send a clean message first and confirm it arrives, so a later effect is attributable to the injected value rather than to the flow.

### Encoding and Validation Mapping

- **Decoding-path recording**: record the decoding path per field, because a value that is decoded more than once crosses the structure boundary after the check has run.
- **Marker landing**: probe each field with a benign marker and read where the marker lands in the delivered message, whether in a header, the body, the subject, or a command transcript.
- **Validation coverage**: record which fields are shape-validated and which are passed through, because validation commonly covers the recipient address and not the display name, the subject, or the reply path.

## Detection Channels

- A delivered message carries a header field the input never named, which is the primary signal.
- An extra recipient receives a copy of a message the application addressed to someone else.
- The delivered body differs from the template the application composed, which signals a structure override.
- A mail-command transcript or error text shows the input reached the command channel rather than a header value.
- The envelope recipient differs from the visible recipient, which shows the transport accepted a value the application never wrote.
- A message arrives at an address the application never accepted as input, which proves transport-level acceptance.

## Adversarial Capabilities

- Hold a reachable mailbox or listener that receives what the target sends, and read the raw message including its full header block.
- Supply values through every input that reaches a message field, one field per attempt.
- Supply line-break and field-boundary encodings in the forms the decoding path produces.
- Trigger the flow repeatedly so each attempt carries its own baseline comparison.
- Read the transport transcript or delivery error where the flow exposes one.

## Trust Assumptions

- **The agreement**: the mail composition step trusts each supplied value to remain data inside the field the template assigned it, so the header set, the recipient set, and the body are decided by the application's own template, and the transport accepts only the fields the application wrote.
- **The failing clause**: the composition step treats a user value as message structure, so a line-break sequence in the value starts a new header field, ends the header block, or splits the value into a command argument.
- **The channel clause**: where the value reaches a command channel, the transport trusts the composed command to contain only the operands the application intended.

## Key Vulnerabilities

### Recipient Injection

- **Extra-recipient fields**: a value that carries a recipient field name adds a copy of the message to an attacker address, and a repeated recipient field broadens the delivery set.
- **Address-list broadening**: a field that accepts several addresses lets one injected value relay the message to arbitrary recipients under the target's sending reputation.
- **Envelope-versus-header divergence**: the transport may accept an injected recipient while the visible header stays as the application wrote it, so the effect is read from delivery rather than from the header alone.

### Sender and Reply-Path Spoofing

- **Sender override**: an injected sender field makes the message appear to originate from an address the application never used, which defeats recipient-side trust in the brand.
- **Reply-path override**: an injected reply-path field redirects the victim's reply to an attacker address while the visible sender stays legitimate.
- **Display-name separation**: the display name and the address are separate fields, and validation commonly covers only one of them.

### Body and Structure Override

- **Structure replacement**: an injected content-type and boundary pair replaces the template body with attacker-composed content, so the message carries a payload the application never rendered.
- **Header-block termination**: a value that ends the header block early turns the remainder of the template into body content.
- **Part injection**: an injected body-part boundary adds a part beside the legitimate one.

### Command-Channel Reach

- **Operand injection**: a value that reaches a command channel carries an operand the application never intended, which broadens or redirects the transport action.
- **Verification and search commands**: features that ask the transport a question about an address or a mailbox accept the same input, so the command channel is a second reach.
- **Transcript confirmation**: the command channel confirms reach through its own transcript, which is a different proof from a delivered message.

## Advanced Techniques

- **Chained decoding**: where the value is decoded more than once before composition, a doubly encoded line-break sequence crosses the boundary after the validation step has run.
- **Folded-header forms**: a continuation-line shape can extend a header the application wrote rather than adding a new one, which defeats a check that counts fields.
- **Recovery-mail copy**: a copy injected into a recovery message delivers a recovery artifact to the attacker mailbox without touching the recovery flow's own checks; name `account-recovery` at the artifact-delivery step rather than restating that flow here.
- **Relay shaping**: injected recipient fields combined with a legitimate-looking body turn the target into a relay that passes reputation-based filters.
- **Transport re-encoding**: where the transport re-encodes the composed message, the effect depends on whether the re-encoding normalizes the injected structure or preserves it.

## Bypass Techniques

- **Literal-byte filtering**: a validation that rejects only the literal line-break byte while accepting encoded, double-encoded, and alternative line-break forms.
- **Field-selective sanitization**: a library that sanitizes the recipient address but not the display name, the subject, or the reply path.
- **Shape-only validation**: a check that validates the whole value against an address shape without inspecting the decoded form that reaches the header.
- **Post-check composition**: a composition path that decodes or concatenates the value after the validation step, so the checked value is not the composed value.
- **Command-context filtering**: a filter written for the header context applied to a value that reaches a command channel, where the operand boundary differs.
- **Encoding-path divergence**: a decoding path that differs between the validation component and the composition component, so one side sees data and the other sees structure.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Recovery artifact copy**: an injected copy delivers a recovery artifact into the attacker channel, and `account-recovery` owns the artifact-consumption step.
- **Spoofed sender plus phishing trust**: the message passes sender-authentication checks because the target's own transport sent it, so recipient-side trust carries the attack.
- **Relay plus volume**: the target's sending reputation turns a single injection into a relay capability, which is a delivery-goal escalation rather than a new injection.
- **Support and help-desk flows**: an injected recipient on a support flow copies internal ticket traffic into the attacker channel.
- **Internal-address reach**: an injected recipient reaches an internal address the application would never expose as an input.

## Testing Methodology

Injection reads the delivered message first and mutates one field second, because no effect is meaningful without the raw baseline.

1. **Inventory features and fields** - list every mail-triggering feature with the inputs that reach a message field, and the step completes when no input that reaches a message field is unlisted.
2. **Baseline the clean message** - trigger the flow with benign values and read the raw message, and the step completes when the header set, the body, and the recipient set of the clean message are recorded.
3. **Map the decoding path** - record the encodings the composition path decodes per field, and the step completes when each field carries its decoding record.
4. **Inject one field per attempt** - supply a line-break-bearing value in one field at a time and read the delivered raw message, and the step completes when every field carries an effect verdict.
5. **Probe the structure boundary** - test the header-to-body boundary and the body-part boundary separately, and the step completes when each boundary carries an acceptance or refusal verdict.
6. **Probe the command channel** - test the features that pass the value to a command channel and read the transcript, and the step completes when each such feature carries a transcript verdict.
7. **Confirm the effect** - tie every claimed effect to the delivered raw message and the exact value that produced it, and the step completes when each finding carries a reproducible value and its observed effect.

## False Positives

- A message that arrives only because the tester's own address stood in the recipient field, with no injected field in the raw message.
- A display name that looks like a header in the rendered view while the raw message shows a single header field.
- A transport or relay that rewrites the message after the application composed it, which normalizes the injected structure.
- A bounce or delivery-status message that mirrors the submitted value without executing it.
- A mail client that renders a header-looking line inside the body, which is presentation rather than injection.
- A refused attempt reported by the flow as success, where the raw message shows the value stayed data.

## Pro Tips

1. Read the raw message, never the rendered one, because structure effects are invisible in a rendered view.
2. Keep one field per attempt so the effect attributes to exactly one input.
3. Test the display name, the subject, and the reply path, not only the recipient address.
4. Record the encoding that produced the effect, because the same field may refuse one form and accept another.
5. Trigger the flow from a clean session per attempt, so a cached or queued message never masquerades as a fresh effect.
6. Stop at the narrowest proof: one injected field in one delivered message is enough.

## Summary

An outbound message is safe only when every user value stays data inside the field the application assigned it, at the composition point and at the transport point.
Validate the decoded value at the last composition step, keep the recipient set server-decided, and never let one input reach a command channel.

