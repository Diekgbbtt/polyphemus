---
name: deserialization-deferred-trigger
description: Deferred-trigger deserialization testing for stored blobs rehydrated later. Triggers on plantable storage rehydrated by later jobs, on wrapper path references consumed by file operations, on delayed callbacks needing plant-trigger correlation.
metadata:
  version: 1.0.0
---

# Deserialization Deferred Trigger

Stored blobs and path references deserialize long after submission at a locus the submitter never touches directly.
This variant plants a payload at an injection locus, induces or awaits the distinct trigger, and correlates the delayed oracle back to the plant.

## Attack Surface

- **Applicability**: a blob is stored at one locus and rehydrated at a distinct later trigger.
- **Plant locus**: accepts attacker-influenced blobs or path references through profiles, imports, uploads, cache writes, or stored session data.
- **Trigger locus**: rehydrates through exports, cache warming, batch jobs, administrative views, or file operations that implicitly deserialize path references.
- **Variant boundaries**: direct submit-and-observe sinks belong to the gadget-chain variant, and signature-gated state belongs to the signed-forgery variant.

## Reconnaissance

- **Plant-locus hunt**: hunt plant loci that persist attacker-influenced blobs into storage the agent can write to.
- **Plant-trigger mapping**: map each plant locus to the later trigger that rehydrates it, recording the inducement action for each pair.
- **File-operation sink discovery**: discover file-operation sinks that consume path references, since they trigger implicitly without an unmarshal call in view.
- **Batch and administrative trigger discovery**: discover batch and administrative triggers and record which ones the agent can induce versus only await.
- **Hunt completion**: stop hunting only when every plantable locus has a trigger pairing or a documented no-trigger finding.

## Detection Channels

- **Delayed callbacks**: confirm a planted blob rehydrated after the submission interaction closed.
- **Timing correlation between plant, trigger, and callback**: attributes the effect to the paired loci.
- **File-operation trigger signals**: confirm a path reference reached implicit deserialization.
- **Job and administrative invocation records**: confirm the trigger ran after the plant landed.

## Adversarial Capabilities

- **Prerequisites**: this variant presupposes the ability to plant stored values at reachable injection loci.
- **Trigger inducement**: induces triggers through exports, cache warming, or administrative actions where the agent holds access, and otherwise awaits scheduled triggers.
- **Delayed oracle listener**: operates a delayed oracle listener that stays open across the plant-to-trigger window.
- **Path-reference shaping**: shapes path references that file operations consume as implicit triggers.

## Trust Assumptions

- **The agreement**: the feature executes an object-graph rehydration step under a standing agreement. The agreement holds that every consumed blob is sender-faithful and every stored blob reaches rehydration unmodified. The runtime exposes only its own stored state, rehydrates only what its own writers produced, and leaks at most a benign error on malformed input.
- **The failing clause**: the storage-stability clause: the blob is planted at one locus and rehydrated at a distinct later trigger outside the submission interaction.

## Key Vulnerabilities

- **Plant-store-trigger sequencing**: writes a payload at the injection locus and separately induces deserialization at the trigger locus, correlating the delayed oracle across the gap.
- **Wrapper-implicit triggering**: passes a path reference that a file operation consumes, using the abstract shape `[WRAPPER-PLACEHOLDER, PATH-PLACEHOLDER]` to reach rehydration without a visible unmarshal call.
- **Polyglot storage**: survives upload inspection by carrying valid image framing plus an archive body, so the plant reaches storage as an accepted image and rehydrates on the later file operation.
- **Delay and timing**: shape the correlation, since trigger latency separates the plant observation from the effect observation.
- **Locus-splitting delta**: the locus-splitting plant-and-trigger sequence is the delta submit-and-observe language never names.
- **Convergence**: each path converges on the same proof: the delayed effect attributes to the planted value and not to background activity.

## Advanced Techniques

- **One-trigger pairing**: pair every plant with exactly one trigger before sending, since unattributed delays produce inconclusive findings.
- **Inducible-trigger preference**: favour inducible triggers such as exports and cache warming over scheduled ones, since inducement shortens the correlation window.
- **Unique correlator**: tag each planted value with a unique correlator so concurrent activity cannot misattribute the callback.
- **Wrapper trigger affinity**: treat wrapper-implicit shapes as trigger affinity inside this variant, resolving gadget-content disputes toward the trigger pair by first-step assignment.
- **File-operation triggers**: treat every file operation on a wrapper path as a candidate trigger, since existence checks and size reads fire as readily as copies.

## Bypass Techniques

- **Path-reference shaping**: shape path references to pass file-operation validation while still resolving to the planted content.
- **Storage-locus staggering**: stagger plants across equivalent storage loci when one locus is inspected and another feeds the same trigger.
- **Trigger blending**: spread trigger inducement across normal-use actions so the trigger blends with expected administrative behaviour.
- **Defence-bypass family naming**: name the defence-bypass family at steps that defeat hardened inspection instead of restating its mechanics here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Delayed code execution**: hands off to command-execution consumers once correlation attributes the effect to the plant.
- **Delayed credential or session effects**: hand off to the authorization-principal skill for privilege-effect demonstration.
- **Egress opened through resolved references**: hands off to server-side request consumers where the fetch is owned.

## Testing Methodology

1. **Plant-trigger pairing** - pair each plantable injection locus with its distinct trigger locus; the step is complete when every pair has a recorded inducement action or a documented await-only finding.
2. **Correlatable planting** - plant a uniquely correlatable value at the injection locus; the step is complete when the stored value is confirmed present without yet claiming deserialization.
3. **Trigger inducement** - induce or await the trigger at the distinct locus; the step is complete when the trigger invocation is confirmed through interface feedback or invocation records.
4. **Delayed-oracle correlation** - correlate the delayed oracle back to the plant through correlator match and timing order; the step is complete when exactly one plant explains the observed effect.
5. **Bounded impact** - demonstrate bounded impact through the correlated trigger with the least destructive action; the step is complete when the effect ties to the planted value and not to background activity.
6. **Remaining coverage** - cover remaining plant loci and wrapper-implicit paths; the step is complete when each named storage and path-reference locus is tested or ruled out with an observation.

## False Positives

- **Schema-validated storage**: storage layers that re-encode or schema-validate blobs into primitive-only structures close this variant when rehydration never instantiates graphs.
- **Unexecuted triggers**: triggers that never execute during the observation window leave an uncorrelated plant rather than a finding.
- **Background-matching callbacks**: callbacks that match background activity instead of the unique correlator mark misattribution rather than success.
- **Sandboxed trigger contexts**: sandboxed trigger contexts without network or execution primitives neutralise the effect demonstration when isolation is verified thoroughly.
- **Misleading error text**: error text naming storage classes without the planted value reaching rehydration marks a dead code path rather than a finding.

## Pro Tips

- **Unique correlators**: plant unique correlators on every run, since concurrent jobs make untagged delays unreadable.
- **Fastest trigger first**: prefer the fastest inducible trigger first, since short windows produce the cleanest attribution.
- **Listener persistence**: keep the delayed listener open past the longest expected schedule before ruling a locus out.
- **Time recording**: record plant time, trigger time, and callback time together so the correlation survives later review.
- **Administrative triggers as await-only**: treat administrative triggers as await-only until access is confirmed, since failed inducement attempts pollute the timing record.

## Summary

Stored blobs and path references become live payloads when a distinct later trigger rehydrates them.
Prove each finding by pairing plant with trigger and correlating the delayed oracle back to the planted value.
Safe patterns validate stored content against primitive-only schemas at write and read time, isolate trigger contexts, and avoid implicit rehydration in file operations.
