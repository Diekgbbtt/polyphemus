# 410 - Rewrite the trust-modelling procedure with the four axes

**What to build:** Rewrite Branch A of the modeller prompt around the four trust axes: identity, spatial, temporal, and controls_semantics. Add the field-level artifact inventory and the component and data-state elicitation. Give Branch A the same structural weight as Branch B, and keep temporal shorter when the unit has few state transitions instead of padding it.

**Blocked by:** 409

**Status:** done

**Seams:** attack/hunting/prompts/threat-modeller.md, attack/hunting/threat_modeller.py

## Context

The spatial axis enumerates the spatially significant variables at each interface and during processing, traces their origin and lifecycle, and distinguishes resource-selecting identifiers from identity claims. The controls_semantics axis characterizes the precise invariant checks on untrusted attributes, including schema, type, allowlist, sanitization, canonicalization, ownership, tenant binding, network destination, and the placement of the control across stages. The temporal axis covers concurrency assumptions, replay, freshness, partial states, stale caches, fail-open fallbacks, and silent activation such as TOCTOU and DNS rebinding. The identity axis covers provenance, authority, delegation, and the binding of the claimed principal to the caller, session, resource, and function.

## Acceptance criteria

- [x] The prompt names the four axes and their elicitation questions.
- [x] The prompt requires the spatially significant variables at each interface and during processing.
- [x] The prompt requires the origin and lifecycle trace across creation, transformation, persistence, caching, queueing, replication, and service propagation.
- [x] The prompt distinguishes resource-selecting identifiers from identity claims.
- [x] The prompt requires the controls-semantics characterization, including the placement and the effective representation.
- [x] The prompt requires the temporal state and concurrency assumptions.
- [x] Branch A and Branch B carry comparable structural weight.
- [x] Temporal is not padded when the unit has few transitions.
- [x] The prompt tests assert the clauses, and the prompt stays within the line budget.

## Verification

- Run the prompt tests.
- Adversarial review for concision and cohesion.
