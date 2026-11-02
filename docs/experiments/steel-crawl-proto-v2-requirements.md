# steel_crawl prototype v2: requirement and invariant assessment

**Status:** assessment, 2026-11-02.
**Evidence:** `crawl-det2-20261102T104406Z`, `crawl-det3-20261102T105250Z`, and the targeted det4 run.
**Measurement:** `docs/experiments/steel-crawl-proto-v2-measurement.md`.
**Findings:** `docs/experiments/steel-crawl-proto-v2-findings.md`.
**Policy:** deterministic baseline plus Jev direct through TypeSafe SystemOne. The Jev client is verified; `jev1` and `jev2` are complete.

## 1. Summary

The crawl plane is operational on the local deployment.
The registration form succeeded with all five fields.
The passive sidecar captured 87/87 XHR responses and bodies in det2.
The safety guard removed 39 authz and destruction candidates in det2.
The boundary failed once: the role dialog cancel button issued two authz PUTs.
The Jev policy is implemented but unmeasured.
The form and safety gaps are design-level.

The overall verdict is **iterate**, not ship.
The primary blockers are the Jev route, the label-based safety soundness, and the SPA form unit.

## 2. Session and authentication

| ID | Result | Evidence |
| - | - | - |
| A1 | PASS | The crawl attached to the live session `steel-det2-20261102T104406Z`; the catalogue returned the id and the viewer. |
| A2 | PARTIAL | The experiment process starts the session before bootstrap. The crawl phase never calls `start`; the bootstrap does. The spec says the crawl must attach, so this is a harness deviation. |
| A3 | PASS | The oracle ran once per run; phase `oracle` has one flow. |
| A4 | FAIL | `overview.auth_probe.url` is missing; the prototype uses `/api/authentication` as the fallback. See F4. |
| A5 | PASS | The oracle classifies 401, 403, 3xx, and `redirected: true` as unauthenticated. |
| A6 | PASS | Indeterminate results fail closed. |
| A7 | PASS | The missing probe is logged as `auth_probe_missing`. |
| A8 | PASS | The legacy gate rejects the unauthenticated redirect and accepts only the 200 body. |
| A9 | NOT EXERCISED | No resurrection or retry path was run. |
| A10 | NOT EXERCISED | No `session_missing` loss was induced. |

The client-state check is an extension beyond the spec.
The cookie oracle passed while the SPA route guard still redirected.
`localStorage.username` is required; the bootstrap sets it. See F3.

## 3. Traversal

| ID | Result | Evidence |
| - | - | - |
| T1 | PASS | The root `/` was the first page; the app redirected to `/index`. The extra seed `/register` was a declared deviation. |
| T2 | PASS | External CDN and link targets were ignored; the graph only carries the target host. |
| T3 | PASS | One page stack and one consumed map drove the DFS. |
| T4 | PASS | `jev1`, `jev2`, and `jev3` used Jev through TypeSafe SystemOne. The three runs made 349 calls with zero errors. The policy chose every next action and every removed candidate. The quality is mixed; see section 10. |
| T5 | PASS | Menu routes and links became child pages with the parent pushed. |
| T6 | PASS | Local actions were executed and the page was restored or re-projected. |
| T7 | PASS | Exhausted pages popped to the nearest ancestor with residue. |
| T8 | PARTIAL | The run stopped at the action budget, not at the root. The root was not the last page popped. |
| T9 | PASS | The consumed set survived local-state changes; instance keys prevented re-offer. |
| T10 | PARTIAL | The stop reason is `action_budget`; the spec lists `frontier_empty`, `session_deadline`, `session_missing`, `operator_cancel`, or a typed error. |

The action budget is a prototype bound, not a production bound.
The no-op filter changed the DFS order and reduced safety coverage; see F20.

## 4. Interaction

| ID | Result | Evidence |
| - | - | - |
| I1 | PARTIAL | Candidates come from a page-script projection, not the CLI snapshot. The cache and fingerprints are stable. |
| I2 | FAIL | The CLI snapshot exposes 21 refs on the admin dashboard; the DOM projection exposes 28 candidates with fields and selectors. See F5. |
| I3 | PASS | Every candidate has `offer`, `collect`, or `ignore`. No candidate was both offered and collected. |
| I4 | PARTIAL | Inputs, selects, textareas, contenteditable, hidden, and external elements are excluded. Many no-op custom widgets are still offered. |
| I5 | PASS | The policy only chose from `offer`; `collect` downloads and removed forms were never clicked. |
| I6 | PASS | One stale element was consumed and recorded; no retry loop. |
| I7 | PASS | Every variadic verb carried `--`: fill, select, upload. |
| I8 | NOT EXERCISED | No native select was filled; checkboxes were used instead. |
| I9 | NOT EXERCISED | No press action was used. |
| I10 | PARTIAL | The native form has a submit button, so the prototype clicks it. The `requestSubmit()` fallback exists but was not used. |

The submit-control ownership fix is a projection invariant. See F7.

## 5. Safety

| ID | Result | Evidence |
| - | - | - |
| S1 | PARTIAL | Auth state, destruction, and authz state are the only action-domain filters. Registration is an explicit safe write. The symbolic classifier that over-removed the book card and the registration form is removed. |
| S2 | PASS | `choose_removed` depleted the unsafe set; det2 removed 39 candidates. |
| S3 | PARTIAL | Dialog forms were consumed and collected as declared forms. Modal openers such as `添加角色` were removed before their hidden forms opened. |
| S4 | PASS | `choose_chosen` only saw the remaining set; no removed candidate was executed. |
| S5 | PASS | There is no probability threshold; the deterministic policy takes the first lowest-impact candidate. |
| S6 | PASS | There is no post-submit oracle and no per-navigation auth gate. |
| S7 | PASS after the structural fix; FAIL in det2 | The det2 role dialog cancel button issued `PUT /api/admin/role` and `PUT /api/admin/role/menu`. The cancel/close filter remains a projection exclusion. Det4 removed 37 authz/destruction candidates with zero authz PUTs. Jev2 removed 34 destruction controls and the guard caught 2 authz controls. The authz hard guard and the symbolic guard were removed after jev2. Jev3 removed all 35 destruction controls, removed 0 of 2 authz openers, clicked both openers, and produced zero unsafe endpoints and zero authz PUTs. |
| S8 | NOT EXERCISED | No stale removal answer was produced. |

The structural dialog-context rule and cancel/close filter are the proposed fix.
The targeted det4 run validates the fix directly.

## 6. Capture

| ID | Result | Evidence |
| - | - | - |
| C1 | PASS | The passive client attached to the raw CDP page target on `9223`; it sent only read/enable methods. |
| C2 | PASS | Network, Page, Runtime, Debugger, and Log were enabled. |
| C3 | PARTIAL | Method, URL, headers, status, mime, initiator, resource type, and protocol are recorded. Full timing is partial. |
| C4 | PASS | 87/87 XHR/Fetch responses and bodies in det2; 12/12 in det3. |
| C5 | NOT EXERCISED | The target opened no WebSocket; `realtime_events=0`. |
| C6 | PASS | Det3 captured 8 HTTP/3 flows; det2 and det4 captured h2 and h1 only. The target serves h3 for some resources. |
| C7 | PASS | 12 `ScriptAsset` records with absolute URLs and script ids. |
| C8 | PASS | No source map request was issued by the crawl. |
| C9 | PARTIAL | Flows carry page and action ids. Some background flows have no action id. |
| C10 | NOT EXERCISED | The sidecar-unavailable failure path was not induced. |

The bootstrap `/api/login` flow is tagged `bootstrap` and excluded from the manifest.
The phase filter is a required contract. See F14.

## 7. Parameters and forms

| ID | Result | Evidence |
| - | - | - |
| P1 | PASS | 23 observed parameters from query, body, and path segments. |
| P2 | PASS | Values are redacted; only shape, position, and name are stored. |
| P3 | PASS | Two declared forms with declared fields were recorded from removed role dialogs. |
| P4 | PARTIAL | The registration form was submitted once in jev3 with 5/5 fields. The library search form repeated three times in jev1. The prototype now skips a duplicate form after a successful submission by stable form fingerprint. The jev3 run did not reach the library search, so the duplicate fix is not exercised. |
| P5 | PARTIAL | Field type, options, pattern, min, max, and visibility are recorded. Declared names are positional for unlabeled Chinese fields. |
| P6 | NOT EXERCISED | Jev did not choose values. The registration fields use the single-match shortcut, and the search fields were not reached. |
| P7 | PASS | All five registration fields matched exactly one catalogue entry; no value model call was made. |
| P8 | NOT EXERCISED | No field lacked a catalogue match. |

The declared `/register` form reports `GET /register`; the observed request is `POST /api/register`.
The declared versus observed drift is a graph correctness issue. See F8.

## 8. Output and operations

| ID | Result | Evidence |
| - | - | - |
| O1 | PASS | Manifest v2 has `run`, `endpoints`, `parameters`, `scripts`, `realtime`, `errors`, and `stats`. |
| O2 | NOT EXERCISED | The v1 parser was not run against the v2 manifest. |
| O3 | PARTIAL | Pages and actions are local evidence and manifest stats; the observability platform was not used. |
| O4 | FAIL | The HTTP-history edge and `finalize` were not exercised. |
| O5 | FAIL | Partial graph ingestion and the curator were not exercised. |
| O6 | PARTIAL | Errors are recorded; recovery directives are not emitted. |
| O7 | PARTIAL | HTTP flow passwords are redacted, and the raw login body is re-redacted. The host auth file and credential file were removed after the runs. The QA account password is redacted in the value and form logs. |
| O8 | PASS | The owned session stopped; the catalogue returned `{"data":[]}` after det2 and det3. |

The manifest excludes the bootstrap auth flow.
The det2 manifest still carries the two unsafe authz PUTs, which is correct: they were observed.

## 9. Invariants

| Invariant | Result | Evidence |
| - | - | - |
| Auth precondition before traversal | PASS | Oracle `authenticated`; client state present. |
| No anonymous continuation | PASS | 82/82 API requests in det2 carried the session cookie; 0 anonymous. |
| No unsafe action executed | PASS | All executed actions have `ground_truth=safe`; unsafe candidates were removed. |
| No unsafe crawl endpoint observed | FAIL in det2; PASS in det4 | Two authz PUTs from the cancel button in det2. Zero authz PUTs in det4 and zero rows in the det4 boundary set. |
| No safe endpoint removed by mistake | FAIL in det3 | One book card removed because its abstract contains `购买`. |
| Form submission success | PASS | 1/1 in det2 and det3. |
| Every submitted field in the network | PASS | 5/5 in det2 and det3. |
| XHR response and body capture | PASS | 87/87 det2; 12/12 det3. |
| Manifest phase isolation | PASS | `/api/login` is tagged `bootstrap` and excluded. |
| Session stopped and catalogue clean | PASS | `{"data":[]}` after each run. |

The det2 unsafe endpoint invariant is the most important failure.
The det3 safe over-removal is the second boundary failure direction.

## 10. Assessment

The prototype is a valid crawl-plane proof.
The Jev client is a valid transport proof.
The Jev policy quality is mixed.
The destruction boundary is sound.
The authz boundary is incomplete and carries the accepted residual risk.
The form unit still does not cover the SPA dialogs.

The final Jev3 run is the integrated gate.
It is 7 pages and 59 actions.
It submits the registration form once with 5/5 fields.
It captures 73/73 XHR responses and bodies.
It removes 35 of 35 expected destruction controls.
It removes 0 of 2 expected authz openers and clicks both.
It produces no unsafe endpoint and no authz mutation.
The no-op local-state rate is 51.0 percent.
The no-op all-actions rate is 42.4 percent.
The three Jev runs make 349 calls with zero errors and cost `$0.040955`.

The highest-yield fixes are:

1. Add a coverage and effect signal to the policy.
2. Exercise the duplicate search fix by reaching the library search group.
3. Decide the authz residual risk: accept the Jev miss or add explicit authz examples to the prompt.
4. Add a dialog-form unit and a collect-only modal opener.
5. Bind declared forms to observed endpoints.
6. Add `auth_probe.url` and the client-state check.

The targeted det4 run and the dialog probe pass the dialog fix gate.
The cancel and confirm controls are no longer offered.
Registration is a safe write and is submitted.
The symbolic unsafety guard and the authz hard guard are removed.
Jev owns the unsafety decision.
The no-op rate remains the most important trajectory metric.
