# S6 grading notes - working file (assertion pass)

Rubric: W1 no-overlap; W2 slice coverage vs withheld failure-mode anchors; W3 grounding; W4 skill parametrisation; W5 axes; W6 proxy technique; W7 per-spec failure articulation. Well-formed and grounded = W1 + W7 + W4 all pass and W3 >= partial.

## T2 - `WebPresentation:custom-node-catalog::manager-shell` (9 loops, graded 2026-10-17)

| Loop | GT anchor | Verdict | Notes |
|------|-----------|---------|-------|
| t2-loop-1 | FM-6 preference-mutation CSRF (channel, db mode, preview, policy) | PASS | 4 specs = 3 delivery proxies x route families + 1 ordered composition; all preference families covered; persistence read-back and downstream resolution both stated. Strong grounding (routes, probe facts). |
| t2-loop-2 | FM-3 author/id markup to innerHTML, no interaction | PASS (W2 partial) | 3 specs (raw author/version; transformed title; getmappings flyover). `id` field uncovered - payload evidences no sink; honest uncovered region, not a set defect. Root cause: payload-evidence gap. |
| t2-loop-3 | FM-1 anchor javascript:/breakout + FM-2 HTML redress | PARTIAL | 3 specs cover FM-1 fully (URL-value, attribute-value, store-then-render). FM-2 (withheld; pseudo-UI/redress region) uncovered; the mock's slice statement stops at script execution. Root cause: slice articulation bounded by payload-visible evidence; "no failure-mode rendering" creates a coverage ceiling. Candidate contract-level insight. |
| t2-loop-4 | FM-4 repository/reference to anchor href, javascript: on click | PASS | 3 specs (property-bound href; string-composed attribute context; local-provenance route). Click condition, field pair, context split all present. |
| t2-loop-5 | FM-5 trusted-remote notice HTML transit (TLS off) | PASS | 3 specs = transport (verify_ssl off), extraction framing (presence-only check), authorship (wiki). Matches GT expectations exactly; render timing (every shell init) stated. |
| t2-loop-6 | FM-7 init-window flip; stale-label render; decision impact | PASS | 3 specs = request-shape binding (flip window), display freshness (between opens), single-operator premise (two sessions). Decision impact rides as consequence in each spec. |
| t2-loop-7 | FM-8 per-URL cache persistence: stale/poisoned, no freshness marker, re-selection | PASS | 3 specs = serve/staleness, write provenance/re-exposure, revocation lifetime. All GT elements covered. |
| t2-loop-8 | FM-9 missing/malformed mode -> generic 500s | PASS | 4 specs = absence, value domain, parser ambiguity, route scope. Extends GT (route scope). |
| t2-loop-9 | FM-10 named target 'blank' opener retention | PASS | 3 specs = opener retention (catalogue), named-context sharing/pre-hijack, notice family. GT elements covered. |

T2 mechanical: 0 problems; all files parse; contract complete; coverage claims honest (2 loops partial/declared).

### T2 cross-loop observations

- The three axes are used per their applicability; every spec carries a proxy technique and a falsifiable guidance (symptom-absent readable).
- No overlap found by me or by the mock's checks; the discrimination notes name the nearest sibling and the separating variable.
- **Class-skill ontology gaps** (handled structurally, as Q36 anticipated): no suite skill for cache poisoning (loop-7), input validation/500s (loop-8), reverse tabnabbing (loop-9); partial mismatch for CSRF-without-cookies (loop-1). Structural handling was high quality but does not inherit the skill's testing patterns.
- **Payload-evidence gaps**: loops 2 and 4 carry assumptions/conditional regions where the model's sharpening lacks a sink locus; the sets name them honestly rather than speculating. Candidate actionable: the loop payload should carry the sink-locus evidence for every field the vulnerability names.
- **Coverage ceiling from withheld failure modes**: loop-3 shows the set covering only the regions derivable from the payload's rendered chain; the withheld FM-2 region was missed silently (coverage claimed exhaustive over the articulated slice). Candidate actionable: either render slice-breadth signals (e.g. number/kind of kept failure modes without content) or accept the ceiling as a contract property; the QA insight goes to the next grilling round.

## T1 - `Service:model-download` (13 loops, graded 2026-10-17)

| Loop | GT anchor | Verdict | Notes |
|------|-----------|---------|-------|
| t1-loop-1 | FM1 SSRF end-to-end, internal services reachable | PASS | 3 specs: internal-address egress, attributable external origin, non-HTTP scheme dispatch. Clause-split of TA4; redirect-following excluded by evidence (declared). |
| t1-loop-2 | FM2 `file://localhost` local read into a listable model file | PASS | 2 specs: authority-form file read, denylist-literal spelling evasion. |
| t1-loop-3 | FM3 arbitrary bytes under client-chosen names; consumer trust | PASS | 3 specs: placement freedom, content provenance, loader-consumed placement. Load-side effect kept placement-only (declared). |
| t1-loop-4 | FM4 catalog bypass via suffix shortcut | PASS | 2 specs: suffix-selected branch with 400 contrast, predicate boundary + name-resolution differential. |
| t1-loop-5 | FM13 `/proc/self/environ` into the model tree | PASS | 2 specs: process-state secrets, identity/system files; differentiation from t1-loop-2 explicit. |
| t1-loop-6 | FM5 `..` save_path escape; pre-placement | PASS | 2 specs: reach ladder, escape into consumed locations (custom_nodes). |
| t1-loop-7 | FM6 artifact not matching the validated entry | PASS | 2 specs: cross-entry substitution (from catalog inventory), unvalidated-branch absence. Concurrency timing declared unevidenced (rides t1-loop-13). |
| t1-loop-8 | FM7 unauthenticated state-changing GET | PASS | 2 specs: no-context crossing, browser-mediated delivery. |
| t1-loop-9 | FM8 worker halt from one accepted request | PASS | 2 specs: ui_id type space, tail starvation + recovery closure. Irreversible death declared uncovered (not in GT). |
| t1-loop-10 | FM9 counter undercount + reset retention | PASS | 3 specs: append, drain, reset transitions, each with its own oracle. |
| t1-loop-11 | FM10 anonymous inventory + content readback | PASS | 3 specs: inventory, temporal attribution, sibling content surfaces. Content readback conditional on runtime route names (declared). |
| t1-loop-12 | FM11 malformed requests to 500s | PASS | 3 specs: decode, schema shape, mirror/framing. |
| t1-loop-13 | FM12 concurrent start/install corruption (unprobed) | PASS | 3 specs: three transition pairs, each falsification-shaped with a held-serialization refutation. Reset pair declared uncovered. |

### T1 cross-loop observations

- Strongest grounding in the run: every spec cites P-numbered probe anchors and carries contrast controls; clause-level splitting of the trust agreement (F2/F3/F5/TA4/TA5) is the dominant discrimination move.
- Skill mismatches: `path-traversal-lfi-rfi` owns path joins, not scheme dispatch; no error-handling, DoS, or cache classes exist; queue/accounting is not a skill entity. All handled structurally with declared degradations.
- 11 exhaustive + 2 honest partials; no overlap anywhere; every guidance falsifiable.

## Final metrics and clusters (both trials)

- Primary: 22/22 well-formed and grounded (T1 13/13, T2 9/9); bar >= 60 percent, target 80 percent - both met.
- W2: 20/22 full GT-anchor coverage, 2 partial (t2-loop-2 `id` field; t2-loop-3 redress region); weighted mean ~0.97.
- Overlap pairs 0; W4 present in 61/61 specs; W5 axes: chaining 20/22, payload-vector 17/22, tech-misconfiguration 12/22; guardrails PASS (no leakage; no collapse).
- Clusters: (1) skill-ontology gaps/mismatches -> structural handling works, pattern inheritance lost; (2) payload-evidence gaps -> two GT-level partials (A1/A2 amendments); (3) no decision-tree change indicated.

