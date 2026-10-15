# ADR: the Assigner judges its chunk through the HTTP-history seam alone

Date: 2026-10-15.
Status: accepted.
Supersedes: `docs/design/assigner-adjacent-surface-adr.md` D-A2 and D-A4
**for the Assigner only**. The mechanism-typist keeps its D-A2 surface
(`graph_view` + HTTP pair + bounded `exec`); the D-A3 deductive target is
untouched.

## Context

Arm G2 measured the streamed assigner at 74/75 aggregates naming the
non-ground-truth `editor-shell` (`docs/experiments/assigner-calibration-collapse-diagnosis.md`).
The turn-by-turn trace shows the adjacent-surface phase as the amplifier:
the model re-judged a previously-withheld endpoint re-presented through the
adjacent phase, and cited prior concretisation as evidence ("already owned
by `editor-shell` (28 siblings)") - a progressive-concentration loop over
the `graph_view`-roamed neighbourhood.
The skeleton's contract-less shell Services are the load-bearing defect,
but the roaming read gave the loop its fuel: each chunk's shell endpoints
joined the concretised family, which licensed the next chunk's.

## Decisions

**R-A1. The `graph_view` binding leaves the Assigner turn.**
The Assigner binds ONLY `search_http_history` / `get_http_artifact`.
The recorded-transaction read becomes the whole widening seam, kept
central in the prompt rather than auxiliary: disambiguation/confirmation
AND the adjacently promising surface's fuller response.

**R-A2. The out-of-scope filter is restored.**
`resolve_l0_refs` resolves against the chunk's admitted slice ONLY.
A reference outside the chunk drops as `unresolvable`, even when the
settled project surface holds it - there is no discovery seam left to
license it, so there is no write path for it. The settled-surface reader
(`surface_fn` threading through the supervisor) is removed with it.

**R-A3. The judgment stays chunk-scoped even when the reading roams.**
An HTTP-history read may suggest a neighbour the slice does not carry;
that suggestion stays a hypothesis, never an aggregate.

## Consequences

- The httpx:0 forensics shape (a correct out-of-chunk proposal refused as
  `unresolvable`) can recur; it is the priced cost of removing the
  concentration loop's fuel, and `AssignmentStats.unresolvable` names it
  per chunk instead of hiding it.
- Per-chunk cost falls by the bounded graph phase; the HTTP pair's own
  bound (a handful of lookups, never a trawl) is unchanged.
- `tests/integration/test_assigner_contracts.py::test_C33b/C34b/C34c`
  encode the restored filter and are rewritten by this change, not
  grandfathered - the same rule D-A4 applied in reverse.
