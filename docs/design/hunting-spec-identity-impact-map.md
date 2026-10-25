# Hunting spec identity impact map

*Status: implemented on `fix/hunt-spec-contract-realign`.
Base: `hunt-enhancement-trunk` at `28c6a878`.*

## The identity

The retired identity was `<fault_keyword>_<strategy_keyword>`.
It had three defects:

1. the two words had no defined semantics against SLICE and DISCRIMINATE;
2. `_` was both the separator and a legal keyword character, so two tuples could collide;
3. a fixed two-slot tuple could not express separation on actor, state, or chaining.

The live identity is `<class>__<value>__<value>[__...]`.

- The class is `provenance.web_vulnerability_class`, falling back to `canonical_class`, then `spec`.
- The values are the ordered discriminator instances the hunter chose in DISCRIMINATE.
- The list is two to four entries.
- `__` is the separator and is absent from the value alphabet, so the join is unambiguous.
- The store derives the identity; the hunter never authors `spec_id`.
- A terminal `ratified` write must address an existing draft.
- A discriminator value is stable across status writes.
- A merge keeps the survivor identity and records the absorbed identities in `merged_from`.

## Impact map

| Component | What it offered or consumed | Change |
|---|---|---|
| `attack/hunting/spec_contract.py` | `SkillProcedure`, the seven-field excerpt, `SpecProvenance.skill_procedure` | Adds `Discriminator`, `SkillConcretisedProcedure` (nine fields), `spec_identifier`, and drops the copied excerpt |
| `attack/hunting/hunter_memory.py` | `spec_identifier(fault, strategy)`, `_require_spec_identity`, `_validate_skill_procedure` | New identity from the class and the discriminator values; new concretisation validator; terminal-identity stability check |
| `attack/hunting/hunter_tools.py` | `SpecWrite.fault_keyword`, `.strategy_keyword`, required `target_identity`, `render_spec_contract` | `SpecWrite.discriminators`, optional bound `target_identity`, `skill_concretised_procedure`, `merged_from`; generated table updated |
| `attack/hunting/hunter_state.py` | `SpecItem.fault_keyword`, `.strategy_keyword` | `SpecItem.discriminators` |
| `attack/hunting/hunting_agent.py` | Re-derived the id from the two keywords; built tools without a target | Derives from the class and the discriminators; binds `TargetIdentity` from the payload |
| `attack/hunting/surfer.py` | Materialised the loop payload | Adds `target_context.target_url` from the run's canonical origin |
| `attack/hunting/mover.py` | Dropped `status`, `fault_keyword`, `strategy_keyword` at the pod boundary | Drops only `status`; the discriminators and concretisation reach the pod |
| `attack/hunting/pipeline_sync.py` | Reads `status` and the file stem | No code change; the stem is opaque and the status is unchanged |
| `attack/hunting/pod/types.py` | `SkillProcedure` read from provenance | `SkillConcretisedProcedure` read from the spec; `discriminators` added |
| `attack/hunting/pod/pod_memory.py` | A second copy of `spec_identifier` | Re-exports the ONE shared identity function |
| `attack/hunting/pod/context.py` | Rendered `provenance.skill_procedure` | Renders the top-level concretisation once |
| `attack/hunting/pod/graph.py`, `triage.py` | Read the typed procedure from provenance | Read the typed concretisation from the spec |
| `attack/hunting/pod/variant_basis.py` | Ten bases, seven procedure gaps | Twelve bases, nine procedure gaps (`payload-vector`, `technology-misconfiguration`) |
| `attack/hunting/prompts/hunting-agent.md` | Named the two keywords and the copied excerpt | Names `discriminators` and the concretisation; explains the derived identity and merge rule |
| `attack/hunting/prompts/examples.md` | Referenced the copied excerpt | References the concretisation |
| `attack/hunting/prompts/pod-runner.md` | Read the provenance excerpt | Reads the top-level concretisation; optional `load_skill`; target-specific breadth rule |
| `attack/hunting/prompts/pod-triager.md` | Read the provenance excerpt; seven-gap table | Reads the top-level concretisation; nine-gap table |
| `app/memory/tool_contract.py` | Coded rejection handled missing/unknown/enum errors | Also handles length and pattern constraints |
| `tests/attack`, `tests/attack/pod`, `tests/integration`, `tests/e2e` | Old identity fixtures | Updated to the new identity and lifecycle |

## Stale-verbatim audit

The audit searches the rendered hunter prompt, the rendered hunter tool surface, the pod prompts, and the pod context.

| Key | Where it appeared | Injected into the model context? | Action |
|---|---|---|---|
| `payload_vector_space` | `pod/types.py` docstring, `pod/symbolic.py` docstring | no | doc only; kept as a retirement note |
| `interpretation_guidance` | `pod/types.py` docstring | no | doc only; kept as a retirement note |
| `testing_pattern` | `pod/types.py` docstring, tests | no | doc/test only; kept as a retirement note |
| `fault_keyword` | hunter prompt, spec table, tool description, store, state | yes | removed |
| `strategy_keyword` | hunter prompt, spec table, tool description, store, state | yes | removed |
| `skill_procedure` | hunter prompt, spec table, provenance, pod context, triager prompt | yes | replaced by `skill_concretised_procedure` |
| `fault_class` | `hunt_store.py` legacy notes notation, CONTEXT | no (legacy note store) | recorded as a separate legacy store; not on the hunter spec path |
| `hypothesis` | prompt prose and pod prose | yes, as ordinary domain language | legitimate; not a field name |
| `mechanism` | prompt prose | yes, as ordinary domain language | legitimate; not a field name |
| `supports` / `conflicts` | prompt absence tests | no | absent |
| `rank` | likelihood ranking prose | yes, as a verb | legitimate; not a persisted field |

The retired field names remain in code comments and tests as retirement guards.
A rendered-prompt test asserts the retired names are absent from the hunter prompt.
A schema test asserts the retired keys are rejected by `extra="forbid"`.

## Migration and risk

- Persisted specs written before this change carry the old fields.
  The eval instance will be reset before the next trial, so no live migration is required.
- A stale spec body that reaches the pod is rejected by `extra="forbid"`.
  The malformed fail-safe work (next commit) turns that rejection into a degraded PodExport instead of a queue halt.
- The identity is now longer.
  The store caps it at 120 characters and rejects a fifth discriminator.
- The `target_identity` is bound from the project's canonical origin.
  A target with several origins needs the loop evidence to carry the specific URL; the hunter keeps an authored override as the degraded path.
- The concretisation is capped at 6000 characters.
  It is larger than the retired 4000-character excerpt because it carries the target-specific instance description.
