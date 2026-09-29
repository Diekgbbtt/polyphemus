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

- Archive intake flows whose entries extract onto a server filesystem apply here.
- Staged pipelines apply where the extractor runs as a background processor after ingress acceptance.
- Nested-archive conditions apply where extracted content re-enters the extractor recursively.

## Reconnaissance

- Map the pipeline from archive submission through storage to the extraction point and record validation ownership.
- Probe with a benign archive carrying nested paths and link-shaped entries to observe extraction rules.
- Record the extraction root with overwrite behavior and link handling before attempting live content.
- Capture baseline resource behavior for legitimate archives so exhaustion stands out.

## Detection Channels

- Out-of-directory file presence after extraction proves traversal or link escape.
- Overwritten configuration or executable content proves high-impact write placement.
- Processing exhaustion with queue stalls proves compression-ratio abuse.

## Adversarial Capabilities

- Submit crafted archives through the application submission path with controlled entry paths and link targets.
- Nest archives recursively and tune compression ratios to stress the extractor.
- Locate extracted content inside and outside the intended root and read processing side effects.

## Trust Assumptions

- The pipeline agrees that a file accepted at ingress keeps its validated type through storage and processing and serving, that serving reflects only server-set type with sniffing disabled, that extraction and conversion stay confined, and that no late control point re-opens the gate.
- The failing clause is extraction confinement: archive entries escape their intended directory.

## Key Vulnerabilities

- Traversal extraction writes entries whose paths resolve outside the intended root.
- Link-escape extraction follows link-shaped entries to targets outside the intended root.
- Exhaustion extraction expands nested or high-ratio content until processing resources stall.

## Advanced Techniques

- Submit traversal with link-shaped plus nested plus high-ratio archives then prove out-of-directory writes or exhaustion.
- Chain a traversal write into a configuration overwrite by aiming entry paths at sensitive relative locations.
- Widen nesting depth gradually to find the recursion limit before triggering full exhaustion.

## Bypass Techniques

- Defeat path validation with encoded and normalized entry paths that resolve outside the root after the check.
- Defeat link policy by submitting link-shaped entries where the extractor honors links instead of dropping them.
- Defeat size gates by splitting abusive content across nested layers that each pass alone and expand together.

## Chaining Attacks

- Chain traversal writes into configuration overwrite and then into server execution through the overwritten file.
- Chain exhaustion into availability impact by stalling shared processing queues behind crafted archives.

## Testing Methodology

- Map the pipeline and record archive intake with extraction ownership and root placement.
- Complete when the extraction root with overwrite and link behavior is recorded for every archive intake.
- Submit benign traversal with link-shaped plus nested probes and record where each entry lands.
- Complete when every probe entry has a recorded landing path inside or outside the root.
- Submit traversal with link-shaped plus nested plus high-ratio archives then prove out-of-directory writes or exhaustion.
- Complete when out-of-directory presence or resource exhaustion is demonstrated for every probe family or when extraction confinement with link rejection is proven.

## False Positives

- Exclude extractors confined in isolated roots that reject traversal and drop link-shaped entries.
- Exclude pipelines that flatten entry paths to an explicit allowlist before writing.
- Exclude resource-capped extractors where nested and high-ratio content fails closed without queue impact.

## Pro Tips

- Keep traversal probes uniquely identifiable so out-of-directory presence stays unambiguous.
- Extract in an isolated root with an explicit allowlist when advising the fix.
- Drop link-shaped entries and reject traversal at extraction time rather than at submission time.

## Summary

Archive extraction holds when crafted entries land outside the intended root or stall processing.
Treat every extractor as a filesystem writer until confinement with link rejection is proven.
