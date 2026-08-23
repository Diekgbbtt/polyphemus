# Hunting-84 Regrounding - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reground the test-executor pod onto the dev session abstractions (HuntSession + stateful_turn + compaction middleware + async-native graph) and reconcile the Q3 vocabulary, while keeping the branch fast-forwardable onto the imminent `95-context-compaction` merge.

**Architecture:** The pod stays a sub-module of the hunting module (DDD). Its two LLM roles (`pod_runner` / `pod_triager`) become `session` roles on `HUNTING_ROLES`. Their sessions reuse the built `HuntSession(run_id, hunt_id, spec, role_id)` (thread `run:{hunt_id}:{spec_hash}:{role}`) with the parent's canonical hash relocated into the pod. Graph nodes own the ContextVar binding (read parent `hunt_session` when present). The pod becomes async-native (`arun_pod` via `ainvoke`, `run_pod` is the `run_coro_blocking` wrapper) with `BaseMessage` + `add_messages` channels. #95 compaction is wired as `build_role_compaction_middleware("pod_runner"|"pod_triager")` middleware on the `stateful_turn` calls, matching every other stateful agent (inspected in `~/polymerhus/.claude/worktrees/95-context-compaction`). `curate_messages` is removed as interim once 95 lands (Q13 mooted). E2E is a bounded hunting pipeline with fallback to an isolated pod scaffold. No stateless fallback remains (Q9) - capability-adaptive layer owns the failure mode (distinct risk pass before final commit).

**Tech Stack:** Python 3.13, LangGraph StateGraph + `add_messages`, `langchain.agents.create_agent` + `ToolStrategy`, `app/llm` session/checkpointer/compaction seams, `HuntSession` SessionAddress, `run_coro_blocking`, pytest.

---

## Ticket map (published 2026-08-21, parent #84)

The regrounding is executed as chained `workflow` tickets on the parent #84, ordered blockers-first with native `blocked_by` edges:

| Ticket | Parent issue | Scope | Notes |
|---|---|---|---|
| T0 | #150 | Differential + `resume_point` removal (D84-30/31/32) | Work-preamble; lands BEFORE the regrounded runner |
| T1 | #151 | Register pod roles + env contract | Plan Task 1 |
| T2 | #152 | Relocate canonical hash + HuntSession address | Plan Task 2 |
| T3 | #153 | Graph-owned ContextVar binding | Plan Task 3 |
| T4 | #154 | Async-native pod, async-only | Plan Task 4 (Q4+Q7) |
| T5 | #155 | Compaction middleware wiring | Plan Task 5 (Q10) |
| T6 | #156 | BaseMessage + add_messages channels | Plan Task 6 (Q5) |
| T7 | #157 | Runner ReAct + KB tool + pod memory + note tool + third-party triager | Plan Task 8 + note-schema (D84-32) |
| T8 | #158 | E2E bounded pipeline + isolated pod scaffold | Plan Task 7 (Q6) |
| T9 | #159 | Living docs in same change + Pass C curate removal | Plan Task 9 (Q11+Q14, D84-13) |
| T10 | #160 | Integration sweep, full suite green, code-review applicability | - |

Edges: T0 -> T2/T4/T6/T7; T1/T2/T3/T4/T5/T6 -> T7 (the runner/triager build); T7 -> T8/T9; T8/T9 -> T10.

## Addressing sequence (grilling outcome -> implementation)

Verdicted now (D84-1..8 in `docs/design/hunting-84-regrounding-decisions.md`): Q1(a), Q2(a.i), Q4(a), Q5(a), Q6, Q10, Q11(high), Q12(a), Q14.
Deferred to distinct passes: Q3 (messages handed to stateful_turn - reframed extensively), Q9/Q7 (drop stateless + sync lane risks), Q13 (curate debt, mooted by 95).
This plan orders the implementation so deferred passes gate only the minimal code that depends on them.

### Task 1: Q1 - Register pod roles + env contract

**Files:**
- Modify: `src/polymerhus/app/llm/providers.py:296-299`
- Modify: `.env.example`
- Modify: `docs/design/statefulness-pattern-matrix.md` (add Hunting rows)
- Test: `tests/test_llm_config.py` or `tests/attack/test_hunting_config.py` (validate hunting bootstrap)

- [ ] **Step 1: Write failing test - roles resolve and validate**
```python
def test_pod_roles_registered():
    from polymerhus.app.llm.providers import HUNTING_ROLES, role_record
    ids = {r.role_id for r in HUNTING_ROLES}
    assert "pod_runner" in ids and "pod_triager" in ids
    assert role_record("pod_runner").agent_mode == "session"
    assert role_record("pod_runner").thinking == "high"
    assert role_record("pod_triager").thinking == "high"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv/bin/python -m pytest tests/test_llm_config.py::test_pod_roles_registered -v`
Expected: FAIL - role not found

- [ ] **Step 3: Add roles to HUNTING_ROLES**
```python
HUNTING_ROLES: tuple[Role, ...] = (
    Role("hunting_orchestrator", "LLM_MODEL_HUNTING_ORCHESTRATOR", "session", "medium"),
    Role("hunting_hunter",       "LLM_MODEL_HUNTING_HUNTER",       "session", "high"),
    Role("pod_runner",           "LLM_MODEL_POD_RUNNER",           "session", "high"),
    Role("pod_triager",          "LLM_MODEL_POD_TRIAGER",          "session", "high"),
)
```

- [ ] **Step 4: Add LLM_MODEL_POD_RUNNER / LLM_MODEL_POD_TRIAGER to .env.example, run test to pass**
Run: `.venv/bin/python -m pytest tests/test_llm_config.py::test_pod_roles_registered -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/polymerhus/app/llm/providers.py .env.example
git commit -m "feat(hunting): register pod_runner/pod_triager as session/high roles"
```

### Task 2: Q2 - Relocate canonical hash + wire HuntSession address

**Files:**
- Create/Modify: `src/polymerhus/attack/hunting/pod/context.py` (or `types.py`) - canonical_spec_hash
- Modify: `src/polymerhus/attack/hunting/hunting_agent.py:221` - import from pod
- Modify: `src/polymerhus/app/llm/session_address.py` - docstring touch if needed
- Test: `tests/attack/pod/test_context.py` - hash determinism

- [ ] **Step 1: Write failing test - canonical hash stable and shared**
```python
def test_canonical_hash_shared_between_pod_and_hunter():
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash
    from polymerhus.attack.hunting.hunting_agent import _canonical_hash
    spec = {"verification_symptoms": ["a"], "payload_vector_space": {"method": "GET"}}
    assert canonical_spec_hash(spec) == _canonical_hash(spec)
```

- [ ] **Step 2: Move helper into pod/context.py, have hunting_agent import it, run test**
Expected: PASS after move; hunting_agent._canonical_hash becomes re-export

- [ ] **Step 3: Add HuntSession derivation helper in pod/pod.py**
```python
def _pod_session_address(run_id: str, hunt_id: str, spec: dict, role_id: str):
    from polymerhus.app.llm.session_address import HuntSession
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash
    return HuntSession(run_id=run_id, hunt_id=hunt_id or "", role_id=role_id, spec=canonical_spec_hash(spec))
```

- [ ] **Step 4: Commit**

### Task 3: Q12 - Graph-owned ContextVar binding (blocks Q4/Q9 wiring)

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/pod.py` - pod session ContextVar
- Modify: `src/polymerhus/attack/hunting/pod/graph.py` - runner_agent/triager nodes bind it
- Modify: `src/polymerhus/attack/hunting/pod/agents.py` - default seams read it via stateful_turn
- Test: `tests/attack/pod/test_graph.py` - graph binds pod session, seams receive typed address

- [ ] **Step 1: Write failing test - nodes bind pod session when hunt_session present**
```python
def test_graph_binds_pod_session_from_hunt_ctx():
    from polymerhus.attack.hunting.llm import hunt_session
    # run graph inside hunt_session, assert default seam sees HuntSession address
```

- [ ] **Step 2: Implement pod _pod_ctx ContextVar + pod_session() manager mirroring hunting/llm.py pattern**
- [ ] **Step 3: Wire runner_agent/triager nodes to bind HuntSession(run_id, hunt_id, spec_hash, role)**
- [ ] **Step 4: Run tests, commit**

### Task 4: Q4+Q7 - Async-native pod, async-only (Q7 VERDICTED: drop sync wrapper)

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/pod.py` - `arun_pod` async only, remove `run_pod` wrapper
- Modify: `src/polymerhus/attack/hunting/pod/graph.py` - async nodes, `_call_maybe_await` pattern, `ainvoke`
- Modify: `tests/attack/pod/*`, `tests/integration/test_test_executor_pod_contracts.py` - migrate to `@pytest.mark.asyncio` / `await arun_pod`
- Test: `tests/attack/pod/test_graph.py` - async entry awaitable via `_await_seam`

- [ ] **Step 1: Write test for `arun_pod` being awaitable via `_await_seam`**
- [ ] **Step 2: Convert nodes to async, `graph.compile().ainvoke`, delete `run_pod` sync wrapper**
- [ ] **Step 3: Migrate 50 contract tests to async, verify parent awaits natively**

> **Note Q3.1:** Graph owns inbox pooling, idle gate is `runner_agent` entry, clear after delta. Agent must use `/overthink` when implementing; harness tracks internal plan execution state (complex).
> **Note Q3.3:** Delta via inbox deletion (reliable), not committed-ids tracking (simpler).

### Task 5: Q10 - Wire #95 compaction middleware (inspected APIs)

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/agents.py` - build_role_compaction_middleware for both roles
- Modify: `src/polymerhus/attack/hunting/pod/pod.py` or `graph.py` - pass middleware=[compaction_mw] into stateful_turn / run_session_turn
- Test: injectable middleware (tests pass compaction=False or fake middleware)

Inspected API (from `~/polymerhus/.claude/worktrees/95-context-compaction`):
```python
from polymerhus.app.llm import compaction as C
mw_runner = C.build_role_compaction_middleware("pod_runner")
mw_triager = C.build_role_compaction_middleware("pod_triager")
# then: stateful_turn("pod_runner", addr, messages, checkpointer=cp, schema=RunnerStep, middleware=[mw_runner])
# or via run_session_turn(middleware=[mw_runner])
# Actor path auto-wires via build_hunter_compaction_middleware pattern; sync-leaf pod uses sync path.
# cached_role_compaction_middleware("pod_runner") is the shared per-role singleton if desired.
```
95 has landed on dev (ff completed); the import is live, no guard needed.

- [ ] **Step 1: Add middleware factories, wire into default_runner_step_fn/default_triager_fn stateful path**
- [ ] **Step 2: Tests with compaction=False stay green**

### Task 6: Q5 - BaseMessage + add_messages channels (no scaffold assumptions)

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/context.py` - _dicts_to_lc / _lc_to_dicts id stamping
- Modify: `src/polymerhus/attack/hunting/pod/graph.py` - Annotated[list[BaseMessage], add_messages] + nodes return appended only
- Test: `tests/attack/pod/test_graph.py` - channels merge correctly, seams receive curated dict views

Caveat: do not assume e2e message creating/feeding scaffold completeness; keep client/server feeding minimal and behind seams.

### Task 7: Q6 - E2E bounded pipeline + isolated pod scaffold

**Files:**
- Create: `tests/e2e/test_test_executor_pod_walkthrough.py::test_trivial_real_run`
- Create: `tests/e2e/test_hunting_chain_walkthrough.py` - full chain 2 candidates (or reuse)
- Skeleton: mint realistic TestImplementationSpec via hunt-store fixture if orchestrator/hunter not yet wired, bring up stack from worktree sibling container.

### Task 8: Q2 sub-decision execution + D84-16/17/18 - runner/procedure, KB tool, note-taking

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/agents.py` - bind `tools=[exec, kb_retrieve]` on the runner's create_agent; add note_tool
- Modify: `src/polymerhus/attack/hunting/pod/prompts.py` - runner prompt = P0-P3 plan + meta-reasoning paradigm (under `/writing-for-agents`), triager prompt = third-party variant miner
- Modify: `src/polymerhus/attack/hunting/pod/tools.py` - kb_retrieve surfaced as a bound tool (KB wiring hole fix per D84-16)
- Modify: `src/polymerhus/attack/hunting/pod/graph.py` - ONE `stateful_turn` per ReAct stretch (Q3.5a), note-taking final step at P3 exhaustion
- Modify: `src/polymerhus/attack/hunting/pod/context.py` (note store/indexing)
- Test: `tests/attack/pod/test_graph.py`, `tests/attack/pod/test_context.py` - notes CRUD, note tool read/write used by triager, KB binding

- [ ] **Step 1: Investigate note tool index/retrieval applicability** - does the existing experiment-log indexing/retrieval cover note requirements, or are new requirements needed (per D84-17).
- [ ] **Step 2: Wire runner create_agent with `tools=[exec, kb_retrieve]`** (fix the KB wiring hole).
- [ ] **Step 3: Rewrite runner/triager prompts per D84-16** (writing-for-agents; use `/overthink`).
- [ ] **Step 4: Add the note-taking tool + P3 terminal note write; triager reads notes.**
- [ ] **Step 5: Commit; document the plan-lives-in-thread decision (D84-18).**

### Task 9: Q11+Q14 - Living docs in same change

**Files:**
- Modify: `src/polymerhus/attack/hunting/CONTEXT.md`, `docs/design/statefulness-pattern-matrix.md`, `docs/design/hunting-67-test-executor-pod-spec.md` (4-value -> 6-value + clean/init_validation), `docs/design/domain-model.md` §3.7 if needed, `docs/design/llm-role-architecture-agent-prompt.md` reservation release, `src/polymerhus/app/llm/session_address.py` docstring.
- Note: `hunting/CONTEXT.md` pod entry gains the ReAct runner + KB tool + note-taking step + third-party triager.

### Deferred distinct passes (gate implementation of their dependent code)

- **Pass A (Q3.5/Q3.6 - VERDICTED as D84-17/18):** Per-stretch ReAct + note-taking final step (D84-17); plan lives in thread, #136 owns the plan-tool (D84-18). No open questions remain - the seam message-handling follows D84-9/10/11/12/16/17/18.
- **Pass B (Q9+Q7 - VERDICTED as D84-14/15):** Stateless lane dropped, sync wrapper dropped; capability-adaptive layer owns failure. Risks recorded and accepted.
- **Pass C (Q13 - VERDICTED):** `curate_messages` removed (95 replaces it); `HUNT_POD_SESSION_TOKENS` deleted.
