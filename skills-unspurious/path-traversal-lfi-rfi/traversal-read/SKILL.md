---
name: traversal-read
description: Read out-of-root files through traversal shapes. Use when file-operation carriers join input into filesystem reads, when edge and application decoders disagree on normalization, when masked responses need length adjudication.
metadata:
  version: 1.0.0
---

# Traversal Read

Prove that crafted path input resolves outside its intended root and discloses file content through a read oracle.
Treat every joined path as untrusted until canonical reads with in-root controls confirm containment.

## Attack Surface

- **Applicability**: applies where user influence reaches a filesystem read sink that joins a base location with carrier-supplied names.
- **Response signals**: applies where normalization settles before the read and the response carries content, errors, or length signals.
- **Read-sink variance**: varies only in which read sink consumes the input and which read oracle proves the crossing.

## Reconnaissance

- **Carrier inventory**: inventory file-operation carriers that feed filesystem reads across downloads, previews, exports, and log views.
- **Join-shape recording**: record each join shape that combines a base location with a carrier-supplied name.
- **Normalization probing**: probe normalization with separator shapes, encoding shapes, repeated-decoding shapes, and trailing-symbol shapes.
- **Edge-versus-application contrast**: contrast edge handling against application handling to record mismatch acceptance.
- **Survey completion**: complete the survey when every read carrier has a recorded join shape and a recorded normalization response.

## Detection Channels

- **Direct response disclosure**: where the body returns file content for a crafted traversal shape.
- **Error echo**: where exception text exposes canonicalized locations for a crafted traversal shape.
- **Masked-content shift**: where length and entity-tag values change between in-root controls and traversal candidates.
- **Encoded-content disclosure**: where a filter-style read returns content that decodes to valid source, which proves the read even when the raw body is not plain text.
- **Out-of-band callback receipt**: carrying a per-sink sub-tag, which confirms a blind read and attributes it to one sink.

## Adversarial Capabilities

- **Input submission**: submit path-like input through file-operation carriers without control over server code or read policy.
- **Signal observation**: observe response bodies, error text, and length signals across crafted candidates and in-root controls.
- **Decoder contrast**: contrast edge decoding against application decoding to expose mismatch acceptance.
- **Masked-response adjudication**: adjudicate masked responses by comparing control measurements against candidate measurements.

## Trust Assumptions

- **The agreement**: when the file-operation feature executes, the server trusts that carrier-supplied names join a base location under a normalization contract. The server trusts that resolution states settle inside one intended root before any read occurs. The server trusts that request primitives read only what the join permits and that exposed readers stay unreachable to crafted names. The server trusts that sensitive file content never leaks to the sender through crafted resolution.
- **The failing clause**: the read-containment clause: joined paths resolve outside the root and disclose file content.

## Key Vulnerabilities

- **Traversal shapes**: that ascend past the base through relative segments, absolute roots, and mixed separators.
- **Encoding shapes**: that survive one decoding pass through single, double, and overlong spellings held as <encoded-shape>.
- **Dot-folding shapes**: that collapse during normalization through doubled and trailing-symbol spellings held as <dot-shape>.
- **Mismatch shapes**: that exploit decoder disagreement through folded delimiters and re-encoded separators held as <mismatch-shape>.
- **Variant delta**: the delta over the parent is canonical-read proof with in-root controls plus masked-content adjudication, which the parent escalation step never names.

## Advanced Techniques

- **Canonical anchoring**: anchor proof on small canonical files that render quietly and compare cleanly across requests.
- **Paired controls**: pair every traversal candidate with an in-root control from the same carrier to isolate the crossing signal.
- **Masked-content adjudication**: adjudicate masked content by collecting length and entity-tag measurements across controls and candidates.
- **Escalation sequencing**: escalate confirmed reads toward adjacent names only after the read oracle completes on its canonical pair.
- **Blind-read confirmation**: confirm blind reads with an out-of-band callback carrying a per-sink sub-tag, and corroborate a timing or length delta across three repeats before claiming the read.
- **Wrapped-read decoding**: decode wrapped reads before judging them, since a filter-style read may return encoded content rather than plain text.

## Bypass Techniques

- **Pre-normalization bypass**: defeat pre-normalization checks by placing traversal meaning after the check boundary with <encoded-shape>.
- **Separator-filter bypass**: defeat separator filters by alternating separator spellings held as <separator-shape>.
- **Join-binding bypass**: defeat join binding by supplying rooted names that discard the base, held as <absolute-shape>.
- **Normalization-inconsistency bypass**: defeat inconsistent normalization by routing folded delimiters through the more permissive decoder with <mismatch-shape>.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Credential recovery**: carry disclosed configuration and source material into credential and secret recovery.
- **Targeted follow-on reads**: carry disclosed path layouts into targeted follow-on reads against adjacent sensitive names.
- **Companion-skill reference**: name the server-side request companion at the fetch-to-execution step rather than restating its procedure here.

## Testing Methodology

1. **Carrier inventory** - inventory read carriers across the file-operation surface and record each join shape, and the step completes when every read carrier has a recorded join shape with no unvisited file-operation surface remaining.
2. **Normalization probing** - probe normalization with separator, encoding, repeated-decoding, and trailing-symbol shapes and record acceptance, and the step completes when every normalization shape has a recorded acceptance verdict across all inventoried carriers.
3. **Handler contrast** - contrast edge handling against application handling with mismatch shapes and record divergent acceptance, and the step completes when every mismatch shape has a recorded edge verdict paired with a recorded application verdict.
4. **Bent step** - prove out-of-root reads with canonical files plus in-root controls plus masked-content adjudication, and the step completes when every traversal candidate has a paired in-root control measurement and a recorded disclosure or length-shift verdict.

## False Positives

- **Virtual names**: exclude virtual names that resolve into safe stores without touching the filesystem.
- **Allowlist-constrained paths**: exclude canonicalized paths constrained to an allowlist root after normalization completes.
- **Volatile framing**: exclude masked responses whose length shifts trace to volatile framing rather than disclosed content.
- **Reflections and routing effects**: exclude echoed input paths and lone status changes, which mark a reflection or a routing effect rather than a read.

## Pro Tips

- **Quiet anchoring**: anchor on quiet canonical files to keep the disclosure signal legible across runs.
- **Edge isolation**: isolate edge behavior from application behavior before judging a mismatch candidate.
- **Paired controls**: prefer paired controls over lone beacons when content stays masked.
- **Evidence recording**: record hashes and canonical locations as hard evidence for every confirmed read.

## Summary

Confirm out-of-root reads with canonical files, paired in-root controls, and masked-content adjudication.
Hold every joined path inside its root through canonical resolution and allowlist enforcement applied at the input-output boundary.
