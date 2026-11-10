# Iteration E Failure-Mode Fixes Implementation Plan

## Execution status (2026-11-10)

Tasks 1-12 are implemented, tested, and committed on `fix/iter-e-failure-modes`.
The branch is merged to `dev` (delivery commit `080eb12c`).
Both adversarial-review passes are closed: the first found the initial blockers, the second verified the corrections and the remaining residuals.
The rerun is running on the fresh project `fb865e52-719d-4637-ae7f-e6856f571166` under `eval/runs-iteration-e-20261110`.
The steel crawl finished and the analysis/hunting drain is in progress.
The checkpoint-serde allowlist fix is on `dev` but not in the running image; it applies to the next resume or run.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the iteration-E failure modes at their most upstream seam, then rerun the trial.

**Architecture:** The plan moves serially through the bug map in dependency order.
It fixes the analysis proposer contract first, then the recon surface filter, then the three small recon defects, then the pod notes path, then the hunting provenance contract, then the bootstrap auth-persistence contract, and finally the measurement harness.
Each task is one red-green loop at a public seam.
Each task updates the closest system design specification before its commit.

**Tech Stack:** Python 3.13, pydantic, LangChain/LangGraph, pytest, Neo4j, Steel crawl, OpenCode eval orchestrator.

---

## Decision log

These decisions are fixed for the whole plan.

| Decision | Value |
|---|---|
| Chunk cap | `CHUNK_MAX_ASSETS = 120` |
| Cap evaluation | After the stream filter, the `(type, identity)` collapse, and the coherent micro-family grouping; counts Endpoint, Parameter, Header, Secret, and every other streamed type |
| Chunk vision | The assigner and the mechanism typist receive the identical `Chunk` object and `chunk_id`; each narrows with its own `ROLE_ADMITS` |
| Assigner view | Endpoint-only (`ROLE_ADMITS["assigner"] = {"Endpoint"}`) |
| Assigner schema | `AssignerDelta` with `Aggregation(service, endpoints, evidence)` |
| Typist schemas | `SystemExtraction` for systems and witnesses; `SystemLinking` for links |
| Repair backstop | One bounded re-ask per structured turn; on a second `None`, a named `generation_failed` census entry, never a silent empty batch |
| Chunk retry | No requeue; the feed's exactly-once contract stays intact, and the named failure is the escalation signal |
| Provenance | `SpecProvenance` carries only `run_id`, `threat_id`, `unit_id`, `canonical_class`, `web_vulnerability_class`; `baseline_ref` and `playbook` move top-level; `source_recon_refs` and `assumption_ref` are removed |
| Media filter | Keep images and media by default; filter only static, `/_next/static/`, verified CDN, and confidently static template/theme/skin image paths; fail-open on ambiguity |
| Data URIs | Never become manifest endpoints or parameters; reuse `base_and_path` where it fits |
| Q5 account write | The agent passes the full account identifier it already retrieved; a new account is a create; the tool contract carries the exact `snapshot`/`tokens` semantics; no matching feature and no prompt-side account projection |
| Browser persistence | No `persist_context=true` at session end; the authenticated session is persisted through `auth_store` writes |
| Cookie dedupe | Internal request-material projection only; dedupe by cookie name; the token-located entry wins a name collision |
| Q6 corpus | Prefer `unit-spec.yaml`; fall back to `l1-profile.md`; count all nine concretisation fields; attribute by `(unit_id, threat_id)`; count distinct threat files for narrowing; include every threat file with a float `risk` |
| Pod notes | `hunting/test-executor-pod/notes.yaml`; read fallback from legacy `hunting/pod-export/notes.yaml` |

## Work item order

The order is strict.
A task starts only after the previous task is green and committed.

1. Q2c chunk cap and shared-chunk consistency.
2. Q2a assigner component contract.
3. Q2b typist component contract.
4. Q4 media and data-URI filtering.
5. C1 DOM fail-safe.
6. C2 probe-source label.
7. C3 duplicate request cookies.
8. Pod notes path.
9. Q1 provenance ownership.
10. Q5 auth-session persistence contract.
11. Q6 measurement harness.
12. Critical adversarial review.
13. Iteration-E rerun.

## Baseline loop

Run this once before Task 1.
It must be green.

```bash
pytest -q \
  tests/integration/test_chunking_contracts.py \
  tests/integration/test_assigner_contracts.py \
  tests/integration/test_mechanism_typist_contracts.py \
  tests/recon/test_noise_filter.py \
  tests/recon/test_auth_feed.py \
  tests/recon/crawl/steel/test_frontier.py \
  tests/recon/crawl/steel/test_auth.py \
  tests/recon/crawl/steel/test_live_run.py \
  tests/recon/crawl/steel/test_manifest.py \
  tests/attack/test_pod_export_memory.py \
  tests/attack/pod/test_spec_reads.py \
  tests/eval/test_measure_utm.py
```

Expected: all pass.

---

### Task 1: Q2c chunk cap 120 and shared-chunk consistency

**Files:**
- Modify: `src/polymerhus/analysis/chunking.py:48-54`
- Modify: `src/polymerhus/analysis/pod.py:69`
- Modify: `src/polymerhus/analysis/CONTEXT.md:436`
- Modify: `tests/integration/test_chunking_contracts.py:113,121,423,429,512-518`
- Modify: `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md`
- Test: `tests/integration/test_chunking_contracts.py`

- [ ] **Step 1: Write the failing cap test**

Append this test to `tests/integration/test_chunking_contracts.py`.
It uses the existing `_ep` helper.

```python
def test_the_default_cap_is_120_and_counts_every_streamed_asset_type():
    assets = []
    for index in range(121):
        path = f"/api/orders/{index}"
        assets.append(_ep(path))
        assets.append(_parameter(path, f"p{index}"))
        assets.append(_header(path, "X-Trace"))
    chunks = chunks_for_job(JOB, assets)
    assert chunks
    assert max(len(chunk.assets) for chunk in chunks) <= 120
    for chunk in chunks:
        assert len({(a.type, tuple(sorted(a.identity.items()))) for a in chunk.assets}) == len(chunk.assets)
    assert sum(len(chunk.assets) for chunk in chunks) == len(assets)
```

Add the two helpers next to `_ep` if they are absent.

```python
def _parameter(path: str, name: str):
    return AssetDelta(
        type="Parameter",
        identity={
            "name": name,
            "position": "query",
            "endpoint_path": path,
            "baseurl": BASEURL,
        },
    )


def _header(path: str, name: str):
    return AssetDelta(
        type="Header",
        identity={"name": name, "endpoint": path, "baseurl": BASEURL},
    )
```

- [ ] **Step 2: Write the failing shared-chunk test**

Append this test to `tests/integration/test_chunking_contracts.py`.

```python
def test_assigner_and_typist_receive_the_same_chunk_object():
    assets = [_ep("/api/orders/1"), _parameter("/api/orders/1", "page")]
    chunks = chunks_for_job(JOB, assets)
    schedule = build_schedule(chunks, "run-1", roles=("assigner", "mechanism_typist"))
    by_role = {dispatch.role: dispatch for dispatch in schedule}
    assert by_role["assigner"].chunk is by_role["mechanism_typist"].chunk
    assert by_role["assigner"].chunk.chunk_id == by_role["mechanism_typist"].chunk.chunk_id
    assert [a.type for a in admit_for_role(by_role["assigner"].chunk, "assigner")] == ["Endpoint"]
    assert {a.type for a in admit_for_role(by_role["mechanism_typist"].chunk, "mechanism_typist")} == {
        "Endpoint",
        "Parameter",
    }
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest -q tests/integration/test_chunking_contracts.py::test_the_default_cap_is_120_and_counts_every_streamed_asset_type tests/integration/test_chunking_contracts.py::test_assigner_and_typist_receive_the_same_chunk_object
```

Expected: the cap test fails because the default is 300.
The shared-chunk test may pass already; it pins the invariant the user requires.

- [ ] **Step 4: Implement the cap**

Change `src/polymerhus/analysis/chunking.py`:

```python
# The per-chunk packing threshold (#13's asset budget, reshaped 2026-10-21 by
# the F-013 correction, retuned 2026-11-10 from the iteration-E capacity read).
# The builder stacks COHERENT endpoint MICRO-FAMILIES (one endpoint plus the
# headers and parameters that target it) until adding the next micro-family
# would exceed this count. The cap is evaluated AFTER the stream filter, the
# `(type, identity)` collapse, and the micro-family grouping, and it counts
# EVERY streamed asset type: Endpoint, Parameter, Header, Secret, and every
# other type the stream carries. 120 is the operating point: large enough to
# keep a recon job's coherent family set in one dispatch, small enough that a
# malformed tool call cannot hide a whole job's judgments in one generation.
CHUNK_MAX_ASSETS = 120
```

Update the docstring references from 300 to `CHUNK_MAX_ASSETS`.
Update `src/polymerhus/analysis/pod.py:69` and `src/polymerhus/analysis/CONTEXT.md:436` to say 120.

- [ ] **Step 5: Update the existing cap expectations**

In `tests/integration/test_chunking_contracts.py`, replace every hard-coded 300 with `chunking.CHUNK_MAX_ASSETS` or 120 where the test asserts the default.
Keep the `max_assets=300` explicit calls in the safety-valve test if they test the function, not the default.
The assertions become:

```python
assert [len(c.assets) for c in chunks] == [120, 100]
```

for a 220-asset single-family payload, and 120/60 for a 180-asset payload.

- [ ] **Step 6: Run the task tests**

```bash
pytest -q tests/integration/test_chunking_contracts.py
```

Expected: all pass.

- [ ] **Step 7: Update the design spec**

In `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md`, add the 2026-11-10 amendment:

```markdown
The per-chunk packing threshold is `CHUNK_MAX_ASSETS = 120`.
The cap is evaluated after the stream filter, the `(type, identity)` collapse, and the coherent endpoint micro-family grouping.
It counts every streamed asset type, not Endpoints alone.
A single family above 120 is split by the pathological safety valve.
The assigner and the mechanism typist receive the identical `Chunk` object and `chunk_id`; each role narrows it with its own `ROLE_ADMITS` view.
```

- [ ] **Step 8: Commit**

```bash
git add src/polymerhus/analysis/chunking.py src/polymerhus/analysis/pod.py src/polymerhus/analysis/CONTEXT.md tests/integration/test_chunking_contracts.py docs/design/plans/2026-10-15-streamed-pipeline-corrections.md
git commit -m "fix(analysis): cap chunks at 120 and pin the shared role chunk"
```

---

### Task 2: Q2a assigner component contract

**Files:**
- Modify: `src/polymerhus/analysis/analyser_types.py`
- Modify: `src/polymerhus/analysis/assigner.py`
- Modify: `src/polymerhus/analysis/proposer_turn.py`
- Modify: `src/polymerhus/analysis/supervisor.py`
- Modify: `src/polymerhus/analysis/prompts/assigner.md`
- Test: `tests/integration/test_assigner_contracts.py`
- Test: `tests/analysis/test_stateful_invoke_fns.py`
- Docs: `docs/design/analysis-unit-enrichment-assigner-subproblems.md`

- [ ] **Step 1: Write the failing schema and mapping tests**

Append these tests to `tests/integration/test_assigner_contracts.py`.
Import the new types at the top.

```python
from polymerhus.analysis.analyser_types import (
    Aggregation,
    AssignerDelta,
    EndpointRef,
)


def test_C35_assigner_schema_is_component_oriented():
    seen = {}

    def invoke(messages, *, schema=None, system_prompt=None, **_):
        seen["schema"] = schema
        seen["prompt"] = "\n".join(str(m.content) for m in messages)
        return AssignerDelta(aggregations=[
            Aggregation(
                service="checkout",
                endpoints=[
                    EndpointRef(method="GET", path="/orders/1", baseurl=BASEURL),
                    EndpointRef(method="POST", path="/orders/2", baseurl=BASEURL),
                ],
                evidence="path segment /orders",
            )
        ])

    out = assign(_chunk("/orders/1"), invoke_fn=invoke, inventory=INVENTORY, existing_slugs=SLUGS)
    assert seen["schema"] is AssignerDelta
    assert len(out.batch.aggregates) == 2
    assert {a.service_slug for a in out.batch.aggregates} == {"checkout"}
    assert {a.l0.identity["path"] for a in out.batch.aggregates} == {"/orders/1"}
    assert out.batch.aggregates[0].evidence_refs == ["path segment /orders"]


def test_C36_assigner_repair_reasks_once_on_none():
    calls = []

    def invoke(messages, *, schema=None, system_prompt=None, **_):
        calls.append(messages)
        if len(calls) == 1:
            return None
        return AssignerDelta(aggregations=[
            Aggregation(
                service="checkout",
                endpoints=[EndpointRef(method="GET", path="/orders/1", baseurl=BASEURL)],
                evidence="path segment /orders",
            )
        ])

    out = assign(_chunk("/orders/1"), invoke_fn=invoke, inventory=INVENTORY, existing_slugs=SLUGS)
    assert len(calls) == 2
    assert "previous response" in str(calls[1][-1].content).lower()
    assert len(out.batch.aggregates) == 1
    assert out.generation_failed is False


def test_C37_assigner_repair_exhaustion_is_a_named_failure():
    calls = []

    def invoke(messages, *, schema=None, system_prompt=None, **_):
        calls.append(messages)
        return None

    out = assign(_chunk("/orders/1"), invoke_fn=invoke, inventory=INVENTORY, existing_slugs=SLUGS)
    assert len(calls) == 2
    assert out.generation_failed is True
    assert out.batch.aggregates == []
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/integration/test_assigner_contracts.py::test_C35_assigner_schema_is_component_oriented tests/integration/test_assigner_contracts.py::test_C36_assigner_repair_reasks_once_on_none tests/integration/test_assigner_contracts.py::test_C37_assigner_repair_exhaustion_is_a_named_failure
```

Expected: import error for the new types.

- [ ] **Step 3: Add the component schemas**

In `src/polymerhus/analysis/analyser_types.py`, add these models before `L1DeltaBatch`.
Every field carries a `Field(description=...)` because the tool schema is the model-facing contract.

```python
class EndpointRef(BaseModel):
    """The L0 Endpoint identity an aggregation names."""

    method: str = Field(description="HTTP method, for example GET or POST.")
    path: str = Field(description="L0 path, for example /admin/index/index.")
    baseurl: str = Field(description="L0 base URL, for example http://target.")


class Aggregation(BaseModel):
    """One Service's ownership of a group of Endpoints."""

    service: str = Field(
        description="The exact business_function_slug of the Service that owns "
                    "these endpoints. Copy a slug from the inventory."
    )
    endpoints: list[EndpointRef] = Field(
        description="The L0 endpoints this Service aggregates."
    )
    evidence: str = Field(
        default="",
        description="One short sentence naming the path segment or parameter "
                    "that supports the ownership. Omit the aggregation when you "
                    "cannot cite evidence. Never write a placeholder object."
    )


class AssignerDelta(BaseModel):
    """The assigner's complete answer: one group per owning Service."""

    aggregations: list[Aggregation] = Field(
        description="One group per Service. The writer expands each group to one "
                    "AGGREGATES edge per endpoint."
    )
```

Add the mapping function at the end of the module.

```python
def assigner_delta_to_batch(delta: AssignerDelta) -> L1DeltaBatch:
    """Expand the model-facing groups into the curator's per-endpoint union."""
    aggregates: list[AggregatesProposal] = []
    for group in delta.aggregations:
        evidence = [group.evidence.strip()] if group.evidence.strip() else []
        for endpoint in group.endpoints:
            aggregates.append(
                AggregatesProposal(
                    service_slug=group.service,
                    l0=L0Ref(
                        label="Endpoint",
                        identity={
                            "path": endpoint.path,
                            "method": endpoint.method,
                            "baseurl": endpoint.baseurl,
                        },
                    ),
                    evidence_refs=evidence,
                )
            )
    return L1DeltaBatch(aggregates=aggregates)
```

- [ ] **Step 4: Add the one-turn repair helper**

In `src/polymerhus/analysis/proposer_turn.py`, add:

```python
def repair_instruction(tool_name: str) -> str:
    """The one bounded re-ask after a structured turn returns no parseable call."""
    return (
        f"Your previous response did not produce a valid `{tool_name}` tool call. "
        f"Call the `{tool_name}` tool now with ONE complete JSON object. "
        "Do not write the JSON in your message text. "
        "Do not use placeholder objects, and do not invent fields. "
        "Every list entry must match the declared type exactly."
    )


def structured_turn(
    invoke_fn,
    messages,
    *,
    schema,
    system_prompt,
    tool_name: str,
    role: str,
    chunk_id: str,
):
    """One structured turn plus one bounded repair; `(result, generation_failed)`."""
    from langchain_core.messages import HumanMessage

    result = invoke_fn(messages, schema=schema, system_prompt=system_prompt)
    if result is not None:
        return result, False
    repair = list(messages) + [HumanMessage(content=repair_instruction(tool_name))]
    result = invoke_fn(repair, schema=schema, system_prompt=system_prompt)
    if result is None:
        logger.warning(
            "%s: structured generation failed after one repair (chunk=%s)",
            role,
            chunk_id,
        )
        return None, True
    return result, False
```

- [ ] **Step 5: Use the new schema in the assigner**

In `src/polymerhus/analysis/assigner.py`:

1. Import `AssignerDelta` and `assigner_delta_to_batch`.
2. Add `generation_failed: bool = False` to `AssignmentOutcome`.
3. Replace the current `invoke_fn(..., schema=L1DeltaBatch, ...)` and `if raw is None` block with:

```python
    from polymerhus.analysis.analyser_types import AssignerDelta, assigner_delta_to_batch
    from polymerhus.analysis.proposer_turn import structured_turn

    raw, generation_failed = structured_turn(
        invoke_fn,
        ([HumanMessage(content=overview)] if overview else [])
        + [HumanMessage(content=_user_prompt(
            l0_slice, inventory, chained=bool(overview)))],
        schema=AssignerDelta,
        system_prompt=system_prompt,
        tool_name="AssignerDelta",
        role=ROLE,
        chunk_id=chunk.chunk_id,
    )
    if generation_failed:
        return AssignmentOutcome(
            generation_failed=True,
            stats=AssignmentStats(admitted=len(admitted)),
        )
    if raw is None:
        return AssignmentOutcome()
    if isinstance(raw, L1DeltaBatch):
        batch = raw
    else:
        batch = assigner_delta_to_batch(raw)
```

Then pass `batch` to `shape_proposal`.
Keep the existing `except Exception` fail-open around the call.
The legacy `L1DeltaBatch` branch is the compatibility path for unit tests and the one-shot seam; the production schema is `AssignerDelta`.

- [ ] **Step 6: Record the named failure in the pass census**

In `src/polymerhus/analysis/supervisor.py`:

1. Add `generation_failures: int = 0` and `generation_failure_details: tuple[str, ...] = ()` to `PassCensus`.
2. In `analyse_chunked`, create `generation_failures: list[str] = []`.
3. Define:

```python
    def _record_failure(role: str, chunk_id: str, admitted: int) -> None:
        detail = f"{role}:generation_failed chunk={chunk_id} admitted={admitted}"
        generation_failures.append(detail)
        logger.warning("analysis: %s", detail)
```

4. Pass `failure_fn=_record_failure` to `make_assigner_body` and `mechanism_typist_body`.
5. Add the fields to the returned `PassCensus`.

In `src/polymerhus/analysis/assigner.py`, change `make_assigner_body(*, invoke_fn, inventory_fn, failure_fn=None)` and call:

```python
        if outcome.generation_failed and failure_fn is not None:
            failure_fn("assigner", dispatch.chunk.chunk_id, outcome.stats.admitted)
```

- [ ] **Step 7: Update the assigner prompt**

In `src/polymerhus/analysis/assigner.py`:

1. Change every `L1DeltaBatch` mention in `_ROLE_VERBATIM` and `_FEW_SHOTS` to `AssignerDelta`.
2. Replace the output-contract paragraph with:

```python
    "OUTPUT - call the `AssignerDelta` tool. Emit ONE `aggregations` entry per "
    "owning Service. Each entry is `{service, endpoints, evidence}`: `service` "
    "is the exact inventory slug, `endpoints` is the list of L0 endpoints that "
    "Service owns, and `evidence` is ONE short sentence naming the path segment "
    "or parameter you matched. Do not emit `services`, `systems`, "
    "`system_edges`, or any data-modelling list. Never write a placeholder "
    "object, a null endpoint, or an evidence list - `evidence` is a string."
```

In `src/polymerhus/analysis/prompts/assigner.md`:

1. Change the delivery sentence to name `AssignerDelta`.
2. Replace `evidence_refs` examples with `evidence` strings.
3. Add a line: "One aggregation group per Service; list every endpoint that Service owns in that group."
4. Add a line: "Never write a placeholder object; omit the group when you cannot cite evidence."

- [ ] **Step 8: Update the stateful schema test**

In `tests/analysis/test_stateful_invoke_fns.py`, update the expected assigner schema from `L1DeltaBatch` to `AssignerDelta` if the test asserts it.
Keep the legacy one-shot test if it exists.

- [ ] **Step 9: Run the task tests**

```bash
pytest -q tests/integration/test_assigner_contracts.py tests/analysis/test_stateful_invoke_fns.py tests/analysis/test_proposer_turn.py
```

Expected: all pass.
Existing tests that return `L1DeltaBatch` still pass through the compatibility branch.

- [ ] **Step 10: Update the design spec**

In `docs/design/analysis-unit-enrichment-assigner-subproblems.md`, add a section:

```markdown
## Model-facing assigner contract (2026-11-10)

The assigner no longer emits the shared `L1DeltaBatch` union.
It emits `AssignerDelta`:

```text
AssignerDelta { aggregations: [Aggregation { service, endpoints: [EndpointRef], evidence }] }
```

`service` is the exact `business_function_slug`.
`endpoints` lists the L0 endpoints the Service owns.
`evidence` is one short sentence naming the matched path segment or parameter.
The writer expands each group to one `AGGREGATES` edge per endpoint.
The internal curator still consumes `L1DeltaBatch`; the mapping is `assigner_delta_to_batch`.
```

- [ ] **Step 11: Commit**

```bash
git add src/polymerhus/analysis/analyser_types.py src/polymerhus/analysis/assigner.py src/polymerhus/analysis/proposer_turn.py src/polymerhus/analysis/supervisor.py src/polymerhus/analysis/prompts/assigner.md tests/integration/test_assigner_contracts.py tests/analysis/test_stateful_invoke_fns.py docs/design/analysis-unit-enrichment-assigner-subproblems.md
git commit -m "fix(analysis): give the assigner a components-oriented tool contract"
```

---

### Task 3: Q2b typist component contract

**Files:**
- Modify: `src/polymerhus/analysis/analyser_types.py`
- Modify: `src/polymerhus/analysis/mechanism_typist.py`
- Modify: `src/polymerhus/analysis/supervisor.py`
- Modify: `src/polymerhus/analysis/prompts/technical-system.md`
- Test: `tests/integration/test_mechanism_typist_contracts.py`
- Docs: `docs/design/analysis-unit-enrichment-mechanism-typist-subproblems.md`

- [ ] **Step 1: Write the failing typist schema tests**

Append these tests to `tests/integration/test_mechanism_typist_contracts.py`.
Import the new types at the top.

```python
from polymerhus.analysis.analyser_types import (
    EndpointWitness,
    SystemAttributes,
    SystemDefinition,
    SystemExtraction,
    SystemLink,
    SystemLinking,
)


def test_N13_typist_uses_component_schemas():
    inv = ScriptedInvoke(
        systems=SystemExtraction(systems=[
            SystemDefinition(
                kind="ReverseProxy",
                discriminator="__singleton__",
                attributes=SystemAttributes(description="nginx fronts the origin."),
                evidence=[EndpointWitness(method="GET", path="/", baseurl=BASEURL)],
            )
        ]),
        linking=SystemLinking(links=[
            SystemLink(
                service="checkout",
                kind="ReverseProxy",
                discriminator="__singleton__",
                relation="FRONTED_BY",
            )
        ]),
    )
    out = type_mechanisms(_chunk(), invoke_fn=inv, inventory={"services": ["checkout"]})
    assert [s.kind for s in out.systems] == ["ReverseProxy"]
    assert out.systems[0].props["description"] == "nginx fronts the origin."
    assert out.systems[0].evidence[0].label == "Endpoint"
    assert [(e.service_slug, e.rel) for e in out.system_edges] == [("checkout", "FRONTED_BY")]


def test_N14_typist_repair_reasks_each_structured_call_once():
    calls = []

    def invoke(messages, *, schema=None, system_prompt=None):
        calls.append(schema)
        if schema is SystemExtraction and calls.count(SystemExtraction) == 1:
            return None
        if schema is SystemExtraction:
            return SystemExtraction(systems=[])
        return SystemLinking(links=[])

    type_mechanisms(_chunk(), invoke_fn=invoke, inventory={"services": []})
    assert calls.count(SystemExtraction) == 2
    assert calls.count(SystemLinking) == 1


def test_N15_typist_repair_exhaustion_is_a_named_failure():
    calls = []

    def invoke(messages, *, schema=None, system_prompt=None):
        calls.append(schema)
        if schema is SystemExtraction:
            return None
        return SystemLinking(links=[])

    out = type_mechanisms(_chunk(), invoke_fn=invoke, inventory={"services": []})
    assert out.systems == []
    assert calls.count(SystemExtraction) == 2
```

The `ScriptedInvoke` helper needs to accept the new schema types.
Extend its `__call__` mapping:

```python
    def __call__(self, messages, *, schema=None, system_prompt=None):
        self.schemas.append(schema)
        if schema is None:
            return self.prose
        if schema is SystemExtraction:
            return self.systems
        if schema is SystemLinking:
            return self.linking
        return self.systems if schema is L1DeltaBatch else self.linking
```

Keep the legacy `L1DeltaBatch` mapping for the existing tests.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/integration/test_mechanism_typist_contracts.py::test_N13_typist_uses_component_schemas tests/integration/test_mechanism_typist_contracts.py::test_N14_typist_repair_reasks_each_structured_call_once tests/integration/test_mechanism_typist_contracts.py::test_N15_typist_repair_exhaustion_is_a_named_failure
```

Expected: import error for the new types.

- [ ] **Step 3: Add the component schemas**

In `src/polymerhus/analysis/analyser_types.py`, add:

```python
class EndpointWitness(BaseModel):
    method: str = Field(description="HTTP method.")
    path: str = Field(description="L0 path.")
    baseurl: str = Field(description="L0 base URL.")


class HeaderWitness(BaseModel):
    name: str = Field(description="Header name.")
    endpoint: str = Field(description="The endpoint path the header was seen on.")
    baseurl: str = Field(description="L0 base URL.")


class TechnologyWitness(BaseModel):
    name: str = Field(description="Technology name.")
    version: str = Field(default="", description="Observed version, or empty.")


class CertificateWitness(BaseModel):
    subject_cn: str = Field(description="Certificate subject common name.")


Witness = EndpointWitness | HeaderWitness | TechnologyWitness | CertificateWitness


class SystemAttributes(BaseModel):
    description: str = Field(
        description="One or two sentences naming the mechanism and its "
                    "adversarial edge. This is the attribute the next batch reads."
    )
    pages: list[str] = Field(default_factory=list)
    rendering_model: str = ""


class SystemDefinition(BaseModel):
    kind: str = Field(description="A known System kind, for example ReverseProxy.")
    discriminator: str = Field(
        default="__singleton__",
        description="The System discriminator. Use __singleton__ when the kind "
                    "has one instance.",
    )
    attributes: SystemAttributes
    evidence: list[Witness] = Field(
        default_factory=list,
        description="The L0 nodes that witness the mechanism.",
    )


class SystemExtraction(BaseModel):
    systems: list[SystemDefinition] = Field(
        description="One entry per mechanism the reflection identified."
    )


class SystemLink(BaseModel):
    service: str = Field(description="The exact business_function_slug.")
    kind: str = Field(description="The System kind.")
    discriminator: str = Field(default="__singleton__")
    relation: str = Field(
        description="One of EXPOSED_VIA, FRONTED_BY, PROTECTED_BY, ROUTED_BY, "
                    "IDENTIFIED_BY, AUTHENTICATED_BY, AUTHORIZED_BY, SHAPES_DATA_OF."
    )
    role: str | None = None
    realm: str | None = None
    order: int | None = None


class SystemLinking(BaseModel):
    links: list[SystemLink] = Field(
        description="One typed Service-to-System link per evidenced pair."
    )
```

Add the mappings:

```python
def witness_to_l0_ref(witness) -> L0Ref:
    if isinstance(witness, EndpointWitness):
        return L0Ref(label="Endpoint", identity={
            "path": witness.path, "method": witness.method, "baseurl": witness.baseurl,
        })
    if isinstance(witness, HeaderWitness):
        return L0Ref(label="Header", identity={
            "name": witness.name, "endpoint": witness.endpoint, "baseurl": witness.baseurl,
        })
    if isinstance(witness, TechnologyWitness):
        return L0Ref(label="Technology", identity={
            "name": witness.name, "version": witness.version,
        })
    return L0Ref(label="Certificate", identity={"subject_cn": witness.subject_cn})


def system_extraction_to_batch(extraction: SystemExtraction) -> L1DeltaBatch:
    systems = []
    for definition in extraction.systems:
        props = {"description": definition.attributes.description}
        if definition.attributes.pages:
            props["pages"] = list(definition.attributes.pages)
        if definition.attributes.rendering_model:
            props["rendering_model"] = definition.attributes.rendering_model
        systems.append(SystemProposal(
            kind=definition.kind,
            discriminator=definition.discriminator,
            props=props,
            evidence=[witness_to_l0_ref(witness) for witness in definition.evidence],
        ))
    return L1DeltaBatch(systems=systems)


def system_linking_to_batch(linking: SystemLinking) -> L1DeltaBatch:
    return L1DeltaBatch(system_edges=[
        SystemEdgeProposal(
            service_slug=link.service,
            kind=link.kind,
            discriminator=link.discriminator,
            rel=link.relation,
            role=link.role,
            realm=link.realm,
            order=link.order,
        )
        for link in linking.links
    ])
```

- [ ] **Step 4: Use the component schemas in the typist**

In `src/polymerhus/analysis/mechanism_typist.py`:

1. Import the new types and mappings.
2. In `type_mechanisms`, replace the extraction call:

```python
    extraction, extraction_failed = structured_turn(
        invoke_fn,
        [HumanMessage(content=_systems_prompt(inventory))],
        schema=SystemExtraction,
        system_prompt=skill,
        tool_name="SystemExtraction",
        role="mechanism_typist",
        chunk_id=chunk.chunk_id,
    )
    if extraction_failed and failure_fn is not None:
        failure_fn("mechanism_typist", chunk.chunk_id, 0)
    systems_batch = (
        system_extraction_to_batch(extraction)
        if extraction is not None else L1DeltaBatch()
    )
```

3. Replace the linking call:

```python
    linking, linking_failed = structured_turn(
        invoke_fn,
        [HumanMessage(content=_linking_prompt(systems_batch, primary, secondary, owned, inventory))],
        schema=SystemLinking,
        system_prompt=skill,
        tool_name="SystemLinking",
        role="mechanism_typist",
        chunk_id=chunk.chunk_id,
    )
    if linking_failed and failure_fn is not None:
        failure_fn("mechanism_typist", chunk.chunk_id, 0)
    link_batch = system_linking_to_batch(linking) if linking is not None else L1DeltaBatch()
```

4. Add `failure_fn=None` to the `type_mechanisms` signature and to `mechanism_typist_body`.
5. Pass `failure_fn=failure_fn` from `mechanism_typist_body` to `type_mechanisms`.

The legacy `L1DeltaBatch` branch stays for the one-shot seam: if `invoke_fn` returns an `L1DeltaBatch`, accept it as-is.
The repair helper already returns the raw result; this branch is the compatibility path.

- [ ] **Step 5: Update the typist prompts**

In `src/polymerhus/analysis/prompts/technical-system.md`:

1. Replace `L1DeltaBatch` with `SystemExtraction` in the systems-output section and with `SystemLinking` in the links-output section.
2. Replace `systems`/`system_edges` instructions with the new nested shapes:
   - `systems` entries: `kind`, `discriminator`, `attributes {description, pages, rendering_model}`, `evidence`.
   - `links` entries: `service`, `kind`, `discriminator`, `relation`, optional `role`/`realm`/`order`.
3. Keep the witness identity-key guidance; the witness objects are now typed by node kind.
4. Remove the "leave services, aggregates empty" instruction; the schema no longer carries them.
5. Keep the WebPresentation special case: `attributes.pages` and the `<service>::<cluster>` discriminator.

In `src/polymerhus/analysis/mechanism_typist.py`, update `_systems_prompt` and `_linking_prompt` to name `SystemExtraction` and `SystemLinking` and the new shapes.

- [ ] **Step 6: Update the existing typist tests**

In `tests/integration/test_mechanism_typist_contracts.py`:
- Update `test_N2_three_call_sequence_reflection_then_extract_then_link` to expect `[None, SystemExtraction, SystemLinking]`.
- Keep the legacy tests that return `L1DeltaBatch` through the compatibility branch.
- Update tests that assert `L1DeltaBatch` in `inv.schemas` only where the production schema changed.

- [ ] **Step 7: Run the task tests**

```bash
pytest -q tests/integration/test_mechanism_typist_contracts.py tests/analysis/test_mechanism_typist.py tests/analysis/test_technical_system_prompt.py tests/analysis/test_stateful_invoke_fns.py
```

Expected: all pass.

- [ ] **Step 8: Update the design spec**

In `docs/design/analysis-unit-enrichment-mechanism-typist-subproblems.md`, add:

```markdown
## Model-facing typist contracts (2026-11-10)

The typist's structured turns no longer share `L1DeltaBatch`.
The extraction turn emits `SystemExtraction`:

```text
SystemExtraction { systems: [SystemDefinition { kind, discriminator, attributes, evidence }] }
```

`attributes` is `{description, pages, rendering_model}`.
`evidence` is a typed witness union: Endpoint, Header, Technology, or Certificate.

The linking turn emits `SystemLinking`:

```text
SystemLinking { links: [SystemLink { service, kind, discriminator, relation, role?, realm?, order? }] }
```

The internal curator still consumes `L1DeltaBatch`; the mappings are `system_extraction_to_batch` and `system_linking_to_batch`.
```

- [ ] **Step 9: Commit**

```bash
git add src/polymerhus/analysis/analyser_types.py src/polymerhus/analysis/mechanism_typist.py src/polymerhus/analysis/supervisor.py src/polymerhus/analysis/prompts/technical-system.md tests/integration/test_mechanism_typist_contracts.py tests/analysis/test_mechanism_typist.py tests/analysis/test_technical_system_prompt.py tests/analysis/test_stateful_invoke_fns.py docs/design/analysis-unit-enrichment-mechanism-typist-subproblems.md
git commit -m "fix(analysis): split the typist tool contract into extraction and linking"
```

---

### Task 4: Q4 media and data-URI filtering

**Files:**
- Modify: `src/polymerhus/recon/domain/noise_filter.py`
- Modify: `src/polymerhus/analysis/chunking.py:92-198`
- Modify: `src/polymerhus/recon/crawl/steel/manifest.py:198-320`
- Modify: `src/polymerhus/recon/crawl/steel/parameters.py:590-600`
- Test: `tests/recon/test_noise_filter.py`
- Test: `tests/recon/crawl/steel/test_manifest.py`
- Test: `tests/integration/test_chunking_contracts.py`
- Docs: `docs/design/amv-8-filtering-assertions.md`

- [ ] **Step 1: Write the failing filter tests**

Append to `tests/recon/test_noise_filter.py`:

```python
def test_static_cdn_base_paths_are_filtered():
    for path in (
        "/static/logo.png",
        "/assets/logo.svg",
        "/_next/static/media/logo.png",
        "/cdn-cgi/image/width=100/logo.png",
        "/vendor/theme/logo.jpg",
        "/template/default/index/img/banner/1.jpg",
        "/theme/skin/logo.png",
    ):
        assert classify_endpoint(path) == "static"


def test_user_upload_media_stays_recall_biased():
    for path in (
        "/uploads/20181224/10ba9f34431727269dbeadae6dc786f8.jpg",
        "/downloads/report.pdf",
        "/media/clip.mp4",
        "/photo.jpg",
    ):
        assert classify_endpoint(path) != "static"
```

Append to `tests/recon/crawl/steel/test_manifest.py`:

```python
def test_data_uri_flows_never_become_endpoints():
    manifest = build_manifest_from_output(
        _output_with_flow("data:image/png;base64,iVBORw0KGgo="),
        run=_run_block(),
    )
    assert manifest.endpoints == []


def test_http_media_flows_still_become_endpoints():
    manifest = build_manifest_from_output(
        _output_with_flow("http://app.test/uploads/1.jpg"),
        run=_run_block(),
    )
    assert [endpoint.path for endpoint in manifest.endpoints] == ["/uploads/1.jpg"]
```

Use the existing helpers in `test_manifest.py`; add `_output_with_flow` and `_run_block` if absent.

Append to `tests/integration/test_chunking_contracts.py`:

```python
def test_chunk_stream_filters_static_image_base_paths_and_keeps_uploads():
    assets = [
        _ep("/template/default/index/img/banner/1.jpg"),
        _ep("/uploads/20181224/abc.jpg"),
        _ep("/api/orders"),
    ]
    chunks = chunks_for_job(JOB, assets)
    paths = {a.identity["path"] for chunk in chunks for a in chunk.assets if a.type == "Endpoint"}
    assert "/template/default/index/img/banner/1.jpg" not in paths
    assert "/uploads/20181224/abc.jpg" in paths
    assert "/api/orders" in paths
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/recon/test_noise_filter.py::test_static_cdn_base_paths_are_filtered tests/recon/test_noise_filter.py::test_user_upload_media_stays_recall_biased tests/recon/crawl/steel/test_manifest.py::test_data_uri_flows_never_become_endpoints tests/integration/test_chunking_contracts.py::test_chunk_stream_filters_static_image_base_paths_and_keeps_uploads
```

Expected: the static CDN/template paths are still "ambiguous" and the data URI becomes an endpoint.

- [ ] **Step 3: Add the base-path classifier**

In `src/polymerhus/recon/domain/noise_filter.py`, add:

```python
# The static base paths (2026-11-10, iteration-E capacity read). These are
# paths where an image is presentational with high confidence: framework build
# output, the static tree, a CDN image transform, or a theme/template skin.
# The filter is deliberately FAIL-OPEN: an image under any other base path is
# kept, because user-uploaded media can carry executable SVG or be an SSRF /
# path-traversal witness. The token tax of keeping an ambiguous image is
# cheaper than losing that surface.
STATIC_BASE_SEGMENTS = frozenset({
    "static", "assets", "_next", "cdn-cgi", "cdn", "vendor", "vendors",
    "dist", "build", "node_modules", "bower_components",
})
TEMPLATE_IMAGE_SEGMENTS = frozenset({
    "template", "templates", "theme", "themes", "skin", "skins",
})
```

Add the function:

```python
def is_static_base_path(path: str, *, extension: str = "") -> bool:
    """True when `path` sits under a confidently static base path.

    The check is on whole path segments, never substrings. The template/theme/
    skin rule applies to image and media extensions only: a template-rendered
    HTML/PHP route is real surface and stays.
    """
    segments = {
        segment.lower()
        for segment in (path or "").split("?", 1)[0].split("/")
        if segment
    }
    if segments & STATIC_BASE_SEGMENTS:
        return True
    if extension in IMAGE_EXTS | MEDIA_EXTS and segments & TEMPLATE_IMAGE_SEGMENTS:
        return True
    return False
```

Extend `classify_endpoint` before the image/media branch:

```python
    if is_static_base_path(path, extension=ext):
        return "static"
```

Keep the existing `under_drop_path` behavior for the remaining cases.

- [ ] **Step 4: Use the shared classifier in the analysis stream**

In `src/polymerhus/analysis/chunking.py`, import `is_static_base_path` and replace the local `_NOISE_SEGMENTS` check in `is_noise_endpoint`:

```python
    return not is_noise_static_path(...)
```

The simplest change is:

```python
    if is_static_base_path(bare, extension=_endpoint_extension(bare)):
        return True
```

Keep the hard-drop extension check first.
Keep the recall-biased image/media branch out: `is_static_base_path` now owns the static-path decision, and everything else stays.

- [ ] **Step 5: Drop data URIs at the manifest**

In `src/polymerhus/recon/crawl/steel/parameters.py`, change `split_url`:

```python
def split_url(url: str) -> tuple[str, str] | None:
    """The URL path without its query, and the baseurl `scheme://netloc`.

    Only an absolute HTTP(S) URL has a graph endpoint. A `data:` URI, a
    `javascript:` URI, or any other scheme has no base URL and no path, so it
    returns `None` and the caller never mints an endpoint for it.
    """
    parts = urlsplit(normalize_url(url))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return parts.path or "/", f"{parts.scheme}://{parts.netloc}"
```

Update every caller to skip `None`.
In `manifest.py`, the flow loop becomes:

```python
    for flow in flows:
        split = split_url(flow.url)
        if split is None:
            continue
        path, baseurl = split
```

The declared-endpoint loop also checks `base_and_path(declared.url)` before adding the record.
The parameter loop already keys on `parameter.endpoint_key`, and a parameter whose endpoint was skipped is dropped.

- [ ] **Step 6: Run the task tests**

```bash
pytest -q tests/recon/test_noise_filter.py tests/recon/crawl/steel/test_manifest.py tests/recon/crawl/steel/test_parameters.py tests/integration/test_chunking_contracts.py
```

Expected: all pass.
Update any existing test that asserted a data URI or a static CDN image was kept; the new requirement overrides it.

- [ ] **Step 7: Update the design spec**

In `docs/design/amv-8-filtering-assertions.md`, add:

```markdown
## Image and media base-path filter (2026-11-10 amendment)

Images and media are KEPT by default.
They can be user-controlled and can carry executable artifacts such as SVG, so the filter is fail-open.
The filter drops an image or media endpoint only under a confidently static base path:

- `/static/`, `/assets/`, `/_next/static/`;
- verified CDN image paths such as `/cdn-cgi/image/`;
- vendor/build roots (`/vendor/`, `/dist/`, `/build/`, `/node_modules/`, `/bower_components/`);
- template/theme/skin image paths that the Steel crawl identifies as rendered theme assets.

An image under `/uploads/`, `/downloads/`, `/media/`, or any unknown base path stays.
A `data:` URI is never a graph endpoint.
```

- [ ] **Step 8: Commit**

```bash
git add src/polymerhus/recon/domain/noise_filter.py src/polymerhus/analysis/chunking.py src/polymerhus/recon/crawl/steel/manifest.py src/polymerhus/recon/crawl/steel/parameters.py tests/recon/test_noise_filter.py tests/recon/crawl/steel/test_manifest.py tests/integration/test_chunking_contracts.py docs/design/amv-8-filtering-assertions.md
git commit -m "fix(recon): filter confident static media paths and data URIs"
```

---

### Task 5: C1 DOM fail-safe

**Files:**
- Modify: `src/polymerhus/recon/crawl/steel/frontier.py:296-326`
- Test: `tests/recon/crawl/steel/test_frontier.py:607-632`
- Docs: `docs/design/steel-crawl-implementation-plan.md`

- [ ] **Step 1: Rewrite the failing-action test**

Replace `test_a_typed_action_error_stops_with_its_code_and_message` with:

```python
def test_a_typed_action_error_consumes_the_element_and_continues():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(button("e-boom", "Boom"), link("e-a", "A", "/a"))
    )
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")
    graph.failures[(ROOT, "e-boom")] = CommandFailed("the browser did not answer")

    result = graph.frontier().run(root)

    assert result.stop_reason == "frontier_empty"
    assert result.error is None
    assert result.failed[0].element.element_id == "e-boom"
    assert "command_failed" in result.failed[0].error
    assert graph.state.unconsumed(root, [button("e-boom", "Boom")]) == []
    assert graph.executed == [(ROOT, "e-boom"), (ROOT, "e-a")]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest -q tests/recon/crawl/steel/test_frontier.py::test_a_typed_action_error_consumes_the_element_and_continues
```

Expected: `stop_reason == "error"`.

- [ ] **Step 3: Implement the fail-safe**

In `frontier.py`, in the generic `except Exception` branch:

```python
            except Exception as error:  # noqa: BLE001 - a typed action failure
                # One element can fail for a page-level reason that is not the
                # session and not a stale ref. Record the true outcome, consume
                # the element so the frontier never retries it, restore the page,
                # and continue with the next candidate. The traversal ends only
                # when no candidate remains.
                failed.append(
                    FailedVisit(
                        page=current,
                        element=chosen,
                        error=_error_text(error),
                    )
                )
                self._state.consume(current, chosen.fingerprint)
                needs_restore = True
                continue
```

Keep `SessionMissing` and `StaleElement` branches unchanged.

- [ ] **Step 4: Run the frontier suite**

```bash
pytest -q tests/recon/crawl/steel/test_frontier.py
```

Expected: all pass.
Update any test that asserted a generic action failure stops the run; the new fail-safe is the contract.

- [ ] **Step 5: Update the design spec**

In `docs/design/steel-crawl-implementation-plan.md`, add:

```markdown
A typed action failure that is not `StaleElement` and not `SessionMissing` is a per-element failure.
The frontier records the failure in the action ledger, consumes the element fingerprint, restores the page, and continues.
The run ends only when no candidate remains.
This is the DOM fail-safe: one broken element never ends a session that can still traverse.
```

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/recon/crawl/steel/frontier.py tests/recon/crawl/steel/test_frontier.py docs/design/steel-crawl-implementation-plan.md
git commit -m "fix(steel): continue traversal after a per-element action failure"
```

---

### Task 6: C2 probe-source label

**Files:**
- Modify: `src/polymerhus/recon/crawl/steel/auth.py:250-330`
- Modify: `src/polymerhus/recon/crawl/steel/live.py:630-680,844-856`
- Test: `tests/recon/crawl/steel/test_live_run.py`
- Test: `tests/recon/crawl/steel/test_auth.py`
- Docs: `docs/design/crawl-session-fanout-adr.md`

- [ ] **Step 1: Write the failing resolver test**

Append to `tests/recon/crawl/steel/test_live_run.py`:

```python
def test_the_probe_source_names_the_actual_source():
    context = LiveRunContext(
        project_id="proj-1",
        run_id="run-1",
        session_name="steel-proj-1",
        target_url="https://app.test/",
        scope=["app.test"],
        data_root="/tmp",
        root_url="https://app.test/declared",
        auth_probe="https://app.test/declared-probe",
    )
    loaded = SimpleNamespace(
        root_url="https://app.test/loaded",
        auth_probe="https://app.test/loaded-probe",
    )
    assert crawl_session_probe_with_source(context, loaded) == (
        "https://app.test/loaded-probe",
        "session.auth_probe",
    )
    loaded_no_probe = SimpleNamespace(root_url="https://app.test/loaded")
    assert crawl_session_probe_with_source(context, loaded_no_probe) == (
        "https://app.test/declared-probe",
        "account.auth_probe",
    )
    assert crawl_session_probe_with_source(
        LiveRunContext(
            project_id="proj-1",
            run_id="run-1",
            session_name="steel-proj-1",
            target_url="https://app.test/",
            scope=["app.test"],
            data_root="/tmp",
            root_url="https://app.test/member",
        )
    ) == ("https://app.test/member", "session.root_url")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest -q tests/recon/crawl/steel/test_live_run.py::test_the_probe_source_names_the_actual_source
```

Expected: import error for `crawl_session_probe_with_source`.

- [ ] **Step 3: Implement the source resolver**

In `src/polymerhus/recon/crawl/steel/live.py`:

```python
def crawl_session_probe_with_source(
    ctx: LiveRunContext, loaded: Any = None
) -> tuple[str | None, str]:
    """The probe URL and the label of the source that supplied it.

    The session's own loaded probe is the most specific source; the account's
    configured probe is next; the session root is the declared default; the
    overview probe is the legacy fallback. An absent probe returns `(None, "")`.
    """
    loaded_probe = getattr(loaded, "auth_probe", None)
    if isinstance(loaded_probe, str) and loaded_probe:
        return loaded_probe, "session.auth_probe"
    configured = getattr(ctx, "auth_probe", None)
    if isinstance(configured, str) and configured:
        return configured, "account.auth_probe"
    root = crawl_session_root(ctx, loaded)
    if root:
        return root, "session.root_url"
    return None, ""
```

Keep `crawl_session_probe` as a thin wrapper.

In `auth.py`, add `probe_source: str = PROBE_SOURCE` to `AuthOracle.__init__` and use `self._probe_source` in `_probe`.
The legacy gate keeps `LEGACY_PROBE_SOURCE`.

In `live.py` `auth_fn`, call the with-source resolver and pass `probe_source=source` to `AuthOracle`.
The manifest `auth.probe_source` then reads `verdict.probe_source`.

- [ ] **Step 4: Update the auth tests**

In `tests/recon/crawl/steel/test_auth.py`, update the default `AuthOracle` tests to expect the default `PROBE_SOURCE` only when no source is passed.
Add:

```python
def test_the_oracle_carries_the_source_it_was_given():
    verdict = AuthOracle(
        fetch_fn=FakeFetch({"status": 200, "redirected": False, "url": PROBE_URL}),
        page_url=PAGE_URL,
        probe_url=PROBE_PATH,
        probe_source="session.auth_probe",
    ).check()
    assert verdict.probe_source == "session.auth_probe"
```

- [ ] **Step 5: Run the task tests**

```bash
pytest -q tests/recon/crawl/steel/test_live_run.py tests/recon/crawl/steel/test_auth.py tests/recon/crawl/steel/test_job.py
```

Expected: all pass.

- [ ] **Step 6: Update the design spec**

In `docs/design/crawl-session-fanout-adr.md`, add:

```markdown
The auth verdict's `probe_source` names the source that actually supplied the probe: `session.auth_probe`, `account.auth_probe`, `session.root_url`, `overview.auth_probe.url`, or `legacy_surface_gate`.
A probe resolved from the loaded session is never labelled as an overview probe.
```

- [ ] **Step 7: Commit**

```bash
git add src/polymerhus/recon/crawl/steel/auth.py src/polymerhus/recon/crawl/steel/live.py tests/recon/crawl/steel/test_live_run.py tests/recon/crawl/steel/test_auth.py docs/design/crawl-session-fanout-adr.md
git commit -m "fix(steel): label the auth probe with its actual source"
```

---

### Task 7: C3 duplicate request cookies

**Files:**
- Modify: `src/polymerhus/recon/control/auth_feed.py:180-221`
- Test: `tests/recon/test_auth_feed.py`
- Docs: `docs/design/crawl-session-fanout-adr.md`

- [ ] **Step 1: Write the failing dedupe test**

Append to `tests/recon/test_auth_feed.py`:

```python
def test_project_request_auth_dedupes_a_cookie_by_name():
    account = {
        "snapshot": {"cookies": [{"name": "PHPSESSID", "value": "snapshot"}]},
        "tokens": {
            "PHPSESSID": {"value": "token", "location": "cookie"},
        },
    }
    material = project_request_auth(account, {})
    assert material["cookies"] == [{"name": "PHPSESSID", "value": "token"}]


def test_project_request_auth_dedupes_repeated_snapshot_cookies():
    account = {
        "snapshot": {
            "cookies": [
                {"name": "sid", "value": "one"},
                {"name": "sid", "value": "two"},
            ]
        }
    }
    material = project_request_auth(account, {})
    assert material["cookies"] == [{"name": "sid", "value": "one"}]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/recon/test_auth_feed.py::test_project_request_auth_dedupes_a_cookie_by_name tests/recon/test_auth_feed.py::test_project_request_auth_dedupes_repeated_snapshot_cookies
```

Expected: duplicate names in the list.

- [ ] **Step 3: Implement the dedupe**

In `auth_feed.py`, add:

```python
def _dedupe_cookies(cookies: list[dict]) -> list[dict]:
    """One cookie per name, first-seen order; a later entry replaces the value.

    The snapshot is the broad capture and the token list is the deliberate auth
    fact, so the token entry wins a name collision. Duplicate snapshot names
    keep the first value. Malformed entries are skipped.
    """
    merged: dict[str, dict] = {}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = cookie.get("name")
        value = cookie.get("value")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(value, str):
            continue
        merged[name] = {"name": name, "value": value}
    return list(merged.values())
```

In `project_request_auth`, build the cookie list in one place:

```python
    cookies: list[dict] = []
    snapshot = account.get("snapshot") or {}
    if isinstance(snapshot, dict):
        snapshot_cookies = snapshot.get("cookies") or []
        if isinstance(snapshot_cookies, list):
            cookies.extend(snapshot_cookies)
    tokens = account.get("tokens") or {}
    if isinstance(tokens, dict):
        for name, entry in tokens.items():
            ...
            elif location == "cookie" and isinstance(name, str) and name:
                cookies.append({"name": name, "value": value})
    if cookies:
        material["cookies"] = _dedupe_cookies(cookies)
```

Keep the header-located token behavior unchanged.

- [ ] **Step 4: Run the task tests**

```bash
pytest -q tests/recon/test_auth_feed.py
```

Expected: all pass.
The existing test that asserts `{"sid", "session"}` still passes.

- [ ] **Step 5: Update the design spec**

In `docs/design/crawl-session-fanout-adr.md`, add:

```markdown
The request-material projection dedupes cookies by name.
The snapshot is the broad capture; the token list is the explicit auth fact, so a token-located cookie wins a name collision.
The projection is internal to the recon request tools; it is never rendered into an agent prompt.
```

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/recon/control/auth_feed.py tests/recon/test_auth_feed.py docs/design/crawl-session-fanout-adr.md
git commit -m "fix(recon): dedupe request cookies by name"
```

---

### Task 8: Pod notes path

**Files:**
- Modify: `src/polymerhus/attack/hunting/pod_export_memory.py:53-160`
- Modify: `src/polymerhus/app/data_root.py`
- Test: `tests/attack/test_pod_export_memory.py`
- Docs: `docs/design/hunting-84-pod-memory-system-spec.md`
- Docs: `docs/design/hunting-67-test-executor-pod-spec.md`

- [ ] **Step 1: Update the failing path test**

Replace `test_pod_export_store_writes_its_own_module_file` with:

```python
def test_pod_export_store_writes_the_pod_module_notes_file(tmp_path):
    store = PodExportStore(tmp_path)
    _write(store)
    path = tmp_path / PROJECT / "hunting" / "test-executor-pod" / "notes.yaml"
    assert path.exists()
    assert not (tmp_path / PROJECT / "hunting" / "pod-export" / "notes.yaml").exists()


def test_pod_export_store_reads_the_legacy_export_bucket(tmp_path):
    legacy = tmp_path / PROJECT / "hunting" / "pod-export" / "notes.yaml"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(yaml.safe_dump([{
        "key": f"{HUNT}:pod-export:{SPEC}",
        "hunt_key": HUNT,
        "note_name": f"pod-export:{SPEC}",
        "kind": "freeform",
        "body": "{}",
    }]), encoding="utf-8")
    store = PodExportStore(tmp_path)
    assert [record["key"] for record in store.read_exports(PROJECT)] == [
        f"{HUNT}:pod-export:{SPEC}"
    ]


def test_pod_export_and_pod_notes_share_one_file(tmp_path):
    store = PodExportStore(tmp_path)
    _write(store)
    memory = PodMemoryStore(project_id=PROJECT, root_dir=tmp_path)
    memory.append(SPEC, order=0, note_name="freeform", kind="freeform", body="x")
    records = yaml.safe_load(
        (tmp_path / PROJECT / "hunting" / "test-executor-pod" / "notes.yaml").read_text()
    )
    keys = {record["key"] for record in records}
    assert f"{HUNT}:pod-export:{SPEC}" in keys
    assert f"{SPEC}:0:freeform" in keys
```

Import `PodMemoryStore` and `yaml` at the top.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/attack/test_pod_export_memory.py::test_pod_export_store_writes_the_pod_module_notes_file tests/attack/test_pod_export_memory.py::test_pod_export_store_reads_the_legacy_export_bucket tests/attack/test_pod_export_memory.py::test_pod_export_and_pod_notes_share_one_file
```

Expected: the new path is absent and the legacy path is written.

- [ ] **Step 3: Implement the path move and fallback**

In `pod_export_memory.py`:

```python
    def _project_dir(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/test-executor-pod", root=self._root)

    def _legacy_notes_file(self, project_id: str) -> Path:
        return project_dir(project_id, "hunting/pod-export", root=self._root) / "notes.yaml"

    def read_exports(self, project_id: str, *, hunt_key: str | None = None) -> list[dict]:
        records = self._read_records(self._notes_file(project_id))
        if not records:
            records = self._read_records(self._legacy_notes_file(project_id))
        if hunt_key is not None:
            records = [record for record in records if str(record.get("hunt_key") or "") == hunt_key]
        return list(reversed(records))
```

`write_export` writes only the new path.
The shared project lock already serialises both stores; the `PodMemoryStore` writes the same file with its own record list.
Keep the pod-export record shape and the `pod-export:` key namespace.

Update `src/polymerhus/app/data_root.py`:

```text
│   ├── test-executor-pod/  # PodMemoryStore + PodExportStore (the durable Q16 exports)
```

Remove the `pod-export/` line.

- [ ] **Step 4: Run the task tests**

```bash
pytest -q tests/attack/test_pod_export_memory.py tests/attack/test_hunting_wiring.py tests/attack/test_hunting_surfer_agent_submodule.py tests/attack/test_hunting_session_watchdog.py
```

Expected: all pass.

- [ ] **Step 5: Update the design specs**

In `docs/design/hunting-84-pod-memory-system-spec.md` and `docs/design/hunting-67-test-executor-pod-spec.md`, replace the `hunting/pod-export/notes.yaml` statement with:

```markdown
The durable pod-export records live in the pod module's own notes file:
`data/<project_id>/hunting/test-executor-pod/notes.yaml`.
They keep the `pod-export:<spec_id>` key namespace and share the one project lock and the one notes bound with the pod's `freeform`/`kb_insight` records.
A read falls back to the legacy `hunting/pod-export/notes.yaml` bucket so an existing run does not lose its exports.
```

- [ ] **Step 6: Commit**

```bash
git add src/polymerhus/attack/hunting/pod_export_memory.py src/polymerhus/app/data_root.py tests/attack/test_pod_export_memory.py docs/design/hunting-84-pod-memory-system-spec.md docs/design/hunting-67-test-executor-pod-spec.md
git commit -m "fix(hunting): move durable pod exports into the pod module notes"
```

---

### Task 9: Q1 provenance ownership

**Files:**
- Modify: `src/polymerhus/attack/hunting/spec_contract.py:151-226`
- Modify: `src/polymerhus/attack/hunting/pod/types.py:72-130`
- Modify: `src/polymerhus/attack/hunting/hunter_tools.py:221-296,330-420,1040-1070`
- Modify: `src/polymerhus/attack/hunting/http_history_contract.py:20-120`
- Modify: `src/polymerhus/attack/hunting/pod/symbolic.py:50-70`
- Test: `tests/attack/pod/test_spec_reads.py`
- Test: `tests/attack/test_hunting_agent_prompt.py`
- Test: `tests/attack/test_http_history_tools.py`
- Docs: `docs/design/hunting-67-hunting-agent-spec.md`

- [ ] **Step 1: Write the failing provenance tests**

Append to `tests/attack/pod/test_spec_reads.py`:

```python
def test_the_baseline_ref_is_top_level_and_legacy_provenance_still_reads():
    top_level = {**SPEC, "baseline_ref": "http_TOP"}
    top_level.pop("provenance", None)
    assert baseline_ref_from_spec(top_level) == "http_TOP"
    legacy = {**SPEC, "provenance": {"baseline_ref": "http_LEGACY"}}
    assert baseline_ref_from_spec(legacy) == "http_LEGACY"


def test_provenance_rejects_the_retired_grounding_fields():
    from polymerhus.attack.hunting.spec_contract import SpecProvenance

    with pytest.raises(ValueError):
        SpecProvenance(source_recon_refs=["x"])
    with pytest.raises(ValueError):
        SpecProvenance(assumption_ref="A-1")
    with pytest.raises(ValueError):
        SpecProvenance(baseline_ref="http_1")
    with pytest.raises(ValueError):
        SpecProvenance(playbook="do the thing")
```

Append to `tests/attack/test_hunting_agent_prompt.py`:

```python
def test_the_contract_shows_baseline_and_playbook_at_the_top_level():
    from polymerhus.attack.hunting.hunter_tools import render_spec_contract

    text = render_spec_contract()
    assert "| `baseline_ref` |" in text
    assert "| `playbook` |" in text
    assert "provenance.baseline_ref" not in text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/attack/pod/test_spec_reads.py::test_the_baseline_ref_is_top_level_and_legacy_provenance_still_reads tests/attack/pod/test_spec_reads.py::test_provenance_rejects_the_retired_grounding_fields tests/attack/test_hunting_agent_prompt.py::test_the_contract_shows_baseline_and_playbook_at_the_top_level
```

Expected: the top-level read fails and the retired fields are accepted.

- [ ] **Step 3: Change the provenance contract**

In `src/polymerhus/attack/hunting/spec_contract.py`:

```python
SPEC_PROVENANCE_FIELDS: tuple[str, ...] = (
    "run_id",
    "threat_id",
    "unit_id",
    "canonical_class",
    "web_vulnerability_class",
)
```

Remove `baseline_ref`, `source_recon_refs`, `assumption_ref`, and `playbook` from `SpecProvenance`.
Update the docstring:

```python
"""The symbolic dispatch provenance every hunter spec carries.

Every field is bound by the symbolic layer or copied from the dispatch
payload; the hunter never authors a narrative provenance.
The recorded-baseline pointer and the playbook are top-level spec fields.
"""
```

- [ ] **Step 4: Move the two fields top-level**

In `src/polymerhus/attack/hunting/pod/types.py`, add to `TestImplementationSpec`:

```python
    baseline_ref: str = ""
    playbook: str = ""
```

Place them beside `rationale` and before `skill_concretised_procedure`.
Update the docstring.
Change `baseline_ref_from_spec`:

```python
def baseline_ref_from_spec(spec: dict | TestImplementationSpec | None) -> str:
    """The optional recorded-baseline artifact id.

    The top-level field is the contract. The provenance read is the legacy
    fallback for a spec written before the 2026-11-10 split.
    """
    if isinstance(spec, TestImplementationSpec):
        value = spec.baseline_ref or spec_provenance(spec).get("baseline_ref")
    elif isinstance(spec, dict):
        value = spec.get("baseline_ref") or spec_provenance(spec).get("baseline_ref")
    else:
        value = None
    return value.strip() if isinstance(value, str) else ""
```

- [ ] **Step 5: Update the write contract**

In `hunter_tools.py` `SpecWrite`, add:

```python
    baseline_ref: str = Field(
        default="",
        description="Optional: the recorded-baseline artifact id to replay.")
    playbook: str = Field(
        default="",
        description="Optional: the short procedure the pod should follow.")
```

Update the `provenance` description to name only the symbolic fields.
`render_spec_contract` already iterates `SpecWrite.model_fields`, so the two rows appear automatically.
Update `hunter_tools.py:1057` from `provenance.baseline_ref` to `baseline_ref`.

- [ ] **Step 6: Update the prompt examples**

In `http_history_contract.py`, replace every `provenance.baseline_ref` with `baseline_ref`.
In `hunter_tools.py`, replace the prompt mention.
Keep the tool `get_http_artifact` guidance unchanged.

- [ ] **Step 7: Update the pod reads**

In `pod/symbolic.py`, the call to `baseline_ref_from_spec` already handles both shapes; no change beyond the helper.
In `pod/agents.py`, update the prose from `provenance.baseline_ref` to `baseline_ref`.
In `pod/types.py` and `pod/__init__.py`, update docstrings.

- [ ] **Step 8: Update the fixtures and tests**

Update every test fixture that builds a spec with `provenance.baseline_ref` to use top-level `baseline_ref`.
Keep one legacy fixture to pin the fallback.
Update `tests/attack/test_http_history_tools.py` and `tests/attack/test_hunting_agent_prompt.py` assertions.
Update `tests/hunting_fixtures.py` if it carries the old shape.

- [ ] **Step 9: Run the task tests**

```bash
pytest -q tests/attack/pod/test_spec_reads.py tests/attack/pod/test_symbolic.py tests/attack/pod/test_request_ref.py tests/attack/pod/test_graph.py tests/attack/pod/test_react_seams.py tests/attack/test_http_history_tools.py tests/attack/test_hunting_agent_prompt.py tests/integration/test_hunter_prompt_protocol.py
```

Expected: all pass.

- [ ] **Step 10: Update the design spec**

In `docs/design/hunting-67-hunting-agent-spec.md`, replace the provenance field list with:

```markdown
- `provenance`: the symbolic dispatch context.
  It carries `run_id` (bound by the tool, never authored), `threat_id`, `unit_id`, `canonical_class`, and `web_vulnerability_class`.
  The recorded-baseline pointer is the top-level `baseline_ref`; the playbook is the top-level `playbook`.
  `source_recon_refs` and `assumption_ref` are removed: they were model-authored narrative, not symbolic provenance.
```

- [ ] **Step 11: Commit**

```bash
git add src/polymerhus/attack/hunting/spec_contract.py src/polymerhus/attack/hunting/pod/types.py src/polymerhus/attack/hunting/hunter_tools.py src/polymerhus/attack/hunting/http_history_contract.py src/polymerhus/attack/hunting/pod/symbolic.py src/polymerhus/attack/hunting/pod/agents.py src/polymerhus/attack/hunting/pod/__init__.py tests/attack tests/hunting_fixtures.py docs/design/hunting-67-hunting-agent-spec.md
git commit -m "fix(hunting): make spec provenance symbolic and move baseline/playbook top-level"
```

---

### Task 10: Q5 auth-session persistence contract

**Files:**
- Modify: `src/polymerhus/recon/control/prompts/auth-gateway.md:100-160`
- Modify: `src/polymerhus/recon/control/authn_loop.py:140-165`
- Modify: `src/polymerhus/recon/control/orchestrator_agent.py:160-220`
- Modify: `src/polymerhus/app/auth/tool.py:50-145`
- Modify: `eval/OPERATOR.md:1110-1125`
- Test: `tests/recon/test_authn_skill_writing.py`
- Test: `tests/recon/test_steel_session_only_surfaces.py`
- Docs: `docs/design/auth-store-220-decisions.md`

- [ ] **Step 1: Write the failing contract tests**

Append to `tests/recon/test_authn_skill_writing.py`:

```python
def test_the_authn_contract_persists_through_the_auth_store_not_browser_end():
    from polymerhus.recon.control.prompts import read_prompt

    text = read_prompt("auth-gateway")
    assert 'persist_context=true' not in text
    assert "accounts.<account>.snapshot" in text
    assert "accounts.<account>.tokens" in text
    assert "auth_store" in text
```

If `read_prompt` does not exist, use the existing prompt-loading helper in the test module.

Append to `tests/recon/test_steel_session_only_surfaces.py`:

```python
def test_every_branch_manner_uses_the_auth_store_write():
    from polymerhus.recon.control.orchestrator_agent import _BRANCH_MANNER

    for manner in _BRANCH_MANNER.values():
        assert "persist_context=true" not in manner
        assert "auth_store" in manner
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest -q tests/recon/test_authn_skill_writing.py::test_the_authn_contract_persists_through_the_auth_store_not_browser_end tests/recon/test_steel_session_only_surfaces.py::test_every_branch_manner_uses_the_auth_store_write
```

Expected: the old `persist_context=true` text is present.

- [ ] **Step 3: Rewrite the auth-gateway contract**

In `src/polymerhus/recon/control/prompts/auth-gateway.md`, replace every persistence paragraph with:

```markdown
## Persist the authenticated session through the auth store

Call `browser(command="end")` without `persist_context` when the browser is no longer needed.
The session state is persisted through the `auth_store` tool, not through the browser.

Use the account identifier you already retrieved (or create the new account first).
The write paths are:

- `accounts.<account>.snapshot` with `{cookies, headers, params, captured_at}` for a browser session that will be replayed as request material.
- `accounts.<account>.tokens` with one entry per token: `{value, location: cookie | header | storage, target?, expiry?}`.

A new account is a create at `accounts.<account>`.
An existing account is a field merge at the same path.
The tool contract defines the exact field shapes; read it before the first write.
Do not paste a secret into a prompt or a note.
```

Keep the account-retrieval instructions.
Remove the "record `browser_context.ref`" instruction; the browser context is no longer the persistence channel for the bootstrap.

- [ ] **Step 4: Rewrite the runtime hints**

In `authn_loop.py`:
- Replace the `GENERATION_SIGNIN_HINT` persistence sentence with:

```python
    "After the flow, persist the authenticated session through an `auth_store` "
    "write at `accounts.<account>.snapshot` (cookies/headers/params/captured_at) "
    "or `accounts.<account>.tokens` (value/location/target/expiry). "
    "Do not call `browser(command=\"end\", persist_context=true)`."
```

- Update `FINISH_HINT` to say "persisted through the auth store".

In `orchestrator_agent.py` `_BRANCH_MANNER`, replace every `browser(command="end", persist_context=true)` and `browser_context.ref` instruction with the auth-store write.
For each branch, state the snapshot/tokens choice and the full account path.
Keep the oracle validation instructions unchanged.

- [ ] **Step 5: Clarify the auth-store tool contract**

In `src/polymerhus/app/auth/tool.py` `AUTH_STORE_CONTRACT`, add to the account record paragraph:

```text
A session snapshot is the concrete request state `{headers, cookies, params, captured_at}` and is written at `accounts.<account>.snapshot`.
A token is one entry in `accounts.<account>.tokens`, shaped `{value, location: cookie | header | storage, target?, expiry?}`.
The account identifier is the full `accounts.<name>` path the read returned; a write to a new name is a create, and a write to a known name merges the field.
```

- [ ] **Step 6: Update the operator doc**

In `eval/OPERATOR.md`, replace the `persist_context=true` paragraph with the auth-store persistence contract.

- [ ] **Step 7: Run the task tests**

```bash
pytest -q tests/recon/test_authn_skill_writing.py tests/recon/test_steel_session_only_surfaces.py tests/recon/test_auth_feed.py
```

Expected: all pass.

- [ ] **Step 8: Update the design spec**

In `docs/design/auth-store-220-decisions.md`, add:

```markdown
## Session persistence (2026-11-10 amendment)

The bootstrap no longer persists the browser context at session end.
After authentication, the agent writes the authenticated session to the account it already retrieved:

- `accounts.<account>.snapshot` for request-replayable state;
- `accounts.<account>.tokens` for token-located material.

The account identifier is the full path the read returned; a new account is a create.
There is no prompt-side account matching and no projection of the account catalog into the prompt.
```

- [ ] **Step 9: Commit**

```bash
git add src/polymerhus/recon/control/prompts/auth-gateway.md src/polymerhus/recon/control/authn_loop.py src/polymerhus/recon/control/orchestrator_agent.py src/polymerhus/app/auth/tool.py eval/OPERATOR.md tests/recon/test_authn_skill_writing.py tests/recon/test_steel_session_only_surfaces.py docs/design/auth-store-220-decisions.md
git commit -m "fix(auth): persist the authenticated session through the auth store"
```

---

### Task 11: Q6 measurement harness

**Files:**
- Modify: `eval/measure_utm.py:96-127,262-365,502-647,990-1011,1320-1436`
- Test: `tests/eval/test_measure_utm.py`
- Docs: `eval/CONTEXT.md`
- Docs: `eval/ASSERTIONS.md`

- [ ] **Step 1: Write the failing corpus and procedure tests**

Append to `tests/eval/test_measure_utm.py`:

```python
def test_load_corpus_unit_reads_the_l1_profile_markdown(tmp_path):
    target = tmp_path / "corpus" / "siyucms"
    unit = target / "siyucms-001"
    unit.mkdir(parents=True)
    (unit / "l1-profile.md").write_text(
        "# L1 profile - `siyucms-001` (`Weak Credentials`)\n\n"
        "The target unit is `Service:admin-authentication`.\n\n"
        "## Render block\n\n"
        "```\n"
        "unit kind: Service\n"
        "spine (present keys): ['api_paradigm', 'business_function']\n"
        "outgoing edges:\n"
        "  - DEPENDS_ON: ['AuthenticationMechanism -> kind=AuthenticationMechanism; discriminator=__singleton__']\n"
        "aggregated endpoints:\n"
        "  - method=GET; path=/admin/index/index.html; baseurl=http://web:80; service_slug=admin-authentication\n"
        "```\n",
        encoding="utf-8",
    )
    spec = measure_utm.load_corpus_unit(target, "siyucms-001")
    assert spec["unit"]["match"]["business_function_slug"] == "admin-authentication"
    assert spec["fault_class"] == "Weak Credentials"
    assert spec["edges_to_l0"]["endpoints"][0]["path"] == "/admin/index/index.html"
    assert spec["typed_backbone"]["required"][0]["field"] == "api_paradigm"
    assert spec["service_to_system_edges"]["required"][0]["target_kind"] == "AuthenticationMechanism"


def test_spec_metrics_counts_all_nine_concretised_procedure_fields():
    spec = {
        "target_identity": {"unit_id": "Service:sign-in"},
        "verification_symptoms": ["a symptom"],
        "assumptions": [],
        "rationale": "a rationale",
        "provenance": {"threat_id": "Service-sign-in__threat-1"},
        "skill_concretised_procedure": {
            "recon_action": "a",
            "bypass_technique": "b",
            "advanced_technique": "c",
            "preliminary_chaining": "d",
            "payload_vector": "e",
            "technology_misconfiguration": "f",
            "technology_grounding": "g",
            "pro_tips": "h",
            "interpretation_pitfalls": "i",
        },
        "discriminators": [{"axis": "technique", "value": "burst"}],
    }
    identity = {
        "expected_id": "Service:sign-in",
        "names": ["Service:sign-in"],
        "fault_class": "",
        "location": "",
    }
    row = measure_utm.spec_metrics(spec, {"type": ""}, identity)
    assert row["procedure_fields"] == 9
    assert row["procedure_total"] == 9
```

- [ ] **Step 2: Write the failing attribution and risk tests**

Append:

```python
def test_threat_downstream_matches_the_unit_and_the_threat_id():
    threat = {"threat_id": "threat-1", "unit_id": "Service:console-dashboard"}
    specs = [
        {"threat_id": "Service-console-dashboard__threat-1", "unit_id": "Service:console-dashboard", **_spec("technique")},
        {"threat_id": "Service-console-dashboard__threat-1", "unit_id": "Service:content-browsing", **_spec("actor")},
    ]
    downstream = measure_utm.threat_downstream(threat, specs)
    assert downstream["spec_count"] == 1


def test_the_narrowing_block_counts_distinct_threat_files():
    threats = [
        {"threat_id": "threat-1", "unit_id": "Service:a", "risk": 5.0},
        {"threat_id": "threat-1", "unit_id": "Service:b", "risk": 5.0},
    ]
    models = []
    metric = measure_utm.impact_metric(models, threats)
    assert metric["risk_total"] == 10.0


def test_a_threat_file_without_a_model_file_still_carries_its_risk(tmp_path):
    unit = tmp_path / "consumed" / "Service-console-dashboard"
    unit.mkdir(parents=True)
    (unit / "threat-1.yaml").write_text(
        yaml.safe_dump({"risk": 9.9, "threat_id": "threat-1"}), encoding="utf-8"
    )
    models, threats = measure_utm.load_models(tmp_path)
    metric = measure_utm.impact_metric(models, threats)
    assert metric["risk_total"] == 9.9
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest -q tests/eval/test_measure_utm.py::test_load_corpus_unit_reads_the_l1_profile_markdown tests/eval/test_measure_utm.py::test_spec_metrics_counts_all_nine_concretised_procedure_fields tests/eval/test_measure_utm.py::test_threat_downstream_matches_the_unit_and_the_threat_id tests/eval/test_measure_utm.py::test_the_narrowing_block_counts_distinct_threat_files tests/eval/test_measure_utm.py::test_a_threat_file_without_a_model_file_still_carries_its_risk
```

Expected: the markdown loader returns {}, procedure fields are 0, attribution is ambiguous, and the risk total excludes the model-less threat.

- [ ] **Step 4: Implement the markdown corpus loader**

In `eval/measure_utm.py`, replace `load_corpus_unit`:

```python
def load_corpus_unit(corpus_target: Path, vuln_id: str) -> dict:
    """The unit's ground-truth spec.

    Prefer the structured `unit-spec.yaml`; fall back to the current corpus
    shape, `l1-profile.md`, which carries the same identity in a rendered
    block. A missing file returns `{}` and the graph block degrades empty.
    """
    unit_spec = load_mapping(corpus_target / vuln_id / "unit-spec.yaml")
    if unit_spec:
        return unit_spec
    profile = corpus_target / vuln_id / "l1-profile.md"
    if not profile.exists():
        return {}
    return unit_spec_from_profile(profile.read_text(encoding="utf-8"))
```

Add the parser:

```python
_UNIT_LINE = re.compile(r"The target unit is `([^`]+)`")
_TITLE_LINE = re.compile(r"^# L1 profile - `[^`]+` \(`([^`]+)`\)")
_SPINE_LINE = re.compile(r"^spine \(present keys\): \[(.*)\]$")
_EDGE_LINE = re.compile(r"^  - ([A-Z_]+): \[(.*)\]$")
_ENDPOINT_LINE = re.compile(
    r"^  - method=([^;]+); path=([^;]+); baseurl=([^;]+); service_slug=([^;]+)$"
)


def unit_spec_from_profile(text: str) -> dict:
    """Translate the corpus `l1-profile.md` into the unit-spec shape the metric reads."""
    unit_id = ""
    fault_class = ""
    spine: list[str] = []
    edges: list[dict] = []
    endpoints: list[dict] = []
    for line in text.splitlines():
        title = _TITLE_LINE.match(line)
        if title:
            fault_class = title.group(1).strip()
            continue
        unit = _UNIT_LINE.search(line)
        if unit:
            unit_id = unit.group(1).strip()
            continue
        spine_match = _SPINE_LINE.match(line)
        if spine_match:
            spine = [
                part.strip().strip("'\"")
                for part in spine_match.group(1).split(",")
                if part.strip()
            ]
            continue
        edge = _EDGE_LINE.match(line)
        if edge:
            target = edge.group(2).split("->", 1)[-1]
            kind = ""
            if "kind=" in target:
                kind = target.split("kind=", 1)[1].split(";", 1)[0].strip()
            edges.append({"rel": edge.group(1), "target_kind": kind})
            continue
        endpoint = _ENDPOINT_LINE.match(line)
        if endpoint:
            endpoints.append({
                "method": endpoint.group(1).strip(),
                "path": endpoint.group(2).strip(),
                "baseurl": endpoint.group(3).strip(),
                "service_slug": endpoint.group(4).strip(),
            })
    kind, _, slug = unit_id.partition(":")
    match = (
        {"business_function_slug": slug}
        if kind == "Service"
        else {"kind": slug or kind, "discriminator": ""}
    )
    return {
        "unit": {"kind": kind, "match": match},
        "fault_class": fault_class,
        "location": "",
        "edges_to_l0": {"endpoints": endpoints},
        "typed_backbone": {
            "required": [{"field": name, "non_empty": True} for name in spine]
        },
        "service_to_system_edges": {"required": edges},
    }
```

Add `import re` at the top if absent.

- [ ] **Step 5: Fix the procedure-field count**

In `spec_metrics`, replace:

```python
    procedures = as_dict(provenance.get("skill_procedure"))
```

with:

```python
    procedures = as_dict(
        spec.get("skill_concretised_procedure")
        or provenance.get("skill_procedure")
    )
```

and set `procedure_fields` to the nine fields:

```python
    procedure_fields = (
        "recon_action", "bypass_technique", "advanced_technique",
        "preliminary_chaining", "payload_vector", "technology_misconfiguration",
        "technology_grounding", "pro_tips", "interpretation_pitfalls",
    )
```

Add `skill_concretised_procedure` to the `required` tuple.

- [ ] **Step 6: Fix the spec attribution**

Change `threat_id_of` to keep the full dispatch id:

```python
def threat_id_of(provenance: dict) -> str:
    """The spec's dispatch threat id, verbatim."""
    return str(as_dict(provenance).get("threat_id") or "").strip()
```

Change `threat_downstream` to match `(unit_id, threat_id)`:

```python
def threat_downstream(threat: dict, spec_rows: list[dict]) -> dict:
    threat_id = str(threat.get("threat_id") or "").strip()
    unit_id = str(threat.get("unit_id") or "").strip()
    specs = []
    for spec in spec_rows:
        spec = as_dict(spec)
        spec_threat = str(spec.get("threat_id") or "").strip()
        spec_unit = str(spec.get("unit_id") or "").strip()
        if _threat_id_matches(spec_threat, threat_id) and (
            not unit_id or not spec_unit or spec_unit == unit_id
        ):
            specs.append(spec)
    return discrimination_summary(specs)
```

Add:

```python
def _threat_id_matches(spec_threat: str, threat_id: str) -> bool:
    if not spec_threat or not threat_id:
        return False
    if spec_threat == threat_id:
        return True
    return spec_threat.rsplit("__", 1)[-1] == threat_id
```

Keep `spec_metrics` carrying the full `threat_id` and add `unit_id`.
Update the existing test that expects `"threat-1"` to expect the full dispatch id, or keep a separate `threat_id_suffix` field.
The safer approach: keep `threat_id` as the full id and add `threat_id_suffix` for display; update the test.

- [ ] **Step 7: Fix the narrowing and risk totals**

For the narrowing block, use the distinct global threats and specs, not the per-vuln matched rows:

```python
    distinct_threats = threats
    distinct_specs = specs
    narrowing_rows = [
        {
            **as_dict(threat),
            "downstream": threat_downstream(threat, distinct_specs),
        }
        for threat in distinct_threats
    ]
```

Then compute `broad`, `narrow`, `breadth_unknown`, `substantial_specs`, `well_formed_specs`, `narrow_without_well_formed`, `broad_without_well_formed` over `narrowing_rows`.
Keep `threat_rows_matched` as the matched-pair count in `counts`.

For the risk total, change `v5_impact`:

```python
    for threat in threats:
        risk = file_risk(threat)
        if risk is None:
            continue
        risk_total += risk
        risk_breakdown[severity_band(risk)] += 1
```

Remove the `threat_schema(threat) < 5` skip.
The `file_risk` presence is the dispatchable-v5 contract; a model-less consumed threat still carries the float the mover reads.

- [ ] **Step 8: Run the measurement suite**

```bash
pytest -q tests/eval/test_measure_utm.py
```

Expected: all pass.

- [ ] **Step 9: Re-run the harness on the existing trial**

Run on the eval server or against a local copy:

```bash
python eval/measure_utm.py \
  --trial /opt/polymerhus-dev/eval/runs-iteration-e-20261109/siyucms-web/siyucms-web-20261110T070858-38e49ca5 \
  --data-root /opt/polymerhus-dev/eval/instances/data/eval-server-2 \
  --corpus /root/utm-groundtruth \
  --target siyucms \
  --ground-truth /opt/polymerhus-dev/eval/data/webexploitbench/siyucms \
  --api http://127.0.0.1:8080 \
  --out /tmp/metrics-fixed.yaml
```

Verify:

- `impact.risk_total == 158.0`;
- every `per_vuln[*].graph` is non-empty;
- `procedure_fields == 9` for a spec that carries the full procedure;
- `counts.spec_unit_candidates` is non-zero where the unit matches.

- [ ] **Step 10: Update the eval docs**

In `eval/CONTEXT.md`, add the corpus fallback and the distinct-threat narrowing rule.
In `eval/ASSERTIONS.md`, add an assertion row for the measurement harness:

```markdown
| C21 | unit measurement | success + outlier | a legacy `unit-spec.yaml` corpus; an `l1-profile.md` corpus; a threat file with no model file; a spec with the nine-field procedure | the graph block is populated; `procedure_fields` is 9; specs attribute by `(unit_id, threat_id)`; the risk total includes every threat file with a float `risk`; the narrowing counts distinct threats | `tests/eval/test_measure_utm.py` |
```

- [ ] **Step 11: Commit**

```bash
git add eval/measure_utm.py tests/eval/test_measure_utm.py eval/CONTEXT.md eval/ASSERTIONS.md
git commit -m "fix(eval): read the current corpus and count the real threat risk"
```

---

### Task 12: Critical adversarial review

**Files:**
- Read: the full diff since `a1cac1d9`
- Read: every design spec changed in Tasks 1-11
- Read: `docs/superpowers/plans/2026-11-10-iter-e-failure-fixes.md` (this plan)

- [ ] **Step 1: Dispatch the review**

Dispatch one `general` subagent with the critical-thinking skill path.
Use this prompt:

```text
Read and follow the reasoning discipline in
/Users/diekgbbtt/.config/opencode/skills/critical-thinking-logical-reasoning/SKILL.md.

You are the adversarial reviewer for the iteration-E failure-mode fixes.
Review the complete diff on branch fix/iter-e-failure-modes since a1cac1d9.
The plan is docs/superpowers/plans/2026-11-10-iter-e-failure-fixes.md.

For every work item, answer these questions with evidence:

1. Does the change match the design spec and the validated contract exactly?
2. Is the fix at the most upstream seam, or is it a symptom patch?
3. Does the change introduce a regression in an existing behavior?
4. Does it handle the outlier: empty input, malformed input, missing file, absent account, duplicate name, model-less threat file?
5. Does it respect the project design patterns: one writer, fail-open at the boundary, typed seams, pure shaping functions, deterministic ids?
6. Is the test at the right seam, and would it fail on the original bug?

Run the targeted suites for each work item.
Report every finding with severity, file:line, the evidence, and the minimal correction.
Do not accept a passing test as proof when the test is tautological or implementation-coupled.
```

- [ ] **Step 2: Address every finding**

For each finding, either fix it in a new red-green loop or record a precise justification in the plan.
Do not make a cheap patch to silence the reviewer.

- [ ] **Step 3: Re-run the full targeted suite**

```bash
pytest -q \
  tests/integration/test_chunking_contracts.py \
  tests/integration/test_assigner_contracts.py \
  tests/integration/test_mechanism_typist_contracts.py \
  tests/recon/test_noise_filter.py \
  tests/recon/test_auth_feed.py \
  tests/recon/crawl/steel/test_frontier.py \
  tests/recon/crawl/steel/test_auth.py \
  tests/recon/crawl/steel/test_live_run.py \
  tests/recon/crawl/steel/test_manifest.py \
  tests/attack/test_pod_export_memory.py \
  tests/attack/pod/test_spec_reads.py \
  tests/eval/test_measure_utm.py
```

Expected: all pass.

- [ ] **Step 4: Commit the review fixes**

```bash
git add -A
git commit -m "fix: address the adversarial review findings"
```

---

### Task 13: Iteration-E rerun

**Files:**
- Read: `eval/OPERATOR.md`
- Read: `eval/setups/iteration-e.yaml` (or the configured setup)
- Runtime: eval server `eval-server-polyphemus`

- [ ] **Step 1: Merge and deploy the fix branch**

```bash
git checkout dev
git merge --no-ff fix/iter-e-failure-modes
git push origin dev
ssh eval-server-polyphemus 'cd /opt/polymerhus-dev && git fetch origin && git checkout dev && git pull --ff-only origin dev'
```

- [ ] **Step 2: Rebuild and restart the stack**

Use the eval operator procedure.
The stack name is `ph-17747005`.
Verify the API is healthy at `http://127.0.0.1:8080`.

- [ ] **Step 3: Rerun the external bootstrap**

The Q5 change means the auth sessions must be regenerated.
Run the bootstrap with the same project config.
Verify at least one usable account per role, each with `root_url`, `auth_probe`, and the persisted `snapshot`/`tokens`.

- [ ] **Step 4: Run the trial**

Use the same eval and project config.
Set:

- risk budget `220`;
- `CHUNK_MAX_ASSETS=120`;
- steel crawl deadline `3600`;
- `KATANA_DEPTH=3`.

- [ ] **Step 5: Monitor and assess**

Run the orchestrator loop.
Advance the target chain first, then call `eval_monitor` once.
Converge when every trial is `complete`, `deferred`, or `escalated`.

- [ ] **Step 6: Measure the rerun**

Run the fixed `eval/measure_utm.py` against the new trial.
Verify:

- the graph block is non-empty for every vuln;
- `procedure_fields == 9` where the spec carries a full procedure;
- the risk total equals the sum of the distinct threat files;
- the `spec_unit_candidates` reflects the exact `(unit_id, threat_id)` attribution.

- [ ] **Step 7: Record the result**

Write the outcome into the plan and the run diary.
If a failure remains, open one work item per named failure.
Do not start a second rerun before the named failures are resolved.
```

