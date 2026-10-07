# ADR: one shared atomic whole-file write primitive

## Status
Accepted (2026-10-08).
Resolves #340 (eval-bugs-map EV-29).

## Context
- `HunterMemoryStore._write_records` rewrote the whole `notes.yaml` with a plain `path.open("w")` plus `yaml.safe_dump`.
  That truncates the target before it dumps, so a kill or an exception mid-write leaves a truncated or malformed file.
- The observed failure was on the jetlinks-1 project `0022f9ac` after its orphaned run `665ba875` (#338) rewrote `notes.yaml` to 18 MB.
  The file landed malformed (`could not find expected ":" ... while scanning a simple key`) and every later read raised.
  The failure cascaded: `hunt store: unreadable hunter notes` on every read, and `surfer: durable pod-export record failed` - so the Q16 durable pod-export record was lost for the rest of the run.
- The same non-atomic whole-file rewrite hazard lived in the orchestrator store (`hunt_store`) and the pod memory (`pod/pod_memory.py`).
  The auth store (`app/auth/store.py`) and the skill store (`app/llm/skills.py`) already wrote atomically (temp file plus `os.replace`, decision D220-6), but through private copies of the idiom; the other writers did not mirror it at all.

## Decision
- Introduce ONE shared app primitive, `src/polymerhus/app/atomic_write.py`, with `write_text_atomic(path, text)` and `write_bytes_atomic(path, data)`.
  The caller renders the full body in memory; the primitive then:
  1. creates the target's parent directory;
  2. writes the body to a sibling temp file in the SAME directory (`.{name}.{uuid8}.tmp`);
  3. `flush` plus `os.fsync` the temp file;
  4. `os.replace`s the temp onto the target (an atomic rename on POSIX);
  5. `fsync`s the parent directory so the rename's entry is itself durable;
  6. unlinks the temp best-effort in a `finally` (a no-op after a successful replace).
- Both `fsync`s are deliberate: the file `fsync` forces the new bytes to disk before the rename, and the directory `fsync` forces the rename's entry (the classic ext4 rename-without-dir-fsync zero-length case), so a power loss cannot leave a renamed-but-empty file.
- Every whole-file writer routes through the primitive:
  - `attack/hunting/hunter_memory.py` - `_write_records` (the `notes.yaml` writer, the ticket's target) and `write_spec`;
  - `attack/hunting/hunt_store.py` - `_dump_yaml_atomic` and `_write_records`;
  - `attack/hunting/pod/pod_memory.py` - variant, experiment-log, pod-export, and notes writes;
  - `app/auth/store.py` - `_dump_yaml_atomic` (its private copy is retired);
  - `app/llm/skills.py` - `_dump_text_atomic` (its private copy is retired, still translating `OSError` to `StoreUnavailableError`).
- The hunter `notes.yaml` writer therefore no longer truncates: an aborted write leaves the prior complete file intact, and a reader sees either the previous or the new complete file, never a partial one.

## Acceptance criteria
- (a) An aborted/interrupted write leaves the prior file intact and parseable - covered by `tests/attack/test_hunter_memory.py::test_failed_notes_dump_leaves_prior_content_intact` and `::test_aborted_replace_leaves_prior_notes_intact`, and by the pod-store counterparts.
- (b) A reader never sees a partial file - covered by `test_reader_never_sees_a_partial_notes_file` (the observation hook fires exactly at the rename boundary and records the old complete file).
- (c) The hunter `notes.yaml` writer routes through the shared primitive - the atomic tests fail against a plain `path.open("w")` rewrite.
- (d) Unbounded growth (18 MB for one run) - **resolved by the #341 follow-up**, see below.

## Follow-up: unbounded `notes.yaml` growth (resolved by #341)
The 18 MB growth was a separate, non-corruption defect, deferred here because the atomic write removes the corruption failure mode entirely.
It is now RESOLVED by #341: the whole-file notes stores keep a documented record-count and serialized-size bound (`hunt_store.retain_bounded_records`), so the rewrite cost is O(bound) instead of O(n) and a reader always sees a complete file.
The hunter `notes.yaml` protects the durable prior-insight records (the pod-export stubs) from ordinary eviction.
See `docs/design/hunting-memory-growth-341-adr.md`.

## Consequences
- One construction point for the atomic-write idiom; the three private copies are retired, so the discipline cannot drift per store.
- A crash after the rename leaves a durable complete file; a crash before it leaves the previous file untouched.
- The leftover temp is named `.`-prefixed and removed best-effort; `tests/attack/test_hunt_store.py` asserts no `.tmp` leftovers.
- The eval orchestrator's `FileStore` (`eval/orchestrator/files.py`) keeps its own `write_text_atomic` / `write_bytes_atomic`.
  That is a distinct harness-side seam over a keyed-artifact layout, outside the product `src/` tree; unifying it on `app.atomic_write` is a possible future consolidation, not required here.

## References
- #340 (this bug), #338 (the orphan that amplified it), #220 (auth-store atomic-write decision D220-6).
- `docs/design/eval-bugs-map.md` EV-29; `docs/design/hunting-memory-system-spec.md` section 10; `src/polymerhus/app/CONTEXT.md`; `src/polymerhus/attack/hunting/CONTEXT.md`.
- `src/polymerhus/app/atomic_write.py`; `tests/attack/test_hunter_memory.py`; `tests/attack/pod/test_pod_memory.py`.
