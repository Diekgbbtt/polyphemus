# Pod triager lifecycle v2: cache-first phase design

**Status:** ratified. Design confirmed by the operator; implementation starts with the ADR and slice 1.
**Branch:** `fix/pod-triager-cache-prefix`.
**Base:** `dev` `7edbf7a6`.
**Date:** 2026-11-14.
**Authority:** iteration E trial `siyucms-web-20261112T074242-38e49ca5` and the 50 pod exports under `10e451a3-025c-4648-a21e-0eec5cf9ebb8`.
**Supersedes:** the four-stage routing in `docs/design/staged-triage-decision-tree-plan.md`.
**Contract under revision:** `docs/design/hunting-67-test-executor-pod-spec.md` section 8.11.

## Verdict

The four-stage chain is over-granular.
It is not, however, the direct cause of the 25.56% cache hit ratio.
The direct cause is that each stage encodes its identity in the system prompt at position 0.
The provider caches a token prefix, so a new system prompt resets the reusable prefix to zero.
The chain then pays that reset 42 times in one trial.

Two of the four stages are also not judgments.
`runner_failed` is a property of the Runner step.
`has_populated_procedure(spec)` is a property of the spec.
The harness already computes both in Python.
Asking a model to re-derive them adds turns and schema surface without adding information.

The target lifecycle has two phases, one immutable system prompt, one constant tool surface, and one append-only per-pod thread.

## Evidence

The trial ran 50 pods and 57 loop iterations.
47 iterations reached a model triage decision.
The other 10 aborted before triage: 5 pod-watchdog timeouts, 3 node timeouts, and 2 read-only graph-view refusals.

The 47 decisions split by classification:

| Path | Decisions | Share |
|---|---:|---:|
| Stage A confirmed the symptom | 28 | 60% |
| Stage B found a divergence | 3 | 6% |
| Stage C or D decided the tail | 16 | 34% |

Stage A's `runner_failed` branch fired 0 times.
Stage B was reached on 19 decisions and fired 3 times, or 16% of its entries.

The usage ledger records 105 triager calls:

| Metric | Value |
|---|---:|
| Calls | 105 |
| Cached input | 362,304 |
| Uncached input | 1,054,973 |
| Generated | 77,850 |
| Total | 1,495,127 |
| Hit ratio | 25.56% |
| Mean prompt per call | 13,498 |

The ledger has no per-call rows and no stage dimension.
The stage path is also not persisted on the pod export.
These counts are inferred from the decision classification, not read from a stage trace.

## The current tree

```text
ENTRY  after the Runner observation
  |
  +-- symbolic evaluate_symptom
  |     +-- confirmed ----------------> T(successful, symptom-confirmed)
  |     +-- infeasibility ------------> T(unsuccessful, technical-infeasibility)
  |
  +-- else
      v
    A ASSESS        system=pod-triage.md       tools=none
      |
      +-- runner_failed --------------> V(runner-failure)
      +-- symptom_confirmed ----------> T(successful, symptom-confirmed, clean=TRUE)
      |
      v
    B DIVERGE       system=pod-divergence.md   tools=none
      |
      +-- runner_diverged ------------> V(runner-divergence)
      |
      v
    has_populated_procedure(spec)
      |
      +-- true --> C MINE      system=pod-triager.md   tools=full + skills
      +-- false -> D TERMINAL  system=pod-terminal.md  tools=none
      |
      +-- action=variant ------------> V(classification) --> next lap --> ENTRY
      +-- action=terminate ----------> T(verdict, terminal_reason, clean)
```

Transition predicates, exactly as the code evaluates them:

| Edge | Predicate | Owner |
|---|---|---|
| A to T | `TriageDecision.symptom_confirmed` | model |
| A to V | `TriageDecision.runner_failed` | model, but deterministic in fact |
| A to B | neither flag | model |
| B to V | `DivergenceDecision.runner_diverged` | model |
| B to C/D | not diverged | model |
| C/D to V | `action == "variant"` | model |
| C/D to T | `action == "terminate"` | model |
| B to C vs D | `has_populated_procedure(spec)` | harness |

Two edges are harness facts.
One is a model judgment dressed as a harness fact.
Three are genuine model judgments.

## Why the cache misses

A provider caches the token sequence from position 0.
The cached span is the longest common prefix between two requests.
An append at the tail extends that prefix.
An edit at position 0 resets it.

The current staged lane calls `stateful_turn` with a different `system_prompt` per stage.
Stage C also adds `skill_reference_middleware`, which appends a skill reference line to the system prompt.
Stage C also binds more tools, and tool schemas sit in the cached prefix.
So every stage boundary breaks the prefix at or near position 0.

The counts close the argument:

| Call class | Count | Prefix reuse |
|---|---:|---|
| First call of a pod thread | 40 | none, cold |
| Stage entry after a stage switch | 42 | none, head changed |
| Call inside a stage's own tool loop | 23 | full, append-only |
| Total | 105 | |

The arithmetic is exact for the counts.
It is a two-parameter fit for the tokens.
The observed split is 362,304 cached and 1,054,973 uncached.
The model is roughly 40 cold calls at the mean prompt, 42 warm switches at a slightly smaller prompt, and 23 in-stage calls at a slightly larger prompt.
The total matches within one percent.
The conclusion does not depend on the fit: 42 of 82 stage entries start a fresh prefix.

The cache is working as designed.
The design permits cache reuse only inside one stage's tool loop.

## Design smells

### S1. The system prompt carries stage identity

The prefix head is stage-scoped, so state that is structurally shared is encoded as if it were stage-local.
This is the primary smell.
It turns every phase boundary into a cache barrier.

### S2. Two gates are not model judgments

`runner_failed` is a fact of the Runner step.
The harness knows it from `RunnerStep` and from the observation's error fields.
`has_populated_procedure` is a pure spec check.
Neither needs a turn.
The trial confirms the first: `runner_failed` fired 0 times in 47 decisions.

### S3. The four nodes mix two axes

Stage A and Stage B are lifecycle gates.
Stage C and Stage D are decision content.
The chain presents them as one tree.
That is why Stage A and Stage D both own terminal vocabularies.
It is also why Stage A's `clean` field is discarded and the confirmed path hardcodes `clean=True`.

### S4. Stage D loses its reason to exist under a constant tool surface

Stage D exists to avoid the miner's tool surface.
Q4 binds one tool set on every stage.
With that constraint, Stage D is Stage C with variant minting disabled.
That is a branch, not a stage.

## The target lifecycle

### Invariants

1. One system message per pod thread.
   It contains the static contract only: role, third-party stance, what you read, surgical conciseness, observation integrity, evidence sufficiency, output discipline.
   It never contains a spec, a skill name, a phase verbatim, or a stage label.
2. One tool surface per pod thread.
   It is bound once and identical on every turn and every lap.
3. One first human message per pod thread.
   It is the base layer.
   It contains the spec, the verification symptoms, the identity, the assumptions, the bound-skill listing, the v0 variant seed, the first lap's observation and trail, and the `ASSESS` verbatim.
4. Everything after the base is append-only.
   The harness appends AI turns, tool calls, tool results, and phase gates at the tail.
   The harness never inserts, edits, or removes a message.
5. Compaction is the only sanctioned rewrite.
   It rewrites the whole thread once and identically, never one stage at a time.

These invariants also buy a second-order cache win.
The system message and the tool schemas are byte-identical across pods.
A provider that caches per account can reuse that shared head even on a pod's first call.
Any per-pod skill reference in the system prompt would destroy that reuse.
That is why Q5 moves the skill listing to the first human message.

### Tree

```text
BASE  system contract (immutable) + tool schemas (constant)
      first human message: spec, symptoms, procedure, skill listing, v0,
                           first observation and trail, ASSESS verbatim
  |
  v
ASSESS  one turn
        first lap: the verbatim and material ride the base human message
        later laps: the material rides a new human message at the tail
        material: observation, symptoms, identity, assumptions,
                  typed procedure, executed probe trail, raw integrity fields
  |
  +-- runner_failed (harness fact) -------> V(runner-failure)
  +-- symptom_confirmed -------------------> T(successful, symptom-confirmed, assessed clean)
  +-- runner_diverged ---------------------> V(runner-divergence)
  |
  v
DECIDE  one turn
        phase verbatim and material arrive in the decide gate response
        material: variants tried, interpretations, KB flags,
                  memory guidance, variant_allowed
  |
  +-- action=variant and variant_allowed --> V(classification) --> next lap, same thread
  +-- action=variant and not allowed ------> T(unsuccessful, no-symptom-evidence, assessed clean)
  +-- action=terminate --------------------> T(verdict, terminal_reason, assessed clean)
  +-- runner_terminated (harness fact) ----> variant rejected; T(evaluated verdict, reason, clean)
```

### Turn counts

| Outcome | Current stage entries | Target turns |
|---|---:|---:|
| Confirmed | 28 | 28 |
| Diverged | 3 plus 3 assess entries | 3 |
| Tail | 16 plus 16 assess entries plus 19 divergence entries | 32 |
| Total stage entries | 82 | 63 |

The target removes 19 turns.
It also converts 23 warm entries from prefix resets to prefix appends.

### Phase verbatims

The converged system prompt holds only what is true on every turn.
The phase-specific text moves to the phase boundary:

- `ASSESS` verbatim: confirmation rule, divergence rule, clean rule, note rule.
- `DECIDE` verbatim: variant-minting algorithm, duplicate rule, terminal vocabulary, exhaustion rule.

The first `ASSESS` has no prior tool call to answer, so its verbatim and material ride the base human message.
Every later lap appends a new human message at the tail; the verbatim is already in the thread, so the new message carries the lap material and a one-line pointer to the `ASSESS` contract.
The response of `submit_assessment` carries the DECIDE verbatim and material when the route continues.
The response of `submit_decision` carries the terminal acknowledgement.
The gate is a real tool call: `submit_assessment` and `submit_decision`.
No verbatim is a system prompt and no verbatim is a mid-thread insertion.

### Skills

The first human message renders the listing of the bound skills.
The `load_skill` tool description keeps only the usage contract.
It does not advertise the available skills.
It must also stop claiming that the system prompt carries the direct references; the first human message does.
The `skill_reference_middleware` does not run for `pod_triager`.
The skill names never enter the system prompt.

### Why two phases

One phase would force the decide material onto the 60% confirmed path.
That material is the variants, the interpretations, the KB flags, and the memory guidance.
The confirmed path does not need it.
Four phases pay two extra turns on the tail and two extra prefix resets.
Two phases is the floor that keeps the common path cheap and the tail correct.

## Harness pattern (Q6)

The triager adopts the hunting agent's turn-by-turn pattern exhaustively.
The source of truth is `src/polymerhus/attack/hunting/hunting_agent.py`, `hunter_state.py`, and `hunter_graph.py`.
The triager is one stateful session per pod.
One `arun_session_turn` call is one step.
The harness is the sole tool executor.
The tool definitions ride the request as OpenAI tool dicts.
No ToolNode executes them.
The harness reads the model's real tool calls off the turn and executes them itself.

The mapping is direct:

| Hunter pattern | Triager adoption |
|---|---|
| `arun_session_turn` per step | one triage step |
| `request_tools` as OpenAI dicts | the full triager surface, constant |
| `tools_by_name` plus `invoke_tool` | same |
| `detect_phase_signal(tool, args)` | `detect_triage_signal(tool, args)` |
| `StateGraph` with supervise, detect, advance | same, phases `assess`, `decide`, `done` |
| `TRANSITION_HINTS[exited]` | the phase packet |
| hint appended to the gate tool response | the packet appended to the gate response |
| hint consumed once | same |
| `observed_signal`, `injected_constant`, `trail` channels | same |
| never gate a work tool, never reject a signal | same |
| provider failure propagates | same |
| `extra_tags=[run_id]` | `[run_id, mem_key, lap, phase]` |

### The triage state machine

`TriageGraphState` carries `phase`, `observed_signal`, `observed_args`, `observed_outcome`, `injected_constant`, `assessment`, `trail`, and `decision`.
`observed_args` is the gate payload the accepted signal carried.
The graph has three nodes, mirroring `build_hunter_graph`:

```text
supervise
  phase == done            -> END
  observed_signal present  -> detect
  otherwise                -> None, the drive returns

detect
  assessment, confirmed    -> decision(successful, symptom-confirmed), done
  assessment, failed       -> decision(variant, runner-failure), done
  assessment, diverged     -> decision(variant, runner-divergence), done
  assessment, negative     -> advance(decide)
  decision, terminate      -> decision(verdict, terminal_reason), done
  decision, variant        -> decision(variant, classification), done
  decision, variant, not allowed -> decision(unsuccessful, no-symptom-evidence), done

advance
  phase = decide
  injected_constant = the DECIDE packet
  trail = one entry
```

The triage graph selects a decision, never a pod terminal.
The pod graph's terminal node renders the `PodExport` from that decision.
The finalizer applies the monotonicity rule.

`detect_triage_signal` is a pure function.
It maps `submit_assessment` and `submit_decision` to a signal.
Every other tool returns None.
It never raises.
The gate tool body validates the args and returns a coded acceptance or rejection; it never mutates the trial state.
The harness accepts the signal only when the gate tool result says it accepted the call.
This mirrors the hunter's authoritative exits (`_store_write_ok`): a coded rejection persists no exit, so it is no signal and the phase stays put.
The harness passes the accepted args as `observed_args`, and the detect node reads them.

`runner_failed` is not in the assessment schema.
The pod node computes it from the latest observation: an `error_code`, a `fatal` flag, or no HTTP status with a non-zero returncode.
A `warning` alone is not a failed execution; the triager judges it under `clean`.
The same path carries `runner_exhausted`, `runner_terminated`, `variant_allowed`, the lap number, and the thread id as a `TriageFacts` record.
`runner_terminated` is the control-plane end reason, and it makes `variant_allowed` false.
The facts are prompt material and graph state, never model fields.
The injected `triager_fn` seam receives them as an explicit argument.

### The turn loop

The loop mirrors `build_hunting_agent`:

```python
new_messages = [HumanMessage(base_content)]
for step in range(MAX_TRIAGE_STEPS):
    turn = await arun_session_turn(
        POD_TRIAGER_ROLE, thread_id, new_messages,
        checkpointer=ctx.checkpointer,
        tools=request_tools,
        system_prompt=contract,
        middleware=list(pod_middleware()) + triager_binding_middleware,
        extra_tags=[run_id, mem_key, f"lap:{lap}", f"phase:{state['phase']}"],
        usage_scope=project_id,
        ...)
    tool_calls = _last_tool_calls(turn.messages)
    if not tool_calls:
        new_messages = [HumanMessage(gate_correction(state["phase"]))]
        continue
    results = []
    for tc in tool_calls:
        result = await invoke_tool(tools_by_name, tc["name"], tc["args"])
        signal = detect_triage_signal(tc["name"], tc["args"])
        if signal is not None and not _gate_accepted(result):
            signal = None
        if signal is not None:
            state = await triage_graph.ainvoke(
                {**state, "observed_signal": signal, "observed_args": tc["args"]})
        packet = state.get("injected_constant")
        if packet:
            result = f"{result}\n\n<phase-packet>\n{packet}\n</phase-packet>"
            state["injected_constant"] = None
        results.append(ToolMessage(tool_call_id=tc["id"], content=result))
    new_messages = results
    if state["phase"] == "done":
        break
```

A malformed gate call returns a coded rejection, so `_gate_accepted` is false and `triage_graph.ainvoke` never runs.
The model still receives the rejection as its tool result and can correct it.

A turn with no tool call is a model error, not a verdict.
The harness appends a short correction message naming the gate tool and continues, bounded by `MAX_TRIAGE_STEPS`.
If the budget exhausts without a gate call, the node degrades to `no-symptom-evidence` with `clean=false` and a named note.
That is the same honest degrade the current malformed-decision path uses.

The phase packet has two parts.
The first part is the phase verbatim.
The second part is the phase material: the assess delta or the decide delta.
The packet is a tool response, never a system prompt and never a mid-stack insert.

### The transcript

```text
[system]   pod-triager-contract.md          immutable, identical across pods
[human]    base: root spec, identity, skills, v0, ASSESS verbatim
[ai]       work tool calls, optional
[tool]     work tool results
[ai]       submit_assessment {...}
[tool]     "assessment recorded" + DECIDE packet
[ai]       submit_decision {...}
[tool]     "decision recorded"
[ai]       no tool call, the loop ends
```

The base human message carries the ASSESS verbatim.
This is the one phase verbatim that is not a tool response, because no prior tool call exists to answer.
The DECIDE verbatim rides the `submit_assessment` response.
A later lap appends a material message at the tail; the ASSESS verbatim is already in the thread.

### What the current code changes

- `default_triage_fn`, `default_divergence_fn`, and `default_terminal_fn` become one harness loop.
- `default_triager_fn` becomes the harness loop that owns the session, the gate tools, and the state machine.
- `TriageStages` and `make_staged_triager` are removed.
- Four `stateful_turn(schema=...)` calls become one `arun_session_turn` loop per decision.
- The `triager_messages` SystemMessage seed is removed.
- The phase machine is a compiled `StateGraph`, not Python routing in `make_staged_triager`.

The injected `triager_fn` seam remains for the contract tier.
`triager_stages` is retired.

## Measurement (Q7)

The intent is confirmed.
One mechanism I proposed is wrong.
`extra_tags` writes Langfuse trace tags.
It does not add a ledger dimension.
The durable ledger is keyed by `(project_id, agent)` and records flat cumulative axes.

So `extra_tags` cannot price a phase in the ledger.
Use them for trace joins only: `thread:<mem_key>`, `lap:<n>`, `phase:<assess|decide>`, and `phase:close` for the bounded closing turn that answers the final gate call.

The ledger needs three additive counters to compute the marginal ratio.
Add to the entry surface:

- `first_calls`: the count of turns that opened a new pod thread.
- `first_uncached`: the uncached input those turns read.
- `first_cached`: the cached input those turns read, normally zero.

The session marks the first turn of a cold thread.
It is the only layer that knows whether the checkpoint state is empty.
It sets `usage_first_call` in the run config metadata.
`TokenUsageMiddleware` reads the flag and calls `record(..., first_call=True)`.
This is exact on a resumed thread, where the triager's own lap counter cannot know.
This is a small, additive change.
It grows `by_agent` and `SPECTRUM_FIELDS` by three count fields.
The eval projection consumes them; the existing axes are unchanged.

Report three numbers:

1. `prefix_hit_ratio` = cached over cached plus uncached. Current 25.56%. Target about 55% to 62%.
2. `marginal_hit_ratio` = (cached minus `first_cached`) over ((cached minus `first_cached`) plus (uncached minus `first_uncached`)). Current about 41%. Target above 85%.
3. `first_call_share` = (`first_cached` plus `first_uncached`) over (`cached` plus `uncached`). This is the ceiling's complement.

Record the phase path on the interpretation: `assess`, `assess>decide`, `assess>variant`, `assess>decide>variant`, `assess>decide>terminal`.
The path is a product record.
The ledger counter is the cost record.

The headline ratio is a poor KPI.
It is bounded by the unavoidable first call of each pod thread.
With 40 threads and 1,417,277 total prompt tokens, the ceiling is about 62%.
That ceiling is not a defect.
It is the price of a per-pod spec.

## The ownership model (Q9)

The operator split the old `clean` word into three concerns with three owners.
The internal triager architecture mirrors the split.

| Concern | Owner | Carrier | Not this |
|---|---|---|---|
| Observation integrity (`clean`) | Triager | `submit_assessment.clean`, carried into the terminal | Not a harness grep, not a coverage score |
| Evidence sufficiency | Triager | The action: a variant, or a terminal reason | No schema field |
| Domain verdict (`verdict`, `terminal_reason`) | Triager | `submit_decision` | Not the last lap's default |
| Infrastructure terminal | Harness | `PodTerminal.infrastructure` | Not a triager choice |
| Durable finality | Finalizer | First non-empty domain verdict wins | Not a caller policy |

### `clean` is fully triager-owned

The harness grep is not an accurate proxy for observation integrity.
The triager reads the raw observations anyway, so the judgement belongs to it.
The three concrete defects vanish:

- The confirmed path no longer hardcodes `clean=True`; it carries the assessment's `clean`.
- `_clean_from_trail` is removed.
  It checked only `returncode` and ignored `stderr` and the structured `success: false` (FF-06).
- A later terminal cannot overwrite a written domain verdict (FF-07, below).

The ASSESS packet carries the raw fields the judgement needs for every executed probe:

- `status`, `returncode`, `stdout`, `stderr`;
- `error_code`, `error_message`, `warning`;
- `fatal`, `recovery`, `session_state`;
- the structured `success` when the tool payload is a JSON object that carries it.

The latest observation keeps its full body up to the existing body slice.
The executed trail carries the integrity fields for every probe.
The probe line names `success=true|false|unknown`, so a masked shell failure is visible.

The prompt gains a dedicated `Observation integrity (clean)` section.
It defines the test from the raw fields, not from a summary.
It spends the extra attention the operator asked for.

### Evidence sufficiency has no field

Sufficiency answers a different question:
was the probe space covered well enough to claim the symptom is absent?
It is not observation integrity.
A clean observation can be insufficient; an unclean observation can be sufficient.

The prompt gains a dedicated `Evidence sufficiency` section.
The assessment result is implicit in the action:

- a variant decision means "not sufficient, and here is the next test";
- unclean or partial observations mean "partial coverage": mint a variant that covers the unobserved execution modes;
- `space-exhausted` means "sufficient and clean";
- `no-symptom-evidence` means "not sufficient, or the observations are impaired".

There is no `evidence_sufficient` field.
The terminal vocabulary already encodes the answer, and the parent's derivation reads it.

### `space-exhausted` requires clean observations

A `space-exhausted` terminal over `clean=false` is a contradiction.
It must not emerge at all, so the gate blocks it before the terminal.
This is the operator's canonical case, not an edge case:
unclean or partial observations mean some execution path was never observed.

The `submit_decision` gate rejects a `space-exhausted` decision when the assessment's `clean` is false.
The coded rejection names the contradiction and the two legal corrections:

- a partial-coverage assessment plus a variant that covers the unobserved execution modes;
- `no-symptom-evidence`, when no variant is possible.

The prompt's `Evidence sufficiency` section states the rule before the model can break it:
an unclean or partial trail is not an exhausted space, so the canonical move is a variant.
`variant_allowed` decides only whether the variant can be minted now, never whether the space is exhausted.

The terminal coherence guard stays as an unreachable-in-practice backstop.
It logs a named defect when it fires, because that means the gate was bypassed.

The #304 degraded-KB guard keeps its terminal-reason downgrade.
It no longer forces `clean=false`, because degraded KB is a sufficiency condition, not an integrity condition.
A `space-exhausted` claim over degraded KB becomes `no-symptom-evidence`; the triager's `clean` stands.

### Every domain terminal comes from the triager

The old exhausted path selected `space-exhausted` or `no-symptom-evidence` from `_clean_from_trail`, bypassing the triager.
That is the second half of the ownership defect.
The new routing is:

- an exhausted stretch WITH observations routes to the triager with `runner_exhausted=true`;
  the triager mints a variant or writes the verdict and its `clean`;
- an exhausted stretch with NO observation stays a harness terminal (`no-symptom-evidence`, `clean=false`), because there is nothing to judge;
- a budget cap or runner kill routes to the triager for a final pass with `runner_terminated=<reason>` and `variant_allowed=false`.

Two structural terminals stay harness-owned:

- the spec's INIT validation rejection (`technical-infeasibility`, `clean=false`), because the spec itself is malformed and no probe exists;
- the runner's INIT-gate `infeasible` terminal (`technical-infeasibility`, `clean=false`), because the runner proved the assumptions false before any triage evidence exists.

The triager has nothing to add to either.
Both are named exceptions, not a silent fallback.

## Verdict monotonicity (Q9)

The guarantee is structural, not a convention.
`finalize_pod` is the ONE writer, so the rule lives there.

1. A durable DOMAIN verdict is final.
   The existing envelope carries `verdict in (successful, unsuccessful)` and `evidence.terminal_reason` in `DOMAIN_TERMINAL_REASONS`.
   No later write replaces it, whatever `replace_existing` says.
2. A harness terminal is not a domain evaluation.
   A domain verdict may replace it, because the pod did evaluate after the infrastructure stop.
   A harness terminal never replaces a domain verdict.
3. A second harness terminal may replace an earlier harness terminal only through the existing `replace_existing` policy.
   This keeps the scheduler backstop from overwriting the pod's own infrastructure stop.
4. An export with no `verdict`, an empty `verdict`, or no terminal reason is not evaluable.
   It does not latch, and the next write may fill it, even from the `replace_existing=False` backstop.
   This is the operator's "if it does not exist or empty, it can't be evaluated".
   The backstop rule therefore applies only to an evaluable terminal.

The graph reflects the first written verdict.
`_export` returns the envelope's verdict and reason, not the attempted terminal fields, so the in-memory result and the durable record never disagree.

### The control plane keeps the runner end reason

The harness owns the runner end reason whenever it kills the runner.
The kill paths are a runner node timeout, a tool timeout, and the pod budget cap.
The harness records the reason as a `control_plane_end_reason` fact before any triage.

A kill is not a reason to skip triage.
The triager still evaluates the most recent runner loop execution, and its note reports the attempted kill chain.
It evaluates the real attribute: `runner_diverged`, `symptom_confirmed`, or another domain outcome.
The harness passes `runner_terminated=<reason>` in `TriageFacts`, so `variant_allowed` is false and the triager must terminate.

The routing is therefore runner kill to the triager, not runner kill to a harness terminal.
The triager runs under its own node timeout.
If it writes a domain verdict, rule 2 lets it replace the harness terminal.
The harness end reason is never erased; it is carried additively as `evidence.control_plane_end_reason`, optional on every other export.

Two failures still finalize directly, because no further node can run:

- a graph recursion limit, which cannot admit another node at all;
- a context window overflow on the runner.

If the triager itself fails or times out, the harness terminal stands.
A provider failure is re-raised, as today (#329); the surfer owns the retry, and no domain verdict is fabricated.
That is rule 2 in the other direction: the pod did not evaluate, so the control-plane fact is the honest export.

The two facts coexist without conflict.
A domain verdict says what the evidence shows.
`control_plane_end_reason` says why the runner stopped.
Both are true.

### FF-07 under the rule

The earlier lap's `symptom-absent-partial-coverage` is an interpretation, not a verdict.
It does not latch, because the triager did not terminate.
The new flow removes the silent last-lap selection:

- every domain terminal now comes from a triager decision;
- an exhausted stretch with observations routes to the triager, not to a harness terminal;
- the no-probe exhaustion stays a harness terminal with `clean=false`, because no observation exists to judge.

The triager therefore writes a verdict only when it is willing to own it.
A later session expiry that prevents a verdict leaves the harness terminal standing.
That is honest: the pod never evaluated, so there is no earlier verdict to bury.
No early `symptom-absent-confirmed` terminal is added.
The vocabulary has `space-exhausted` for a clean negative after coverage and `no-symptom-evidence` for a partial or impaired one.

## Clients and rollback (Q8)

My earlier question was ambiguous because it bundled three decisions.
It also used "clients" without naming them.
Here is the concrete map.

### Client classes

1. **The pod seam.** `pod.py::arun_pod` is the only public entry.
   `runtime.py::_production_pod_builder` and `surfer.py::run_pod_session` call it.
   None names a triager stage, so the signature is not a client break.
   The turn count and the export contract are.
2. **The injected test seams.** `build_pod_graph(triager_fn=...)` and `arun_pod(triager_stages=...)`.
   These are the contract tier.
   `test_staged_triage.py` and `test_react_seams.py` depend on the four-stage shape.
   Retiring `TriageStages` is a deliberate breaking change.
3. **The eval harness.** `eval/orchestrator` reads the usage ledger and the `PodExport`.
   It does not name a triager stage.
   It breaks only if the ledger schema or the export schema changes.
4. **The parent hunting agent.** It reads `PodExport.to_envelope()`.
   The fields are `verdict`, `terminal_reason`, `clean`, `iterations`, `interpretations`, and the log.
   A `clean` change is a parent-visible contract change, even if no reader today uses it.
5. **The recon pod.** `recon/domain/pod.py` has its own `build_pod_graph` and `triage_fn`.
   It is not a client of the hunting triager.
6. **Docs and glossary.** Section 8.11, the staged plan, and `src/polymerhus/attack/hunting/CONTEXT.md`.

### Rollback modes

1. **Code revert.** One commit series, no data migration.
   Safe if the export shape is unchanged.
2. **Runtime flag.** `POD_TRIAGER_LIFECYCLE=v1|v2`.
   It enables an A/B in one eval iteration, but it doubles the prompt surface and the test matrix.
3. **Thread namespace.** The checkpointer thread is keyed by run id, spec id, and role.
   A v2 pod that resumes a v1 thread would mix two incompatible transcripts.
   Version the triager thread key for v2 so a mid-run deploy never mixes them.
4. **Export compatibility.** The eval and the parent read the envelope.
   Additive fields are safe.
   A `clean` semantic change is not additive.

The chosen mode is 1, code revert.

Resolved:

- **Q8a, scope: classes 1, 6, and 3.**
  Class 1, the pod seam, keeps its signature.
  The turn count and the export contract change behind it.
  Class 6, the docs and glossary, is rewritten.
  Class 3, the eval harness, gains the three cache ratios and reads the additive ledger counters.
  Class 2, the injected test seams, is updated as part of the implementation.
  The old `TriageStages` seam is retired, not preserved.
  Class 4, the parent hunting agent, is untouched.
  The export shape is unchanged except one optional additive field, `evidence.control_plane_end_reason`; the `clean` value's source changes.
  Class 5, the recon pod, is not a client.
- **Q8b, rollout: code revert only.**
  No runtime flag.
  No thread-namespace versioning.
  The operator accepts that new clients do not resume threads written under the legacy contract.
  A mid-run deploy that resumed one would mix two transcripts, so the deploy must start pods on fresh threads.
- **Q8c, thread key: no change.**
  The role part identifier stays `pod_triager`.
  The legacy-contract assumption covers the compatibility window.

## Migration slices

Each slice is red first, then green, then the next slice.
The independent slices come first.
The main vertical slice is 3 through 9.

1. **Ledger cold-call counters** (class 3, independent).
   - Red: `UsageLedger.record(..., first_call=True)` increments `first_calls`, `first_cached`, and `first_uncached`; a normal record leaves them unchanged.
   - Red: `TokenUsageMiddleware` reads `usage_first_call` from the run config metadata and forwards it.
   - Red: `_entry_surface` and `usage_spectrum` project the three counters.
   - Green.
   - Red: the eval CLI prints `prefix_hit_ratio`, `marginal_hit_ratio`, and `first_call_share`.
   - Green.
2. **Finalizer monotonicity** (class 1, independent).
   - Red: a second domain verdict with `replace_existing=True` returns the first.
   - Red: a harness terminal is superseded by a domain verdict.
   - Red: a superseded harness terminal survives as `evidence.control_plane_end_reason`.
   - Red: a domain verdict is not superseded by a harness terminal.
   - Red: an export with no verdict, an empty verdict, or no reason does not latch.
   - Red: `_export` returns the durable verdict and reason, not the attempted ones.
   - Green.
3. **The prompt contract.**
   - Red: `pod-triager-contract.md` carries role, third-party stance, what you read, surgical conciseness, observation integrity, evidence sufficiency, and output discipline.
   - Red: it carries no skill name, no spec, no phase verbatim, and no stage label.
   - Red: the `ASSESS` and `DECIDE` verbatims are separate files.
   - Green.
4. **The pure state machine.**
   - Red: `detect_triage_signal` maps a valid `submit_assessment` to `assessment` and a valid `submit_decision` to `decision`.
   - Red: a malformed submission maps to None, so the phase does not move.
   - Red: every other tool maps to None and never raises.
   - Red: `advance_triage_state` moves `assess` to `decide` to `done`.
   - Green.
5. **The ASSESS packet.**
   - Red: the packet carries the raw integrity fields for every executed probe.
   - Red: the structured `success` marker reads `true`, `false`, or `unknown`.
   - Red: the latest observation keeps its body slice; the trail is bounded.
   - Green.
6. **The gate tools.**
   - Red: `submit_assessment` validates `symptom_confirmed`, `runner_diverged`, `clean`, and `note`.
   - Red: `submit_decision` validates the terminal and variant fields and has no `clean` field.
   - Red: `submit_decision` rejects `space-exhausted` over `clean=false`; the rejection names a partial-coverage assessment and a variant.
   - Red: `submit_decision` rejects a variant action when `runner_terminated` is set.
   - Red: a malformed submission is a coded rejection, never a phase move.
   - Green.
7. **The harness loop.**
   - Red: one `arun_session_turn` call per step.
   - Red: the same system prompt and the same request-only tool list on every step.
   - Red: the gate response carries the phase packet and the packet is consumed once.
   - Red: no tool call ends the loop; a provider failure propagates.
   - Red: the trace tags carry run, thread, lap, and phase.
   - Green.
8. **The pod graph wiring.**
   - Red: the triager node runs the harness loop and carries the assessment's `clean` into the terminal.
   - Red: `runner_failed` is a harness fact, not a model field.
   - Red: an exhausted stretch with observations routes to the triager.
   - Red: a no-probe exhaustion is a harness terminal with `clean=false`.
   - Red: a runner node timeout or tool timeout routes to the triager with `runner_terminated` set and `variant_allowed` false.
   - Red: the budget cap routes to a final triage pass instead of `budget_terminal`.
   - Red: a graph recursion limit or a context overflow finalizes the harness terminal without triage.
   - Red: a triager failure after a kill leaves the harness terminal standing.
   - Red: the triager's note reports the attempted kill chain on a terminated run.
   - Red: `_clean_from_trail` is gone.
   - Red: the interpretation records the phase path.
   - Green.
9. **The cache-shape contract test.**
   - Run a scripted pod lifecycle through `arun_pod` with a spy `arun_session_turn`.
   - Assert one byte-identical system prompt, one identical ordered tool-definition list, and a strict prefix extension on every message list.
   - Assert the first human message contains the skill listing.
   - Assert no `SystemMessage` is sent in `messages`.
   - Green after slices 3 through 8.
10. **The teardown.**
    - Remove `TriageStages`, `make_staged_triager`, and the four stage callables.
    - Remove the dead `triager_messages` SystemMessage seed.
    - Remove the unused composers.
    - Update `test_staged_triage.py` and `test_react_seams.py` to the new seam.
11. **Docs and the defect sweep.**
    - Rewrite section 8.11 of the pod spec.
    - Mark the old staged plan as superseded.
    - Update `src/polymerhus/attack/hunting/CONTEXT.md`.
    - Write the ADR for the ownership model and the monotonicity rule.
    - Fix the two stale "seven fields" statements against the nine `PROCEDURE_GAP_FIELD` entries.

Baseline before the change: 91 passed across prompts, react seams, staged triage, and context.

## Defects found along the way

- `TriageDecision.clean` is never read. The confirmed path hardcodes `clean=True`. Fixed by the ownership model.
- `_clean_from_trail` checks only `returncode`. Fixed by removing it and giving the judgement to the triager.
- `_guard_degraded_kb` forces `clean=false` on an absence claim. Fixed by keeping the terminal-reason downgrade and leaving `clean` to the triager.
- The exhausted path selects a terminal from `_clean_from_trail`, bypassing the triager. Fixed by routing exhausted-with-observations to the triager.
- `src/polymerhus/attack/hunting/pod/variant_basis.py` says "seven fields" while `PROCEDURE_GAP_FIELD` has nine.
- `prompts/pod-divergence.md` says "its seven procedure fields" while the mapping has nine.
- The `triager_messages` channel seeds a full `pod-triager.md` SystemMessage that the staged lane never sends.
- No stage telemetry exists, so the next trial cannot price a phase.

## Decisions

Resolved:

- **Q6.** One agent session and loop.
  Adopt the hunting agent pattern: `arun_session_turn` per step, request-only tools, harness as sole executor, a `StateGraph` phase tracker, pure signal detection, and the phase packet appended to the gate response.
- **Q7.** Confirmed in intent, corrected in mechanism.
  `extra_tags` is trace-only.
  The ledger gets `first_calls`, `first_cached`, and `first_uncached`.
  The marginal hit ratio is the KPI.
- **Q8a.** Client classes 1, 6, and 3.
- **Q8b.** Code revert only.
  No runtime flag.
  No thread-namespace versioning.
- **Q8c.** The thread key is unchanged.
- **Q9a.** Split the concerns and reflect the ownership model.
  `clean` is fully triager-owned.
  Evidence sufficiency is a prompt section with no field.
  Every domain terminal comes from the triager.
  The finalizer enforces monotonicity.
- **Q9b.** The monotonic verdict is in this branch.
  FF-06 and FF-07 disappear as part of the same change.

Ratified by the operator on 2026-11-14:

- **Monotonicity.** Rules a, b, and c are sound.
  Caveat: the harness control plane still owns the runner end reason when the runner, and therefore the pod, times out.
  Even then the triager still triages the most recent runner loop execution and reports the attempted kill chain in the note.
  The routing is kill to triager, and `evidence.control_plane_end_reason` keeps the control-plane fact after a domain verdict replaces the harness terminal.
- **FF-07.** No early negative.
  An earlier lap's partial-coverage reading is an interpretation, never a verdict.
- **Exhaustion routing.** The split is confirmed.
  Exhausted with observations goes to the triager; a no-probe exhaustion stays a harness terminal.
- **`space-exhausted` coherence.** The terminal downgrade is rejected as a design.
  A contradictory evaluation must not emerge at all.
  Unclean observations are the canonical partial-coverage case, so the gate rejects `space-exhausted` over `clean=false` and steers the model to a variant or to `no-symptom-evidence`.
  The #304 change is confirmed: the reason downgrade stays, and `clean` is no longer forced false.

Open:

- None for the design.
  The next step is the ADR, the glossary, and slice 1.
