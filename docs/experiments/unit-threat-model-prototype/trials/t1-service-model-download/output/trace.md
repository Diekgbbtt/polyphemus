# Trial trace - t1-service-model-download

## Conventions and setup

- Probe ids `P<n>` map to line `n` of `probes.log` (P01 is line 1, P58 is line 58).
- Probes were run through a small helper (`probe.sh` in the session scratch directory) that appends the log line and keeps the raw last response body for inspection.
- One probe = one shell command, as required.
- The curl in this environment is not websocket-capable, so the websocket client channel was never captured.
- Oracle reads used the callback listener (`ssh eval-server-polyphemus 'docker exec web_comfyui-ssrf-listener-1 tail -n 40 /tmp/ssrf_hits.log'`) and were logged as probes (P54, P56) or retro-log entries (P57, P58).
- Log quirks: P01's method label reads `GETI` (helper typos); the request itself was `GET /`.
- P57 and P58 are retro-logged oracle reads: the reads happened during the campaign, but the lines were appended later with a `retro-log:` prefix and the append timestamp.
- Mutating probes were kept minimal and labelled (queueing downloads, one reset, one poison item, one trailing item).

## State 1 - UNIT_TECHNICAL_SHARP (grounding)

Gate: `GATE-WRITE UNIT_TECHNICAL_SHARP` (gates.log line 1).

- Coarse HTTP responses were run, essentially always with curl.
- P01: `GET /` -> 200, ComfyUI shell.
- P02/P03: `GET /manager/version` and `GET /api/manager/version` -> both `V3.37`.
- P04: `GET /externalmodel/getlist?mode=default` -> catalog JSON.
- P05-P07: queue status empty, start no-op, status again.
- P08: empty body on install_model -> 500.
- P09: non-catalog triple -> 200 (accepted).
- P10: status shows total_count 1, not processing.
- P11: fully random non-safetensors triple -> 400.
- P12: default save_path with `.bin` random name -> 400.
- P13: unknown save_path with random `.safetensors` name -> 200.
- P14/P15: start, then done_count 1.
- P16: `GET /models/checkpoints` lists the file.
- P17: `GET /models` lists directories (custom_nodes included).
- P18: direct file GET -> 404.
- P19: `/experiment/models/checkpoints` -> file entries with sizes (29 B).
- P20: experiment file GET -> 404.
- P21: catalog getlist repeated for the gate comparison.

Decisions made.

- Grounded the unit on the three aggregated endpoints and the two connected systems (outbound-fetch, manager shell).
- Established the live gate semantics differentially: extension rule (P09/P11/P13), directory rule, URL rule (P22/P23/P24 later confirmed in state 2).
- Consulted the upstream ComfyUI-Manager tag 3.37 source only as a probe-design aid.
- Divergence: upstream `check_whitelist_for_model` requires catalog membership for every filename; the live gate accepts `.safetensors` names with any host. The live deployment is the authority for the model.

Model at gate: 12 interface agreements, 7 control flows, 6 data flows; state `UNIT_TECHNICAL_SHARP`.

## State 2 - TRUST_MODELLED (trust agreements + dynamic state)

Gate: `GATE-WRITE TRUST_MODELLED` (gates.log line 2).

- The trust-edge differential probes were run in this phase; probe attribution follows the reasoning phase a probe served, not wall-clock order (batches interleave P27-P42 with P43-P51).
- P22: catalog `.pth` triple with a swapped non-catalog URL -> 403.
- P23: `.pth` triple with a different catalog entry URL -> 200 (cross-entry URL accepted).
- P24: `GET /manager/queue/reset` -> 200 (mutating, labelled).
- P25: status after reset still shows total 1, done 1.
- P26: `file:///` URL -> 400.
- P43: `GET /manager/queue/install_model` -> 404.
- P44: `/manager/channel_url_list` -> fixed GitHub raw URL list, selected default.
- P45: `/manager/version` headers re-read (aiohttp, no TLS).
- P46: malformed JSON body -> 500.
- P47: uppercase `.SAFETENSORS` -> 400.
- P48: catalog URL plus a query parameter -> 403 (strict string equality).
- P49: `/api/manager/queue/status` -> 200 mirror.
- P50: poison item (`ui_id` as a dict) -> 200.
- P51: trailing item behind the poison -> 200.

Decisions made.

- Translated each interface agreement into a trust agreement over data attributes, contexts and principals (TA1-TA10).
- Built the queue EFSM with seven states, eight transitions and six violations.
- Key trust bends: extension-as-safety (TA3), URL set membership instead of per-entry binding (TA2), unvalidated `save_path` (TA5), untyped `ui_id` (TA7), counters as truth (TA8), state-changing GETs (TA10).
- Key EFSM findings: reset retains counters (ES5, V3); a non-string `ui_id` stalls the serial worker (ES6, V4); counters undercount (V6).

Model at gate: 10 trust agreements; EFSM 7 states / 8 transitions / 6 violations; state `TRUST_MODELLED`.

## State 3 - TRUST_ASSUMPTIONS_WRITTEN (assumptions + faults)

Gate: `GATE-WRITE TRUST_ASSUMPTIONS_WRITTEN` (gates.log line 3).

- The fault- and egress-oriented probes were run in this phase.
- P27: `custom_nodes` save_path -> 200 (no fetch observed later, P58).
- P28: loopback fetch URL -> 200 (mutating; wrote 5 B "V3.37").
- P29: `..` save_path -> 200 (mutating; wrote under models/etc).
- P30: `ftp://` scheme with a `.safetensors` name -> 200.
- P31: catalog `.pth` triple with a `file://` URL -> 403.
- P32/P34: duplicate `ui_id` values, both -> 200.
- P33: POST via the `/api` mirror -> 200.
- P35: uppercase `FILE://` -> 400.
- P36-P38: `file://localhost` URLs -> 200 (mutating; environ and passwd samples fetched).
- P39/P40: start, then counters total 2, done 2 (undercount against later oracle reads).
- P41: experiment listing shows t1-api-mirror, t1-dup-a, t1-dup-b (size 29 each).
- P42: POST on status -> 405.
- P52/P53: start with the poison head -> no effect; status total 1, done 0.
- P54: oracle read 3: no fetch from the poison batch.
- P55/P56: second start; done 1; oracle hit `t1-15-dead` (mutating recovery).
- P57/P58: retro-logged oracle reads; `t1-2` and `t1-7` fetched; batch hits `t1-10`, `t1-12`, `t1-13`, `t1-14`; no `t1-11-cnodes`.

Decisions made.

- Named assumptions by inducing them from or to programming faults a developer could have made (A1-A15).
- Produced the fault set F1-F15, including the auth gaps (F15) and the concurrency gap (F14, rung ASSUMED).
- Differential results drafted the scheme filter inconsistency (rejects `file:///` and `FILE://`, accepts `file://localhost` and `ftp://`).
- Batch accounting was recorded as an observed divergence: accepted and executed items exceed the counters; the poison item halts the worker and a later start recovers the tail.

Model at gate: 15 assumptions, 15 faults; state `TRUST_ASSUMPTIONS_WRITTEN`.

## State 4 - VULNERABILITIES_WRITTEN (abduction)

Gate: `GATE-WRITE VULNERABILITIES_WRITTEN` (gates.log line 4).

- No new probes: this state is world-2 abduction from the mapped faults.
- Vulnerability classes were named freely from the canonical taxonomy first (SSRF, local file read, unrestricted content write, catalog membership bypass, path traversal, cross-entry substitution, unauthenticated state-changing GET, worker-crash DoS, accounting corruption, information exposure, improper error handling, race, environ disclosure).
- Only afterwards the suite was consulted at `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/` and each class was mapped to its suite directory.
- Mapped: ssrf, path-traversal-lfi-rfi (twice), insecure-file-uploads (twice), business-logic (several), csrf, information-disclosure, race-conditions.
- Gaps flagged: denial-of-service has no suite class (VUL8 keeps `suite_class: null`); supply-chain repository substitution has no suite class (VUL14 keeps null).
- Drop candidates recorded in place for the state-5 feasibility pass: zip-slip (VUL13), repository substitution (VUL14), catalog poisoning/XSS (VUL15), custom_nodes code-directory staging (VUL16).

Model at gate: 12 kept vulnerabilities and 4 drop candidates (16 total); state `VULNERABILITIES_WRITTEN`.

## State 5 - COMPLETED (failure modes, drops, loops)

Gate: `GATE-WRITE COMPLETED` (gates.log line 5).

- Feasibility pass against the state-1 sharpening; the drop rule was applied strictly (no feasible runtime failure mode AND no collectable evidence).
- Dropped 4: zip-slip (no extraction path - raw-byte stores only); HuggingFace repository substitution (no repo route reachable; `install_model` takes a single URL); catalog poisoning/XSS (channel fixed to GitHub raw URLs; no custom channel observed); custom_nodes staging (accepted P27 but never fetched P58; code loading needs a separate step).
- Kept 13 feasible failure modes and ranked them as `loop-1` .. `loop-13`.
- Top three: loop-1 SSRF (high), loop-2 local file read (high), loop-3 arbitrary content write (high).
- 12 evidence gaps recorded, including the uncaptured websocket channel, unprobed load-side impact, size-only content verification, and the unprobed concurrency branch.

Model at gate: 17 failure modes (13 feasible, 4 dropped), 13 loops, 12 evidence gaps; state `COMPLETED`.

## Blocked probes and unrun branches

- Websocket channel capture blocked: the available client is curl, which cannot speak websockets; event semantics are inferred from the halt and recovery behaviour.
- Server-side catalog fetch (GitHub raw) not directly observable; inferred from the fixed channel list (P44) and the served JSON (P04/P21).
- `ftp://` execution not observable: the listener oracle only sees HTTP; the gate acceptance (P30) is evidence, the fetch is not.
- Content read-back blocked by design: direct file GET routes return 404 (P18/P20); content equality is verified by size only.
- Concurrency pair (start || install) deliberately not run: serial queue makes interleaving narrow, the campaign had reached saturation on other branches, and the budget was nearly exhausted; F14/VUL12/FM12 stayed rung ASSUMED.
- Double-start probed only as an empty-queue no-op (P06/P07); repeated-start counter effects unprobed.

## Deviations from the trial spec

- Suite path: the configured path `/Users/diekgbbtt/.claude/worktrees/feat-skills-suite/skills-unspurious/` does not exist; the suite was read from `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`.
- Upstream source: the ComfyUI-Manager tag 3.37 source was downloaded to the scratch directory and read as a probe-design aid; all model claims rest on live probes, and the live-versus-upstream divergence is disclosed in the model environment block.
- The projection baseurl `http://comfyui-manager:8288` is the synthetic form of the live origin `http://46.224.225.245:44177`.

## Mutating effects left on the target (labelled, minimal)

- Model files `t1-*` in the checkpoints directory (tiny bodies, 5-29 B), written by the download probes.
- `models/etc/t1-tr-save.safetensors` from the `..` save_path probe.
- Queue left empty after the recovery start (P55/P56); counters retained stale values by design of the target.
- No delete route exists for written files, so the files cannot be removed over HTTP; they are small, clearly labelled, and harmless.

## Stop rule

- All probeable ASSUMED claims were probed except the concurrency branch (recorded above), and the saturation pass produced no new assumption branches.
- 58 of 60 probe commands used; 2 remained unused at completion.
