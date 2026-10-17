# Typist expression diagnosis - why arm J System specifications stay thin

Date: 2026-10-16.
Plan: `docs/design/plans/2026-10-16-failure-modes-diagnosis.md` (F5, operator item 3).
Scope: structural root cause of the typist quality defect, tested against measured data; fix direction prefers harness symbolic-layer reasoning over more spurious `.js/.mjs` chunks.

## Question tested

The operator observation: the arm J trials' System specifications stay below arm H's, despite per-chunk quality being comparable.

## Method

- Metrics use one definition set across trials.
- Productive tokens = input + output + output_reasoning, excluding cache reads.
- Typist turns = LLM calls in the `<recon_run>:mechanism_typist` Langfuse session.
- Structured turns = `typist-systems-and-edges` generations (the mint/extend deltas).
- Data windows: J trials entire typist sessions; the arm H baseline is the pulled census slice 13:53:43-14:31:25 UTC (project `a9bb42f9`), which is a mid-trial slice, not the whole H run.

## Typist economics

| trial | window (UTC) | LLM calls | fresh input | cache read | output | reasoning | productive total | tool calls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| J comfyui | 22:03:49-22:21:19 | 59 | 405,136 | 3,241,728 | 32,300 | 95,786 | 533,222 | 146 (graph_view 93, search 32, artifact 16, exec 5) |
| J wj | 23:09:30-23:28:55 | 65 | 459,561 | 4,241,920 | 46,547 | 90,555 | 596,663 | 123 (graph_view 69, search 32, artifact 14, exec 8) |
| H comfyui (census slice) | 13:53:43-14:31:25 | 93 | 375,060 | 4,552,960 | 72,004 | 133,772 | 580,836 | 158 (graph_view 94, search 32, artifact 16, exec 16) |

Per-call output volume (output + reasoning) is comparable: H 2,213, J comfyui 2,171, J wj 2,109.
The difference is call count (93 vs 59/65) and therefore total expressed volume (205,776 vs 128,086/137,102 output tokens).

## Structured turns (mint/extend deltas)

J comfyui: 5 structured turns, one per streamed chunk.

| turn (UTC) | chunk | systems (kinds) | edges | distinct slugs (new in bold) |
| --- | --- | --- | --- | --- |
| 22:08:09 | httpx | 1 (ReverseProxy) | 0 | - |
| 22:09:37 | katana | 3 (ReverseProxy, RESTApi, AuthorizationSystem) | 3 | **model-inventory** |
| 22:12:36 | ffuf | 4 (RESTApi, AuthorizationSystem, ReverseProxy, AuthenticationMechanism) | 10 | **custom-node-content, system-status, user-profile, workflow-history, workflow-submission** |
| 22:14:53 | steel_crawl | 1 (ReverseProxy) | 6 | - (re-emits the same five slugs) |
| 22:21:19 | jsluice | 5 (IntegrationSystem, RESTApi, AuthorizationSystem, ReverseProxy, AuthenticationMechanism) | 16 | **custom-node-catalog, image-upload, image-viewing, node-registry, server-diagnostics** |

J wj: 6 structured turns in-run plus 1 straggler turn from the aborted attempt's session.

| turn (UTC) | systems | edges | distinct slugs |
| --- | --- | --- | --- |
| 23:09:11 (aborted session) | 3 | 20 | 17 |
| 23:11:41 | 7 | 23 | 6 |
| 23:14:26 | 5 | 15 | 15 |
| 23:17:11 | 2 | 2 | 1 |
| 23:20:03 | 6 | 0 | 0 |
| 23:23:00 (post-stream) | 8 | 35 | 20 |
| 23:28:56 (post-stream) | 2 | 2 | 1 |

Every turn repeats the same singleton system kinds (ReverseProxy, WebPresentation, AuthorizationSystem, ...) and emits only slug-level edges.
No turn extends an existing system's contract text.

## Graph outcome per trial

| trial | L1 services | contract chars | AGGREGATES edges |
| --- | --- | --- | --- |
| J comfyui | 23 | 4,084 | 76 |
| H comfyui | 23 | 4,084 | 80 |
| J wj | 24 | 2,820 | 31 |

Key reading:

- H and J comfyui produced the same inventory size and the same total contract volume (23 services, 4,084 chars). The premise "J specifications stay below H's" does not hold at contract level for comfyui. The measurable H/J difference on the same target is evidence support: 80 vs 76 aggregate edges.
- J wj is genuinely thinner (2,820 contract chars, 31 aggregate edges), but that trial is the one whose bundle-relative `/api/*` surface was unresolvable pre-F4 (see the coverage doc). Its thinness is a recon recall defect, not a typist effort defect: the typist ran 65 calls and spent 596,663 productive tokens on it.
- The contract totals are byte-identical between the two comfyui trials. The natural explanation is that contract prose is minted once per (target, lens) service and then never rewritten by later evidence.

## Root cause (structural)

1. Turn cadence is chunk-gated: the typist emits a structured turn per streamed wave. J comfyui had 5 waves -> 5 turns; H's slice shows roughly 1.6x the calls of either J trial. More waves would add turns, but see 2.
2. The delta schema is mint-only: each turn can only emit `systems[]` (kinds) and `edges[]` (service slugs). There is no operation that extends an existing service's contract or description from newly streamed evidence. Extra turns therefore add slugs and edges, never depth; re-emitted systems duplicate.
3. Evidence linking is the only volume that tracks recon: aggregates 76 (comfyui) and 31 (wj) over 107 and 40 admitted endpoints. That number is set by what recon streams, which F4 has now raised.
4. Conclusion: arm J's specification depth is capped by the mint-only schema and by the wave cadence, not by per-chunk quality. The observed H/J gap is an evidence-support and wave-count gap, not a specification-writing gap.

## Fix direction (operator directive)

- Keep the mint/extend-slug deltas, but add a symbolic-layer extension step: per-service-type question sets that ask, for each wave, "which newly streamed evidence updates THIS service's contract/edges?" and append to the contract.
- The symbolic layer should mint and extend descriptions per System kind, so a service's spec grows monotonically with evidence instead of being frozen at first mint.
- Do not add more spurious `.js/.mjs` chunks to raise turn count; the chaining fix (F4) already raises useful evidence without adding noise.
- The evidence-update questions should consume the streamed deltas (assets already qualified by the gate) and the http-history channel the typist already knows how to use (search 32 calls, artifacts 16 in each J trial).
