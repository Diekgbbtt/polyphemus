# Assertions - Memory system (per-project hunt-config + note store, deterministic note step)

**Source:** spec https://github.com/Diekgbbtt/polyphemus/issues/137 ; tickets #138-#143.
**Seams under assertion:** (1) the `tools.store_reads` store handle (write + read funnel), (2) the deterministic note-taking node injected into `build_hunting_graph(..., note_node=...)`, (3) the gate-prompt key-list + reading-tool detection, (4) the LIVE runtime-stack e2e over a bounded project.

## Contract predicates (integration)

- **C1 - per-project lazy store creation (success)**. Given `write_config(project_id="p1", ...)` at the store-handle seam on a fresh `tmp_path`, the contract yields exactly one project folder `projects/p1/` holding `configs.yaml` + `notes.yaml`, created on write, not before.
- **C2 - cross-project isolation (ordering/isolation)**. Given configs for `p1` then `p2`, then a read scoped to `p1`, the contract yields only `p1` records - zero `p2` leakage.
- **C3 - monotonic append + read-latest (duplicate-idempotent)**. Given two config writes for the same `(unit, fault)` then a read, the contract yields BOTH in append order (history preserved), and each note/config carries a monotonic version so the latest is identifiable; within one pass the same `(unit_id, fault_class, kind)` is not duplicated.
- **C4 - grep-match read contract (success + empty-valid)**. Given notes with distinct keys/bodies, the read tool yields: parent-index-only query -> that pair's notes; note-key keyword -> matching keys; body keyword -> matching bodies; combined filters -> intersection; a filter matching nothing -> empty list (valid, not failure).
- **C5 - unknown note kind rejected (malformed)**. Given a note with a kind outside the closed enum `{hypothesis_refusal, implicit_test_primitive, freeform}`, the contract rejects at write (authoring-time discipline) rather than storing a stray kind.
- **C6 - read fail-open (degradation)**. Given a store whose read raises, the tool degrades to an empty result set and the caller keeps serving - never a crash.
- **C7 - write fail-open (degradation)**. Given a store whose write raises, the caller warns and keeps serving - never a crash; the memory write failure is counted and surfaced in the OrchestratorReport `store_write_failures`.
- **C8 - note node always fires (determinism)**. Given a fake note producer injected at the note-node seam, on a pass with a carried pair, the node is invoked for that pair and writes the produced note(s); when the producer/absent node raises, the node writes nothing and the pass continues (fail-open).
- **C9 - carried + refused capture (both-permitted)**. Given a note producer that emits BOTH an implicit-test-primitive note for a carried direction AND a hypothesis-refusal note for a pruned direction, both land in the per-project note store keyed `unit_id:fault_class` with kind-namespaced keys.
- **C10 - reading tool contains matching logic (containment)**. Given the reading tool's surface, the grep-match logic lives strictly inside the tool - the gate prompt and reasoning do not re-implement matching; the tool description enumerates the closed note kinds.
- **C11 - reading tool refactors read_memory compatibly (success/duplicate)**. Given the pre-#137 `read_memory(revival_key)` call shape (parent-index-only), the new tool returns the prior notes/configs for that key, so existing call sites degrade compatibly.
- **C12 - key-list prompt construction (success)**. Given a project with prior hunt-config keys, the gate-prompt builder embeds the list of ALL previous hunt-config keys as brief headers (Seam 3), none omitted; empty prior set embeds an empty index (valid).

## Walkthrough predicates (end-to-end)

- **E1 - bounded live pass lands per-project configs + notes (Seam 4, live edge: runtime stack)**.
  Grounding #138/#139/#142. Entry seam `POST /projects/{project_id}/hunting`. Input: a bounded fixture project `pid` with a small candidate set, e.g. one `DeliveredCandidate(Service:slug:a, fault-x, verdict=applies)` routed through the live control plane + runtime manager + DB.
  Path: `start_hunting` opens the `hunting_runs` row -> the graph pass reasons (gate) -> dispatches (config minted) -> the note node writes per-pair notes -> terminal `complete`.
  Terminal: the per-project store `projects/<pid>/{configs.yaml, notes.yaml}` holds exactly 1 accumulable config for `Service:slug:a::fault-x` and the note(s) the model produced; the `hunting_runs` row is `complete`.
  Observed: read the live `configs.yaml`/`notes.yaml` from the real store; count configs = 1, notes >= 1 for that pair.
- **E2 - gate prompt carries previous-config key-list in a live two-pass run (Seam 3 + 4, live edge: runtime stack)**.
  Grounding #141/#142. Entry seam: two successive `POST /hunting` passes over the same bounded `pid`.
  Input: pass 1 candidate `(Service:slug:a, fault-x)`; pass 2 candidate `(Service:slug:a, fault-y)` (same unit, different fault).
  Path: pass 1 mints + persists config for `fault-x`; pass 2's gate prompt must embed the prior key-list including the `fault-x` key header.
  Terminal: pass 2's captured gate prompt contains the `fault-x` hunt-config key header; the note store holds pass 1's notes.
  Observed: capture and assert the pass-2 gate prompt string; assert the prior key header is present.
- **E3 - orchestrator detects when to call the reading tool (Seam 3 capability measurement, live edge: runtime stack)**.
  Grounding #140/#142/#143. Entry seam `POST /hunting` on a project with an existing note/config for a unit the next pass also hunts.
  Input: a prior pass persisted a `hypothesis_refusal` note with a distinctive body keyword (e.g. "no CSRF token") for `Service:slug:a::fault-x`; a later pass hunts the same unit with `fault-y`.
  Path: the orchestrator's reasoning turn, given the prompt key-list, invokes the note/config reading tool to retrieve the relevant prior note.
  Terminal: a reading-tool invocation occurs during the later pass; the retrieved note body is the prior `hypothesis_refusal` content (matching by keyword and/or body keyword).
  Observed: trace the tool call; assert the returned note body equals the prior note's body.

## Bootstrap needs (only the operator can supply)

- E1/E2/E3 need a LIVE runtime stack: the control-plane runtime manager (`polymerhus.app.runtime`) active, DB reachable, the hunting module's `hunting_control_plane_available()` true, and the hunting agent dispatch real (not degraded). The three-pass chain implies a bounded fixture project id and, per the existing e2e harness, a real deployed-stack session (see `test_hunt_orchestrator_walkthrough.py` / `test_control_plane_walkthrough.py` session fixtures).

## Live-edge decision (operator-confirmed)

E1-E3 run live against the REAL runtime stack (control plane, DB, runtime manager, real graph + real per-project store grounding, bounded project) with the hunting-agent DISPATCH SEAM injected (a recording fixture) - exactly the E3-E16 isolated-e2e pattern. The dispatch seam is this workstream's boundary, not its subject; E1-E3 exist to verify the MEMORY system, not the agent dispatch. This keeps them mechanisable now (not blocked on #83).
