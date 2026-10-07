# ADR: bounded retention for the whole-file hunting memory stores

## Status
Accepted (2026-10-08).
Resolves #341 (the growth follow-up deferred by #340 / EV-29).

## Context
- The hunter `notes.yaml` (`HunterMemoryStore`) and the orchestrator `memory.yaml` (`HuntStore`) are whole-file rewrites with no compaction and no record bound.
- Each write reads the whole file, appends or amends one record, and rewrites the whole file, so a long run grows the file without limit and the rewrite cost grows O(n).
- The observed failure: the jetlinks-1 project `0022f9ac` `notes.yaml` reached 18 MB in one ~8h orphaned run (#338).
- #340 made every write atomic, so growth no longer risks corruption or data loss; the remaining defect is unbounded growth.
- A local survey of the same store shape (`data/<project>/hunting/hunter/notes.yaml`) showed the dominant driver: 107 records at 6.5 MB, of which 95 were Q16 pod-export stubs (`provenance.verdict_stub`) whose `body` is the FULL export (one record's body was 1.3 MB).
- The consumed record of value is the durable prior-insight record: the pod-export stub that `HuntStore.read_hunter_notes` projects into a config's `prior_hunt_insights` (G3/#202). It must survive ordinary eviction.
- `test-specs/` and `hunt_configs/` are one-file-per-record stores, so no single file grows; they are out of scope.

## Decision
- Add ONE bounded-retention primitive, `hunt_store.retain_bounded_records(records, *, max_records, max_bytes, protected=None)`.
- The policy is bounded records with value-aware eviction: the NEWEST records are kept and the OLDEST are dropped until the list fits `max_records` records or `max_bytes` serialized bytes.
- A record for which `protected(record)` is true is dropped only after every unprotected record.
- The hunter `notes.yaml` protects the durable prior-insight records: `protected = provenance.verdict_stub`.
- The orchestrator `memory.yaml` has no protected class (its notes are per-config reasoning); the same oldest-first bound applies.
- The bound is absolute: when the protected records ALONE exceed the bound, the hard ceiling still trims the oldest, so the file can never grow without limit.
- The newest record is always kept whole: a single record larger than the ceiling is never truncated (the write must land).
- Bounds: hunter `HUNTER_NOTES_MAX_RECORDS = 1000`, `HUNTER_NOTES_MAX_BYTES = 4 MiB`; orchestrator `MEMORY_NOTES_MAX_RECORDS = 2000`, `MEMORY_NOTES_MAX_BYTES = 4 MiB`.
- The bound is enforced on every write (`HunterMemoryStore._write_records`, `HuntStore._save_notes`), so the reader always sees one complete parseable file (the #340 atomic-write guarantee holds) and the rewrite cost is O(bound), not O(n).

## Alternatives rejected
- Compaction by dedupe or LLM summarisation: rejected.
  The records are not duplicates (each carries distinct evidence), and an LLM summarisation pass would add a model dependency and a latency cost to a hot store write.
- Append-log plus snapshot: rejected.
  It is a larger redesign of a store whose whole-file atomic rewrite is already the ratified pattern (#340); the bound solves the growth with no change to the reader contract.
- Slimming the pod-export stub body to the verdict envelope only: rejected for THIS change.
  It would change the durable record's on-disk contract, which existing wiring tests pin, and it does not by itself bound the record count. The size ceiling already bounds the file even with the full export body.
- Unbounded retention with only a warning: rejected.
  The acceptance criteria require a documented bound and a non-linear write cost.

## Consequences
- A long run keeps the memory file within a documented bound; the whole-file rewrite stays O(bound).
- The newest durable prior-insight records survive ordinary eviction, so the orchestrator's `prior_hunt_insights` reads keep finding the recent downstream value.
- Older reasoning notes and, under the hard ceiling, the oldest durable records are evicted; the trade is deliberate and documented.
- `hunter_memory` imports the ONE retention primitive from `hunt_store` (the pattern-document module), so the discipline cannot drift per store.

## Evidence
- The observed 6.5 MB `notes.yaml` (107 records, 95 durable stubs) compacts to 2.87 MB (80 records, all durable stubs) on the next write under the default bounds.

## References
- #341 (this bug), #340 (atomic write, `docs/design/atomic-write-340-adr.md`), #338 (the orphan that amplified growth), #202 (the sibling prior-hunt insight reads), #169 Q16 (the durable pod-export record).
- `docs/design/hunting-memory-system-spec.md` section 10; `src/polymerhus/attack/hunting/CONTEXT.md`; `src/polymerhus/attack/hunting/hunt_store.py`; `src/polymerhus/attack/hunting/hunter_memory.py`.
- `tests/attack/test_hunter_memory.py`; `tests/attack/test_hunt_store.py`.
