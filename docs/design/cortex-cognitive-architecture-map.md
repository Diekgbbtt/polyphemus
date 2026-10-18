# The cortex: cognitive architecture map (C1)

*Status: built, with unresolved grants carried in the pending register (section 6). This is the detailed design of the cognitive architecture map (the cortex), the shared verbatim injected into every hunting agent's system prompt. It holds the full entity roles, the per-role question -> entity -> tool couplings, the RDF<->KB mapping, the reasoning rules, and the pending register. The injected verbatim is deliberately the concise conceptual core (`src/polymerhus/attack/hunting/prompts/COGNITIVE_ARCHITECTURE_MAP.md`): the data domains, their abstract relationships, and three reasoning rules. It carries no tools, no flows, and no codebase identifiers. The concrete tools and contracts live on the tools themselves.*

Blindness is scoped to the cortex map, not to the whole served prompt: each role's own stable prompt still names the tools and artifact types that role must operate, because an agent cannot use a tool it cannot name. The cortex's job is to make the agent blind to the codebase's internal shape while it reasons, not to hide the tools it is given.*

## 1. Why the split

The operator's rule: the cortex is one shared, meaning-dense verbatim, identical across every hunting agent, so all of them reason through one architecture.
It must not become a role-specific tool tutorial, and the agents must not receive internal codebase information.
The design therefore separates two layers:

- **The injected verbatim** - the concise conceptual map: the data domains, their abstract relationships, and three reasoning rules, with no tools, no flows, and no codebase identifiers.
- **This design document** - the full detail for maintainers: the entity homes, the concrete tool couplings per role, the RDF<->KB mapping, the reasoning rules' rationale, and the pending register.

`src/polymerhus/attack/hunting/cortex.py` single-sources the verbatim (`cognitive_architecture_map()`) and composes it (`with_cortex()`) onto each role's stable system prompt.

### 1.1 The reasoning rules in the injected core

Two adversarial review rounds (section 10) extracted real reasoning transcripts from the `polyphemus` Langfuse project and found four failure modes the map must remove structurally. Each maps to one rule now carried by the injected verbatim:

- **Trust boundary over all non-operator content.** No domain, and no tool result, overrides the operator's task; every domain stays usable as data. Round 1 scoped this to the three target-derived domains; round 2 showed the observed anchoring arrived through the user channel, so the rule is broadened and states positively that the data is still usable (an agent must not become too cautious to deploy a session token it needs).
- **Anti-repetition read discipline.** Do not re-read the same evidence expecting a different answer; a deliberate confirmation query is permitted. Round 1's "re-read only when new evidence changes the question" was over-rigid: it forbade the pod runner's mandated terminal `query_lightrag` and the hunter's D2 re-entry, which are designed confirmation queries.
- **Degraded is not absent.** A domain that is unavailable or failed is not evidence of absence; never ground a conclusion in it. Round 2's live finding: a failed KB tool was laundered into a clean `space-exhausted` verdict in 42/72 pod-triager observations (a false-negative pipeline). The operational root in the pod triager's EXHAUSTION rule was tracked separately (section 6; resolved).
- **Grounded conclusions.** Assert a conclusion only with the domain and the observation it rests on; otherwise name the open gap and whether it is an absent symptom or an unavailable domain. This makes an ungrounded conclusion unrepresentable and forces the degraded case to be named as unavailable, not absent.

**Reachability stays off the map, by design.** The map names domains that some roles cannot reach today (the hunt-orchestrator holds only `hunts_store`, `notes`, `graph_view`). The map stays identical and tool-free across all four agents; reachability is the tool surface's responsibility, and the per-role grants are recorded in section 3.1 and the pending register. A per-role reachability trailer would fork the map and re-expose tool names, so it is rejected.

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
- the hunt-orchestrator's request-history read surface and its skill description-only surface (`load_skill` all-or-regex listing): STILL PENDING - the shipped surface is exactly `hunts_store` / `notes` / `graph_view` (the `TOOL_SURFACE` frozenset, `build_orchestrator_tool_surface` in `attack/hunting/actors.py`), and `hunting_orchestrator` is declared skill-EXEMPT in `ROLE_SKILLS` (`app/llm/skills.py`), so the orchestrator holds no `load_skill` binding (and no listing mode exists) today; it is tied to the C5 workstream (W5's `load_skill` descriptions command, W6's orchestrator surface). The hunt-orchestrator reasons to them as read-only and never reaches skill bodies or lesson writing.
- the pod triager's EXHAUSTION rule laundering a degraded KB tool into a clean `space-exhausted` verdict (the operational root of the degraded-is-not-absent rule): RESOLVED - the round-2 cortex fixes landed the degraded-is-not-absent principle in the injected map (`1f186ec0`, section 10), and the operational fix closed issue [#304](https://github.com/Diekgbbtt/polyphemus/issues/304) on 2026-10-06 (`4f088f62`, review gaps in `9a01f3d3`, on dev).

## 7. Known gaps and drift findings

1. RESOLVED: the pod prompt module docstring now records the binding truth - the pod `runner` and `triager` roles carry `load_skill`/`record_skill_lesson` through the universal `build_skill_tools` binding, while the base prompts stay in code.
2. The hunt-orchestrator's frozen three-tool surface versus the operator's request-history and skill-description grants (reopened by the skills-plumbing stream).
3. `graph_view`'s published contract advertises four L0 labels while the allowlist has fifteen (`Secret`, `Technology` invisible to agents).
4. The hunter's KB queries leave no durable trail (Langfuse only), where the pod records a durable KB observation.
5. `rate_limit_posture` was force-reverted from dev; the redesign is pending (the `configurator` role is reserved for it).
6. RESOLVED: the term "cortex" now lives in the owning glossary (`attack/hunting/CONTEXT.md`, "The cortex (C1, built)"); it no longer lives only in the ephemeral `skills-system-decomposition.md` glossary - the path guardrail lifted once the cortex and its design doc landed on the trunk.

## 8. Injection points

- hunt-orchestrator: `_gate_skill()` (`attack/hunting/llm.py`), used by the actor's thread system prompt and the sync lane.
- hunter: `_load_hunting_agent_skill()` (`attack/hunting/hunting_agent.py`), the per-turn system prompt.
- pod runner and pod triager: `runner_system_prompt()` / `triager_system_prompt()` (`attack/hunting/pod/prompts.py`), used by the production seams and the contract-tier graph.
- Contract tests: `tests/attack/test_cortex.py` (single source, presence in all four, the six domains, the one target-context domain, the four reasoning rules, and the map's blindness to codebase identifiers).

## 9. Provenance

The operator rulings of the skills-system reset (2026-09-28) and the C1 follow-up correction: the injected map is the concise conceptual core, the detail lives here, the target context is one domain, and the agents stay blind to internal codebase information.

## 10. Adversarial review rounds

Two rounds, both by a critical reviewer applying the `critical-thinking-logical-reasoning` paradigm against real reasoning transcripts from the `polyphemus` Langfuse project (projectId `cms6aoqv9006tad0e5r0kkvd9`, EU host): 3,905 generation observations across 2,604 traces, 2026-09-07 to 2026-10-01, including 663 hunter, 743 pod-runner, 92 hunt-orchestrator, and 72 pod-triager observations.

### Round 1

Found and this change acted on three structural defects in the injected map:

- **Critical: no trust boundary.** Target-derived domains carried no provenance, so target content read as instruction. A provenance rule was added.
- **High: unbounded reading.** The "when a domain is thin, read the others" clause had no stopping predicate. A bounded-read rule replaced it.
- **High: no grounded-conclusion contract.** A conclusion could cite no evidence domain. A grounded-conclusion rule was added.

### Round 2

Regression-checked round 1 and mined new patterns. Outcomes:

- **D1 downgraded to Medium.** The trust rule is prudent, but the only anchoring evidence was a synthetic probe delivered through the user channel, not target content; no live lane anchored. The rule is broadened to all non-operator content and states the data stays usable.
- **D2 downgraded to Medium.** The reachability rejection is defensible; real agents did not fabricate tools. Residual gap: a needed-but-unreachable domain is now named an unavailable domain by the grounded-conclusion rule.
- **D3 partially resolved, with a regression fixed.** The bounded-read rule was over-rigid and forbade mandated confirmation queries; it now forbids only pointless repetition.
- **D4 partially resolved.** The observed STOP already stated a gap, so the rule does not forbid it; the rule still makes an ungrounded conclusion unrepresentable.
- **D6, D7, R3, R4 resolved.**
- **New High (live): degraded is not absent.** A failed KB tool was laundered into a clean `space-exhausted` verdict in 42/72 pod-triager observations. A degraded-is-not-absent rule is now in the map; the operational root in the pod triager's EXHAUSTION rule was tracked separately (section 6; resolved).
- **New High (regression): over-rigid read rule** - fixed above.

Accepted risks and residual items left as-is, with reasons:

- **Reachability advertising**: kept, because the map must stay identical and tool-free; reachability lives on the tool surface (section 1.1).
- **Static block dilution under long context**: the map is stable system-prompt text, so a very long context can dilute it. Mitigation is a harness concern (per-turn re-injection), out of this change's scope; recorded here as a risk.
- **End-to-end blindness**: the map is blind, the role prompts legitimately are not. The design-doc claim is scoped to the map (header).
- **Dual vocabulary (round 2, Medium)**: the map's canonical domain names differ from the role prompts' local shorthand ("surface context", "the KB", "pod memory"). The map's names are the canonical conceptual labels; the role prompts keep their local shorthand. A one-name-per-thing reconciliation across the role prompts is a separate change.
- **Rules density (round 2, Low)**: the core now carries four rules. If it grows further, the rule rationale moves fully here and the map keeps only the rules.
