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

- **Applicability**: an LLM-backed feature whose output flows into an interpreting sink.
- **Sink behaviors**: the sink renders markup, runs statements, follows links, or forwards content to another system.
- **Delivery paths**: direct turns or planted content, since delivery is an aspect carried inside this variant.
- **Evidence requirement**: a sink transcript or otherwise observable sink behavior is required for this variant.

## Reconnaissance

- **Output-path mapping**: handling work starts by mapping the output path before coaxing any sink-bearing text.
- **Sink enumeration**: enumerate every sink the model output reaches, such as renderers plus statement runners plus link followers plus forwarders.
- **Encoding recording**: record the encoding or sanitization applied between the model and each sink.
- **Sink identity**: note which sink identity is under test per run, since sink identity is an aspect carried inside this variant.
- **Transcript source**: list the sink transcript source that will confirm rendering, execution, or forwarding.

## Detection Channels

- **Channel scope**: handling listens to sink behavior.
- **Rendered execution**: rendered script execution or dispatched request at the sink confirms a handling positive.
- **Outbound exfiltration**: outbound request carrying context data to an attacker-observable destination confirms an exfiltration channel.
- **Name-resolution exfiltration**: name-resolution queries whose labels carry context data confirm an exfiltration channel where full egress is filtered.
- **Transcript emission**: sink transcript showing the emitted markup or statements confirms the emission reached the sink.
- **Proper encoding**: properly encoded output at the sink confirms a negative even when the model emitted a suspicious shape.

## Adversarial Capabilities

- **Prerequisites**: handling presupposes prompt influence plus sink reachability, and it consumes both.
- **Coaxing submission**: submit coaxing text through direct turns or through planted ingested content.
- **Emission elicitation**: elicit markup, statement, or link bearing output shapes through placeholder-structured requests.
- **Emission variation**: vary the emission shape per sink identity under test.
- **Evidence inspection**: inspect the sink transcript plus rendered behavior for execution evidence.
- **Destination operation**: operate an observable destination to receive exfiltrated values where the run permits it.

## Trust Assumptions

- **The agreement**: the feature executes under an agreement that the model separates instructions from data, treats ingested content as untrusted data, holds tool choice plus arguments to developer intent, keeps hidden system text undisclosed, and emits only sink-safe output.
- **The behavior bound**: sensitive application behavior changes only when developer instructions direct them.
- **The failing clause**: this variant breaks the sink-safe-output clause because model-emitted markup plus statements plus links render, execute, forward, or exfiltrate at the sink.

## Key Vulnerabilities

### Markup Emission

- **Markup coaxing**: coax placeholder-shaped markup from the model that the downstream renderer interprets.
- **Shape variation**: vary the markup shape per renderer under test because one shape never covers every sink.
- **Procedure ownership**: the parent output-handling step names only generic emission and cannot describe sink-proven rendering, so this variant owns the emission procedure.

### Statement Emission

- **Statement coaxing**: coax placeholder-shaped statements that a downstream statement runner or forwarder interprets.
- **Transcript confirmation**: confirm interpretation in the sink transcript rather than in chat text, because emitted text without sink behavior proves nothing.
- **Neutralised verdict**: treat encoded or neutralised statements at the sink as a negative even when the emission looked suspicious.

### Exfiltration Emission

- **Embed coaxing**: coax placeholder-shaped link or embed constructs that cause the sink to request an observable destination with context data attached.
- **Resolution channel**: where full egress is filtered, a name-resolution query whose labels carry the data still leaves the boundary, so test the resolution channel beside the request channel.
- **Value confirmation**: confirm the outbound request carries the expected value before claiming an exfiltration channel.
- **Markdown-image rule**: treat a markdown-image pattern that reaches a renderer as handling here, since the proving artifact is the rendered request rather than a tool log.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no wrapper changes the sink step itself.
- **Encoding wrappers**: disguise the emission shape past output-side filters.
- **Markup variation**: rotates tag and attribute forms when one shape is neutralised.
- **Split-emission framing**: spreads one sink payload across several model outputs that merge at the sink.
- **Context-breakout shaping**: closes the surrounding sink template before opening the new construct.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: handling chains forward into impact because emission without sink behavior is only text.
- **Stored-content handoff**: hand a rendered-script positive to a stored-content finding where the sink persists the output.
- **Plant handoff**: hand an exfiltration positive to indirect-injection-plant where the leaked value seeds the next plant.
- **Tool handoff**: hand a statement-runner positive to tool-abuse where the executed statement reaches a privileged tool.
- **Encoding intelligence**: treat encoding gaps found here as the output-side intelligence every sibling variant reuses.

## Testing Methodology

Handling runs emission first and everything else follows, because no impact claim stands without sink behavior.
1. **Inventory sinks** - list every output sink with its encoding behavior plus its transcript source, and the step completes when no unlisted sink remains.
2. **Coax markup** - elicit placeholder-shaped markup per renderer, and the step completes when every emission shows a rendered or neutralised verdict.
3. **Coax statements** - elicit placeholder-shaped statements per runner or forwarder, and the step completes when every emission shows an executed or neutralised verdict.
4. **Prove exfiltration** - elicit link or embed constructs carrying placeholder values, and the step completes when every emission shows an exfiltrated or blocked verdict.
5. **Confirm encoding** - recheck each positive against the sink-side encoding path, and the step completes when every claim carries a proven or properly-encoded verdict.

## False Positives

- **Stop rule**: stop when the evidence shows suspicious text without sink behavior, because emission without interpretation is not a finding.
- **Properly encoded output**: model output the sink properly encodes or sanitizes before rendering or running.
- **Unreached emission**: emitted shapes that never reach a sink transcript or observable sink behavior.
- **Undelivered exfiltration**: exfiltration-shaped output whose outbound request never arrives at the observable destination.
- **Single-run rendering**: that never reproduces across repeated emissions.
- **Sandbox-rendered output**: with no sensitive data or action reachable behind it.

## Pro Tips

- **Sink-first discipline**: handling rewards sink-first thinking plus emission variety plus encoding checks.
- **Sink chasing**: chase the sink on every probe because an emission is only critical where interpretation happens.
- **Emission variation**: vary the emission shape per sink identity rather than reusing one markup form.
- **Image testing**: test image and embed rendering explicitly because it is a classic zero-click exfil channel.
- **Encoding confirmation**: confirm each positive against the encoding path so neutralised output never ships as a finding.
- **Verdict separation**: log each emission behind its sink plus shape so rendered and neutralised verdicts stay separable.
- **Sub-tagging**: sub-tag every emission and callback so the firing sink stays attributable when several sinks share one run.

## Summary

Model output that reaches an interpreting sink carries the model's authority into whatever runs there.
Handling proves that transfer with markup plus statement plus exfiltration emissions, confirmed shape by shape at the sink until rendering, execution, forwarding, or proper encoding is established.
