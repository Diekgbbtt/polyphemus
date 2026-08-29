# Hunting spec: hunt-orchestrator LLM-local artifacts (the gate turn's prompt, tool surface, skills, observability)

Part of the [#82](https://github.com/Diekgbbtt/polyphemus/issues/82) hunt-orchestrator lineage, extending
[`hunting-67-orchestrator-spec.md`](hunting-67-orchestrator-spec.md) (the ratified agent contract: role, goal, workflow).
The parent, merged spec is `docs/design/hunting-67-per-agent-specs-spec.md`; the graph engine this work rides is the
#110 supervisor-state `StateGraph` (`attack/hunting/orchestrator_graph.py`), delivered by #110.

*Status: spec (contract), NOT implementation.* This document extends section 1 of the orchestrator spec with the
artifacts LOCAL to the LLM turn - the per-pair fault-unit analysis prompt, the tool surface, the skill mounts, and the
consequent observability - which the #110 graph wiring delivered as degradable stubs. Everything else in the
orchestrator contract (the O1-O10 canon, IA-1..IA-8, D67-01..D67-14) is unchanged and out of this document's scope.

## 1. The problem, stated from the harness

The #110 graph engine drives the orchestrator's single embedded reasoning turn (Q8) per candidate pair - a stateful
`HuntOrchestratorActor` turn on the `hunting_orchestrator` session thread - but the turn itself carries only the barest
LLM-local surface:

- The per-pair user prompt (`llm.py::_compose_gate_prompt`) is a terse listing of candidate identity + witnesses +
  a KB dump + the graph surface, asking for one direction per candidate. It encodes NO cognitive architecture: no
  reasoning flow, no sub-problem decomposition, no end-goal-backward discipline, no evidence-criticality standard.
- The system prompt (`llm.py::_gate_skill`) resolves `skills/hunting/hunt-orchestrator/SKILL.md` - which does NOT
  exist - and degrades to a short fallback paragraph. Same for the re-match judge (`_rematch_skill`).
- The actor turn binds ZERO tools. The orchestrator's three-tool surface (D67-04: the hunt back-edge, the hunt-store
  reads, the read-only L0/L1 graph view) exists as Python seam objects (`OrchestratorTools`) but is never surfaced to
  the model, so the gate cannot ground itself in the live graph, retrieve prior-hunt memory, or raise a targeted-recon
  need from within the turn.
- There is no observability on the orchestrator turn: `hunting_tracing.py` traces the hunting-agent harness only; the
  gate reasoning leaves no inspectable trace (unlike the mechanism-typist's `trace_reasoning`).

Consequence: the entire orchestrator "reasoning" is currently a stateless, inspects-none, grounds-in-nothing LLM call.
The selection quality - and the hunt-config seeding it feeds - depends on a prompt that does not yet exist.

## 2. Solution

Give the orchestrator's gate turn the four LLM-local artifacts the contract always specified:

1. **The per-pair fault-unit analysis prompt**, pinning a cognitive architecture (section 3 below): the gate reasons
   BACKWARD from the end goal (an `EnvisionedDirection` concrete enough to seed the hunting agent's hypothesis),
   decomposing the analysis into consecutive sub-problems addressed sequentially, rich in the unit's typed projection,
   the fault's materialisation-facet content, and the folded sub-fault family - the mechanism-typist's
   hypothesise-and-verify discipline applied to fault-unit selection.
2. **The tool surface, bound onto the actor turn** (section 4): exactly D67-04's three tools (`back_edge`,
   `graph_view`, `store_reads`), each with a real body over an existing seam and fail-open when the seam is absent.
   NO HuntConfig-writing tool: the mint stays deterministic at the dispatch node, confirmed against the current graph
   logic (`mint_hunt_config` is called from the dispatch stretch from the LLM's `EnvisionedDirection`).
3. **The skill mounts** (section 5): `skills/hunting/hunt-orchestrator/SKILL.md` (+ a rematch variant) written with
   the cognitive architecture as system prompt, mounted through the existing `_gate_skill` / `_rematch_skill` loaders;
   pattern = system prompt + composed turn (the actor's existing `[SystemMessage(skill), HumanMessage(prompt)]`).
4. **The observability** (section 6): an orchestrator-gate tracing module mirroring `hunting_tracing.py` - one span
   per gate turn, correlated to the run by session id, a step span for the symbolic render, fail-open when Langfuse is
   absent.

## 3. The prompt: cognitive architecture of the fault-unit analysis turn

### 3.1 Input (the symbolic render, inside the reason stretch)

The reason stretch (`_reason_node`) assembles the per-pair `GateInput` BEFORE the LLM turn, from the symbolic layer:

- the candidate pair `(unit_id, fault_class)`, its `applies_witnesses` (deterministic + LLM half) and three-valued
  `match_verdict`;
- the **unit projection** (`unit_projection.build_projection`): the unit's typed spine, kind, per-family outgoing
  Service->System edges, data-edge counts, DataRelationship kinds - absence surfaced as UNKNOWN, never FALSE;
- the **fault materialisation** (`fault_kb.load_materialisation(fault_class)`): the CWE's rich NL content (extended
  description, alternate terms, related attack patterns, likelihood, consequences, mitigations, functional areas);
- the **sub-fault fold family** (`fault_kb.load_fold_families`): for the parent `fault_class`, the sorted tuple of
  folded fault_ids captured under it - the parent bounds the fault, the sub-faults are consideration material;
- `kb_degraded` and the read-only graph surface (index cards) as today.

Every fetch is fail-open: a failing projection / materialisation / fold-family read degrades that slot (empty, never a
crash) - matching O4/O5/D67-11. The render is pure symbolic mapping; no LLM call happens before it.

### 3.2 The cognitive architecture (what the system prompt pins)

The gate turn is a MEDIUM-reasoning-effort turn (role `hunting_orchestrator`, ThinkingLevel `medium`). The system
prompt must demand a reasoning flow, not a format:

1. **Orient from the end goal (work backward).** State the deliverable first: a CARRIED `EnvisionedDirection` whose
   `rationale`, `research_direction` (G1 feasibility prose, never technique words) and `vulnerability_classes[]` must
   be concrete enough that a later hunting agent can turn them into a test hypothesis. From that end, ask which
   minuscule amount of evidence each backward step needs - never answer a sub-problem before the one it depends on.
2. **Decompose into consecutive sub-problems, address each sequentially.** The fixed decomposition of the per-pair
   analysis: (a) what does this fault-class MEAN at this unit's typed locus (structure + materialisation + fold family
   as consideration); (b) which preconditions - the attacker's existing capabilities AND the environment conditions -
   must hold for the fault's symptoms to be reachable; (c) which observed characteristics of the target would HINDER
   the tests and consequently support a falsification of the hypothesised fault; (d) how the class-level direction
   reads as feasibility reasoning. Address (a) -> (b) -> (c) -> (d) in order; a skip is a stated precondition, not a
   silent omission. (The test-primitive / payload-vector stretch is the hunter's spec-writing ownership, never the
   orchestrator's - #202.)
3. **Hypothesise, then verify against evidence (mechanism-typist discipline, embeddable verbatim).** For each reading
   that would justify CARRYING the direction, hold at least one competing reading that would justify PRUNING it, and
   settle between them on the evidence actually present: the unit projection, the fault materialisation, the
   witnesses, the graph surface. Prefer external signal over fluency; a confident-sounding direction with no witness
   is the failure mode to avoid.
4. **Judge each proposal critically.** Evidence sufficiency (would this witness fit three other faults equally?),
   surfaced hidden assumptions, no unsupported leaps from URL/tech fingerprint to behaviour. Compounding, not
   clobbering: when a prior-hunt insight or a sub-fault speaks to the same seam, fold it in.
5. **Prune ONLY on positive grounds.** A direction is pruned only when evidence positively establishes the fault
   cannot apply at this locus. NEVER prune on degraded grounds (`kb_degraded`, a failed projection slot, a missing
   sub-fault family): degrade to the evidence you hold and carry. This reflects D67-11 and the Q8 three-level model,
   level 1.
6. **Emit the structured `GateDecision`** (one `EnvisionedDirection` per candidate, `carried` true/false) with the
   three seed fields (`rationale`, `research_direction`, `vulnerability_classes[]`) filled for every carried direction.

### 3.3 Prompt composition (patterns)

The overall prompt is composed with `/prompt-engineering-patterns` discipline: role-based system prompt (the skill,
section 5) setting behaviour + evidence standard at system level; the per-pair user prompt rendering ONLY the current
pair's symbolic render (no batched screens, filters, or pipeline noise - the pair under analysis plus its projection /
materialisation / fold family / witness). Deterministic, sorted rendering (the codebase's deterministic-prompt
convention). Structured output stays the actor's `ToolStrategy(GateDecision | MatchVerdict)` - the prompt never asks
for free-text JSON.

## 4. The tool surface (bound onto the actor turn)

Exactly D67-04's three tools, bound onto the orchestrator's session agent (the `create_agent` via
`app/llm/session.py::_build_agent`'s `tools=`), so the turn is a real tool-calling turn:

1. **`back_edge`** - raise a targeted-recon need via `recon/control/targeted.py::request_targeted_recon` with
   `origin="hunting"` (IA-6). Real body; fail-open when the recon seam is absent (returns a denoted error, never
   raises into the turn).
2. **`graph_view`** - the read-only L0/L1 view (`attack/hunting/hunt_orchestrator.py::ReadOnlyGraphView`): read
   index cards / typed facets; write-shaped calls rejected (C5). Real body; fail-open when no graph is reachable
   (degrades to an empty view, O5).
3. **`store_reads`** - the store reads (#202): the hunt-config reads (prior configs by revival key, #70/#68;
   retrieve-before-re-dispatch for the reuse gate footing) AND the **sibling hunter-memory reads** - the downstream
   TestImplementationSpecs + the Q16 durable PodExport insights by the `::` `config_key`, shallow-projected (I3),
   feeding the config's `prior_hunt_insights`. Real body; fail-open when no store is configured (empty insights, O4).
   The tool's description carries this extended capability.

Tool-availability degradation mirrors the #108 capability gate: when a seam body is unavailable, the tool is either
not bound (the surface shrinks) or returns a fail-open stub result - it never aborts the turn.

**NO HuntConfig-writing tool.** Confirmed against the current graph logic: `GateDecision` returns only `directions`
(`EnvisionedDirection`); `mint_hunt_config` (D3) is called deterministically from the dispatch stretch on the carried
direction. The LLM seeds the config through the three direction fields (`rationale`, `research_direction`,
`vulnerability_classes`), never writes the config object.

**Relation to the #110 seam note ("NO LLM-facing store tool").** The #110 ticket's seam-wiring section stated the hunt
store stays the append-only audit trail with "NO LLM-facing store tool (fault attributes are rendered in the per-fault
matching prompt)". That note was about the fault-KB/audit rendering, and the operator has since ratified (in the
grilling for THIS ticket) the #82 D67-04 surface: `store_reads` IS one of the orchestrator's three tools. The store
remains LLM-WRITE-FORBIDDEN (no store-write or fabricate tool); only reads (prior-hunt insights, candidates, results
by revival key) are surfaced. This spec follows the operator's current ruling; the #110 seam note is superseded for the
orchestrator's read tool and left untouched elsewhere.

**Extensibility.** The surface is declared for growth: orchestrator memory (#70) and web search are future additions
to THIS surface, contributed at the same `_build_agent` seam - this work neither builds nor stubs them beyond the
declared surface shape.

## 5. The skill mounts

- **`skills/hunting/hunt-orchestrator/SKILL.md`** - the gate turn's system prompt: the cognitive architecture of
  section 3.2, the fixed sub-problem decomposition, the evidence-criticality standard, the prune-only-on-positive
  rule, the emit contract. Mounted through the EXISTING `_gate_skill()` loader (which already resolves this path -
  today it falls back). Mechanism-typist-inspired; approved verbatims land directly from
  `skills/analysis/technical-system/SKILL.md` (the hypothesise-and-verify / judge-critically passages).
- **`skills/hunting/hunt-orchestrator-rematch/SKILL.md`** - the re-match judge's system prompt: the same
  evidence-criticality discipline narrowed to the D2 three-valued re-match after a back-edge, mounted through
  `_rematch_skill()`.
- **Pattern.** System prompt + composed turn (the actor's existing `[SystemMessage(skill), HumanMessage(prompt)]`),
  the same serving pattern the mechanism-typist and the hunting-agent use. The llm.py fallbacks stay as the degraded
  lane behind the mounts (CODING_STANDARD - a missing mount never crashes the turn).

## 6. Observability

A `attack/hunting/orchestrator_tracing.py` mirroring `hunting_tracing.py`/`analyser_tracing.py`:

- one span per orchestrator gate turn, session = run id (`session_id=run_id`), tags attack/hunting/orchestrator -
  the shared v4 recipe (span = node name, no Langfuse scores);
- a nested step span for the symbolic render (which pair, which slots degraded) and for the gate turn's output
  (carried/pruned directions, seed fields);
- Langfuse optional and fail-open - the elapsed unit tier runs untraced;
- a `flush_orchestrator_traces()` mirror.

## 7. Delivery semantics and degradation (unchanged contract, confirmed)

The O1-O10 canon, the fail-open/honour clauses and the C1-C12/E1-E16 catalogue of the orchestrator spec are UNCHANGED.
This work adds artifacts to the LLM turn; it must not change report shape, trail semantics, store records, or the
deterministic stages. The one new degradation family is the per-slot degrade of the symbolic render (section 3.1) and
the per-tool degrade of the surface (section 4), both silent-and-counted, never raising.

## 8. User stories

1. As the hunt-orchestrator, I want the gate turn to receive the unit's typed projection, so that the selection
   reasons over the live L1 spine and edges rather than a unit id string.
2. As the hunt-orchestrator, I want the gate turn to receive the fault's materialisation-facet content, so that the
   selection is grounded in the CWE NL evidence, not a bare fault-class label.
3. As the hunt-orchestrator, I want the gate turn to receive the sub-fault fold family under the parent fault, so that
   the folded variants are consideration material while the parent bounds the fault.
4. As the hunt-orchestrator, I want a cognitive-architecture system prompt (backward-from-the-end, consecutive
   sub-problems, hypothesise-and-verify, prune-only-on-positive), so that every carried direction is seeded with a
   usable rationale, assumptions, test primitives and payload vectors.
5. As the hunt-orchestrator, I want the tool surface bound on my turn, so that I can ground in the graph, read
   prior-hunt insights, and raise targeted-recon needs from within the reasoning, not through the harness only.
6. As an operator, I want the three tools exactly (no HuntConfig-writing tool), so that the mint stays deterministic
   and D67-04's surface stays enforced.
7. As an operator, I want a tool surface declared for memory and web search additions, so that #70 and future search
   land without reshapinng the actor.
8. As an operator, I want the gate turn traced (span per turn, run-correlated, fail-open), so that selection quality
   is inspectable exactly as the analysis and hunting-agent turns are.

## 9. Out of scope

- The ranker body (#71), the budget governor (#71), the `FaultSource` engine (#66/#71), the hunt-store persistence
  design (#68), the memory system (#70), the back-edge trigger wiring (#64), the hunting agent itself.
- The mechanism or content of the tool bodies beyond their existing seams (a `back_edge` / `graph_view` / `store_reads`
  body that exists today is reused, not rewritten).
- The graph topology: NO new nodes or routing (the symbolic render lives inside the reason stretch).
- Structured-output schema changes: `GateDecision` / `EnvisionedDirection` / `MatchVerdict` are unchanged.