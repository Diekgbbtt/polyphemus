# Context lifecycle follow-up implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the white-jotter context report, implement the approved local context fixes, and quantify the context components and the n-turn offload experiment with the same quality at lower occupancy.

**Architecture:** The plan separates three kinds of work.
First, two factual corrections: the 74,649-char message is not the auth store, and the first hunter call is decomposed into system, overview, loop payload, preloaded tool results, and schema.
Second, the approved local fixes: a bounded auth-store summary view, project `authn` skill access, removal of the full skill index with direct internal and project-authn references, context-only CL-3 deduplication, and pod compaction wiring through the existing `after_model` middleware.
Third, the analyses and design proposals: component occupancy, loop-payload entity occupancy, preloaded tool-message inventory, system-prompt compression, and the n-turn offload simulation.
The prompt, loop-payload, and preloaded-message compressions are design decisions; the plan stops for approval before implementing them.

**Tech Stack:** Python 3.12, pytest, LangChain/LangGraph middleware, Langfuse v4 observability, YAML stores, the polymerhus hunting and analysis modules.

---

## Scope and approvals

The user approved these local changes:

- the default `auth_store` read returns the concise core view;
- all agents that use the auth context store can list and load the project-specific `authn` skill;
- the full skill index is removed from the system prompt;
- the system prompt keeps direct references to the internal skills and the project `authn` skill;
- skill discovery moves to the `load_skill` listing mode;
- the CL-3 duplicate is removed with a context-only projection;
- the pod compaction middleware is wired with the existing LangGraph `after_model` pattern;
- the cache-stable compaction claim is verified and corrected if necessary.

The user did not approve:

- an inline tool-response offload in production;
- broad KB/HTTP/graph/exec/store bounds beyond the auth-store core view;
- a task budget or threshold change;
- F-024 stop fencing or post-stop artifact handling;
- trial-record stamping.

The system-prompt compression, loop-payload compression, and preloaded tool-message contract are design-level proposals.
They are diagnosed and proposed in this plan, but not implemented until the user takes the design decision.

## Evidence corrections

### Auth store

The full redacted auth store is not 74,649 chars.
The project auth files are 7,476 bytes:

- `overview.yaml` is 3,792 bytes;
- `credentials.yaml` is 3,684 bytes.

The auth-store tool result is 22,302 chars in the modeller session.
The 74,649-char message is the HTTP-history search result in the modeller and the replay result in the pod runner.
The earlier report's CL-1 table swapped the two payloads.
The report must be corrected before the auth-store contract work is presented.

### First hunter call

The first nav1 hunter input is 104,119 chars:

- system message: 27,920 chars;
- application overview: 1,761 chars;
- loop payload: 35,491 chars;
- preloaded tool messages: 37,330 chars;
- JSON framing and request tool schema: the remainder.

The 25k-token figure is plausible at about four characters per token.
The 19k-word figure is a rough token-to-word conversion, not a separate fault.
The missing component in the earlier prose was the preloaded tool result block.
The report must replace the vague component claim with this exact breakdown.

### Cache-stable compaction

`_compact_pass` stages the running summary as:

`region_staged + unfolded + [SystemMessage(summary)] + tail`

The summary is already after the stable region and before the replay tail.
It is not the first message.
The 02:26 cache miss is before the 02:34 pass and follows a five-minute twenty-one-second gap.
The report's cache-breaking fix is withdrawn.
The token-accounting gap remains a separate observation.

## Design-bank mapping

| Concern | Design specification | Code seam | Test seam |
|---|---|---|---|
| Auth-store read and projection | `docs/design/auth-store-220-decisions.md`; `docs/design/analysis-auth-store-view-364-adr.md` | `src/polymerhus/app/auth/tool.py`; `src/polymerhus/app/auth/seams.py` | `tests/app/test_auth_store_tool.py`; `tests/app/test_auth_store_tool_readonly.py`; `tests/app/test_auth_seams.py` |
| Skill index and runtime loading | `docs/design/skill-runtime-loading-222-decisions.md`; `docs/design/progressive-skill-lifecycle-adr.md`; `docs/design/skills-typed-surface-spec.md` | `src/polymerhus/app/llm/skills.py`; `src/polymerhus/app/auth/seams.py` | `tests/recon/test_skills.py`; hunting skill tests |
| Project `authn` skill | `docs/design/authn-antiblock-replayability-237-decisions.md`; `docs/design/auth-store-220-decisions.md` | `src/polymerhus/app/auth/seams.py`; `src/polymerhus/app/llm/skills.py` | `tests/app/test_auth_seams.py`; project-bundle tests |
| Pod filtered context | `docs/design/hunting-67-test-executor-pod-spec.md`; `docs/design/hunting-84-regrounding-decisions.md`; `docs/design/hunting-tools-design.md` | `src/polymerhus/attack/hunting/pod/context.py` | pod context tests |
| Pod compaction | `docs/design/context-compaction-95-decisions.md` (D9); `docs/design/hunting-67-test-executor-pod-spec.md` | `src/polymerhus/attack/hunting/surfer.py`; `src/polymerhus/attack/hunting/pod/pod.py`; `src/polymerhus/attack/hunting/pod/graph.py`; `src/polymerhus/attack/hunting/pod/llm.py` | `tests/attack/pod/test_compaction_seam.py`; `tests/attack/test_hunting_compaction.py` |
| Cache behavior | `docs/design/compaction-caching-investigation.md`; `docs/design/context-compaction-95-decisions.md` | `src/polymerhus/app/llm/compaction.py` | `tests/test_llm_compaction.py`; `tests/test_compaction_wiring.py` |
| Hunter prompt and loop payload | `docs/design/hunting-67-hunting-agent-spec.md`; `docs/design/hunting-83-hunting-agent-implementation.md`; `docs/design/cortex-cognitive-architecture-map.md` | `src/polymerhus/attack/hunting/hunting_agent.py`; `src/polymerhus/attack/hunting/hunter_payload.py` | hunting prompt tests |
| Context occupancy | `docs/design/agent-context-architecture.md`; `docs/design/context-engineering-analysis-diagnosis.md` | Langfuse records and the report | the occupancy analysis |

Before any code task, read the mapped design specification and record the decision anchor in the task notes.
If a task would contradict the design, stop and ask before changing it.

## Approved local fixes

### Task 1: Add the bounded auth-store summary view

**Files:**
- Modify: `src/polymerhus/app/auth/tool.py`
- Test: `tests/app/test_auth_store_tool.py`
- Test: `tests/app/test_auth_store_tool_readonly.py`

**Design anchor:** `auth-store-220-decisions.md` read/projection rules and `analysis-auth-store-view-364-adr.md` D364-3.

- [ ] **Step 1: Write the failing summary test**

```python
def test_read_defaults_to_a_bounded_summary_without_secret_values(tmp_path):
    store = AuthStore(root=tmp_path)
    store.write("p", "overview", {
        "login_endpoint": "https://target.test/login",
        "mechanism": "form",
        "defences": ["csrf"],
        "required_headers": ["x-csrf-token"],
        "technical_conditions": [{"name": "session", "check": "cookie"}],
        "notes": "overview",
    }, origin="operator")
    store.write("p", "accounts.alice", {
        "origin": "operator",
        "credentials": {"username": "alice", "password": "secret"},
        "roles": {"admin": {"username": "alice", "password": "secret"}},
        "default_role": "admin",
        "tokens": {"session": {"value": "secret", "location": "cookie",
                               "target": "target.test", "expiry": "later"}},
    }, origin="operator")

    tool = build_auth_store_tool(project_id="p", store=store, read_only=True)
    out = tool.invoke({"command": "read"})

    assert out["ok"] is True
    assert out["view"] == "summary"
    assert out["value"]["overview"]["login_endpoint"] == "https://target.test/login"
    assert out["value"]["accounts"][0]["name"] == "alice"
    assert "secret" not in str(out)
    assert len(str(out)) < 4000
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/app/test_auth_store_tool_readonly.py -q`
Expected: FAIL because `view` is not an accepted arg or the default is the full state.

- [ ] **Step 3: Implement the summary view and the field selector**

Add a `view` field with `summary` (default), `overview`, `account`, and `full` modes.
Add a `fields` tuple for an explicit projection inside the selected view.
Keep `path` as the narrow dot-path selector.
`path` takes precedence over `view`.
The summary contains:

- all `overview` fields;
- an `accounts` list with `name`, `origin`, `procedure`, role names, `default_role`, and token `location`, `target`, and `expiry`;
- no credential values, token values, snapshots, role credential sets, form selectors, steel profiles, or notes bodies.

The `full` view keeps the current redacted full state.
The read-only and read/write bindings share the same projection helper.

- [ ] **Step 4: Add the narrow-path and full-view tests**

```python
def test_read_path_projects_one_account(tmp_path):
    ...
    out = tool.invoke({"command": "read", "path": "accounts.alice.tokens"})
    assert "secret" not in str(out)
    assert out["value"]["session"]["location"] == "cookie"

def test_read_full_view_is_explicit(tmp_path):
    ...
    out = tool.invoke({"command": "read", "view": "full"})
    assert out["view"] == "full"
```

- [ ] **Step 5: Run the auth-store test files**

Run: `pytest tests/app/test_auth_store_tool.py tests/app/test_auth_store_tool_readonly.py tests/app/test_auth_store.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/app/auth/tool.py tests/app/test_auth_store_tool.py tests/app/test_auth_store_tool_readonly.py
git commit -m "fix(auth): default the auth store to a bounded summary view"
```

### Task 2: Make the project `authn` skill listable and loadable

**Files:**
- Modify: `src/polymerhus/app/auth/seams.py`
- Modify: `src/polymerhus/app/llm/skills.py` if the project bundle path is wrong
- Test: `tests/app/test_auth_seams.py`
- Test: `tests/recon/test_skills.py`

**Design anchor:** `authn-antiblock-replayability-237-decisions.md` and the per-project bundle path in `skill-runtime-loading-222-decisions.md`.

The binding already names `AUTHN_SKILL` in `context["skills"]`.
The diagnosis is whether the project bundle resolves at the canonical live skills root path (`skills/target-specific-procedure/<project_id>/`) and whether the listing includes it.
Do not add a second skill index.
The direct reference belongs in the role system prompt.

- [ ] **Step 1: Write the failing project-skill test**

```python
def test_auth_store_agents_can_list_and_load_the_project_authn_skill(tmp_path):
    skills_root = tmp_path / "skills"
    project = "p1"
    bundle = skills_root / "target-specific-procedure" / project / "authn"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text(
        "---\nname: authn\ndescription: Project authentication procedure\n---\n"
        "# Project authn\nUse the recorded login envelope.\n",
        encoding="utf-8",
    )
    store = SkillStore(root_dir=skills_root)
    binding = auth_capable_binding(
        "hunting_hunter", project_id=project, skill_store=store,
        store=AuthStore(root=tmp_path / "auth"),
    )
    load = next(t for t in binding.tools if t.name == "load_skill")
    assert "authn" in load.invoke({"pattern": "authn"})
    assert "Project authn" in load.invoke({"name": "authn"})
    assert "authn" in binding.context["skills"]
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/app/test_auth_seams.py -q -k authn`
Expected: FAIL because the project bundle is not resolved or not listed.

- [ ] **Step 3: Fix the project-bundle resolution**

Use the canonical live skills root path `skills/target-specific-procedure/<project_id>/<name>/SKILL.md`.
The data root is not a skill location; the removed data-root mirror is not a fallback.
The listing and loader must both use the same `SkillStore` seam.
The `authn` skill must remain project-scoped; do not copy it into the shared catalogue.

- [ ] **Step 4: Add the authn direct-reference assertion**

The role system prompt or the binding context must name `authn` explicitly.
The assertion is in the existing prompt test for the hunter, modeller, pod runner, pod triager, assigner, and mechanism typist.

- [ ] **Step 5: Run the seams and skills tests**

Run: `pytest tests/app/test_auth_seams.py tests/recon/test_skills.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/app/auth/seams.py src/polymerhus/app/llm/skills.py tests/app/test_auth_seams.py tests/recon/test_skills.py
git commit -m "fix(skills): expose the project authn skill to auth-store agents"
```

### Task 3: Remove the full skill index and keep direct references

**Files:**
- Modify: `src/polymerhus/app/auth/seams.py`
- Modify: `src/polymerhus/app/llm/skills.py`
- Test: `tests/app/test_auth_seams.py`
- Test: `tests/recon/test_skills.py`

**Design anchor:** `skill-runtime-loading-222-decisions.md` Q3 index and `progressive-skill-lifecycle-adr.md`.
This is the approved index-removal deviation: discovery moves to the `load_skill` listing.

- [ ] **Step 1: Write the failing direct-reference test**

```python
def test_auth_capable_bindings_use_direct_references_not_the_full_index():
    from polymerhus.app.llm.skills import render_skill_references

    binding = auth_capable_binding("hunting_hunter", project_id="p1")
    line = render_skill_references(binding.context["skills"])
    assert "SKILLS - direct references" in line
    assert "`authn`" in line
    assert "`lightrag-query`" in line
    assert "Skills available through the `load_skill` tool" not in line
    assert len(binding.middleware) == 1
```

The bound role must use the direct-reference middleware, not `skill_index_middleware`.

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/app/test_auth_seams.py -q -k direct_references`
Expected: FAIL because the auth binding still renders the full L1 index.

- [ ] **Step 3: Replace the index middleware with the direct-reference middleware**

Replace `skill_index_middleware` with `skill_reference_middleware` in every
`auth_capable_binding` path.
`render_skill_references` names the bounded skills (the internal skills plus
the project `authn`) and points at the `load_skill` listing.
The `load_skill` listing remains the only full discovery surface.
Do not add the full catalog to the prompt.

- [ ] **Step 4: Add the size feedback loop**

Record the system prompt length before and after for each role.
The index block must disappear; the direct reference block must be shorter.

- [ ] **Step 5: Run the prompt and skills tests**

Run: `pytest tests/app/test_auth_seams.py tests/recon/test_skills.py tests/recon/test_skill_seam.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/app/auth/seams.py src/polymerhus/app/llm/skills.py src/polymerhus/attack/hunting/hunting_agent.py tests
git commit -m "fix(prompts): remove the full skill index and keep direct references"
```

### Task 4: Remove the CL-3 duplicate with a context-only projection

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod/context.py`
- Test: the pod context test file

**Design anchor:** `hunting-67-test-executor-pod-spec.md` S5 8.6 and the memory/context decisions.
The spec schema is unchanged.

- [ ] **Step 1: Write the failing duplicate test**

```python
def test_triager_context_renders_the_typed_procedure_once():
    spec = {
        "fault_keyword": "role-swap",
        "provenance": {
            "skill_procedure": {
                "fault_mechanism": "the role check trusts the session",
                "trust_boundary": "session to role",
                "test_recipe": "swap the role cookie",
            }
        },
    }
    log = ExperimentLog()
    text = log.triager_context(spec, None)
    assert text.count("## Skill procedure") == 1
    assert "skill_procedure" not in text
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `pytest tests/attack/pod -q -k triager_context`
Expected: FAIL because the full spec JSON also carries `provenance.skill_procedure`.

- [ ] **Step 3: Add the spec projection**

Add `_pod_spec_view(spec)` that returns a deep copy with `provenance.skill_procedure` removed.
Use it for the `json.dumps` in both `runner_context` and `triager_context`.
Keep the typed excerpt through `_skill_procedure_context`.
Do not change the spec schema or the store.

- [ ] **Step 4: Verify the runner and triager paths**

Run: `pytest tests/attack/pod -q -k 'runner_context or triager_context or skill_procedure'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/polymerhus/attack/hunting/pod/context.py tests/attack/pod
git commit -m "fix(pod): deduplicate the typed skill procedure in pod context"
```

### Task 5: Wire pod compaction through the existing after_model middleware

**Files:**
- Modify: `src/polymerhus/attack/hunting/surfer.py`
- Modify: `src/polymerhus/attack/hunting/pod/pod.py` only if the production builder does not forward the middleware
- Modify: `src/polymerhus/attack/hunting/pod/graph.py` only if the binding drops it
- Test: `tests/attack/pod/test_compaction_seam.py`
- Test: `tests/attack/test_hunting_compaction.py`

**Design anchor:** `context-compaction-95-decisions.md` D9 and `hunting-67-test-executor-pod-spec.md` T5.
The pattern is the existing `CompactionMiddleware.after_model`, not a new hook.

- [ ] **Step 1: Read the LangGraph after_model primitive**

Use `/langgraph-docs` and the local `src/polymerhus/app/llm/compaction.py` implementation.
Confirm that the production pod path can pass the same middleware sequence to `arun_pod`.

- [ ] **Step 2: Write the failing wiring test**

```python
@pytest.mark.asyncio
async def test_run_pod_session_passes_runner_and_triager_compaction(monkeypatch):
    captured = {}

    async def fake_pod_builder(spec, **kwargs):
        captured.update(kwargs)
        return {"verdict": "successful", "evidence": {}}

    await run_pod_session(
        ...,
        pod_builder=fake_pod_builder,
        runner_middleware=("runner-mw",),
        triager_middleware=("triager-mw",),
    )
    assert captured["runner_middleware"] == ("runner-mw",)
    assert captured["triager_middleware"] == ("triager-mw",)
```

If `run_pod_session` does not accept the middleware, the failing test proves the gap.

- [ ] **Step 3: Run the test and verify it fails**

Run: `pytest tests/attack/pod/test_compaction_seam.py -q`
Expected: FAIL because the production pod path passes the default `()`.

- [ ] **Step 4: Pass the role compaction middleware**

Build the runner and triager middleware with the same `build_role_compaction_middleware` path used by the hunters.
Pass them to the production pod builder and `arun_pod`.
Do not change the threshold or add a task budget.

- [ ] **Step 5: Verify the existing after_model path**

Run: `pytest tests/attack/pod/test_compaction_seam.py tests/attack/test_hunting_compaction.py tests/test_compaction_wiring.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/attack/hunting/surfer.py src/polymerhus/attack/hunting/pod tests/attack/pod tests/attack/test_hunting_compaction.py
git commit -m "fix(pod): wire the after_model compaction middleware"
```

### Task 6: Verify the cache-stable compaction and correct the report

**Files:**
- Modify: the context report on the docs branch

- [ ] **Step 1: Read the staged summary order**

Read `src/polymerhus/app/llm/compaction.py` around the `staged` assignment.
Record the exact order: `region_staged + unfolded + summary + tail`.

- [ ] **Step 2: Correct the cache finding**

State that the summary is already after the stable region.
State that the 02:26 cache miss follows the five-minute twenty-one-second gap and is not caused by the 02:34 pass.
Remove the cache-breaking fix from the recommendations.
Keep the token-accounting gap as a separate observation.

- [ ] **Step 3: Commit the correction**

```bash
git add docs/experiments/unit-threat-model-eval-2026-10-20/CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md
git commit -m "docs(eval): correct the cache-stable compaction finding"
```

## Analysis and design proposals

These tasks produce evidence and a proposal.
They do not change production code.

### Task 7: Quantify all text components of each session context

**Files:**
- Create: `docs/experiments/unit-threat-model-eval-2026-10-20/audit_context_occupancy.py`
- Modify: the context report

- [ ] **Step 1: Fetch the generation records**

Use the Langfuse v4 observations API with `fields core,basic,time,io,usage,trace_context` for the trial window.
Keep the per-session records for the modeller, hunters, pod runners, pod triagers, assigner, and mechanism typist.

- [ ] **Step 2: Parse the input messages**

For each generation, split the input into:

- system prompt;
- tools schema;
- first human message, with the application overview and loop payload separated;
- polyhus-specific components: cognitive map, skill index or direct references, module context, memory guidance, loop/spec rendering;
- visible output;
- reasoning;
- tool-call requests;
- tool responses.

The tools schema is not in the message list; measure it from the request tool definitions.
Use the provider `usageDetails` total as the exact anchor.
Use the component character share and the tokenizer estimate for the split.
Report the residual as tool schema plus request overhead.

- [ ] **Step 3: Average the roles**

Average across sessions for the hunter, pod runner, and pod triager.
Use the single `mechanism_typist` session and the single `assigner` session.
Report both the per-session average and the overall role average.

- [ ] **Step 4: Cross-check the sum**

For every role, sum the components and compare to the provider input total.
If the sum differs by more than the documented residual, stop and fix the attribution.

- [ ] **Step 5: Write the report section**

Add a component table per role with the token estimate and the share of the context.
Add the first-call breakdown with the exact 104,119-char decomposition.
Add the auth-store and HTTP-history correction.

### Task 8: Map the loop-payload entities and propose compression

**Files:**
- Modify the context report

- [ ] **Step 1: Extract the first loop payload**

Use the first nav1 hunter generation.
Separate the 35,491-char loop payload into its entities:

- grounding: unit, loop, technical sharpening, trust agreement, dynamic state, fault, evidence, likelihood, confidence;
- tool surface;
- state summary;
- step protocol;
- application overview coupling line.

- [ ] **Step 2: Measure each entity**

Report the char count and the estimated token share.
Identify the repeated or low-value content.

- [ ] **Step 3: Propose the compressed form**

Keep the same meaning and attention allocation.
Make the payload richer and more direct, not merely shorter.
Show the proposed compressed prompt for the largest entities.
Do not implement it yet.

### Task 9: Inventory the tool descriptions

**Files:**
- Modify the context report

- [ ] **Step 1: Name the 12 tool descriptions**

The first hunter input contains 12 `tool` entries with sizes 8,258, 4,012, 2,490, 2,942, 1,753, 716, 566, 3,845, 2,231, 2,045, 2,104, and 6,345 chars.
Identify the tool and the content class of each.
These are the 12 tool schemas/descriptions, not tool results.

- [ ] **Step 2: State the correction**

The 37,330-char block is the tool-description surface.
It is not a preloaded result block.
The first call carries no tool result; results arrive after the first tool call.
State this correction explicitly.

- [ ] **Step 3: Propose the tool-description contract**

The target proxied environment overview, the data contract, and the success/error semantics are the description surface.
The full usage contracts should move behind `load_skill` or a help lookup.
Propose the minimal description and the projection.
Do not implement it yet.

### Task 10: Map the system prompt and propose compression

**Files:**
- Modify the context report

- [ ] **Step 1: Decompose the 27,920-char system message**

Measure the hunting-agent body, the examples, the cognitive map, and the skill index or direct references.
Measure the same components for the modeller, pod runner, pod triager, assigner, and mechanism typist.

- [ ] **Step 2: Identify duplicates and low-value repetition**

Check role prose repeated in the cognitive map, tool usage repeated in the loop payload, and procedure material repeated in the spec.
Record the exact duplicate spans.

- [ ] **Step 3: Propose the compressed system prompt**

Keep the meaning and the attention allocation.
Make it more direct and richer.
Show the compressed text for the hunter and one pod role.
Do not implement it yet.

### Task 11: Simulate the n-turn tool-response offload

**Files:**
- Create: `docs/experiments/unit-threat-model-eval-2026-10-20/audit_offload_simulation.py`
- Modify: the context report

- [ ] **Step 1: Reconstruct the sample modeller session**

Walk the single threat-modeller session from the first call to the last.
Each model call is a turn.
Track every message in the context progressively.

- [ ] **Step 2: Apply the offload rule**

At turn `t`, a tool response whose originating turn is older than 7 turns is replaced by a 50-token fixed marker.
There is no retrieval call.
Use `age > 7` and record the boundary in the report.
The marker states that the response was offloaded and is not retrievable in this experiment.

- [ ] **Step 3: Compute the context growth**

For each turn, compute the observed input size and the simulated input size.
Report the first call, the peak, the area under the growth curve, and the cumulative input.
Compare the observed session to the simulated session.

- [ ] **Step 4: Add the cache-risk model**

Track the first message whose content changes in each turn.
The prefix before that message can still cache; the suffix cannot.
Report the raw-size improvement and the cache-prefix penalty side by side.
Do not claim a net cost win without both numbers.

- [ ] **Step 5: Report the result**

State whether the n-turn offload improves the raw input context and what it costs in cache stability.
If the cache penalty dominates, say so.

### Task 12: Update the report and close the plan

**Files:**
- Modify: `CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md`
- Modify the plan checkboxes

- [ ] **Step 1: Apply the corrections**

Replace the auth-store 74,649 claim with the auth-store 22,302 and HTTP-history 74,649 facts.
Replace the vague first-call claim with the 104,119-char decomposition.
Remove the cache-breaking fix.
Keep the cache-miss observation as a provider-cache timing finding.

- [ ] **Step 2: Add the new sections**

Add the component occupancy section.
Add the loop-payload entity section.
Add the preloaded tool-message section.
Add the system-prompt component section.
Add the n-turn offload simulation section.

- [ ] **Step 3: Run the final checks**

Run the local fix test suites.
Recompute the occupancy totals.
Recompute the offload comparison.
Verify the report has no unapproved fix presented as implemented.

- [ ] **Step 4: Commit the docs and code**

```bash
git add docs/experiments/unit-threat-model-eval-2026-10-20
git commit -m "docs(eval): add context occupancy and n-turn offload analyses"
```

## Feedback loops

- Every code task is red before green.
- The auth-store default must be measured, not assumed; the default result must be under 4,000 chars and must not contain a secret value.
- The project `authn` skill must appear in the listing and in the loaded body, not only in the binding context.
- The system prompt length must be recorded before and after the index removal.
- The triager context must contain the typed procedure exactly once.
- The pod test must prove the middleware reaches the stateful turns.
- The occupancy table must reconcile to the provider input total within the documented residual.
- The loop payload and tool-description blocks must sum to the first-call message sizes.
- The offload simulation must report the raw improvement and the cache penalty together.
- A design-level prompt/loop/preloaded change stops at the proposal and asks for the design decision.

## Acceptance

- The auth-store default read is bounded, has no secret values, and keeps the narrow path and explicit full view.
- The project `authn` skill is listable and loadable by the agents that use the auth store.
- The full skill index is absent from the system prompt; the internal and project-authn direct references are present.
- The CL-3 triager context has the typed procedure once; the spec schema is unchanged.
- Pod compaction middleware reaches the runner and triager stateful turns through the existing `after_model` pattern.
- The cache-stable correction is in the report.
- The occupancy report breaks down every component and averages the multi-session roles.
- The loop payload, tool descriptions, and system prompt have measured entity tables and compression proposals.
- The n-turn offload simulation reports the observed-versus-simulated growth and the cache-prefix risk.
- No unapproved inline offload, broad bound, task budget, F-024, or record-stamping change is implemented.
- The design-level prompt, loop, and preload proposals are presented for the user's decision before implementation.
