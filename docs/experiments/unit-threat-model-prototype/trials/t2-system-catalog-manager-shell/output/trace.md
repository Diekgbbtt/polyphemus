# Trial T2 - trace
Unit: WebPresentation:custom-node-catalog::manager-shell (ComfyUI + ComfyUI-Manager V3.37)
Target probed: http://46.224.225.245:44177 (curl only, one probe per shell command, non-destructive outside labelled mutations)
Artefacts: this directory; suite consulted at /Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/

## Spec deviations and notes

- The suite path in section 3.4 (`/Users/diekgbbtt/.claude/worktrees/feat-skills-suite/skills-unspurious/`) does not exist.
  The suite was located and used from `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`.
- Probes 15 and 16 (cm-api.js and /api/customnode/getlist mirror) were executed in one shell command.
  One probe log line was written per request.
  All other probes were one shell command each.
- Probe line 20 in probes.log is a NORUN entry: the first channel-switch attempt failed in zsh (unquoted URL glob); no HTTP request was sent.
  The corrected probe line 21 follows and performed the request.
- The state field in the model document moves TRUST_MODELLED -> VULNERABILITIES_WRITTEN.
  The TRUST_ASSUMPTIONS_WRITTEN gate content was written to the document before the state field advanced again; both gate log entries exist.
  Metrics for states 3 and 4 are therefore reported as one combined 223 s stretch.
- Probe 19 used a 25 s curl budget (instead of 8 s) to resolve the mode=remote blocking question.
  This is the only timeout deviation, and it is annotated in the probe log line.
- Upstream v3.37 source (github.com raw files) was fetched as a hypothesis generator and cross-check for handler contracts.
  Target-side evidence was still collected for every probed claim; source-only items are labelled INFERRED in the model.

## State 1 - UNIT_TECHNICAL_SHARP

Gate: model document initialised, GATE-WRITE UNIT_TECHNICAL_SHARP logged (2026-10-15T21:38Z).

Probes run (probes.log lines 1-18):

- 1. GET / -> 200, 65200 B, title ComfyUI; no CSP/XCTO/XFO/Set-Cookie headers.
- 2. GET /manager/version -> 200, "V3.37".
- 3. GET /api/extensions -> 200, 35 script paths, 15 under comfyui-manager.
- 4. GET custom-nodes-manager.js -> 200; 11 innerHTML sites, 0 marked, 0 DOMPurify.
- 5. GET common.js -> 200; sanitizeHTML is a full entity escape; used only on response messages.
- 6. GET turbogrid.esm.js -> 200; renderNodeContent sets node.innerHTML = value; string formatter is identity.
- 7. GET /manager/channel_url_list -> 200, {selected: default, list: 6 name::URL channels}.
- 8. GET /customnode/getlist (no mode) -> 500 text/plain "Server got itself in trouble".
- 9. GET /customnode/getlist?mode=cache&skip_update=true -> 200, 8487 packs, 584 descriptions with markup.
- 10. GET comfyui-manager.js -> 200; db-mode combo (cache/local/remote), preference writes over GET ?value=.
- 11. GET /manager/notice -> 200, HTML news block from external wiki + local version footer.
- 12. GET /manager/db_mode -> 200, "cache".
- 13. GET /customnode/getlist?mode=local -> 200, 3421 packs, 4.3 s.
- 14. GET /customnode/getlist?mode=remote&channel=default -> client timeout at 8 s, 0 bytes (blocking server-side fetch).
- 15. GET cm-api.js -> 200 (no channel handling).
- 16. GET /api/customnode/getlist?mode=cache -> 200, 8489 packs (mirror serves same handlers).
- 17. GET /customnode/getmappings?mode=cache -> 200, 1.55 MB pack->node object.
- 18. OPTIONS /manager/channel_url_list -> 200, no Allow header.

Decisions made:

- Grounded the unit on its served assets and route responses (presentation unit, no contract).
- Established: remote catalogue strings (description/title/author/version/id/reference/repository) flow to client DOM as HTML via TurboGrid innerHTML; the server transform only escapes angle brackets and re-introduces anchors from markdown.
- Established: preferences are readable via GET and writable via GET ?value=; no tokens.
- Established: notice HTML originates from an external wiki fetch (TLS verification disabled per upstream source) and lands in innerHTML.

Model state at the gate: environment block, 8 interface agreements, 6 control flows, 6 data flows; all grounded on probes or served code.

## State 2 - TRUST_MODELLED

Gate: trust_model extended, GATE-WRITE TRUST_MODELLED logged (2026-10-15T21:41Z).

Probes run (probes.log lines 19-26):

- 19. GET /customnode/getlist?mode=remote (25 s budget) -> 200 in 10.7 s, 5.1 MB: the outbound channel fetch works but is slow; the 8 s failure was client-side.
- 20. NORUN (shell glob error; no request).
- 21. GET /manager/channel_url_list?value=recent -> 200: unauthenticated GET write of channel selection (prior value recorded: default).
- 22. GET /manager/channel_url_list -> selected=recent: persistence proven.
- 23. GET /customnode/getlist?mode=cache -> channel=recent, 1021 packs: the rendered source follows the persisted config.
- 24. GET /manager/channel_url_list?value=default -> 200: restore of the recorded prior value.
- 25. GET /manager/channel_url_list -> selected=default: restore verified.
- 26. GET /customnode/getlist?mode=cache -> channel=default, 8489 packs: per-channel caches persist independently and are re-served on re-selection.

Decisions made:

- Branch 1 (trust agreements): 8 trust agreements written from the interface agreements, with data-attribute/principal-privilege classification (remote catalogue data treated as markup; GETs trusted as operator intent; external wiki trusted as presentation; no principal model).
- Branch 2 (dynamic state): EFSM defined with 8 states (S0-S7) and 8 transitions; 6 violations recorded, two of them proven by probe (DTV-1 forced preference change and persistence; DTV-4 per-channel cache re-exposure).
- Mutation discipline: current channel recorded before the change and restored immediately after; both verified by read-back.

Model state at the gate: +8 trust agreements, EFSM S0-S7/T1-T8/DTV-1..6.

## State 3 - TRUST_ASSUMPTIONS_WRITTEN

Gate: assumptions and faults written; GATE-WRITE TRUST_ASSUMPTIONS_WRITTEN logged (2026-10-15T21:45Z).

Probes run:

- 27. GET /manager/notice (2nd) -> 200 in 0.5 s, byte-identical to the first: consistent with a live, small external fetch per shell load (upstream: no cache in the handler).

Decisions made:

- Wrote 9 assumptions, each named by induction from or to one programming fault a developer could have made.
- Wrote 9 faults covering: innerHTML sink (F-1), partial sanitiser (F-2), unsanitised href fields (F-3), unauthenticated GET state writes (F-4), notice remote-HTML/TLS (F-5), channel-source binding (F-6), parameter indexing (F-7), missing hardening and principal model (F-8), cache trust (F-9).

Model state at the gate: +9 assumptions, +9 faults.

## State 4 - VULNERABILITIES_WRITTEN

Gate: vulnerabilities written; GATE-WRITE VULNERABILITIES_WRITTEN logged (2026-10-15T21:45Z, same logging batch as state 3).

Probes run: none (state 4 is abduction over existing evidence).

Decisions made:

- Named 10 canonical classes freely first, then mapped onto the suite: xss (V-1 description, V-2 record fields, V-3 href fields, V-4 notice), csrf (V-5), business-logic (V-6), ssrf candidate (V-10), and three canonical-without-suite-class items (V-7 cache poisoning, V-8 input validation, V-9 tabnabbing).
- Suite mapping used top-level class directories: xss, csrf, business-logic, ssrf.
- Gaps flagged for V-7/V-8/V-9 and the out-of-unit install_model URL candidate.
- Deviation: an internet search to confirm named-target noopener semantics failed; V-9 kept at INFERRED with an explicit caveat.

Model state at the gate: +10 vulnerabilities, +8 evidence gaps.

## State 5 - COMPLETED

Gate: failure modes and loops written; GATE-WRITE COMPLETED logged (2026-10-15T21:46Z).

Probes run: none.

Decisions made:

- Deduced 11 runtime failure modes (1:n per vulnerability) grounded in the state-1 sharpening.
- Feasibility check per vulnerability executed; one drop recorded in place: V-10 (SSRF via channel URL) with reason - no interface writes an attacker URL into the channel config; the outbound mechanism itself is evidenced, the attacker-controlled form is not reachable from this unit.
- Ranked 9 loops by likelihood: 1 high, 5 medium, 3 low; loop-1 = forced preference state changes (csrf), loop-2 = stored injection via author/id record fields (xss), loop-3 = stored injection via description markup (xss).
- Stop rule met: every probeable ASSUMED claim was raised, falsified, or blocked with a recorded reason; the final probing pass over the sharpening produced no new assumption branches.

Model state at the gate: state COMPLETED; 11 failure modes; 9 loops; 1 drop (FM-11).

## Blocked probes and reasons

- mode=remote network-failure branch (stale-cache fallback vs 500): no way to make the fixed channel URLs unreachable from the probe position; blocked with reason.
- SSRF via channel URL (listener oracle): no route accepts or persists a channel URL from a request; selection is restricted to the predefined dict; blocked with reason.
- Notice-URL redirection to the ssrf-listener: the notice URL is hardcoded in the server; blocked with reason.
- Named-target noopener behaviour: needed an in-browser check or documentation lookup; the environment search failed; recorded at INFERRED with caveat.
- db_mode/preview/policy write probes: not run; the GET-write class was already proven on the channel route, and the probe budget was preserved.

## Final counts (model document)

interface agreements 8; control flows 6; data flows 6; trust agreements 8; EFSM states 8, transitions 8, violations 6; assumptions 9; faults 9; vulnerabilities 10; failure modes 11 (1 dropped with reason); loops kept 9, dropped 0 loops (the drop is the V-10 vulnerability row).
