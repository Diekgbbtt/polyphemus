---
artifact: experiment-results
version: "1.0"
created: 2026-10-17
status: complete
---

# Experiment results: hunter TestImplementationSpecs quality under the respecified feed-forward contract

*Method source: the measurement procedure of `measure-experiment-results` (adapted: a qualitative engineering QA with a pre-registered ground truth, not a statistical A/B test; section 2 states the adaptation honestly).*
*Authority: the operator directive of 2026-10-17 (the Q36 answer plus the measurement order).*
*Plan: `docs/design/unit-threat-model-qa-plan.md` (S1-S9).*

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | unit-threat-model-qa-1 |
| **Experiment name** | TestImplementationSpecs quality, loop-payload feed-forward |
| **Status** | Complete (ground truth frozen 2026-10-17; results documented 2026-10-17) |
| **Duration** | 2026-10-17 (single session) |
| **Arms** | One arm: the respecified hunter contract mocked over 22 loops (no control arm exists) |
| **Total sample size** | 22 loops (T1: 13, T2: 9) |
| **Owner** | design session (operator-ordered) |
| **Design doc** | `docs/design/unit-threat-model-qa-plan.md` |

## 1. Hypothesis recap

**Original hypothesis:**

> We believe that the respecified hunter feed-forward contract (a brief loop-entity ontology in the system prompt plus a HumanMessage rendering of the abduction chain - technical interface agreement or dynamic-state evolution -> trust boundary agreement or dynamic-state transition trust -> programming faults -> vulnerability classes - with the failure modes withheld) lets a hunter mint TestImplementationSpecs sets that are well-formed over the captured failure-mode slice: no overlap, exhaustive coverage, grounded concretisation, and discrimination across chaining attacks/advanced techniques, technology misconfigurations, and payload/proxy vectors.

**Success criteria (session-set, qualitative):**

- Primary metric: share of loops whose spec set is **well-formed** (W1 no-overlap and W7 per-spec failure articulation pass, every spec carries class parametrisation and a discrimination note) **and grounded** (W3 strong or partial) - success bar >= 60 percent of loops, target 80 percent.
- Secondary: mean slice coverage W2; discrimination axis usage W5; grounding share W3; overlap pair count W1; skill-parametrisation presence W4.
- Guardrails: no spec set may leak or restate the withheld failure modes as fact (the mock never sees them); no set may collapse into a single broad spec when the payload's slice demands discrimination.

## 2. Method (as executed)

- **S1 payloads.** Built by `docs/experiments/unit-threat-model-prototype/qa/build_payloads.py` from the two trial threat models.
  Each payload renders: unit context; the technical sharpening overview (interface agreements, control flows, data flows); the trust overview (trust boundary agreements, dynamic-state trust); the abduction chain (assumptions -> fault -> vulnerability); likelihood with rationale; confidence degree; evidences.
  Failure modes are withheld; the S1 gate verified 22 payloads parse and contain no failure-mode material.
- **S3 mock package.** `docs/experiments/unit-threat-model-prototype/qa/mock/`: the improved hunter prompt (system + task), the loop ontology, the adapted decision tree, the output contract.
  The mock loads web-vulnerability skills as files from `/Users/diekgbbtt/polymerhus/.claude/worktrees/feat-skills-suite/skills-unspurious/`.
- **S4 dispatch.** Two background subagents (T1, T2), one per model, each iterating its loops and persisting `<t>/output/loop-<n>.yaml`.
  The mock mints specs only; it does not execute tests (no pod by design).
- **S5/S6.** Format and completeness pass, then the assertion pass: grade each output against the section 3 ground truth, walk backward to root causes, cluster actionable defects, write section 4-6.
- **Adaptation note.** The source skill assumes a statistical A/B test (p-values, confidence intervals, traffic split).
  This measurement is a single-arm qualitative QA with N=22 and a pre-registered rubric; no statistical significance is claimed, and the absence of a control arm is a named limitation.

## 3. Quality-assessment ground truth (frozen 2026-10-17, before dispatch)

### 3.1 The artifact under measure

A TestImplementationSpecs set is the hunter's outcome for one loop: the set of concretised test-variant specifications that jointly deepens the slice of the failure-mode space captured by the loop.
Each spec declares at least: the web-vulnerability class and skill parametrisation; the concretisation on the target (protocols, technologies, architecture from the payload); its discrimination basis (see 3.2); its execution-failure articulation (the failing execution condition it targets); and its proxy technique for reaching that condition.

### 3.2 Discrimination variables (the ground-truth axes)

1. **Chaining attacks / advanced techniques** (skill ontology entities; sometimes missing in a skill - the workflow must handle them structurally): variants differ on the trust-agreement failure mode and therefore on the programming fault they exercise.
2. **Specific technology misconfiguration**: variants target a concrete misconfiguration of a technology in the unit's stack.
3. **Payload vectors / proxy techniques**: variants differ on the payload/vector or on the proxy technique that makes the application reach the failing execution mode.

A good set discriminates on a **subset** of these per spec, trading narrow against broad; a set that only varies payload strings under one failure mode is under-discriminated.

### 3.3 Rubric

| ID | Criterion | Scale | Pass bar |
|----|-----------|-------|----------|
| W1 | No overlap between specs (distinct sub-slices) | overlap pair count + notes | <= 1 overlapping pair, no duplicate intents |
| W2 | Exhaustive coverage of the loop's slice | share of anchor rows covered (0-1) | >= 0.7 mean |
| W3 | Grounded concretisation on the target (protocols, technologies, architecture named from the payload) | strong / partial / weak | strong or partial |
| W4 | Skill parametrisation named and supplied (class + parametrisation inputs) | present / absent per spec | present in every spec |
| W5 | Discrimination axis usage | set of {chaining/advanced, tech-misconfig, payload/proxy} used | at least 2 axes where the slice supports them |
| W6 | Proxy technique per spec (how the failing condition is reached) | present / absent per spec | present in every spec |
| W7 | Per-spec execution-failure articulation (its own failure condition; not a restatement of model facts) | present / absent per spec | present in every spec |

### 3.4 Per-loop expectations (coverage anchors from the withheld failure modes)

T1 - `Service:model-download` (base `http://46.224.225.245:44177`; ComfyUI + Manager V3.37; serial model worker):

| Loop | Class/suite | Conf. | Slice anchors (coverage ground truth) | Expected discrimination notes |
|------|-------------|-------|----------------------------------------|-------------------------------|
| t1-loop-1 | SSRF / ssrf | OBSERVED | FM1: worker issues the attacker-chosen request and persists the response; internal services reachable through the channel | Target classes (loopback services, the app itself, metadata), scheme coverage (http/https/ftp/file boundary), redirect/proxy techniques, persistence readback |
| t1-loop-2 | LFI/RFI / path-traversal-lfi-rfi | OBSERVED | FM2: `file://localhost` reads a local file; contents land in a listable model file | File-scheme targeting, path selection (passwd-class, app configs), listing readback variants |
| t1-loop-3 | Unrestricted upload / insecure-file-uploads | OBSERVED | FM3: any bytes stored under client-chosen names/dirs; deployment later trusts the stored file | Content shaping (garbage vs plausible model bytes), name/dir control, load-side trust condition |
| t1-loop-4 | Business-logic / business-logic | OBSERVED | FM4: items outside the catalog are downloaded; the supply-chain control never gates artifacts | Suffix/case variants of the shortcut, catalog-membership differentials, observable divergence |
| t1-loop-5 | LFI/RFI (secrets) / path-traversal-lfi-rfi | OBSERVED | FM13: local secrets (`/proc/self/environ`) copied into the model tree, readable via listings | Secret-file targets, environ readback, differentiation from t1-loop-2 by exfiltration channel |
| t1-loop-6 | Path traversal write / path-traversal-lfi-rfi | OBSERVED | FM5: `..` save_path writes outside the intended subdirectory; pre-placement where other consumers look | Traversal encodings in save_path, target-directory classes, consumer pre-placement condition |
| t1-loop-7 | Cross-entry substitution / business-logic | OBSERVED | FM6: the stored artifact does not correspond to the catalog entry nominally validated | Entry/URL binding confusion, rotation or concurrency timing, artifact-identity differentials |
| t1-loop-8 | CSRF / csrf | OBSERVED | FM7: any HTTP participant, including a cross-site GET, can drain/clear the queue | Endpoint inventory, cross-site delivery proxies (img/form), no-auth proof condition |
| t1-loop-9 | DoS worker crash / (none) | OBSERVED | FM8: one accepted request halts the serial worker; later downloads stay queued | Crash-inducing input classes, persistence of the block, operator-recovery interaction |
| t1-loop-10 | Accounting corruption / business-logic | OBSERVED | FM9: counters undercount and survive reset; readers see wrong completion state | Counter differential sequences (start/clear/reset), reader-visible state divergence |
| t1-loop-11 | Information exposure / information-disclosure | OBSERVED | FM10: anonymous clients enumerate model files and read fetched content | Listing endpoints, readback of fetched content, enumeration bounds |
| t1-loop-12 | Error handling / business-logic | OBSERVED | FM11: malformed requests produce 500s; error path exposed to probing | Malformed-request matrix, parser-boundary classes, observable degradation |
| t1-loop-13 | Race / race-conditions | ASSUMED | FM12: concurrent start and install interleavings may corrupt queue bookkeeping (unprobed) | Interleaving windows, timing proxies, bookkeeping observation condition |

T2 - `WebPresentation:custom-node-catalog::manager-shell` (base `http://46.224.225.245:44177`; ComfyUI-Manager V3.37 shell; catalogue from channels):

| Loop | Class/suite | Conf. | Slice anchors (coverage ground truth) | Expected discrimination notes |
|------|-------------|-------|----------------------------------------|-------------------------------|
| t2-loop-1 | CSRF preferences / csrf | OBSERVED | FM-6: cross-origin GET mutates persistent preference state (channel, db mode, preview, policies) | Per-endpoint variants, delivery proxies, persistence proof, downstream consequence (channel switch) |
| t2-loop-2 | DOM injection fields / xss | OBSERVED | FM-3: author/id markup reaches innerHTML cells; executes on render, no interaction | Field matrix (author, id, others), payload shapes vs the renderer, no-interaction condition |
| t2-loop-3 | Stored XSS description / xss | OBSERVED | FM-1: markdown anchor `javascript:` / attribute breakout executes on hover/click; FM-2: HTML redress pseudo-UI | Server markdown transform vectors, attribute-breakout shapes, redress variants, click/hover condition |
| t2-loop-4 | URL-scheme link injection / xss | INFERRED | FM-4: `repository`/`reference` rendered into anchor href; `javascript:` executes on title click | Link-field vectors, click condition, dataset shapes surviving the server transform |
| t2-loop-5 | Transit injection / xss | OBSERVED | FM-5: trusted-remote notice HTML (TLS verification disabled) injected via innerHTML on every shell load | Network-position proxies, wiki-compromise path, notice render timing |
| t2-loop-6 | State confusion / business-logic | INFERRED | FM-7: init-window preference flip; rows render under a stale channel label | Race window proxies, label/payload divergence observation, decision impact |
| t2-loop-7 | Cache poisoning / (none) | OBSERVED | FM-8: per-URL cache re-serves a poisoned/stale channel list up to a day without freshness marker | Cache-key reasoning, re-selection without approval, persistence window |
| t2-loop-8 | Input validation 500s / (none) | OBSERVED | FM-9: missing/malformed mode -> generic 500s | Malformed-param matrix, automation noise condition |
| t2-loop-9 | Reverse tabnabbing / (none) | INFERRED | FM-10: named target `blank` retains `window.opener`; the opened page can navigate the shell | Named-target semantics, opener-retention proxies, phishing-navigation condition |

## 4. Results

Mechanical pass (S5, `qa/check_outputs.py`): all 22 spec sets parse, carry every contract field, and declare coverage honestly (20 exhaustive; 4 partial with named uncovered regions: t1-loop-9, t1-loop-13, t2-loop-2, and t2-loop-3 - the last declared exhaustive over its articulated slice but partial against the true slice, see 4.4).
61 specs were minted (T1 32, T2 29).

### 4.1 Primary metric

| Scope | Well-formed and grounded | Share |
|-------|--------------------------|-------|
| T1 (13) | 13 | 100 percent |
| T2 (9) | 9 | 100 percent |
| All (22) | 22 | 100 percent |

Both bars met (>= 60 percent success, 80 percent target).
Every set passed W1 (zero overlap pairs, found by the checker and none on manual review), W4 (skill parametrisation in every spec), W6 (a proxy technique in every spec), and W7 (every spec articulates its own execution-failure condition); every `interpretation_guidance` reads a symptom-absent outcome (falsifiability).
W3 grounding is strong on all 22 sets: every spec cites the payload's own fact identifiers (IA/TA/DF/CF/ET/ES/DTV/P anchors) and names the loaded skill files and the entities used.

### 4.2 Secondary metrics

| Metric | Value |
|--------|-------|
| Slice coverage vs the withheld failure-mode anchors (W2) | 20/22 loops full; 2 partial - t2-loop-2 (the `id` field has no evidenced sink in the payload, declared uncovered) and t2-loop-3 (FM-1 fully covered; the withheld FM-2 redress region missed). Weighted mean ~0.97 |
| Grounding share (W3 strong/partial) | 22/22 strong |
| Axis usage (W5) | chaining-advanced in 20/22 loops, payload-vector in 17/22, tech-misconfiguration in 12/22; every loop used at least one axis, 20/22 used at least two |
| Overlap pairs (W1) | 0 |
| Skill parametrisation (W4) | present in all 61 specs; the class-less loops (t1-loop-9, t2-loop-7, t2-loop-8, t2-loop-9) parametrise structurally with `skill: null` and declared degradations |

### 4.3 Guardrails

| Guardrail | Status |
|-----------|--------|
| No withheld-failure-mode leakage into outputs | PASS - no failure-mode ids and no runtime-failure text anywhere; the outputs reason in the failure-modes space as their own hypotheses, grounded only in payload facts and loaded skill files (the run logs confirm the models and the measurement document were never read) |
| No single-spec collapse on demanding slices | PASS - 2-4 specs per loop; the widest slices (t2-loop-1, t2-loop-8) carry the most specs (4) |

### 4.4 Per-loop verdicts

Full grading detail is in `qa/grading-notes.md`; this table is the verdict summary.

| Loop | Verdict | Note |
|------|---------|------|
| t1-loop-1 | PASS | 3 specs: internal-address egress, attributable external origin, non-HTTP scheme dispatch. FM1 covered; redirect-following declared outside the evidenced slice. |
| t1-loop-2 | PASS | 2 specs: authority-form file read, denylist-literal spelling evasion. FM2 covered. |
| t1-loop-3 | PASS | 3 specs: placement-path freedom, content-provenance freedom, loader-consumed placement. FM3 covered including the load-side trust condition (placement-only oracle, declared). |
| t1-loop-4 | PASS | 2 specs: suffix-selected bypass with contrast controls, terminal-literal boundary and name resolution. FM4 covered. |
| t1-loop-5 | PASS | 2 specs: process-state secret reads, identity/system file reads. FM13 covered; the differentiation from t1-loop-2 is stated explicitly. |
| t1-loop-6 | PASS | 2 specs: relative escape reach ladder, escape into consumed locations. FM5 covered. |
| t1-loop-7 | PASS | 2 specs: cross-entry URL substitution, unvalidated-branch check absence. FM6 covered; queue-time mutation declared unevidenced (concurrency timing rides t1-loop-13). |
| t1-loop-8 | PASS | 2 specs: no-context participant crossing, browser-mediated cross-site delivery. FM7 covered. |
| t1-loop-9 | PASS | 2 specs: ui_id type-space poison, tail starvation and recovery closure. FM8 covered; irreversible worker death declared uncovered (outside the evidence and the ground truth). |
| t1-loop-10 | PASS | 3 specs: accept-phase undercount, execution-phase undercount, reset retention and indistinguishability. FM9 covered. |
| t1-loop-11 | PASS | 3 specs: anonymous inventory enumeration, change-detection attribution, content retrieval via sibling stack surfaces. FM10 covered; content readback is conditional on runtime-confirmed core route names (declared). |
| t1-loop-12 | PASS | 3 specs: decode-failure class, schema-shape class, mirror and framing delivery. FM11 covered. |
| t1-loop-13 | PASS | 3 specs: start x start, install x start, install x install transition pairs, each with a held-serialization refutation. FM12 covered; the reset pair declared uncovered. |
| t2-loop-1 | PASS | 4 specs: click-mediated channel write, silent image-loader db-mode write, script-driven preview/policy sweep, forced ordered composition. FM-6 covered. |
| t2-loop-2 | PASS (W2 partial) | 3 specs: raw author/version fields, transformed title, getmappings flyover. FM-3's author leg covered; the `id` field has no evidenced sink in the payload and is declared uncovered - a payload-evidence gap, not a set defect. |
| t2-loop-3 | PASS (W2 partial) | 3 specs: scheme href, attribute breakout, store-then-render persistence. FM-1 covered in both injection contexts; the withheld FM-2 redress region (non-script pseudo-UI) was missed while coverage was claimed exhaustive over the articulated slice. |
| t2-loop-4 | PASS | 3 specs: property-bound href, string-composed attribute context, local/installed provenance route. FM-4 covered. |
| t2-loop-5 | PASS | 3 specs: transport (TLS verification off), extraction framing, authored wiki content. FM-5 covered with the render timing (every shell init). |
| t2-loop-6 | PASS | 3 specs: request-shape binding, display freshness across opens, single-operator premise. FM-7 covered; window timings stated in state terms (declared). |
| t2-loop-7 | PASS | 3 specs: serve-path staleness, write-to-retrieve provenance, revocation lifetime. FM-8 covered. |
| t2-loop-8 | PASS | 4 specs: absence shape, value domain, parser ambiguity, route scope. FM-9 covered; extends the ground truth with the route-scope claim. |
| t2-loop-9 | PASS | 3 specs: catalogue opener retention, named-context sharing/pre-hijack, notice anchor family. FM-10 covered. |

## 5. Segment analysis

- **By trial:** T1 (Service:model-download) covered all 13 GT anchors; T2 (WebPresentation shell) covered 7/9 anchors fully and 2 partially.
  T1's payloads carry dense probe-anchored evidence (P-numbers), and the sets exploit it (exact anchors, contrast controls per spec).
  T2's payloads are more inferential in places, and the two partials both sit where the payload's evidence stops.
  T2 also carries 3 class-less loops of 9 against T1's 1 of 13.
- **By confidence degree:** the OBSERVED loops (19) ground on executed probes; the INFERRED loops (t2-loop-4, t2-loop-6) declare their inferred windows as assumptions and one sub-slice becomes conditional (t2-loop-4-s2 - a defined true-negative outcome if every consumption is property-bound); the single ASSUMED loop (t1-loop-13) is explicitly falsification-shaped - each spec carries a held-serialization refutation and states that positives are stronger than negatives.
  Degradation counts rise toward lower confidence, as expected; quality does not collapse.
- **By suite class:** skill-backed sets inherit the class's testing patterns by name (W4), but several class skills mismatch this unit's architecture: `csrf` presumes cookie-based ambient authority (the routes need no cookie at all), `path-traversal-lfi-rfi` owns path joins but not scheme dispatch (the file reads ride URL scheme handling), `insecure-file-uploads` presumes an upload endpoint where this unit has a queued fetch-and-store.
  Class-less loops (DoS, cache poisoning, input validation, reverse tabnabbing) were handled structurally with declared degradations and reached full GT coverage.
  The dominant quality driver is the payload's evidence depth, not the skill ontology.

## 6. Learnings

### What we learned

- The respecified feed-forward contract works: 22/22 sets are well-formed and grounded (primary metric 100 percent against the 80 percent target), the rubric's axes are exercised as designed, and the "no payload-string variants" discipline held everywhere (0 overlap pairs; 17/22 loops use payload-vector discrimination and still split on distinct failure modes or proxies, not strings).
- The three discrimination axes are usable as specified, including the chaining/advanced axis: 20/22 loops used it, mostly as clause-level or chain-level splits with structural notes where the skill lacks entities.
- Structural handling of missing skill ontology is a real, working path: the four class-less loops produced full-coverage sets with explicit degradations, and the sets stayed falsifiable (every guidance reads symptom-absent).
- The honesty disciplines travel: the sets declare partial coverage exactly where the payload's evidence stops (4 loops), prefer a defined conditional negative over a speculative spec (t2-loop-4-s2), and keep assumption-named claims separable from observed anchors.

### Surprising findings

- The payload's evidence depth is the dominant quality driver; skill coverage matters less than expected. T1's probe-anchored payloads yielded exact anchors and paired controls everywhere, while T2's two partials both trace to payload-evidence gaps, not to hunter reasoning gaps.
- The withheld-failure-mode ceiling is real but narrow: one missed region in 22 loops (t2-loop-3's redress sub-slice) while the T1 sets licensed far-reaching coverage from the payload's rendered chain anyway. The "no failure-mode rendering" rule cost less coverage than predicted.
- Several class skills actively mismatch the unit architecture (csrf without cookies; upload skill without an upload endpoint; traversal skill without scheme dispatch). The structural fallback removed the dependency on the mismatch; the cost was losing the class's testing patterns, not the coverage.
- No overlap appeared anywhere despite the mock being free to err and the rubric setting a zero-tolerance bar; the discrimination-boundary discipline (choose the subset of variables first) appears to be what prevents overlap.

### What we still do not know

- Whether the real hunter (attack-surface graph, HTTP-history reads, KB retrieval, pod execution) closes the two partials or changes the shape of the sets; the mock's fidelity limits this measurement.
- Whether a re-run agrees with this run (no repeat arm; the measurement is single-shot).
- Whether the two partials matter downstream: the pod's outcomes may still confirm or refute the covered regions even when a sub-slice was missed.
- The scoring calibration remains open (threshold, weights, level names); this measurement does not touch it.

## 7. Recommendation

### Decision: Iterate (small contract amendments, not ship-blocking)

**Rationale:** the contract met its primary bar with no guardrail breaches; the defects found are specific and small.
The amendments below are the actionable items, ordered, now with the operator's answers of 2026-10-18.

1. **A1 - Payload completeness for named fields and sinks.** Proposed: carry the sink-locus evidence per named field or an explicit "no sink evidenced" status. **Operator answer: not adopted.** Closed.
2. **A2 - Slice-breadth signalling.** Proposed options (accept the ceiling / vulnerability-level consequence wording / neutral breadth signal). **Operator answer: systematically and reliably verifying exhaustiveness is a very complex problem, so the withheld-failure-mode ceiling is documented here as a structural limitation of the contract for the moment.** Closed.
3. **A3 - Skill-suite inputs (workstream note, not ticketed).** Class candidates: cache poisoning, input-validation/error-handling, DoS/robustness, reverse tabnabbing; a csrf "no ambient authority" variant; and a structural-handling pattern section so the fallback keeps pattern inheritance. Today's mismatch cost is pattern loss, not coverage.
4. **A4 - Decision tree (of the mock).** No change is indicated by this evidence. The operator has since ordered the production prompt redesign (workbench R8-1), which keeps the original tree and integrates the workflow into it; the mock's presentation of the tree is superseded, the reasoning findings stand.

**Confirmation run:** re-measure after the first implementation, against the redesigned production prompt and the real hunter (graph, HTTP history, KB, and later the pod) - expected to bound the mock-related gaps.

## 8. Next steps

| Action | Owner | Status |
|--------|-------|--------|
| A1 payload-completeness rule | operator | closed - not adopted (2026-10-18) |
| A2 slice-breadth signalling | operator | closed - documented as a structural limitation of the contract (2026-10-18) |
| A3 skill-gap list | operator / skills workstream | workstream note, not ticketed (2026-10-18) |
| Production hunter prompt redesign (the mock is not the production prompt) | design workstream | ordered 2026-10-18 (workbench R8-1); implementation in a dedicated work phase with refine-adversarial-review iterations |
| Confirmation run against the redesigned prompt and the live hunter | eval | after the build |

## Appendix

### A. Artifacts

- Payloads: `docs/experiments/unit-threat-model-prototype/qa/t1/input/loop-*.yaml`, `qa/t2/input/loop-*.yaml` (+ `manifest.yaml` each).
- Payload builder: `docs/experiments/unit-threat-model-prototype/qa/build_payloads.py`.
- Mock package: `docs/experiments/unit-threat-model-prototype/qa/mock/`.
- Outputs: `docs/experiments/unit-threat-model-prototype/qa/t1/output/loop-*.yaml`, `qa/t2/output/loop-*.yaml`.
- Source models: `docs/experiments/unit-threat-model-prototype/trials/t1-service-model-download/output/`, `.../t2-system-catalog-manager-shell/output/`.

### B. Method caveats

- Single arm, no control; rubric-anchored qualitative grading; N=22.
- The mock has no live graph, HTTP-history database, or pod; the spec set is the artifact under measure.
- Ground truth frozen before dispatch; later changes to the rubric must be recorded as amendments, not silent edits.

### C. Known issues

- The mock's tool surface is the subagent harness surface (filesystem, shell, web), not the production hunter's typed tools; this bounds realism and is a named limitation.
- Dispatch note: the first two mock dispatches died on free-tier provider rate limits before doing work; the third dispatch moved to the same model family on an unthrottled provider. No artifact differs except the provider.
- The `id`-field and redress partials (section 4.4) are the two evidence-backed coverage gaps; both are carried into the amendments (A1, A2).

---

*Initialised 2026-10-17. Ground truth frozen before dispatch. Results documented 2026-10-17 (S6).*
