---
name: upload-pipeline-deferred-trust
description: Pipeline timing proving late control points bypass earlier validation. Triggers on finalize swaps, presigned header control, pre-verdict fetching.
metadata:
  version: 1.0.0
---

# Upload Pipeline Deferred Trust

Exercise control points that act after the validation gate and confirm the bypass with serving effect.
This variant owns act-after-the-gate proof with finalize swaps plus presigned control plus pre-verdict polling.

## Attack Surface

- Multi-step submission flows apply where initialization and finalization are separate operations.
- Delegated-upload conditions apply where the client uploads directly to storage under server-issued permissions.
- Scan-gated pipelines apply where a verdict queue stands between storage and serving.

## Reconnaissance

- Map the pipeline from initiation through storage and verdict to serving and record which stage owns each validation.
- Probe multi-step flows by altering type and disposition hints between initiation and finalization and recording what persists.
- Probe delegated uploads by recording which headers with identity and permission fields stay attacker-steerable.
- Probe scan-gated pipelines by fetching objects immediately after upload and recording verdict timing with access windows.

## Detection Channels

- Post-gate objects served with attacker-steered type or disposition prove late-control bypass.
- Pre-verdict accessibility followed by quarantine transition proves timing-gap exposure.
- Serving-header comparison across initiation and finalization proves finalize-swap acceptance.

## Adversarial Capabilities

- Submit files through multi-step and delegated-upload paths and steer late metadata and header values.
- Swap type and disposition hints at finalization after passing initiation checks with benign values.
- Poll stored objects before verdicts complete and widen timing windows with heavy processing jobs.

## Trust Assumptions

- The pipeline agrees that a file accepted at ingress keeps its validated type through storage and processing and serving, that serving reflects only server-set type with sniffing disabled, that extraction and conversion stay confined, and that no late control point re-opens the gate.
- The failing clause is timing consistency: a late control point accepts content after the gate.

## Key Vulnerabilities

- Finalize-swap acceptance applies initiation-time validation to benign values and persists attacker-swapped values at completion.
- Delegated-upload control lets attacker-steered headers with identity and permission fields shape the stored object and its serving.
- Pre-verdict exposure serves objects before the scan verdict with a fetchable window that load can widen.

## Advanced Techniques

- Exercise late control points such as finalize swaps with delegated header control plus pre-verdict fetch polling then confirm gate bypass with serving effect.
- Reuse stale delegated permissions to replay uploads after the intended window closes.
- Widen the pre-verdict window with heavy conversion jobs and poll for the object inside the gap.

## Bypass Techniques

- Defeat initiation checks by submitting benign values first and swapping hostile values at finalization.
- Defeat permission constraints by steering identity and header fields that the delegated policy leaves open.
- Defeat scan gating by fetching before the verdict and by caching the early response behind a shared serving path.

## Chaining Attacks

- Chain presigned inline rendering into stored script delivery by pairing delegated control with a script-capable served type.
- Chain pre-verdict access into broad distribution by caching the early object behind a shared serving path.

## Testing Methodology

- Map the pipeline and record initiation with finalization plus delegation plus verdict ownership for every flow.
- Complete when every late control point with its validation owner is recorded.
- Exercise benign initiation then hostile finalization plus delegated header steering plus immediate pre-verdict fetching.
- Complete when every late control point has a recorded acceptance verdict with serving headers captured.
- Exercise late control points such as finalize swaps with delegated header control plus pre-verdict fetch polling then confirm gate bypass with serving effect.
- Complete when gate bypass with serving effect is demonstrated for every late control point or when initiation-time values are proven immutable through serving.

## False Positives

- Exclude flows where initiation-time values stay immutable through finalization and serving.
- Exclude delegated uploads where all headers with identity and permission fields are constrained server-side.
- Exclude scan-gated pipelines where access before verdict is impossible by design.

## Pro Tips

- Test finalization steps explicitly because many validations run only at initiation.
- Constrain all headers with object identity server-side when advising the fix for delegated flows.
- Verify shared serving paths honor attachment with sniffing guards before closing a timing finding.

## Summary

Deferred trust holds when a post-gate control point reshapes the object and serving confirms the bypass.
Treat every late control point as a second gate until initiation-time immutability is proven.
