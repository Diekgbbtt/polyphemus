---
name: output-handling
description: Coax sink-bearing markup plus statements plus links from the model, prove rendering or execution at the sink, and confirm exfiltration channels.
metadata:
  version: 1.0.0
---

# Output Handling

An LLM feature whose output reaches a renderer or interpreter can deliver injection when model text executes at the sink.
This variant proves sink impact by coaxing markup plus statement plus link bearing output and inspecting what the sink does with it.
The handling goal is proven rendering, execution, forwarding, or exfiltration rather than suspicious text in a transcript.

## Attack Surface

Applicability centers on an LLM-backed feature whose output flows into an interpreting sink.
The sink renders markup, runs statements, follows links, or forwards content to another system.
Delivery may arrive through direct turns or planted content, since delivery is an aspect carried inside this variant.
A sink transcript or otherwise observable sink behavior is required for this variant.

## Reconnaissance

Handling work starts by mapping the output path before coaxing any sink-bearing text.
- Enumerate every sink the model output reaches, such as renderers plus statement runners plus link followers plus forwarders.
- Record the encoding or sanitization applied between the model and each sink.
- Note which sink identity is under test per run, since sink identity is an aspect carried inside this variant.
- List the sink transcript source that will confirm rendering, execution, or forwarding.

## Detection Channels

Handling listens to sink behavior, so only the entries below are live here.
- Rendered script execution or dispatched request at the sink confirms a handling positive.
- Outbound request carrying context data to an attacker-observable destination confirms an exfiltration channel.
- Name-resolution queries whose labels carry context data confirm an exfiltration channel where full egress is filtered.
- Sink transcript showing the emitted markup or statements confirms the emission reached the sink.
- Properly encoded output at the sink confirms a negative even when the model emitted a suspicious shape.

## Adversarial Capabilities

Handling presupposes prompt influence plus sink reachability, and it consumes both.
- Submit coaxing text through direct turns or through planted ingested content.
- Elicit markup, statement, or link bearing output shapes through placeholder-structured requests.
- Vary the emission shape per sink identity under test.
- Inspect the sink transcript plus rendered behavior for execution evidence.
- Operate an observable destination to receive exfiltrated values where the run permits it.

## Trust Assumptions

The feature executes under an agreement that the model separates instructions from data, treats ingested content as untrusted data, holds tool choice plus arguments to developer intent, keeps hidden system text undisclosed, and emits only sink-safe output.
Sensitive application behavior changes only when developer instructions direct them.
This variant breaks the sink-safe-output clause because model-emitted markup plus statements plus links render, execute, forward, or exfiltrate at the sink.

## Key Vulnerabilities

### Markup Emission

Coax placeholder-shaped markup from the model that the downstream renderer interprets.
Vary the markup shape per renderer under test because one shape never covers every sink.
The parent output-handling step names only generic emission and cannot describe sink-proven rendering, so this variant owns the emission procedure.

### Statement Emission

Coax placeholder-shaped statements that a downstream statement runner or forwarder interprets.
Confirm interpretation in the sink transcript rather than in chat text, because emitted text without sink behavior proves nothing.
Treat encoded or neutralised statements at the sink as a negative even when the emission looked suspicious.

### Exfiltration Emission

Coax placeholder-shaped link or embed constructs that cause the sink to request an observable destination with context data attached.
Where full egress is filtered, a name-resolution query whose labels carry the data still leaves the boundary, so test the resolution channel beside the request channel.
Confirm the outbound request carries the expected value before claiming an exfiltration channel.
Treat a markdown-image pattern that reaches a renderer as handling here, since the proving artifact is the rendered request rather than a tool log.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no wrapper changes the sink step itself.
- Encoding wrappers disguise the emission shape past output-side filters.
- Markup variation rotates tag and attribute forms when one shape is neutralised.
- Split-emission framing spreads one sink payload across several model outputs that merge at the sink.
- Context-breakout shaping closes the surrounding sink template before opening the new construct.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Handling chains forward into impact because emission without sink behavior is only text.
- Hand a rendered-script positive to a stored-content finding where the sink persists the output.
- Hand an exfiltration positive to indirect-injection-plant where the leaked value seeds the next plant.
- Hand a statement-runner positive to tool-abuse where the executed statement reaches a privileged tool.
- Treat encoding gaps found here as the output-side intelligence every sibling variant reuses.

## Testing Methodology

Handling runs emission first and everything else follows, because no impact claim stands without sink behavior.
1. **Inventory sinks** - list every output sink with its encoding behavior plus its transcript source, and the step completes when no unlisted sink remains.
2. **Coax markup** - elicit placeholder-shaped markup per renderer, and the step completes when every emission shows a rendered or neutralised verdict.
3. **Coax statements** - elicit placeholder-shaped statements per runner or forwarder, and the step completes when every emission shows an executed or neutralised verdict.
4. **Prove exfiltration** - elicit link or embed constructs carrying placeholder values, and the step completes when every emission shows an exfiltrated or blocked verdict.
5. **Confirm encoding** - recheck each positive against the sink-side encoding path, and the step completes when every claim carries a proven or properly-encoded verdict.

## False Positives

Stop when the evidence shows suspicious text without sink behavior, because emission without interpretation is not a finding.
- Model output the sink properly encodes or sanitizes before rendering or running.
- Emitted shapes that never reach a sink transcript or observable sink behavior.
- Exfiltration-shaped output whose outbound request never arrives at the observable destination.
- Single-run rendering that never reproduces across repeated emissions.
- Sandbox-rendered output with no sensitive data or action reachable behind it.

## Pro Tips

Handling rewards sink-first thinking plus emission variety plus encoding checks.
1. Chase the sink on every probe because an emission is only critical where interpretation happens.
2. Vary the emission shape per sink identity rather than reusing one markup form.
3. Test image and embed rendering explicitly because it is a classic zero-click exfil channel.
4. Confirm each positive against the encoding path so neutralised output never ships as a finding.
5. Log each emission behind its sink plus shape so rendered and neutralised verdicts stay separable.
6. Sub-tag every emission and callback so the firing sink stays attributable when several sinks share one run.

## Summary

Model output that reaches an interpreting sink carries the model's authority into whatever runs there.
Handling proves that transfer with markup plus statement plus exfiltration emissions, confirmed shape by shape at the sink until rendering, execution, forwarding, or proper encoding is established.
