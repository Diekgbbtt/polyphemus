# LLM role architecture - agent prompt for the #93 design hole

*Status: design note for ticket #93 ("Design hole: unified 'analyser' LLM role key + the one-shot vs resumable agent property", enhancement, `needs-triage`).*
*This document is the deliverable the #93 ticket carries: the description of the hole, the vocabulary it needs, and the prompt that the fixed role architecture must satisfy.*
*It lands with the #83 PR (the hunting role is the first consumer of the fixed vocabulary).*

## 1. The hole

`src/polymerhus/app/llm/providers.py` keys every LLM-gated agent by a role string in the `ROLES` tuple: `("configurator", "triager", "job_orchestrator", "crawler", "analyser")`.
Each role maps to exactly one model environment variable (`LLM_MODEL_ANALYSER` and so on) and is invoked single-shot through `invoke_role(role, messages, schema=...)` (`src/polymerhus/app/llm/roles.py`).

Two facts do not fit the vocabulary:

1. One `analyser` key gates several DISTINCT agents with different cognitive jobs (the mechanism-typist, the assigner, the data-modeller; the hunting agent was nearly forced into the same key).
   The role key conflates "which model to use" with "which cognitive job is running".
2. The role vocabulary has no property for whether the agent is ONE-SHOT (a single LLM call, stateless, e.g. the assigner's assignment turn) or RESUMABLE (a semi-stateful agent that must resume its working set across invocations, e.g. the hunting agent's decision tree, whose candidate set and decision-point records must survive between turns).
   `invoke_role`'s single-shot convention is the only mechanism today; a resumable agent must smuggle its state through the conversation history because the role offers no state seam.

The consequence is a choice between two bad options: either every new agent reuses an existing role key (model coupling, no cognitive distinction, no state seam), or every new agent mints a new key (key proliferation, N model env vars, no shared vocabulary).

## 2. The fixed vocabulary (proposal for #93)

The role record should carry three independent properties:

- `role_id`: the stable identity of the cognitive job (e.g. `mechanism_typist`, `assigner`, `hunting`).
- `model_key`: the environment variable selecting the model (e.g. `LLM_MODEL_ANALYSER`, `LLM_MODEL_HUNTING`).
- `agent_mode`: `one_shot` | `resumable`.

`one_shot`: a stateless single call; the conversation is complete in one invocation; nothing persists between calls.
`resumable`: a semi-stateful agent; each invocation receives a working set (the durable state) and returns an updated working set; the caller persists it; a resumed invocation must be able to continue from where the previous one ended without rebuilding.

`model_key` is a many-to-one mapping: several `role_id`s may share one model key.
`agent_mode` is a property of the role, not of the model.

## 3. The prompt the fixed vocabulary must satisfy

### 3.1 The hunting role (the first consumer, #83)

Role record: `role_id: "hunting"`, `model_key: "LLM_MODEL_HUNTING"`, `agent_mode: "resumable"`.

The hunting agent's system prompt is the stable cognitive-architecture prompt ratified in `docs/design/hunting-83-hunting-agent-implementation.md` section 4.1-4.6 (decision tree, passes, loop discipline, working set, few-shot examples); its user prompt is the per-invocation grounding (HuntConfig parts, KB retrieval, working set state).

The resumable mode contract, as consumed by the hunting agent:
- The working set (ordered candidate set with statuses, decision-point records, spec canonical hashes, experiment log, derived verdicts) is passed in the user prompt on every invocation and returned by the invocation as the new working set.
- The invocation may resume at GROUND (fresh hunt), at the candidate-evaluation sub-loop (a pod result to consume), at D5 (the continuation judgment), or at a re-entry point (a routed back-edge result).
- The caller persists the returned working set; the agent never rebuilds state from the conversation alone.

### 3.2 The general contract for any resumable role

- The prompt declares where the invocation may resume and what state it receives.
- The state is explicit (a typed working set), never implicit in the conversation history.
- The prompt declares the termination rule: the invocation either returns a final result (the hunt's verdict, the assignment, the classification) or an updated working set with a resume point.
- The one-shot roles keep the existing single-turn contract unchanged; only the resumable roles gain the state seam.

## 4. What #93 must decide

- Ratify the three-property role record and the `one_shot`/`resumable` vocabulary.
- Decide whether `resumable` carries the working set in the prompt (as the hunting agent does) or through a dedicated state seam in `invoke_role`.
- Decide whether `LLM_MODEL_ANALYSER` stays as the shared model key for the three analysis roles (many-to-one) or is split.
- Migrate `ROLES` and `validate_llm_config` (`providers.py`) accordingly, with the hunting role as the proof case.

## 5. Non-goals

- This ticket does not build the resumable-state persistence (the hunt store #68 owns the durable records).
- It does not change the `invoke_role` failure semantics (the escalating timeout retry, #73).
- It does not re-key existing roles beyond what the ratified vocabulary requires.
