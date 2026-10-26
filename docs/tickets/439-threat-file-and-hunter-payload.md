# 439 - Threat file impact block and hunter payload

**What to build:** Denormalise the impact assessment into the threat file and render it in the hunter payload. The spec contract and the pod contract stay unchanged. The hunter uses the impact and the precursors as context. The verification symptoms remain variant-specific.

**Blocked by:** 436.

**Status:** done

**Seams:** `attack/hunting/threat_model_store.py`, `attack/hunting/hunter_payload.py`, `attack/hunting/hunting_agent.py`, `attack/hunting/prompts/hunting-agent.md`

## Context

The spec is `docs/design/impact-assessment-system-spec.md` section 8. The prototype is `docs/design/impact-assessment-system-prototype.md`.

The threat file gains an `impact` block:

```yaml
impact:
  impact_ref: IA-2
  damage: "The attacker reads live credential material from the process dump."
  disposition: threat
  precursors:
    - id: P-1
      capability: "read the management route table"
      procedure: "resolve the management base path outside the API filter"
      evidence_refs: ["exec:api-36"]
    - id: P-2
      capability: "read live session material"
      procedure: "fetch a heap dump from the exposed management handle"
      evidence_refs: ["exec:api-35"]
  capability_path: [P-1, P-2]
```

The threat body gains `impact_ref` and `enabling_precursors`. The `Threat.impact` carries only the CIA vector. The `end_impact` string is gone.

`materialise_hunter_payload` adds the `impact` block. `_compose_grounding` renders `## Impact assessment` and `## Attacker position`. The payload carries no request, payload, or procedure that belongs to the hunter.

The hunter prompt states that the impact is shared context. The verification symptoms are variant-specific. The hunter must not duplicate the damage claim into a spec.

No `damage_claim`, `damage_symptom`, or `damage_verdict` is added.

## Acceptance criteria

- [ ] The threat file carries the `impact` block with the damage, the disposition, the precursors, and the path.
- [ ] The hunter payload carries the impact block and the precursors.
- [ ] The payload renders the impact and the attacker position.
- [ ] The payload leaks no request, payload, or tool.
- [ ] The spec contract and the pod contract are unchanged.
- [ ] The hunter prompt states the shared damage and the variant-specific symptoms.
- [ ] A threat with a multi-hop path renders every hop.

## Verification

- `tests/attack/test_threat_model_store.py`
- `tests/attack/test_hunter_payload.py`
- `tests/attack/test_hunting_agent_prompt.py`
- `tests/attack/test_hunting_actors.py`
