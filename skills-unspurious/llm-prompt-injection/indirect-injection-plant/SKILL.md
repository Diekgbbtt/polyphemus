---
name: indirect-injection-plant
description: Plant instructions in ingested content the model later retrieves, trigger detonation through a victim action, and prove cross-domain execution.
metadata:
  version: 1.0.0
---

# Indirect Injection Plant

An LLM feature that ingests third-party content can be steered when planted text executes in a victim's privileged context.
This variant proves cross-domain execution by authoring retrievable content plus seeding the corpus plus triggering a normal victim action.
The plant goal is attacker instructions running where the victim's data and tools are reachable rather than in the attacker's own session.

## Attack Surface

Applicability centers on an LLM-backed feature that ingests content the attacker can author or influence.
The content reaches the model through retrieval, summarization, or document processing rather than direct chat.
A victim trigger such as a summarization request or a query that surfaces the planted record is required.
Direct chat access alone is insufficient for this variant.

## Reconnaissance

Plant work starts by mapping the ingestion path before authoring any content.
- Enumerate every ingested source such as documents plus messages plus metadata plus annotations the model reads.
- Record which queries or actions retrieve each source into the victim's context.
- Note hiding places where authored text survives rendering, such as comments plus annotations plus alternate text fields.
- List the victim-side trigger script plus the corpus seeding notes available for the run.

## Detection Channels

Plant listens to victim-context behavior, so only the entries below are live here.
- Behavior change in the victim's session against developer intent confirms the planted text executed.
- Retrieved-content citation that surfaces the planted record confirms the seeding path works.
- Tool call performed in the victim's context with planted arguments confirms cross-domain steering.
- Absence of execution after retrieval confirms the plant was treated as data.

## Adversarial Capabilities

Plant presupposes content authorship plus a victim trigger, and it consumes both.
- Author or edit content the feature later ingests through its normal pipeline.
- Seed a corpus record so a target query surfaces the planted text.
- Hide instruction shapes in placements that survive ingestion, such as comments plus annotations plus metadata fields.
- Trigger retrieval or summarization through a normal victim-side action.
- Observe the victim-context transcript plus invocation log for execution evidence.

## Trust Assumptions

The feature executes under an agreement that the model separates instructions from data, treats ingested content as untrusted data, holds tool choice plus arguments to developer intent, keeps hidden system text undisclosed, and emits only sink-safe output.
Sensitive application behavior changes only when developer instructions direct them.
This variant breaks the ingested-content-as-data clause because planted third-party text is executed as instructions in the victim's context.

## Key Vulnerabilities

### Hidden Placement

Embed placeholder-shaped instructions in content placements that survive ingestion yet escape casual review.
Vary the placement across attempts because one hiding spot never covers every ingestion pipeline.
The parent indirect-probe step names only generic planting and cannot describe placement-scoped detonation, so this variant owns the placement procedure.

### Corpus Seeding

Author a corpus record shaped so a target victim query retrieves the planted text into context.
Confirm the record surfaces through a cited retrieval before claiming execution, because an unretrieved plant proves nothing.
Treat retrieval without execution as a partial result that needs a stronger trigger rather than a completed finding.

### Victim-Triggered Detonation

Detonate the plant through a normal victim action such as a summarization or query request.
Match the observed victim-context behavior against the planted directive to confirm execution.
Treat detonation that needs no victim interaction as direct override instead, since membership follows the proving step.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no wrapper changes the plant step itself.
- Encoding wrappers disguise the planted instruction past ingestion-time filters.
- Placement rotation moves the instruction across hiding spots when one spot is stripped.
- Multi-record seeding spreads fragments across several records that merge at retrieval.
- Paraphrase variation reshapes the directive when a verbatim pattern is blocked.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Plant chains forward into proofs because retrieval alone is only delivery.
- Hand a detonated plant to tool-abuse for privileged calls that run in the victim's context.
- Hand a detonated plant to context-leakage for hidden-text disclosure under victim privilege.
- Hand a detonated plant to output-handling for sink-bearing emission the victim renders or forwards.
- Treat the full plant-to-call-to-exfiltration chain as three ordered stages with one terminal proof each.

## Testing Methodology

Plant runs seeding first and everything else follows, because no detonation claim is meaningful without a retrieved record.
1. **Inventory ingestion** - list every attacker-reachable source with its retrieval action plus its surviving placements, and the step completes when no unlisted source remains.
2. **Seed the corpus** - author placeholder-shaped records for each target query, and the step completes when every record shows a retrievability verdict.
3. **Confirm retrieval** - trigger a normal victim action and check the citation or context, and the step completes when every plant shows retrieved or unretrieved.
4. **Detonate and compare** - observe victim-context behavior against the planted directive, and the step completes when every retrieved plant shows executed or treated-as-data.
5. **Confirm stability** - repeat each positive through fresh retrieval cycles, and the step completes when every claimed execution reproduces or is recorded as chatter.

## False Positives

Stop when the evidence shows retrieval without execution, because a quoted plant that never runs is not a finding.
- Planted text the model cites or summarizes as data without following as instructions.
- Records that never surface for the target query, which indicate a seeding failure rather than resistance.
- Victim behavior explainable by the victim's own request rather than the planted directive.
- Single-run execution that never reproduces across fresh retrieval cycles.
- Sandbox-scoped execution with no reachable tool, sink, or hidden text behind it.

## Pro Tips

Plant rewards retrievability first plus placement variety plus victim fidelity.
1. Prove the record surfaces before testing whether it executes, since unretrieved plants waste detonations.
2. Vary hiding placements across records rather than reusing one spot the pipeline strips.
3. Trigger through the victim's most ordinary action so the detonation reflects real exposure.
4. Log each plant behind its record plus query plus trigger so execution stays attributable.
5. Treat shared corpora and multi-tenant memory as attacker-writable until the run proves otherwise.

## Summary

Ingested content that executes as instructions turns every reader into a carrier for the author's intent.
Plant proves that conversion by seeding retrievable records and detonating them through ordinary victim actions, repeated until execution in the privileged context is stable.
