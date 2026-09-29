# The cognitive architecture map

The shared map of the hunting data layer.
Every hunting agent reasons through this one architecture: the hunt-orchestrator, the hunter, the pod runner, and the pod triager all read the identical text.
An entity is what a class of question is answered from; a tool is how the agent reaches it.
A path marked pending is an intended grant, not a dead end: reason to the named tool and continue on the evidence you already hold.

## Entities and their roles

- **working memory** - the session context the checkpointer carries across a session's turns, ambient and automatic; no tool reads or writes it.
- **L0/L1 attack-surface graph** - the observed L0 surface (Endpoint, Parameter, BaseURL, Header) and the judged L1 abstraction (Service, System, DataItem); `graph_view` answers it for all four roles.
- **auth_context** - the per-project auth store of principal accounts, holding credentials, tokens, snapshots, and roles; `auth_store` reads and writes it for the hunter, the pod runner, and the pod triager.
- **methodology knowledge base** - the everything-vulnerability-testing KB (WSTG plus writeup overlays) that holds the ten closed methodology entity types; `kb_query` retrieves it for the hunter, and `query_lightrag` for the pod runner and the pod triager.
- **HTTP request/response history** - the immutable `http-artifact/v1` capture of live target traffic; the hunter reads it with `search_http_history` and `get_http_artifact`, and the pod runner executes a captured request with `replay`.
- **episodic notes** - the durable reasoning trail of a hunt, keyed by hunting identity; the hunt-orchestrator writes its `memory.yaml` with `notes`, the hunter writes its `notes.yaml` with `notes`, and the pod writes its experiment memory with `note`.
- **prior hunting artifacts** - the configs, specs, experiment logs, and pod exports a hunt produced; `hunts_store` reads the hunt-orchestrator's `HuntConfig` family, the hunter's store reads its `TestImplementationSpec` entries, and the pod store plus the parent-keyed hunter note carry the `ExperimentLog` and `PodExport`.
- **skills (procedural knowledge)** - the ordered vulnerability-testing procedures a run follows; `load_skill` reads one and `record_skill_lesson` records a reusable lesson for the hunter, the pod runner, and the pod triager.
- **rate_limit_posture** - the target's rate-limit behaviour and the request shaping it demands; intended, not yet in this build, see the pending register.
- **client_side_js_architecture** - the target's client-side JavaScript architecture; intended, not built, see the pending register.

## The coupling paths

Each line reads: the abstract question, the entity that answers it, the tool that reaches it.
Where a role currently lacks the tool, the line names the intended grant and the agent continues on the evidence it holds.

### Fault hypothesisation (the hunt-orchestrator)

- Is this fault feasible at this unit, and which environmental preconditions or adversarial capabilities must hold? -> L0/L1 attack-surface graph -> `graph_view`.
- What did prior hunts conclude about this unit or fault? -> prior hunting artifacts -> `hunts_store` (read).
- What reasoning stands behind an earlier decision on this locus? -> episodic notes -> `notes` (read).
- Is this direction a duplicate of an already-minted config? -> prior hunting artifacts -> `hunts_store` (read).
- What request shape did the target already expose? -> HTTP request/response history -> `search_http_history` and `get_http_artifact` (pending grant to the hunt-orchestrator).
- Which procedural discipline bears on this class? -> skills -> `load_skill` description listing only (pending grant to the hunt-orchestrator; it never reaches skill bodies or lesson writing).

### Test engineering (the hunter)

- How do I concretise this class's testing methodology, proxy technique, or bypass technique? -> methodology knowledge base -> `kb_query`.
- Which environmental precondition or adversarial capability does this specific fault need? -> L0/L1 attack-surface graph -> `graph_view`.
- Have these payloads, vectors, or application primitives already been tested? -> prior hunting artifacts and episodic notes -> `hunts_store` (read) and `notes` (read).
- What exact request shape did the target already accept? -> HTTP request/response history -> `search_http_history`, then `get_http_artifact`.
- How do I gain or hold a principal's session to reach the surface? -> auth_context -> `auth_store`.
- What procedure governs this class of test? -> skills -> `load_skill`.

### Execution (the pod runner)

- Which missing concept concretises this payload or vector? -> methodology knowledge base -> `query_lightrag`.
- Where on the target is this surface? -> L0/L1 attack-surface graph -> `graph_view`.
- How do I re-run this captured request under a mutation? -> HTTP request/response history -> `replay`.
- Which authenticated principal's context applies? -> auth_context -> `auth_store`.
- What is the experiment trail so far? -> episodic notes -> `note`.
- What procedure is under test, and what diverged from it? -> skills -> `load_skill` and `record_skill_lesson`.

### Triaging (the pod triager)

- Which concept separates this observation from noise? -> methodology knowledge base -> `query_lightrag`.
- What surface and expectation did the target expose? -> L0/L1 attack-surface graph -> `graph_view`.
- What did the runner record? -> episodic notes -> `note`.
- Is the principal valid, and which one applies? -> auth_context -> `auth_store`.
- Which procedure was under test, and what is the reusable lesson? -> skills -> `load_skill` and `record_skill_lesson`.

### Cross-cutting readings

- Does the target consistently answer 429, 403, or 401? -> rate_limit_posture (pending); until it lands, read the HTTP request/response history -> `search_http_history` and `get_http_artifact`.
- How does the target's client-side JavaScript architecture expose this surface? -> client_side_js_architecture (not built); until it lands, read the L0/L1 attack-surface graph -> `graph_view`.

## The RDF<->KB mapping

The skill data model's notion sections answer to the knowledge base's ten closed methodology entity types.
The mapping is many to many and deliberately not a full cover: a notion with no KB counterpart, and a KB type with no notion, are the intended state.
The hunter and the pod runner read a lack as a necessity to use the architecture above, which most often ends in a methodology knowledge base query.
This section is the inverse of the entity-to-section mapping landed in `docs/design/skills-ontology.md` (status: proposed, awaiting operator review) and is grounded on `docs/design/skills-variant-boundary.md`.

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

## Pending register

- `client_side_js_architecture`: intended entity, not built; integration tracking ticket pending.
- the rate-limit posture redesign: absent from the shortened dev, pending; integration tracking ticket pending.
- the hunt-orchestrator's HTTP-history read surface and its skill description-only surface (`load_skill` all-or-regex listing): granted in the skills-plumbing stream, pending; the hunt-orchestrator reasons to them as read-only and never reaches skill bodies or lesson writing.
