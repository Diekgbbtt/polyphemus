---
artifact: experiment-results
version: "1.0"
created: 2026-10-19
status: completed
---

# Arm L: high vs max analysis workflow comparison and the analysis-owned residual (2026-10-19)

Extends `docs/experiments/2026-10-19-arm-l-384-385-fixes-and-thinking-trials.md` (the arm L results) with an analysis-only deep dive.
The question: which residual well-formedness gains are owned by the analysis pipeline alone, and what experiments capture them.

## Summary

| Attribute | Value |
|-----------|-------|
| **Scope** | The analysis phase of both arm L trials only (typist + assigner). Hunting is not compared (see caveats). |
| **Declared variable** | Thinking level of the typist and the assigner: `high` (trial 1) vs `max` (trial 2) |
| **Controlled** | Same stack, target, model, prompts, L0 input (checkpoint-verified) |
| **Target score** | high 0.697 -> max 0.716 (+0.019) |
| **GT misses** | high 17, max 15 |
| **All of the gain** | `white-jotter-002` M3 only (+0.133 on that spec); the rest of the delta is zero |
| **Analysis-owned stable misses** | 5 requirement items in both arms, worth about +0.097 target points when fixed |
| **Owner of the rest** | recon 9 items, instrument 1 item |

The max arm is better on this target, but narrowly.
Its advantage comes from two things: a live auth-state differential that produced direct evidence about the session gate, and wording that satisfies the GT's keyword-conjunction statements.
The analysis pipeline owns 5 stable misses that neither thinking level fixes.
Closing those 5 items would move the max arm to about 0.813 (0.716 + 0.097).
The high arm reaches the same point when the E3 description rule also recovers its 2 run-specific S2/S4 items.

## The controlled comparison

### What is controlled

| Control | Evidence |
|---|---|
| Stack | `eval_sha` `7c7b5d1fedab1c9183a384216271b0c971158418` for both |
| Model | `opencode-go/deepseek-v4.1-flash`, no forced tool choice |
| Prompts | Same prompt files for both trials |
| Target | `white-jotter` only |
| L0 input at the big-block delivery | 87 Endpoints + 4 Parameters in both runs (container checkpoint decode; see method notes) |
| L0 input, per chunk | `l0_assets` 9 / 36 / 3 / 4 / 24 / 591 in both runs |
| Graph endpoint identities | 113 endpoint rows, 113 shared between the runs |
| Triager output | 17 generations both; raw output 77,585 vs 77,292 chars |

### What is not controlled (found and quantified)

- **Recon insight text.** One insight is repeated on every L0 asset: a BaseURL-anchored observation.
  Its text differs between runs: 3,578 chars under `high` vs 1,509 under `max`.
  The totals over all assets are 329,176 vs 138,828 chars.
  This is recon-side variance, not analysis-side, and it is not the declared variable.
- **Delivery concurrency.** Trial 1 re-delivered the big block 9 times while recon kept streaming (09:08:43 to 09:10:49; 6 of the deliveries emitted nothing).
  Trial 2 delivered it once after recon settled (10:47:41, 25 generations).
  This shaped how fragmented the two typists' reasoning and batches were.
- **Langfuse capture truncation.** The captured analysis input appears to show 59 endpoints under `high` and 87 under `max`.
  That is an artifact: the trace payload cap truncates long inputs (marker shape `[truncated 142347 bytes]`).
  The checkpoint decode proves the inputs were identical.
  Use the checkpoint, not the captured input, as the L0 control.

## Dimension 1: chain of thought

| Measure | high | max |
|---|---:|---:|
| Typist dispatches | 14 (5 early + 9 tail) | 6 (5 early + 1 settled) |
| Typist generations | 78 | 97 |
| Typist phase mix (reflection / extraction / linking) | 70 / 5 / 3 | 86 / 8 / 3 |
| Typist reasoning chars (total) | 366,346 | 364,914 |
| Typist reasoning chars (avg per generation) | 4,697 | 3,762 |
| Assigner dispatches / generations | 5 / 15 | 5 / 16 |
| Assigner reasoning chars (total) | 138,657 | 78,802 |
| Assigner reasoning chars, final big-block dispatch | 96,506 | 45,462 |

Reading the numbers:

- The two typists spent almost the same total reasoning volume.
  The max spread it over more, shorter generations; the high concentrated it into fewer, longer ones.
  "Max thinks more" is wrong at this granularity.
- The assigner is the sharper contrast: the high reasoned 1.8x more than the max, and its final big-block dispatch alone carried 96,506 chars (70% of its total).
  The max's final dispatch carried 45,462 chars and placed a deliberately narrower batch (see Dimension 4).
- The high's extra reasoning sits in re-derivations of the same slice.
  Its 9 tail deliveries of the big block each re-ran the three-phase typist loop.

Specimen quotes (verbatim from the traces):

- high, typist: "the lists are empty, so strictly no service slugs are authorized.
  However, emitting zero edges means no linkage at all."
  The high keeps the graph connected even when the evidence seam is thin.
- max, assigner: "leaving it unowned is defensible and correct per the null hypothesis.
  Unowned stays in stale pool."
  The max prefers the empty answer over a weak claim.

Both stances are defensible.
The pipeline should not depend on which stance the model picks; the placement and linking rules should say what to do.

## Dimension 2: environment interaction

Both runs made 11 exec probes.
The probe styles differ:

- **high: a static census.**
  Root document, `index.html`, JS bundles, source maps, chunk names, 405 checks on mirror paths.
  This produced the deep WebPresentation and ReverseProxy descriptions and the SHAPES_DATA_OF coverage.
- **max: an auth-state differential.**
  A forged `JSESSIONID=0000`, a request with no cookie, a request with an empty cookie, port 443, a trailing-slash variant `/api/login/`, `/api/search?keywords=test`, and `/api/admin/content/books/covers` among others.
  This produced the direct cookie and no-cookie facts and the redirect-filter fact that the GT statements S2 and S4 of `white-jotter-002` reward.

Tool-use profile:

| Tool | high typist | max typist | high assigner | max assigner |
|---|---:|---:|---:|---:|
| `graph_view` | 63 | 70 | - | - |
| `search` | 40 | 58 | 24 | 30 |
| `artifact` | 20 | 34 | 16 | 8 |
| `exec` | 11 | 11 | - | - |

Consequence: the probe style is a decision the analysis pipeline should schedule, not a property of the model.
The pipeline needs both shapes: a static asset census and a live state differential against the auth surface.
The max found the gate facts because it probed for them.

## Dimension 3: interpretation

### Perimeter relationship divergence (FRONTED_BY vs ROUTED_BY)

The proxy edges are disjoint between the runs: high `FRONTED_BY` x10, max `ROUTED_BY` x9, zero overlap.
Both runs quoted the same vocabulary line from `technical-system.md`: "FRONTED_BY / PROTECTED_BY / ROUTED_BY (perimeter: CDN / WAF / reverse proxy / gateway)".
The high resolved it from the worked examples: "Example 3 uses FRONTED_BY for CDN.
Example 8 uses FRONTED_BY for ReverseProxy.
So FRONTED_BY for the reverse proxy."
The max resolved it from the parenthetical mapping: "Mapping: CDN -> FRONTED_BY, WAF -> PROTECTED_BY, reverse proxy/gateway -> ROUTED_BY."
Both are valid vocabulary, and no GT item depends on the label.
But the prompt is internally inconsistent: the positional mapping says reverse proxy -> ROUTED_BY while Example 8 links FRONTED_BY from a ReverseProxy.
This is a prompt contradiction, not a thinking difference.
A graph consumer that filters on `FRONTED_BY` sees completely different answers per run.

### SHAPES_DATA_OF scope (8 services vs 1)

The high linked `SHAPES_DATA_OF` from 8 services; the max linked it from 1 (`library-catalog`).
The skill says: "prefer the PRIMARY services (those that already aggregate this chunk's assets)".
The max read "prefer" as "restrict to": its reasoning kept the chunk-scope primary service only.
The high read it as a soft ordering hint and linked the roster.
The max's reading loses cross-cutting integration coverage: one System with one consumer instead of a shared integration concern.
This is another wording ambiguity, and the fix is to state that "prefer" means "link these first", not "link only these".

### The authorization gate set (identical, both exclude register)

Both runs link `AUTHORIZED_BY` from the same 5 services: `article-management`, `book-management`, `navigation-menu`, `role-permission-administration`, `user-administration`.
Neither links `register`.
The GT requires `account-registration` `AUTHORIZED_BY` in three specs (`002`, `004`, `007` M4).
The analysis reasoning is that register is public enrollment and therefore not "authorized".
The GT model is that the filter chain covers the route, so the gate applies even when the route allows anonymous access.
The pipeline needs one explicit gate-coverage rule for this class of case, because both thinking levels reason the same way here.

### Description composition and the M3 keyword mechanics

| System description | high len | max len |
|---|---:|---:|
| AuthorizationSystem | 1,916 | 2,287 |
| IdentificationSystem | 1,425 | 2,319 |
| IntegrationSystem | 1,261 | 2,249 |
| AuthenticationMechanism | 2,047 | 2,213 |

The `white-jotter-002` M3 delta comes from keyword conjunctions on the AuthorizationSystem description:

| Keyword | high | max |
|---|---:|---:|
| `principal` | 1 | 1 |
| `cookie` | 0 | 2 |
| `filter` | 0 | 1 |
| `reachable` | 1 | 2 |
| `username` | 0 | 0 |

The high's description is semantically close on the session gate: it describes the session check, the admin-redirect behavior and the bodiless 200 responses.
It fails S2 and S4 because it does not use the words "cookie" and "filter" that the checker requires.
The max passes, and its wording is grounded: its probes produced the no-cookie facts, and it wrote "redirect filter" from the observed redirect behavior.
So the +0.133 on `white-jotter-002` is partly evidence (the probes) and partly vocabulary.
The durable rule for the pipeline is description completeness: name the identity material (cookie/session), the decision point (filter/gate), the reachable surface, and the identity inputs such as `username`.
That rule generalizes beyond this target and does not depend on the thinking level.

## Dimension 4: decision-node branches

### Branch: endpoint placement policy

The assigner's final big-block dispatch differs by design:

| Measure | high | max |
|---|---:|---:|
| Aggregates in the final batch | 72 | 27 |
| Non-`/api/` mirror paths among them | 41 | 0 |
| Endpoints placed in the graph | 71 of 114 | 29 of 114 |
| M2 endpoint items matched | same in both | same in both |

The max stated the policy: "the bare paths are SPA routes / not-live.
Assigning them to a business Service would be wrong." and "these have no business ownership per the contracts.
Better: don't assign them."
The high asked the same question ("does a Service own a client-side route page like `/jotter` or `/login`?") and then placed the mirror paths anyway.
The GT does not score placement, so both runs match the same M2 items.
Placement feeds hunting: more placed endpoints mean more service-scoped hypotheses, and fewer mean higher precision.
Neither arm states the policy explicitly; the assigner discipline should require an evidence tag per endpoint ("live route" vs "mirror") and a stated default.

### Branch: which structured call's edges get written

The typist makes two structured calls per delivery: systems extraction and services linking (`mechanism_typist.py`).
The writer reconciles and writes only the linking batch's edges (`mechanism_typist.py:670-679`).
The high emitted `AUTHENTICATED_BY` and `IDENTIFIED_BY` for `navigation-menu` in the extraction call at 09:02:51.
Both edges were discarded silently.
The committed graph confirms it: the high's `navigation-menu` carries `AUTHORIZED_BY`, `EXPOSED_VIA`, `FRONTED_BY` and `AGGREGATES` but no `AUTHENTICATED_BY` and no `IDENTIFIED_BY`; the max's `navigation-menu` carries both.
The max re-emitted its edges in the linking call, so it lost nothing, but the duplicate emission pattern (identical batches at 10:40:26/10:40:42 and at 10:50:30/10:50:47/10:51:04) shows the model emits edges in both phases.
Recall therefore depends on a coin flip: if the linking call omits an edge that the extraction call proposed, the edge is gone.
Fix direction: union both batches' edges, deduplicate by identity.
That is deterministic and cheap.

### Branch: re-emission and duplicate calls

- high: 7 `EXPOSED_VIA` edges emitted at 09:05:16, then the same 7 emitted at 09:10:30 and committed at 09:10:57.
- max: two identical 10-edge batches (10:40:26, 10:40:42) and three identical 5-edge batches (10:50:30, 10:50:47, 10:51:04).

The graph writer merges, so duplicates do not corrupt the graph.
They do waste calls and they muddy the emission inventory.
The emission inventory from Langfuse is also incomplete (some batches arrive as message content), so the graph's `first_seen` timestamps are the authoritative record.

### Branch: delivery cadence

The high re-delivered the big block 9 times as recon kept producing observations; 6 of those deliveries emitted nothing.
The max processed the settled slice once.
This is the largest non-controlled difference between the runs and it is not the declared variable.
It explains part of the high's fragmentation: repeated full-slice reasoning, repeated edge batches, and a longer tail.

## Dimension 5: pitfalls when reading this comparison

1. **The Langfuse truncation artifact.**
   The apparent 59-vs-87 endpoint difference is a capture cap artifact, not an input difference.
   Checkpoint decode is the control.
2. **The witnessed-systems race.**
   The high shows 14 analyser-provenance systems (14 witnessed); the max shows 7 analyser-provenance plus 8 `data-dependency-scaffold` shells (7 witnessed).
   The scaffold shells landed before the analyser provenance for 8 systems in trial 2.
   The max's per-system evidence is actually higher: AuthN 10 vs 6, Identification 11 vs 5, Authorization 11 vs 9, Integration 18 vs 5 (max vs high).
   The "14 vs 7" line in the arm L report is a bootstrap race, not a capability difference.
3. **The checker's path-template mismatch.**
   `_match_endpoint` compares paths exactly (`tools/measure_gt_wellformedness.py:264-274`).
   The GT requires `DELETE /api/admin/content/article/1`; the graph stores `DELETE /api/admin/content/article/EXPR`.
   That miss belongs to the instrument, not to the pipeline.
4. **Keyword conjunctions.**
   M3 statements are satisfied by keyword presence.
   A semantically complete description can miss on wording alone (see the S2/S4 case above).
   Report both the statement verdict and the wording when judging.
5. **Run-specific vs stable misses.**
   Only 2 of the high's 17 misses are thinking-variant.
   The other 15 are stable or non-analysis-owned.
   Build the enhancement plan on the stable inventory.
6. **n=1 and directional.**
   Each arm is one deterministic trial.
   Differences are reported in points, never as significance.

## The GT delta, decomposed by owner

The target score is the mean of seven spec scores.
Each spec score is the mean of three shares (M2 endpoints+params, M3 fields+statements, M4 system shape), given that the M1 identity check passes.
The arm L corpus has 16 M2 items, 20 M3 items and 17 M4 items across the 7 specs.

Per-spec detail (shares in parentheses):

| Spec | M2 | M3 | M4 | high | max |
|---|---|---|---|---|---:|---:|
| white-jotter-001 | 2/5 | 2/2 | 3/3 | 0.800 | 0.800 |
| white-jotter-002 | 2/3 | 3/5 vs 5/5 | 1/2 | 0.589 | 0.722 |
| white-jotter-003 | 1/1 | 2/2 | 3/3 | 1.000 | 1.000 |
| white-jotter-004 | 1/1 | 4/5 | 1/2 | 0.767 | 0.767 |
| white-jotter-005 | 1/2 | 2/2 | 2/2 | 0.833 | 0.833 |
| white-jotter-006 | 0/1 | 2/2 | 0/2 | 0.333 | 0.333 |
| white-jotter-007 | 0/3 | 2/2 | 2/3 | 0.556 | 0.556 |
| **Target** | | | | **0.697** | **0.716** |

Miss inventory by owner (17 high / 15 max):

| Owner | Items | Detail | Spec delta | Target delta |
|---|---:|---|---:|---:|
| Analysis, stable | 5 | register `AUTHORIZED_BY` x3 (`002`/`004`/`007` M4); `keywords` Parameter on `GET /api/search` (`005` M2); AuthZ "username" statement (`004` M3) | +0.678 | +0.097 |
| Analysis, run-specific | 2 | `002` M3 S2 (principal+cookie) and S4 (filter+reachable), high only | +0.133 | +0.019 |
| Recon | 9 | `POST /api/login` + username + password (`001`); `POST /api/register` + username + password (`007`); `GET /api/file/cover.png` (`006`); 2 cover-serving `EXPOSED_VIA` M4 items (`006`) | +1.200 | +0.171 |
| Instrument | 1 | `DELETE /api/admin/content/article/1` path-template mismatch (`002` M2) | +0.111 | +0.016 |
| **All** | **17** | | **+2.122** | **+0.303 -> 1.000** |

Projection: fixing the 5 stable analysis-owned items moves the max arm to about 0.813 (0.716 + 0.097).
The high arm reaches about 0.794 with the same fixes (0.697 + 0.097), and about 0.813 once the E3 description rule also recovers its 2 run-specific S2/S4 items.
The recon and instrument items sit outside the analysis pipeline and are tracked separately.

## Residual enhancement room (analysis-owned) and the experiments

Rule: only items the analysis pipeline owns enter this section.
Each experiment names the change surface, the hypothesis, the measurable outcome and the risk.

| ID | Gap | Change surface | Measurable outcome | Risk |
|---|---|---|---|---|
| E1 | register missing from the authorization gate set (3 GT items) | Linking guidance in `technical-system.md` plus one worked example: the gate filters every route its chain covers, including anonymous-allowed routes | The 3 GT M4 items land; `AUTHORIZED_BY` count stays near 6-7, not 12 | Over-linking: every public service gains a gate edge |
| E2 | `keywords` Parameter never aggregated (1 GT item) | Deterministic inheritance: when an Endpoint is aggregated, its L0 Parameter nodes join the aggregate; or an explicit assigner prompt rule | `white-jotter-005` M2 becomes 2/2; Parameter placement count 1-4 | Parameter spam beyond the parsed vocabulary |
| E3 | AuthZ description omits the identity input `username` (1 GT item) and is wording-fragile on S2/S4 | Description composition rule in the systems-extraction guidance: name the identity material, the decision point, the reachable surface and the identity inputs | `white-jotter-004` M3 becomes 5/5; S2/S4 stay satisfied on a re-run without the max's probes | Boilerplate descriptions that inflate size without content |
| E4 | Extraction-call edges are discarded (2 edges on `high`, silently) | `mechanism_typist.py` writer: union `systems_batch.system_edges` with `link_batch.system_edges`, dedupe by identity | Emitted-vs-committed parity: the `navigation-menu` pair lands; zero dropped edges in the parity check | None beyond a trivial dedupe rule |
| E5 | Perimeter rel choice is a prompt coin flip (`FRONTED_BY` vs `ROUTED_BY`) | The skill line: pick one mapping, delete the contradicting example | Cross-run rel agreement: the same proxy produces the same rel in two runs | None, no GT item depends on the label |
| E6 | "prefer the PRIMARY services" reads as "restrict to" | The skill line: state that `prefer` orders the links, it does not restrict them | SHAPES_DATA_OF coverage across services stays at the high arm's level (8) | None material |
| E7 | Placement policy is implicit (72 vs 27 aggregates) | Assigner discipline: require a per-endpoint evidence tag ("live route" vs "mirror shell") and a stated default | Placement completeness stays at the high level (71/114) with a sampled precision audit | A stricter default could starve hunting of anchors |
| E8 | Witness metric depends on provenance timing (instrument-owned) | Count `EVIDENCED_BY` independently of `prov_job`; optional scaffold-race fix | The witnessed-systems count stops depending on bootstrap order | Measurement change only |

Sequencing:

1. E1 first.
   Largest measurable gain (+0.064 target), prompt-only, and the semantics are already decided by the GT model.
2. E2 next.
   One deterministic code path plus a test.
3. E4, E5, E6 as one robustness batch.
   No GT delta, but they remove coin flips and silent drops.
4. E3 next.
   It carries the last GT item and the repeated-run robustness.
5. E7 last, because it needs a sampling plan for the precision audit.
6. E8 rides the instrument workstream, not the analysis experiments.

The next experiment: apply E1, E2, E3, E4, E5 and E6 in one analysis-side change, then run one `white-jotter` trial with thinking held at `high` (the arm with the wider analysis-owned surface, so the experiment is sensitive), same target, same instrument.
Acceptance: the 5 stable GT items land; emission parity is clean; one perimeter vocabulary appears; SHAPES coverage does not collapse.
Then, if budget allows, one `max` run as the convergence check.
The predicted outcome is both arms near 0.813, with the arm difference at or near zero once E3 recovers the S2/S4 wording as well.

## Caveats and method notes

- Hunting is not compared: trial 2's hunting arm was cut by a harness read timeout at 87 minutes.
  See `docs/experiments/2026-10-19-arm-l-recommendations-1-2-overview.md` for the failure mode and the fix.
- The comparison is n=1 per arm and directional.
- The recon insight-text variance (3,578 vs 1,509 chars per repeated insight) is a real confound.
  It changes what the typist reads, and it is not the declared variable.
- The L0 control comes from container checkpoint decodes (`/tmp/ckpt_read.py`, `/tmp/ckpt_dump.py` run via `docker exec -w /srv/src ph-dd131acc-agent-1`), not from Langfuse captures.
- Edge and provenance claims come from Neo4j reads against the two project graphs (`7a8bdcce-3b81-4113-adad-c3a0876925a7` and `da6340e5-5f17-4117-9515-edaad54c6ddc`).
- The GT measurement comes from `tools/measure_gt_wellformedness.py` on the persisted inventories (`/tmp/arml-wj-high-gt.json`, `/tmp/arml-wj-max-gt.json`).
- Timestamps are UTC.

*Analysis documented on 2026-10-19.*
