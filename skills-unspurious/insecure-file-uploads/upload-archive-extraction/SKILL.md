---
name: upload-archive-extraction
description: Archive extraction proving traversal writes with symlink escapes. Triggers on archive imports, out-of-directory writes, compression exhaustion.
metadata:
  version: 1.0.0
---

# Upload Archive Extraction

Submit crafted archives and prove extraction escapes its directory or exhausts processing resources.
This variant owns extract-then-locate-outside proof with symlink and nesting plus exhaustion oracles.

## Attack Surface

- **Archive intake**: archive intake flows whose entries extract onto a server filesystem apply here.
- **Staged pipelines**: apply where the extractor runs as a background processor after ingress acceptance.
- **Nested-archive conditions**: apply where extracted content re-enters the extractor recursively.

## Reconnaissance

- **Pipeline map**: map the pipeline from archive submission through storage to the extraction point and record validation ownership.
- **Extraction-rule probe**: probe with a benign archive carrying nested paths and link-shaped entries to observe extraction rules.
- **Extraction-root baseline**: record the extraction root with overwrite behavior and link handling before attempting live content.
- **Resource baseline**: capture baseline resource behavior for legitimate archives so exhaustion stands out.

## Detection Channels

- **Out-of-directory presence**: out-of-directory file presence after extraction proves traversal or link escape.
- **Overwrite placement**: overwritten configuration or executable content proves high-impact write placement.
- **Processing exhaustion**: processing exhaustion with queue stalls proves compression-ratio abuse.

## Adversarial Capabilities

- **Crafted-archive submission**: submit crafted archives through the application submission path with controlled entry paths and link targets.
- **Recursive nesting**: nest archives recursively and tune compression ratios to stress the extractor.
- **Extraction survey**: locate extracted content inside and outside the intended root and read processing side effects.

## Trust Assumptions

- **The agreement**: the pipeline agrees that a file accepted at ingress keeps its validated type through storage and processing and serving, that serving reflects only server-set type with sniffing disabled, that extraction and conversion stay confined, and that no late control point re-opens the gate.
- **The failing clause**: extraction confinement: archive entries escape their intended directory.

## Key Vulnerabilities

- **Traversal extraction**: writes entries whose paths resolve outside the intended root.
- **Link-escape extraction**: follows link-shaped entries to targets outside the intended root.
- **Link-preserving formats**: escape through a link entry plus a follow-on write even where entry names are sanitized, so test the format that keeps links first-class beside the one that drops them.
- **Exhaustion extraction**: expands nested or high-ratio content until processing resources stall.

## Advanced Techniques

- **Combined-archive submission**: submit traversal with link-shaped plus nested plus high-ratio archives then prove out-of-directory writes or exhaustion.
- **Overwrite chaining**: chain a traversal write into a configuration overwrite by aiming entry paths at sensitive relative locations.
- **Recursion-limit search**: widen nesting depth gradually to find the recursion limit before triggering full exhaustion.

## Bypass Techniques

- **Path-validation defeat**: defeat path validation with encoded and normalized entry paths that resolve outside the root after the check.
- **Link-policy defeat**: defeat link policy by submitting link-shaped entries where the extractor honors links instead of dropping them.
- **Link-dropping defeat**: defeat link-dropping sanitizers by switching to a format that stores links as first-class entries, then pairing the link with a follow-on write.
- **Size-gate defeat**: defeat size gates by splitting abusive content across nested layers that each pass alone and expand together.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Traversal-to-execution chain**: chain traversal writes into configuration overwrite and then into server execution through the overwritten file.
- **Exhaustion-to-availability chain**: chain exhaustion into availability impact by stalling shared processing queues behind crafted archives.

## Testing Methodology

1. **Pipeline mapping** - map the pipeline and record archive intake with extraction ownership and root placement, and the step completes when the extraction root with overwrite and link behavior is recorded for every archive intake.
2. **Probe submission** - submit benign traversal with link-shaped plus nested probes and record where each entry lands, and the step completes when every probe entry has a recorded landing path inside or outside the root.
3. **Escape demonstration** - submit traversal with link-shaped plus nested plus high-ratio archives then prove out-of-directory writes or exhaustion, and the step completes when out-of-directory presence or resource exhaustion is demonstrated for every probe family or when extraction confinement with link rejection is proven.

## False Positives

- **Confined extractors**: exclude extractors confined in isolated roots that reject traversal and drop link-shaped entries.
- **Path-flattening pipelines**: exclude pipelines that flatten entry paths to an explicit allowlist before writing.
- **Resource-capped extractors**: exclude resource-capped extractors where nested and high-ratio content fails closed without queue impact.

## Pro Tips

- **Unique traversal probes**: keep traversal probes uniquely identifiable so out-of-directory presence stays unambiguous.
- **Isolated extraction**: extract in an isolated root with an explicit allowlist when advising the fix.
- **Extraction-time rejection**: drop link-shaped entries and reject traversal at extraction time rather than at submission time.

## Summary

Archive extraction holds when crafted entries land outside the intended root or stall processing.
Treat every extractor as a filesystem writer until confinement with link rejection is proven.
