# Projection and prompt fix results

*Status: implemented and verified on `fix/l1-projection-prompt-fixes`.*
*Root cause: `ROOT-CAUSE-UNIT-DIFF.md`. Plan: `ROOT-CAUSE-AND-FIX-PLAN.md`.*

## What changed

| Change | Result |
|---|---|
| Projection render | The 4000-character JSON cap is gone for the unit projection. |
| Render shape | Markdown tree: unit -> service -> endpoints -> parameters, plus one separate unique-header list per baseURL. |
| Endpoint identity | Every endpoint carries method, path, status code, content type, and content length. |
| Cooperating systems | Non-Service neighbours render as `### System: <kind>:<discriminator>` with their description. |
| Parameters | Read from `Endpoint-[:HAS_PARAMETER]->Parameter`; absent renders "Parameters: none observed". |
| Headers | Read from `BaseURL-[:HAS_HEADER]->Header`, with an Endpoint fallback declassed to the baseURL; deduplicated by name, value, and direction. |
| Secret headers | `set-cookie`, `cookie`, `authorization`, and `proxy-authorization` values are redacted; cookie attributes remain. |
| Spatial axis | The three HTTP-carrier bullets are replaced by the data-contract and application-context paragraph. |
| Typist status codes | 404 is a request-shape mismatch, 400 a parser-shape mismatch, 401/403 an existing route behind a boundary, 5xx an existing handler that failed. |
| Typist recovery | The typist queries HTTP history, recovers the canonical shape, and replays it before concluding absence. |
| Typist reconciliation | Every API-backed Service is linked to the API System, or the withheld link names the status code and request shape that justified it. |

## Live projection replay

The replay ran against the remote Neo4j graph over an SSH tunnel. No remote code was changed.

| Project | JSON before | Markdown after | Services | Endpoints | Header lines |
|---|---:|---:|---:|---:|---:|
| Old `7eb71c29` | 7,627 chars | 3,126 chars | 7 | 11 | 12 |
| New `dda347be` | 4,420 chars | 2,070 chars | 4 | 5 | 14 |

The old render includes the full business surface:

- `article-management`, `jotter-reading`, `library-catalog`, `navigation-menu`, `register`, `sign-in`, `user-administration`.
- Every one of the 11 aggregated endpoints, with its status and content type.
- Every service contract, including the catalogue, journal, and account-roster contracts.

The new render includes the four services the new graph actually holds.
It cannot include `library-catalog`, `jotter-reading`, or `user-administration` because the graph lacks those edges.
A new trial is required to prove the typist prompt change restores them.

## Tests

| Suite | Result |
|---|---|
| Targeted projection, renderer, modeller, spatial, typist tests | 72 passed |
| `tests/attack` | 1,114 passed |
| `tests/analysis` | 399 passed |
| `tests/eval` | 849 passed |
| `compileall` on the touched source files | clean |
| `git diff --check` | clean |

The renderer tests pin four properties beyond the plan:

- Endpoint status and content type render beside the path.
- Non-Service cooperating systems render for a Service unit.
- Orphan endpoints on a System unit are never dropped.
- Secret header values are redacted while their attributes remain.

## Remaining limitations

- The new graph still lacks the three lost edges. The renderer cannot invent them; the typist prompt change needs a fresh run to prove it.
- Both live graphs contain zero `Parameter` nodes. The parameter read and render path are pinned by fixtures only.
- The hidden provider thinking effort is still not recorded. The trace-visible model and parameters are identical.
- The old run was a one-unit modeller-only run. The new run was a full three-unit pipeline. The per-unit budget comparison remains descriptive.

## Commits

| Commit | Change |
|---|---|
| `31f4324d` | Read headers and parameters; add the coherent Markdown renderer. |
| `b19c62f5` | Use the renderer in the modeller turn. |
| `095bc48c` | Lean the spatial axis toward data contracts and application contexts. |
| `800b0aec` | Add the typist status-code and reconciliation rules. |
| `ca3eeed3` | Show endpoint status and cooperating systems; redact secret headers. |
| `65ce0a1b` | Root-cause report and plan. |
