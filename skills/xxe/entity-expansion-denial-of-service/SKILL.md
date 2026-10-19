---
name: entity-expansion-denial-of-service
description: Expansion DoS through nested entity amplification. Use when parsers accept entity definitions without bound, when responses slow under small payload growth, when background processors share request-path parser settings.
metadata:
  version: 1.0.0
---

# Entity-Expansion Denial of Service

Expansion treats the entity-definition table itself as the weapon rather than any external fetch.
Expansion nests small definitions inside larger ones until processor time and memory collapse under geometric growth.

## Attack Surface

- **Unbounded definitions**: a consumer accepts entity definitions without a bound on depth or total expanded size.
- **Shared-parser surfaces**: attacker XML reaches service endpoints, upload converters, report pipelines, or background jobs with a shared parser configuration.
- **Self-contained effect**: exhaustion itself is the observable effect, so no network egress and no reflected output are needed.

## Reconnaissance

- **Consumer inventory**: inventory every XML consumer with its carrier and record which consumers accept entity definitions.
- **Minimal seed probe**: probe each consumer with a tiny two-level nesting seed and measure whether latency moves at all.
- **Baseline recording**: record per-consumer baselines for response time plus error shape plus resource behaviour before scaling anything.

## Detection Channels

### Latency Growth

- **Latency growth**: measure response latency across geometrically growing payload seeds and confirm superlinear growth per level.
- **Primary verdict**: treat reproducible geometric slowdown that tracks payload depth as the primary verdict.

### Error Shape

- **Error harvest**: harvest processor errors that surface under expansion load, including timeout, memory, and recursion-limit messages.
- **Load-induced errors**: treat load-induced error shapes as confirmation that expansion executed rather than merely parsed.

### Response Anomaly

- **Baseline comparison**: compare truncated, empty, or failed responses against the recorded baseline for the same consumer.
- **Depth-scaled degradation**: treat consistent response degradation that scales with nesting depth as supporting evidence alongside latency.

## Adversarial Capabilities

- **Nested-definition submission**: submit attacker-shaped XML carrying nested entity definitions to each inventoried consumer.
- **Geometric scaling**: scale payload seeds geometrically from tiny definitions while observing latency and error signals.
- **Minimal-payload discipline**: sustain minimal-payload discipline so each probe stays as small as the signal allows.
- **Slowness discrimination**: distinguish expansion-induced exhaustion from ordinary slowness through depth-correlated measurement.

## Trust Assumptions

- **The agreement**: the XML consumer executes attacker-supplied markup under a five-part agreement in which declarations are rejected or neutered on every code path, general-entity resolution stays disabled wherever markup is parsed, transclusion processors stay off unless the feature requires them, network access stays closed for parsers and transformers, and parsed content never carries file or internal-network data back to the requester.
- **The failing clause**: the agreement fails at the expansion-bounding clause because nested entity definitions expand without bound until processor time and memory are exhausted.

## Key Vulnerabilities

- **Nested amplification**: defines a small base entity and references it repeatedly inside each successive definition.
- **Level multiplication**: each nesting level multiplies total expanded size while the transmitted payload grows only linearly.
- **Resolution-time multiplication**: the parser performs the multiplication during entity resolution, so no external target and no output channel is required.
- **Abstract shaping**: shape the amplification abstractly with placeholders before runtime values fill them.
  ```
  [ENTITY-DEF name=[L0] value=[SHORT-TOKEN repeated K times]]
  [ENTITY-DEF name=[L1] value=[REF L0 repeated K times]]
  [ENTITY-DEF name=[L2] value=[REF L1 repeated K times]]
  [DOCUMENT-BODY single REF to=[DEEPEST-LEVEL]]
  ```

## Bypass Techniques

- **Encoding variation**: vary declaration encoding and newline shapes so naive declaration filters miss the nested definitions.
- **Placement variation**: vary the definition block between internal placement and external-subset placement to reach the resolution path.
- **Shape splitting**: split definitions across indentation and comment shapes so pattern filters match no single recognisable block.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Availability handoff**: hand expansion-induced outages to availability follow-ups when the exhausted processor shares capacity with other tenants.
- **Divergence handoff**: hand parser-option divergences found during expansion probing to sibling XXE variants when the same consumer also fetches.
- **Load-testing authority**: treat sustained load testing as a separately authorised activity and stop at first reproducible exhaustion.

## Testing Methodology

1. **Inventory definition-accepting consumers.**
List every XML sink with its carrier and its entity-definition acceptance answer.
Completion holds when every sink carries an acceptance answer and no consumer lacks a carrier label.
2. **Probe with a minimal seed.**
Submit a tiny two-level nesting definition and record latency plus error shape against the baseline.
Completion holds when every accepting consumer shows either a measured delta or recorded indifference.
3. **Fix the exhaustion oracle.**
Confirm which signal moves with depth: latency growth, load-induced errors, or response degradation.
Completion holds when every vulnerable consumer has a fixed exhaustion channel with a recorded baseline.
4. **Scale geometrically to exhaustion.**
Grow nesting depth one level at a time with minimal payloads until reproducible exhaustion appears.
Completion holds when a fixed depth produces reproducible timeout, error, or degradation across repeated trials.
5. **Validate parity.**
Repeat the minimal seed across service endpoints plus uploads plus background jobs and record every divergence in expansion limits.
Completion holds when every channel shows the same limits or a recorded divergence.

## False Positives

- **Depth-independent slowness**: slow responses that ignore nesting depth signal ordinary load rather than amplification.
- **Literal definition markup**: definition markup echoed literally with flat latency signals a non-resolving parser.
- **Mock success**: mock success simulates parsing without performing expansion.
- **Client-side-only processing**: client-side-only processing expands entities where no server processor runs.

## Pro Tips

- **Tiny seeds**: scale geometrically from tiny seeds because the smallest depth that moves the signal already proves the bound missing.
- **First-exhaustion stop**: stop at first reproducible exhaustion because further scaling adds load without adding evidence.
- **Depth correlation**: measure depth-correlated latency rather than single slow responses so ordinary slowness never counts as expansion.
- **Background processors**: probe background processors separately because shared parser settings turn one vulnerable path into fleet-wide exposure.
- **Failing-depth record**: record the exact failing depth per consumer so remediation sets limits against measured evidence.

## Summary

Expansion ends when parsers bound entity depth and total expanded size on every code path.
Harden the definition layer first because fetch controls never constrain multiplication that needs no fetch.
