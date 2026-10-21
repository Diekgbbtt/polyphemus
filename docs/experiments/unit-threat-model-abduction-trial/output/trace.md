# Trace - trial `t1-tbsg-service-model-download` (threat modeller, boundary-abduction variant)

Target: `http://46.224.225.245:47745` (ComfyUI + ComfyUI-Manager V3.37, aiohttp/3.14.3).
Unit: `Service:model-download`.
Raw probe lines: `probes.log` (57). Episodic notes: `notes.md` (15). Gates: `gates.log` (5).
Shell probe commands used: 57 curl probes + 2 ssh oracle reads = 59 (limit 60).

## Conventions used throughout

- One probe = one shell command; every probe appended one `probes.log` line with method, path, status and a one-line observation.
- Black-box discipline: all target interaction was HTTP via `curl --max-time 8`; only target-served HTTP responses (HTML, JS) were read; no container filesystem, process or log access.
- Mutating probes were minimal and labelled: the accepted install jobs were cleared with `queue/reset`; the one completed download (1.01KB asset) could not be removed (no HTTP delete route found) and is recorded as a labelled residue (EG-5).
- No HTTP-history store exists (`environment.http_history: none`), so every evidence record is a request run in this trial or a note written in it.

## State 1 - UNIT_TECHNICAL_SHARP

Gate write: `GATE-WRITE UNIT_TECHNICAL_SHARP` (2026-10-18T13:21:36Z). Model initialised with
`environment`, `technical_sharpening.interface_agreements` (IA-1..IA-7), `control_flows` (CF-1..CF-4),
`data_flows` (DF-1..DF-4). State of the model at this point: no trust model, no assumptions.

Probes run (all 59 shell probe commands of the trial belong to this phase):

| # | probe | result used for |
|---|-------|-----------------|
| 1-4 | `GET /`, `/manager/version`, `/manager/queue/status`, `/api/manager/queue/status` | base grounding: ComfyUI SPA 200, V3.37, queue counts JSON, `/api` mirror identical |
| 5-8 | `GET /api/externalmodel/getlist` (no mode), `/externalmodel/getlist`, `POST install_model {}`, `GET /manager/queue/start` | catalog route needs `mode` (500 without it); `{}` -> 500; start idle -> 200 empty |
| 9-10 | `POST install_model {"id": ...}`, `GET /api/extensions` | wrong key also 500; extension list revealed the manager shell JS paths |
| 11 | `GET /manager/` | octet-stream response (not useful; branch dropped) |
| 12-13 | `GET /extensions/comfyui-manager/cm-api.js`, `model-manager.js` | exact request shapes: install posts `item.originalData` + `ui_id`, `getlist?mode=`, `queue/start` after installs |
| 14-16 | `GET /externalmodel/getlist?mode=default`, `/api/externalmodel/getlist?mode=default`, `comfyui-manager.js` | 564-record catalog JSON (url/filename/save_path per record); queue control surface |
| 17 | `POST install_model` forged url (listener marker 1) | 400 "Invalid model install request is detected" |
| 18 | `POST install_model` correct md5 ui_id + forged url/filename (marker 2) | 400; ui_id formula not sufficient |
| 19 | `POST install_model` verbatim record + computed ui_id | 200 accepted (queue 1) |
| 20 | `POST install_model` forged save_path only | 400 |
| 21 | `POST install_model` verbatim + bogus ui_id | 200 (ui_id not checked) |
| 22 | `POST install_model` forged filename only | 400 |
| 23-25 | `GET queue/status`, `queue/reset`, `queue/status` | pending count reached 3; reset cleared them (restore) |
| 26-29 | `GET /manager/channel_url_list`, `getlist?mode=__tm_unknown_mode__`, `?mode=recent`, `?mode=http://ssrf-listener:8000/...` | channel list (6 name::url pairs); mode ignored: four byte-identical 265778-byte responses |
| 30 | `POST /api/manager/queue/install_model` verbatim | 200; mirror shares validation and queue |
| 31 | `GET queue/status` | count 1 |
| 32-33 | `POST install_model` forged description+reference; url + suffix | reference accepted (200); url deviation -> 403 "A security error has occurred..." |
| 34-35 | `POST install_model` save_path traversal, filename traversal | both 400: exact-value semantics |
| 36 | `POST install_model` filename as number | 500 "Server got itself in trouble" (type not validated) |
| 37-38 | `GET queue/reset`, `queue/status` | restore to 0 before the end-to-end run |
| 39-42 | `POST install_model` smallest catalog entry (1.01KB GroundingDINO cfg), `GET queue/start`, `queue/status` (done 1/1), `GET getlist?mode=default` | end-to-end: the worker fetched and installed the artifact; `installed` False -> True |
| 43-44 | oracle read (ssh) + `GET /manager/channel_url_list?value=tmprobe::http://ssrf-listener:8000/...` + read-back | no listener hits; injected channel value: no list change, no fetch |
| 45-48 | channel select `tutorial`, read-back, restore `default`, read-back | the setter works and is unauthenticated; selection flipped and restored |
| 49 | `POST install_model` forged url with `Content-Type: text/plain` | parsed anyway -> 400 (no media-type check) |
| 50-52 | `POST install_model` mixed record (url A + filename/save_path B) -> 200; `queue/status` (total 2); `queue/reset` + `queue/status` | per-field membership accepted; restore to pending 0 |
| 53-54 | `GET install_model`, `POST queue/start` | 404 (POST-only route under GET), 405 (GET-only route under POST) |
| 55-57 | (queue/reset, status confirmations) | final restored state: total 1 done 1, pending 0, installed asset residue recorded |

Corrections during the phase: the first catalog request without `mode` was a 500 and was re-run with
`mode`; the first method-tampering pair replaced an earlier plan to test batch payloads (dropped as
uninformative).

Decisions: (a) probe the aggregated endpoints first, then the shell JS to learn exact request shapes;
(b) map the acceptance predicate by single-field deviation probes rather than guessing the validator;
(c) run exactly one full install job (smallest catalog entry) to observe the file data flow;
(d) falsify every attacker-URL hypothesis with the callback listener instead of assuming reachability.

## State 2 - TRUST_MODELLED

Gate write: `GATE-WRITE TRUST_MODELLED`. Model extended with `trust_model.trust_agreements`
(TA-1..TA-6) and `dynamic_state_trust` (states S0..S5, transitions T-1..T-8, violations V-1..V-3).

Branch 1 (trust agreements): every IA became a `requires` list; the comparison establishes-vs-requires
produced the gap candidates. The distributing observation is that the established side is a per-field
membership test over catalog value sets, while every "the record is one record" requirement is unmet.

Branch 2 (dynamic state): the EFSM was written from the probed transitions. Only T-1 carries a real
guard (per-field membership); T-3 and T-5 carry none. T-7/T-8 (install or reset during processing)
were modelled `ASSUMED`: probing them needs a long-running job and was blocked with reason (see below).

Decisions: keep `requires` items as claims with rungs; do not promote the client-side `is_processing`
check to a server-side guard without evidence.

## State 3 - TRUST_ASSUMPTIONS_WRITTEN

Gate write: `GATE-WRITE TRUST_ASSUMPTIONS_WRITTEN`. Model extended with `assumptions` (A-1..A-9) and
`faults` (F-1..F-9).

Abduction: the four dimension questions were run over all 7 interface agreements and all 8
transitions. Gaps found and their dimensions:

- IA-1 interpretation+spatial: no joint record binding; size/description/reference/ui_id unvalidated
  (A-1, A-2, A-8, A-9).
- IA-2/T-3/T-5 identity+temporal: no entitlement, global mutable pending set (A-3, A-4, A-5).
- IA-6 interpretation: unverified origin bytes (A-6).
- IA-7 interpretation: raw DOM interpolation (A-7).

Propagation walk (bounded): A-7 was marked `propagated` with origin IA-6 (unverified remote catalog
content carried into the shell renderer). A-5 was traced to A-4 but kept `local` because the transition
boundary T-8 is where the bend occurs. No interleaving enumeration; no composition-only claims.

Closure check before the gate: every IA and every transition carries a boundary record; every
assumption resolves to exactly one (`unresolved boundary_refs` = empty, re-verified by YAML parse).

## State 4 - VULNERABILITIES_WRITTEN

Gate write: `GATE-WRITE VULNERABILITIES_WRITTEN`. Model extended with `vulnerabilities`
(V-1..V-9 kept; V-D1..V-D4 falsified and kept in place with `rung: FALSIFIED`).

Class naming came first (no suite consulted): record recombination, unbound job-identifier spoofing,
forced operations via CSRF, shared-queue manipulation, reset/worker TOCTOU, unverified artifact
installation, catalog-driven DOM injection, catalog-value traversal, validation-layer oracle. Only then
were they mapped onto the suite (`skills-unspurious`): business-logic, two-principal-authz, csrf,
business-logic, race-conditions, rce, xss, path-traversal-lfi-rfi, information-disclosure. The four
falsified SSRF candidates were named before the probes and dropped after them.

The suite was consulted (SKILL.md frontmatter of the candidate classes) only after the free naming.
Every `suite_class` equals an existing class directory name.

## State 5 - COMPLETED

Gate write: `GATE-WRITE COMPLETED`. Model extended with `failure_modes` (FM-1..FM-10 feasible,
FM-D1..FM-D4 dropped), `loops` (loop-1..loop-9, ranked by likelihood, impact excluded) and
`evidence_gaps` (EG-1..EG-9).

Deduction: each vulnerability was mapped back onto its runtime failure mode in the state-1 picture
(write path under `models/<save_path>/<filename>`, global queue transitions, shell DOM, origin fetch).
Feasibility: all kept failure modes are technically feasible; the four SSRF-shaped candidates were
dropped with in-place reasons (see below). Ranking by likelihood: loop-1 and loop-2 `high`; loop-3 and
loop-4 `medium`; loop-5..loop-9 `low`.

## Blocked probes and their reasons

- T-7/T-8 server-side behaviour (install or reset while `is_processing` is true): blocked - would need
  a long-running job (largest catalog entries are hundreds of MB); recorded as ASSUMED (EG-2).
- websocket status channel (`client_id`-keyed): blocked - not probeable with `curl` only (EG-1, EG-8).
- worker TLS/redirect behaviour: blocked - the url set is closed to catalog values (EG-6).
- case/unicode/whitespace variants of the acceptance predicate: blocked by budget - the matrix covered
  one record plus cross-record mixing (EG-7).
- catalog values containing traversal segments: blocked - a probe cannot forge a catalog value (EG-5
  analogue; assumption A-8 remains ASSUMED).
- `mode`-driven catalog refresh: not blocked but unobservable (byte-identical lists) - recorded EG-3.

## Falsification summary (listener oracle + rejection matrix)

Four attacker-URL hypotheses were falsified with the listener (no hits on two reads) and with the
rejection matrix: url field SSRF (403 on deviation / 400 on force), mode-parameter SSRF (byte-identical
cached list), reference-field fetch (accepted but never fetched), channel-url injection (no effect).
Dropped in place as V-D1..V-D4 with FM-D1..FM-D4 `feasible: false`.

## Saturation and stop rule

Stop rule satisfied: every probeable `ASSUMED` claim was probed, raised or blocked-with-reason (A-5,
A-8, EG-2/EG-6/EG-7); the final pass (method-discipline probes plus the YAML closure re-verification)
produced no new assumption branches. Total 59 shell probe commands, under the 60 limit.
