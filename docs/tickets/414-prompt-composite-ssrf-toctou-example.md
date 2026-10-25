# 414 - Add the composite SSRF/TOCTOU example

**What to build:** Add one composite example to the modeller prompt: an SSRF through a host parameter concatenated into a URL, with a TOCTOU gap between the initialization check and the fetch. Show the four axes, the impact metrics, the well-formedness check, and the low-yield contrast.

**Blocked by:** 413

**Status:** ready-for-agent

**Seams:** attack/hunting/prompts/threat-modeller.md

## Context

The example is synthetic and must not overfit to the eval target. It shows the trust agreement, the assumption and fault, the SSRF class, VC=H, VI=L, VA=N, the impact 0.6568 and weight 3, the end impact on the metadata endpoint and the internal services, the SSRF skill's trust-assumption countercheck, the local patch, and the soft-404 contrast that stays out of the loops because its impact is zero.

## Acceptance criteria

- [ ] The example shows the technical sharpening, the trust agreement, the assumption and fault, the class, the impact metrics, the end impact, the well-formedness check, and the low-yield contrast.
- [ ] The example uses the four axes by name.
- [ ] The example's metric arithmetic is correct.
- [ ] The example does not name the eval target.
- [ ] The prompt tests assert the example's presence and the impact arithmetic.
- [ ] The prompt stays within the line budget.

## Verification

- Run the prompt tests.
- Adversarial review for length and cohesion.
