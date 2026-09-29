---
name: direct-injection-override
description: Override model behavior through direct chat input, break delimiter framing, and smuggle instructions past input filters using encoding wrappers.
metadata:
  version: 1.0.0
---

# Direct Injection Override

An LLM feature that treats chat input as data can be steered when attacker text is read as instructions instead.
This variant proves behavior override inside the attacker's own turns by sending instruction replacements plus delimiter breakouts plus wrapped encodings.
The override goal is a visible behavior change against developer intent that later justifies sink-bound follow-ups.

## Attack Surface

Applicability centers on an LLM-backed feature reachable through direct conversational input in the attacker's own session.
The feature accepts free-text turns that are merged into a single prompt alongside developer instructions.
No ingested third-party content and no victim trigger is required for this variant.
A tool layer or output sink may exist downstream, but this variant proves only the chat-behavior override itself.

## Reconnaissance

Override work starts by mapping what the model obeys before sending any attack text.
- Enumerate every direct prompt entry where attacker text merges with developer instructions.
- Record the model's declared capabilities plus refusal baseline plus boilerplate phrasing.
- Note guard placement and whether moderation shares the model or sits outside it.
- List downstream tools and sinks only to scope follow-up variants, since this variant stops at behavior proof.

## Detection Channels

Override listens to chat behavior, so only the entries below are live here.
- Behavior change against developer intent confirms the model followed attacker instructions.
- Refusal-pattern shift across repeated turns signals a guardrail boundary rather than a pass.
- Absence of change after override plus breakout plus wrapped attempts records a resisted probe.
- Non-reproducible compliance across runs marks chatter rather than a finding.

## Adversarial Capabilities

Override presupposes direct chat submission in the attacker's own session, and it consumes that access.
- Submit arbitrary text turns in the attacker's own session without needing a victim.
- Shape replacement instructions that compete with developer instructions in the merged prompt.
- Close surrounding framing and open a new instruction block through delimiter confusion.
- Wrap payloads in encoding or obfuscation forms to probe filter strength.
- Repeat turns across a session to test multi-turn instruction persistence.

## Trust Assumptions

The feature executes under an agreement that the model separates instructions from data, treats chat input as untrusted data, holds tool choice plus arguments to developer intent, keeps hidden system text undisclosed, and emits only sink-safe output.
Sensitive application behavior changes only when developer instructions direct them.
This variant breaks the instruction-separation clause because attacker chat text is executed as instructions in the attacker's own turns.

## Key Vulnerabilities

### Instruction Replacement

Send replacement directives inside the attacker's own turns that compete with the developer instructions in the merged prompt.
Use placeholder-shaped directive blocks rather than literal command text, and vary the framing across attempts.
The parent direct-probe step names only generic overriding and cannot describe turn-scoped behavior proof, so this variant owns the replacement procedure.

### Delimiter Breakout

Close the application's surrounding framing with a placeholder closer, then open a new instruction block in the same turn.
Vary the closer shape across attempts because one framing style never covers every merge template.
Treat a behavior change after the closer as a positive and treat unchanged framing as a resisted probe.

### Wrapped Smuggling

Wrap the replacement or breakout shape in encoding plus obfuscation plus translation forms to test filter strength.
Combine each wrapper with a delimiter breakout because filters often inspect only one layer.
Record which wrapper family passes and which the guard stops, since wrapper strength is an aspect of this variant rather than its own finding.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no wrapper changes the override step itself.
- Encoding wrappers transform the instruction shape past a textual input filter.
- Character-substitution wrappers alter surface form while preserving model readability.
- Translation wrappers shift the instruction into another language form the filter misses.
- Multi-turn laundering splits one blocked request across several turns that merge in context.
- Role-play framing wraps the same instruction in a hypothetical the guard misclassifies.

## Chaining Attacks

Override chains forward into proofs because chat compliance alone is only behavior.
- Hand a stable override to context-leakage for hidden-text extraction through verbatim-repeat requests.
- Hand a stable override to tool-abuse for privileged calls with attacker-chosen arguments.
- Hand a stable override to output-handling for sink-bearing emission and renderer proof.
- Treat guardrail bypassability discovered here as confirmation discipline inside each follow-up.

## Testing Methodology

Override runs direct turns first and everything else follows, because no sink proof is meaningful without a stable behavior change.
1. **Inventory entries** - list every direct chat entry with its merge position plus the refusal baseline, and the step completes when no unlisted entry remains.
2. **Send replacement probes** - submit placeholder-shaped directives in the attacker's own turns, and the step completes when every probe shows followed or resisted behavior.
3. **Attempt breakout** - close the framing and open a new instruction block per turn shape, and the step completes when every framing style shows a behavior verdict.
4. **Wrap and relaunch** - combine each passing shape with encoding plus obfuscation plus translation forms, and the step completes when every wrapper family shows a pass or stop verdict.
5. **Confirm stability** - repeat each positive across runs, and the step completes when every claimed override reproduces or is recorded as chatter.

## False Positives

Stop when the evidence shows words without effect, because chatter without a behavior change is not a finding.
- The model describing an override it never performs in subsequent behavior.
- Hallucinated instruction text that matches no real developer directive.
- Single-run compliance that never reproduces across repeated turns.
- Properly refused turns where the refusal boundary holds across wrappers.
- Sandbox-scoped compliance with no reachable tool, sink, or hidden text behind it.

## Pro Tips

Override rewards placeholder shapes plus repetition plus wrapper layering.
1. Prefer abstract directive shapes first, then promote only stable positives to wrapped forms.
2. Vary the delimiter closer per merge template rather than reusing one framing style.
3. Combine each wrapper with a breakout because single-layer probes undertest filters.
4. Log every turn behind its wrapper family so pass and stop verdicts stay attributable.
5. Stop promoting non-reproducible compliance and record it as chatter rather than impact.

## Summary

A model that executes chat text as instructions surrenders behavior control to whoever holds a turn.
Override proves that surrender with replacement plus breakout plus wrapped probes, repeated until the behavior change is stable enough to carry into sink-bound variants.
