# The proposers' tool-use workflows (assigner + mechanism-typist)

Date: 2026-10-15.
Status: accepted.
Owner change: the proposer-tool-workflows rework (branch `feat/proposer-tool-workflows`).
Amends: `docs/design/assigner-adjacent-surface-adr.md` D-A2 (the HTTP-history remit and the tools' role reach).

## Context

Two of the three chunk-fed proposers can reach beyond the chunk slice.

The Assigner already had a bounded adjacent-surface phase (D-A2): the read-only `graph_view` plus the HTTP-history pair, bound on its turn.
The mechanism-typist had a THREE-call chain (reflection, systems extraction, services linking) and no tools bound at all, so every mechanism hypothesis had to be grounded in the chunk slice alone.

This change does three things and records why:

1. It stops the Assigner's volatile user turn from restating the `graph_view` widening that the system prompt already owns, and it widens the HTTP-history remit past disambiguation-only.
2. It gives the mechanism-typist a real tool surface (`graph_view`, the HTTP-history pair, and a bounded `exec`), with a when+how spec in both the skill and the reflection scaffold.
3. It removes the typist's redundant per-call `system_prompt=` restatement, relying on the seam default.

## Trace evidence

The trunk mechanism-typist binds no tools today, so the only LIVE typist tool-use evidence is the service-sourced experiment, which runs the same role and the same ORIENT / VERIFY / EMIT vocabulary over one unit.
It is cited here as evidence for WHERE tool calls pay off, not as the trunk's request shape.

Mined with `langfuse/references/query-observations.py --tags mechanism_typist` (2026-10-12 runs; observations named `ReasoningPreservingChatOpenAI`):

- **Volume.** Across the tool-using typist traces the model called `graph_view` 364 times and `search_http_history` 52 times.
  `exec` never appears because it was never bound; that absence is the gap this change closes, not evidence against it.
- **ORIENT - broad L0 enumeration.** The first reflection act is almost always a broad, no-name-assumption read of the unit's surface, for example `MATCH (s:L1Service {project_id: $project_id, business_function_slug: 'custom-node-content'})-[:AGGREGATES]->(e:Endpoint) ...` (trace `2d8e970338c6e488350f46bc093a76e0`).
  A wrong slug returns empty and the model broadens (`MATCH (n) RETURN labels(n) ...`), then pins the project scope.
- **ORIENT - response evidence.** It reads each endpoint's `content_type` / `title` / `status_code` / `server` / `content_length`, then the owning BaseURL's Headers and Technologies, then the anchored Observations:
  `MATCH (h:Header {project_id: $project_id}) RETURN h.name, h.value, h.baseurl` and `MATCH (t:Technology ...)`.
  A live note: "all four endpoints answer 404 with application/octet-stream and content_length=0 under server: nginx/1.31.6" - the mechanism read off the response, not the path.
- **ORIENT - page census for WebPresentation.** `MATCH (e:Endpoint) WHERE e.baseurl CONTAINS 't-...' RETURN e.content_type, count(*), collect(DISTINCT e.title)`.
  The cluster decision is then made on hard counts ("the only navigable text/html rows are GET / and GET /index.html, both 65,200 B, title ComfyUI").
- **VERIFY / FALSIFY - read the live graph before committing.** Before emitting, the model reads the currently-defined Systems and the edges the unit ALREADY carries, so an extension reuses the exact key and a committed edge is not duplicated:
  "server-diagnostics already carries committed edges in 8 scopes - FRONTED_BY and ROUTED_BY ReverseProxy::__singleton__, plus EXPOSED_VIA ...".
- **VERIFY / FALSIFY - HTTP-history probes.** Representative filters actually issued:
  - `{"filters": [{"side": "request", "namespace": "core", "key": "url", "op": "contains", "value": "/view"}], "limit": 50}` (trace `d7aa5472d2541639909061d43586e543`) - listing a chunk endpoint's recorded transactions to confirm web-presentation equality.
  - `{"filters": [{"key": "authorization", "namespace": "header", "op": "absent", "side": "request"}], "limit": 5}` - an authorization-primitive control-group probe.
  - `{"filters": [{"side": "response", "namespace": "header", "key": "server", "op": "contains", "value": "nginx"}], "limit": 40}` - confirming a perimeter mechanism from a response header.
  - `{"text": "/view", "limit": 20}` - a free-text fallback when the store returned empty.
- **EMIT - linking reads the graph.** Immediately before the linking call: `MATCH (s:L1Service)-[r]->(sys:L1System) WHERE sys.kind = 'ReverseProxy' ...` to extend the overlay without duplicating edges.

The recurring failure mode is a mechanism asserted from a path noun with no witness; every tool call above is a witness, and the ones that returned empty were followed by a broader read rather than a guess.

## The state model

The typist's three calls are three states of one reasoning pass, and the tool surface serves a different purpose in each.

| Call | State | What the model is doing | Where a tool call pays off |
|---|---|---|---|
| 1 reflection (prose) | **ORIENT** | read each asset + its insight + its response evidence; decide what mechanisms the slice could evidence | `graph_view` broad enumeration (unit's endpoints, content_type/title/status/server, Headers/Technologies, Observations); text/html census for page clustering |
| 1 reflection (prose) | **VERIFY / FALSIFY** | test each hypothesis against evidence; decide new-vs-extend | `graph_view` read of currently-defined Systems and the unit's existing edges; `search_http_history`/`get_http_artifact` for the recorded request/response shape; bounded `exec` to read a rendered page's embedded features |
| 2 systems extraction (structured) | **EMIT (systems)** | fold the surviving mechanisms into typed `systems` with compounded descriptions | none required; the tools remain bound only so the request shape stays constant |
| 3 services linking (structured) | **EMIT (links)** | connect each System to the Services it overlays | `graph_view` read of existing edges immediately before the link, to avoid duplicating a committed edge |

The state model is the reason the tools ride EVERY call rather than the reflection alone: the linking state has a genuine pre-commit read, and the constant-shape rule (below) forbids a tool set that toggles.

## Binding decisions

### D-A2 change: the surface tools are no longer assigner-only

D-A2 (as originally written) bound `graph_view` plus the HTTP-history pair on the Assigner turn alone, and framed the HTTP pair as disambiguation/confirmation only.
This change amends it in two directions:

- **Reach.** `proposer_turn._surface_tools` now binds the read tools on the Assigner AND the mechanism-typist turns.
  The typist's turn additionally binds the bounded `exec` term.
  No other role binds surface tools: adjacent-surface reading and probing are not their ownership.
- **Remit.** The HTTP-history pair is no longer disambiguation/confirmation only: when a collected Endpoint looks even adjacently promising for a candidate Service, the Assigner MAY pull its fuller response (one endpoint often embeds several features - iframes in HTML, menu entries, tabs).

The D-A2 ownership fence is unchanged: deep TECHNICAL understanding stays the mechanism-typist's; the Assigner stops at the ownership judgment.

### The constant-request-shape rule (the cache contract)

Every turn of a proposer binds the SAME tool set, or the provider prefix cache never matches (the `mechanism_typist` quadratic-growth lesson, `converged-agent-turn-adr.md`).

The typist's set is: the surface tools plus the role's structured tool.
- On the prose reflection turn the structured tool rides `tools=`.
- On the structured extraction/linking turns it rides `response_format` (the A6 `ToolStrategy`).
- Binding the surface tools makes `stateful_turn` read `tools_bound=True` on the structured turns, so their `response_format` is `ToolStrategy` (not `ProviderStrategy`).
  The prose turn therefore carries the `ToolStrategy`-shaped structured tool, computed with the SAME `tools_bound` axis, so the two turn kinds agree.

The byte-identity is pinned end to end in `tests/analysis/test_proposer_turn.py::test_the_typist_surface_tools_keep_the_request_shape_byte_identical`: the `convert_to_openai_tool` definitions are identical across P, S, S.

**Consequence to review:** binding tools flips the typist's structured turns from the no-tools negotiation axis (`json_schema` on a structured-output-capable model) to the tools axis (`function_calling` / voluntary). This is the shape the Assigner already runs in production, and it is forced by binding any tool; it is called out here because it changes the typist's wire method on capable models.

### Exec: reuse the hunting `execute_command`, do not rebuild

The `exec` term reuses the SAME execution seam the hunting agents use:

- The seam is the pod's `default_exec_fn` (`attack/hunting/pod/tools.py`), which delegates to recon's `default_exec_fn` (`recon/domain/pod.py`), which runs `execute_command` through the kali MCP (`app/clients/kali_mcp.py`).
- The tool is `attack/hunting/hunter_tools.ExecTool`, the hunting agent's exec tool, bound by `build_hunter_tools` and wired in production with `exec_fn=default_exec_fn` (`attack/hunting/runtime.py::_default_hunter_builder`).

`analysis/graph_tools.build_analysis_exec_tool` returns a THIN wrapper over the hunting `exec` tool.
It adds exactly two things, both analysis-side:

- the model-facing description (`ANALYSIS_EXEC_CONTRACT`) - the hunter's description is written for a spec-holding probe agent (the partition guard, the replay lineage) and would mislead the typist;
- a per-call call budget - the typist is a bounded read phase, and an unbounded exec loop must not sit on the analysis critical path.

Everything else is the hunting tool verbatim: it holds an `hunter_tools.ExecTool` and delegates each call to it, so the same `exec_fn(command, timeout_s)` seam, the same `ExecArgs` schema, the same fail-open result shaping, and the same tool name (`exec`) are reused unchanged.
The budget defaults to 6 (`ANALYSIS_TYPIST_EXEC_BUDGET`, env-overridable) and degrades to a denoted `exec_budget_exhausted` result, never a raise.

### Prompt delivery and the 4c dedup

The role prompt rides `create_agent(system_prompt=...)` (the converged seam), never a `SystemMessage` in the trail.
`proposer_turn._role_prompt("mechanism_typist")` returns `mechanism_typist._load_skill()`, so passing `system_prompt=_load_skill()` and passing nothing resolve to the SAME memoized string.

- The first chain call keeps the explicit `system_prompt=skill`.
- The 2nd and 3rd calls omit it; the stateful seam defaults it to the byte-identical `_load_skill()`.
- The legacy one-shot leg (`_default_invoke_fn`) also defaults an absent `system_prompt` to `_load_skill()`, so the one-shot request stays byte-identical too.

The precondition (`_load_skill()` is exactly the seam default and is memoized) is pinned in `tests/analysis/test_proposer_tool_workflows.py::test_the_typist_skill_is_the_seam_default_prompt_memoized`; the dedup itself in `...::test_the_later_typist_calls_rely_on_the_seam_default_prompt`.

### The Assigner's prompt layering (4a)

The adjacent-surface policy is the SYSTEM prompt's job (`prompts/assigner.md`, D-A2/D-A3).
The volatile user turn carried a verbatim copy of the `graph_view` widening; it is deleted, so the user turn now carries only the task and the deductive target and no longer restates the read policy on every chunk.
The policy itself stays in the system half (byte-stable, cacheable), where it belongs.

## Consequences

- The typist can now ground a hypothesis in the target's real evidence, closing the "asserted from a path noun" failure mode the traces expose.
- Per-chunk cost grows by the typist's bounded read/probe phase; the exec budget and the `graph_view` LIMIT discipline keep it bounded.
- The typist's structured-output wire method moves to the tools axis on capable models (see above).
- The 2026-09-17 operator ruling ("the analysis proposers carry no skill surface") is preserved: the new tools are a data-grounding surface, not a skill surface. The adjacent-surface tools are not `load_skill`, carry no L1 index middleware, and pass no skill context.
- `tests/integration/test_assigner_contracts.py::test_C35c` and `test_C35e` encoded the old layering and the disambiguation-only remit; they are rewritten by this change, not grandfathered.
