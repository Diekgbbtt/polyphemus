# The cortex: cognitive architecture map (C1)

*Status: built. This is the detailed design of the cognitive architecture map (the cortex), the shared verbatim injected into every hunting agent's system prompt. It holds the full entity roles, the per-role question -> entity -> tool couplings, the RDF<->KB mapping, and the pending register. The injected verbatim is deliberately the concise conceptual core (`src/polymerhus/attack/hunting/prompts/COGNITIVE_ARCHITECTURE_MAP.md`), which lists only the data domains and their abstract relationships: the agents stay blind to internal codebase information, and the concrete tools and contracts live on the tools themselves.*

## 1. Why the split

The operator's rule: the cortex is one shared, meaning-dense verbatim, identical across every hunting agent, so all of them reason through one architecture.
It must not become a role-specific tool tutorial, and the agents must not receive internal codebase information.
The design therefore separates two layers:

- **The injected verbatim** - the concise conceptual map: the data domains and their abstract relationships, with no tools, no flows, and no codebase identifiers.
- **This design document** - the full detail for maintainers: the entity homes, the concrete tool couplings per role, the RDF<->KB mapping, and the pending register.

`src/polymerhus/attack/hunting/cortex.py` single-sources the verbatim (`cognitive_architecture_map()`) and composes it (`with_cortex()`) onto each role's stable system prompt.

## 2. The data domains

Six domains. The target context is ONE domain that groups the target's authentication state and its rate-limit posture; they are not two domains.

- **Target surface** - the observed L0 surface (Endpoint, Parameter, BaseURL, Header) and the judged L1 abstraction (Service, System, DataItem).
- **Target context** - the authentication state (principals, sessions, credentials, roles) and the rate-limit posture of the target.
- **Hunt memory** - the episodic trail of a hunt and the prior hunting artifacts (`HuntConfig`, `TestImplementationSpec`, `ExperimentLog`, `PodExport`).
- **Request history** - the immutable HTTP request/response capture.
- **Testing knowledge** - the everything-vulnerability-testing knowledge base (WSTG plus writeup overlays), holding the ten closed methodology entity types.
- **Procedural knowledge** - the vulnerability-testing skills.

`client_side_js_architecture` is intentionally absent from the injected map until it is implemented; it is tracked in the pending register (section 6) only.

## 3. Entity roles and homes (verified)

- working memory - the session checkpointer's ambient context; no tool reads or writes it.
- target graph - `graph_view`, bound for all four roles.
- target context - the auth store plus `auth_store`, bound for the hunter, the pod runner, and the pod triager; the rate-limit posture is absent from the current build.
- testing knowledge - `kb_query` (hunter), `query_lightrag` (pod runner and pod triager).
- request history - `search_http_history` and `get_http_artifact` (hunter), `replay` (pod runner).
- hunt memory - the orchestrator's `notes` over `memory.yaml`, the hunter's `notes` over `notes.yaml`, and the pod's `note` over its experiment memory; the skill lesson shard (`skills/lessons/<skill>.yaml`, written by `record_skill_lesson`) is a fourth, skill-keyed surface.
- prior hunting artifacts - `hunts_store` (orchestrator `HuntConfig` family), the hunter store (`TestImplementationSpec`), the pod store plus the parent-keyed hunter note (`ExperimentLog`, `PodExport`).
- procedural knowledge - `load_skill` and `record_skill_lesson` (hunter, pod runner, pod triager).

### 3.1 Verified per-role tool surfaces (base `96fb82a`)

| Role | Bound tools |
|---|---|
| hunt-orchestrator | `hunts_store`, `notes`, `graph_view` |
| hunter | `hunts_store`, `notes`, `graph_view`, `kb_query`, `exec`, `search_http_history`, `get_http_artifact`, `load_skill`, `record_skill_lesson`, `auth_store` |
| pod runner | `exec`, `note`, `query_lightrag`, `graph_view`, `replay`, `load_skill`, `record_skill_lesson`, `auth_store` |
| pod triager | `note`, `query_lightrag`, `graph_view`, `load_skill`, `record_skill_lesson`, `auth_store` |

## 4. The coupling paths (question -> entity -> tool)

Each line reads: the abstract question, the entity that answers it, the tool that reaches it.
Where a role lacks the tool, the line names the intended grant; the agent continues on the evidence it holds.

### Fault hypothesisation (the hunt-orchestrator)

- Is this fault feasible at this unit, and which environmental preconditions or adversarial capabilities must hold? -> target surface -> `graph_view`.
- What did prior hunts conclude about this unit or fault? -> prior hunting artifacts -> `hunts_store` (read).
- What reasoning stands behind an earlier decision on this locus? -> hunt memory -> `notes` (read).
- Is this direction a duplicate of an already-minted config? -> prior hunting artifacts -> `hunts_store` (read).
- What request shape did the target already expose? -> request history -> `search_http_history` and `get_http_artifact` (pending grant to the hunt-orchestrator).
- Which procedural discipline bears on this class? -> procedural knowledge -> `load_skill` description listing only (pending grant to the hunt-orchestrator; never skill bodies, never lesson writing).

### Test engineering (the hunter)

- How do I concretise this class's testing methodology, proxy technique, or bypass technique? -> testing knowledge -> `kb_query`.
- Which environmental precondition or adversarial capability does this specific fault need? -> target surface -> `graph_view`.
- Have these payloads, vectors, or application primitives already been tested? -> prior hunting artifacts and hunt memory -> `hunts_store` (read) and `notes` (read).
- What exact request shape did the target already accept? -> request history -> `search_http_history`, then `get_http_artifact`.
- How do I gain or hold a principal's session to reach the surface? -> target context -> `auth_store`.
- What procedure governs this class of test? -> procedural knowledge -> `load_skill`.

### Execution (the pod runner)

- Which missing concept concretises this payload or vector? -> testing knowledge -> `query_lightrag`.
- Where on the target is this surface? -> target surface -> `graph_view`.
- How do I re-run this captured request under a mutation? -> request history -> `replay`.
- Which authenticated principal's context applies? -> target context -> `auth_store`.
- What is the experiment trail so far? -> hunt memory -> `note`.
- What procedure is under test, and what diverged from it? -> procedural knowledge -> `load_skill` and `record_skill_lesson`.

### Triaging (the pod triager)

- Which concept separates this observation from noise? -> testing knowledge -> `query_lightrag`.
- What surface and expectation did the target expose? -> target surface -> `graph_view`.
- What did the runner record? -> hunt memory -> `note`.
- Is the principal valid, and which one applies? -> target context -> `auth_store`.
- Which procedure was under test, and what is the reusable lesson? -> procedural knowledge -> `load_skill` and `record_skill_lesson`.

### Cross-cutting readings

- Does the target consistently answer 429, 403, or 401? -> the rate-limit posture of the target context (pending); until it lands, read the request history -> `search_http_history` and `get_http_artifact`.
- What secret material or technology stack did the surface expose? -> target surface -> `graph_view`, whose published schema names only Endpoint, Parameter, BaseURL, and Header; the wider L0 label allowlist (including Secret and Technology) is not documented to agents, so treat those as unreachable through the tool for now.

## 5. The RDF<->KB mapping

The skill data model's notion sections answer to the knowledge base's ten closed methodology entity types.
The mapping is many to many and deliberately not a full cover: a notion with no KB counterpart, and a KB type with no notion, are the intended state.
The hunter and the pod runner read a lack as a necessity to use the architecture above, which most often ends in a methodology knowledge base query.
This section is the inverse of the entity-to-section mapping landed in `docs/design/skills-ontology.md` (status: proposed, awaiting operator review) and is grounded on `docs/design/skills-variant-boundary.md` (status: proposed, awaiting operator review).

| Skill notion | KB entity type |
|---|---|
| the skill's identity: frontmatter `name` and `description`, title, intro | `VulnerabilityClass` |
| testing methodology, key vulnerabilities, advanced techniques | `AttackTechnique` |
| attack surface and reconnaissance, authored as applicability conditions | `PreconditionEnvironment` |
| adversarial capabilities | `AttackerCapability` |
| detection channels | `ObservableSignal` |
| bypass techniques | `DefensiveControl` |
| attack goal, in the intro, summary, and chaining | `AttackGoal` |
| payload shapes, in key vulnerabilities and references | `PayloadPattern` |
| artifacts, in chaining and detection channels | `Artifact` |
| no section | `TechnologyStack`, a runtime knowledge base fact only |
| trust assumptions, false positives, pro tips, tooling | no KB entity |

The divergence from the operator's five canonical pairs, following the landed document: proxy techniques have no in-body section (an external family, #278), and bypass techniques answer to `DefensiveControl` by induction, the control that the bypass reveals, while the bypass action itself is an `AttackTechnique`.
The landed set additionally pairs `ObservableSignal`, `AttackGoal`, `PayloadPattern`, and `Artifact`, and keeps `TechnologyStack` as a runtime knowledge base fact with no section.

## 6. Pending register

- `client_side_js_architecture`: intended entity, not built; held out of the injected verbatim until it lands; integration tracking ticket [#282](https://github.com/Diekgbbtt/polyphemus/issues/282).
- the rate-limit posture redesign: absent from the shortened dev, pending; integration tracking ticket [#283](https://github.com/Diekgbbtt/polyphemus/issues/283).
- the hunt-orchestrator's request-history read surface and its skill description-only surface (`load_skill` all-or-regex listing): granted in the skills-plumbing stream, pending; the hunt-orchestrator reasons to them as read-only and never reaches skill bodies or lesson writing.

## 7. Known gaps and drift findings

1. The pod prompt module docstring still says skills are deferred, while the bindings grant `pod_runner`/`pod_triager` `load_skill`/`record_skill_lesson`.
2. The hunt-orchestrator's frozen three-tool surface versus the operator's request-history and skill-description grants (reopened by the skills-plumbing stream).
3. `graph_view`'s published contract advertises four L0 labels while the allowlist has fifteen (`Secret`, `Technology` invisible to agents).
4. The hunter's KB queries leave no durable trail (Langfuse only), where the pod records a durable KB observation.
5. `rate_limit_posture` was force-reverted from dev; the redesign is pending (the `configurator` role is reserved for it).
6. The term "cortex" is not yet in any tracked `CONTEXT.md`; it lives only in the ephemeral `skills-system-decomposition.md` glossary. Migrate it into the owning glossary when the stream's path guardrail lifts.

## 8. Injection points

- hunt-orchestrator: `_gate_skill()` (`attack/hunting/llm.py`), used by the actor's thread system prompt and the sync lane.
- hunter: `_load_hunting_agent_skill()` (`attack/hunting/hunting_agent.py`), the per-turn system prompt.
- pod runner and pod triager: `runner_system_prompt()` / `triager_system_prompt()` (`attack/hunting/pod/prompts.py`), used by the production seams and the contract-tier graph.
- Contract tests: `tests/attack/test_cortex.py` (single source, presence in all four, blindness to codebase identifiers).

## 9. Provenance

The operator rulings of the skills-system reset (2026-09-28) and the C1 follow-up correction: the injected map is the concise conceptual core, the detail lives here, the target context is one domain, and the agents stay blind to internal codebase information.
