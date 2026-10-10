# Proposer cache experiment - one worktree, TDD, surgical

**Status:** experiment, operator-directed (2026-10-10). Branch `exp/proposer-cache`.
**Owner:** analysis proposer turns (`analysis/{mechanism_typist,data_modeller}.py`,
`analysis/proposer_turn.py`) + the compaction config layer (`app/llm/providers.py`,
`app/llm/compaction.py`).

## Objective

Cut the analysis proposers' prompt-cache misses. Trade a little quality for a
large drop in uncached input. Do not change the core implementation model of the
impacted components; adopt existing patterns; keep it easy.

## Evidence (measured, this run)

- `data_modeller`: `cache_read=0` on all 36 model calls, `over_budget=False`
  throughout (max occupancy 148,949 < 200,000 budget). So it is NOT compaction.
- `mechanism_typist`: caches normally (`cache_read` up to 188,160) except when it
  crosses the budget (7 of 88 calls zero).
- The message head is byte-stable (system + first-user hashes constant across the
  16 reflection calls; trail append-only 2->40). So it is NOT an anchor cut.
- The request SHAPE toggles every call: the reflection turn binds no tool
  (`schema=None`); the extraction turn binds the `L1DeltaBatch` structured tool
  (A6 voluntary rung). `data_modeller` runs strictly `P,S,P,S,...`, so no two
  consecutive calls share a tool set -> the provider prefix (which includes the
  tool definitions) never matches. `mechanism_typist` runs `P,S,S` per chunk, so
  its `S,S` pair shares the tool set and caches. This asymmetry is the signal.

### Vertical growth (why occupancy climbs while output is tiny)

- `data_modeller` over the run: input(new,uncached)=1,632,634 tokens, cached=0,
  output(generated)=33,508 tokens (~2%). Harness-injected message chars are 63%
  of the total; the model's own chars 37%.
- Per-batch occupancy delta from the ledger: `data_modeller` ~8,162 tokens/batch
  (2 calls x ~4,081); `mechanism_typist` ~41,424 tokens/batch (3 calls x ~13,808);
  `assigner` ~5,389/call. So the context grows because each chunk RE-INJECTS the
  streamed surface + inventory (+ the whole prior trail under the run-long
  session), not because the model writes much. The reasoning + the proposed
  deltas are the load-bearing output and are a small token fraction.

## The three changes

### 1. Constant request shape per role (fix the toggling tool binding)

Requirement (testable): across a role's calls, the request's tool /
`response_format` set is byte-identical, and the request prefix overlap is 1.0
where the messages are append-only.

Approach: bind the role's structured tool on EVERY turn - the reflection turn
included - so the set never toggles. Prefer the smallest edit: pass the role's
schema on the reflection invoke as well, or bind it through the seam's `tools=`
while leaving the reflection's `response_format` prose. Then confirm with a
recording-model test that the tool set is constant and the prose turn still
returns prose. A collapse to a single structured call is allowed only if the
reflection stop is kept; do not otherwise change the proposer bodies' contract.

### 2. Stateful per batch (fresh context per streamed chunk)

Each new chunk streamed from recon starts a fresh agent context; within one
chunk the turn chain still shares memory.

Preferred edit path (native): a per-batch thread id. `AnalysisSession` gains a
`batch` discriminator (thread = `run:batch:role`), threaded from the chunk id
through the proposer bodies' invoke call. This uses the existing
thread-id-keyed checkpointer with no lifecycle code.

Fallback (if the batch is hard to reach at the invoke site): keep the thread and
reset memory after each chunk via the native primitive
(`app/llm/checkpoints.py::ModuleIndex.drop` / langgraph `delete_thread`), called
once per chunk at the dispatch boundary.

Decide by inspection and state the choice in the ADR. Do not change the
serialized `run:role` contract used by observability/runtime unless required.

### 3. Per-agent compaction threshold

Add a per-role compaction threshold to the role config layer
(`app/llm/providers.py::Role`) and a per-agent env var
`LLM_COMPACTION_THRESHOLD_<ROLE_ID_UPPER>`, resolved
`per-agent env > global LLM_COMPACTION_THRESHOLD > default`. Wire it through
`app/llm/compaction.py::resolve_window` / `build_role_compaction_middleware`.
`LLM_COMPACTION_THRESHOLD` stays as the global fallback (back-compatible).

Mined starting values (relative decimal of the 1M window; budget = threshold x
limit), sized so one batch fits without crossing:

| role | per-batch tokens | threshold (size/1M) | proposed default |
|---|---|---|---|
| data_modeller | ~8,162 | 0.008 | **0.016** (2x headroom) |
| mechanism_typist | ~41,424 | 0.041 | **0.08** (2x headroom) |

Report the raw mined numbers; set the proposed defaults above.

## Tests (TDD, no live stack)

- Turn shape: a recording model asserts the bound tool/`response_format` set is
  constant across a role's reflection + extraction turns, and the request prefix
  overlap is 1.0 for an append-only trail.
- Per-batch: two chunks on one run produce two distinct threads (or a reset
  thread); chunk N+1's first request does not carry chunk N's messages.
- Per-agent compaction: `resolve_window`/middleware reads the per-agent env var
  first, then the global, then the default; unit-tier, no DB.
- Regression: the existing proposer/session/compaction unit suites stay green.

Run: `.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/integration`
plus the impacted integration tier in-network once the stack gate allows.

## Docs (commit gate)

- ADR: `docs/design/proposer-per-batch-cache-adr.md` (root cause, the chosen
  per-batch edit path, the constant-shape rule, the per-agent threshold).
- Update `analysis/CONTEXT.md` (proposer session memory: per-batch) and
  `app/CONTEXT.md` (per-role compaction threshold) + `eval/CONTEXT.md` if the
  eval threshold note changes.
