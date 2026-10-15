# Assigner calibration collapse (arm G2) - diagnosis

## Verdict

The 74/75 editor-shell collapse is a three-layer failure, measured end to end from the assigner's own recorded reasoning.
The skeleton carries `editor-shell` and `manager-shell` as Services with NULL `service_contract`, which the differential machinery cannot match anything against - every assignment to them is topical by construction.
The model emits 0.55-0.85 confidences for those topical guesses (including eighteen edges below the designed 0.75 bar and seventeen exactly at it), quotes the bar correctly in prose, then emits the edge anyway instead of nothing.
The seam writes everything because `ANALYSER_ASSIGN_BAR=0.0` on the eval instance (present in every `.env` backup back to 2026-10-10, so all arms measured the ungated model - fair comparison, but none tested the designed gate).
No n:n cardinality defect exists: the prompt explicitly teaches shared ownership and the model demonstrates it correctly where contracts exist.
Restoring the bar to 0.75 would drop 18/75 edges but leave GT aggregation at ~1/14 - necessary, insufficient; the contract-less shell Services are the load-bearing defect.

## Question

Arm G2's assigner kept 75/75 proposed aggregates with zero withholds, 74 naming non-ground-truth `editor-shell` and 1 naming `model-inventory` (GT 1/14).
Three modelling failure modes were on the table: mass assignment of one turn's streamed input, assignment of graph_view-collected (previously streamed) surface, or progressive concentration onto an already-concretised service.
A fourth question was whether any instruction inhibits assigning one Endpoint to several Services (n:n cardinality), which would itself be a defect.

## Evidence (all from the run's own records)

Per-turn proposals were recovered by parsing all 73 assigner generation outputs (`L1DeltaBatch` tool calls): 12 proposal turns holding exactly the 75 edges the graph kept (confidence sums match: 0.55x1, 0.6x17, 0.75x17, 0.78x11, 0.8x27, 0.84x1, 0.85x1).
The outputs carry the model's full chain of thought (content prose plus `reasoning_content`), so each verdict below quotes the turn that produced it.

### The non-assigning turn (20:46:31Z, first chunk, `GET /`)

The model reads the root HTML document correctly (no path nouns, `text/html`, the editor front-end shell), runs the differential across `node-registry`, `custom-node-content`, diagnostics candidates, finds topical fit only ("evidence that fits three Services is evidence for none"), states confidence ~0.2, and emits `"aggregates": []`.
Self-withholding works here, exactly as designed.

### The first editor-shell turn (20:48:54Z, second chunk)

The turn's streamed slice is eight `.mjs` vendor-library endpoints; the model correctly withholds those ("my honest confidence for these static vendor bundles is low", bar cited as 0.75).
It then re-judges `GET /` - the FIRST chunk's asset, re-presented by the adjacent-surface phase - and assigns it to `editor-shell` at confidence 0.55, "at the honest confidence for a root document whose path carries no noun".
In the same breath its reasoning states "the contract for editor-shell is empty (no description)" and "the withholding bar is 0.75".
A 0.55 edge emitted against a known 0.75 bar is a prompt-adherence failure (the discipline says a below-bar judgment produces no edge), and the seam's zero bar then writes it.
This turn also shows the category error: "the inventory's own presentation identity names it `WebPresentation:editor-shell::editor-root`" - a System description used as a Service's ownership evidence, against the mechanism-as-System principle.

### The concentration turn (21:02:35Z, nine theme/icon modules to editor-shell)

The differential is textbook against `custom-node-content` and the manager Services (both correctly withheld as topical-only), then commits to `editor-shell` "cited on the bundle segment and the vendored theme library path, not on the slug" - no contract noun matched, because none exists.
Decisively, it cites prior concretisation as evidence: "Graph confirms the same family is already owned by `editor-shell` (28 sibling `/assets/lib/@primevue/themes/material/...` endpoints)".
That sentence confirms the progressive-concentration failure mode in the model's own words: each chunk's shell endpoints join the concretised family, and the family licenses the next chunk's.
With `withheld=0` everywhere, the loop runs away from 1 to 74 across the run.

### The discriminating turn (21:23:47Z, `GET /experiment/models` to model-inventory at 0.78)

Noun-to-contract match (`/models` = the record the contract explicitly owns), genuine runner-up (`model-download`) considered and withheld at ~0.3 with reasons, neighbouring paths checked for inheritance ("a fresh judgment, not a consistency lookup"), calibration one tier below 0.9 for the generic plural.
The machinery - differential, runner-up discipline, calibration tiers, explicit withholding - works correctly wherever a discriminating contract exists.

## Failure-mode answers

Mass assignment of one turn's streamed input: no.
The 74 edges are 74 distinct endpoints (each proposed once), spread over ten proposal turns, each turn assigning its own chunk's slice (katana frontend-bundle chunks); the paths were the live streamed assets, not graph_view recalls.
Assignment of graph_view-collected surface: partly, once.
`GET /` (withheld in chunk 1 at ~0.2) was re-proposed in chunk 2's turn at 0.55 via the adjacent phase, with no memory of the prior withhold (the per-chunk reset wipes it) - re-presentation without recollection.
Progressive concentration on the concretised service: yes, quoted verbatim above; it is the amplifying loop, not the seed (the seed is the empty contract plus the zero bar).

## The three layers

Skeleton (load-bearing): `editor-shell` and `manager-shell` are Services with NULL `service_contract` (graph-verified), yet the inventory presents them as assignment candidates every chunk.
A differential matcher needs contract nouns; with none, the model's only available moves are the System description (category error) and topical proximity (0.5-0.6 tier by the prompt's own scale).
The honest skeleton positions are either a discriminating contract ("serves the editor SPA shell document and its static bundle") or demotion to System-only; the bootstrapper wrote neither.
Model: emits below-bar edges it knows are below-bar (0.55 against a self-quoted 0.75), quantizes confidences to tiers (0.6/0.75/0.78/0.8), and treats accumulated ownership as evidence (concentration loop).
Seam: `ANALYSER_ASSIGN_BAR=0.0` keeps every emitted edge; census `withheld=0` is the mechanical consequence, not a model behaviour.
The zero bar predates arm G (all backups to 2026-10-10 carry the identical line and comment), so arms A-F measured the same ungated model - the arm comparison is fair, and the designed gate remains untested anywhere.

## No n:n defect

`analysis/prompts/assigner.md` line 27 teaches shared ownership explicitly ("Two contracts that genuinely both reach the Endpoint are two owners rather than a tie to break - emit an aggregate for each"), with a worked two-aggregate example (lines 80-85).
The model-inventory turn applies it correctly ("this is not a genuine two-contract case, so no second aggregate" - a true negative, with the runner-up named and priced).
Cardinality needs no fix.

## What restoring the bar would and would not do

At the designed 0.75, 18/75 edges drop (the 0.55 and seventeen 0.6s) and 57 remain, still ~all editor-shell: GT aggregation stays ~1/14, coverage stays ~8%.
The bar restores volume discipline only; discrimination needs the contract fix (or the demotion) plus a self-withhold that actually withholds.
The bar_sweep calibration the zero bar was presumably kept for ("correct in principle") is now measurable off this run's real confidences - the distribution above is its input.

## Formal diagnosis (both investigations)

Functional defect 1 (placement collapse, this file): root causes are the contract-less shell Services in the skeleton (R1, load-bearing), the model's below-bar emission plus concentration-on-concretised-owners reasoning (R2, amplifying), and the zero confidence bar writing everything the model emits (R3, permissive); the shared-ownership path is exonerated.
Functional defect 2 (typist cache collapse, `typist-cache-collapse-diagnosis.md`): root cause sits downstream of request construction (gateway relay or provider cache eligibility/reporting) - the app side is exonerated on seven independent stabilities (system bytes, tool-spec bytes incl. the prose structured tool, negotiation, bind params, reset behaviour, ledger occupancy never breaching a 200k budget, schedule symmetry with the caching data-modeller); compaction, threshold, lifecycle, and tool-toggle hypotheses are falsified with numbers.
Upstream-most actionable items, in order: give the shell Services discriminating contracts or demote them (fixes discrimination); restore `ANALYSER_ASSIGN_BAR=0.75` once the bar_sweep is read out (fixes volume discipline, untested configuration - predict, do not assert); run the identical-prompt-twice probe plus gateway-verbose capture for the cache anomaly (fixes cost); fix the `...`/`\u2026` recorder split in Langfuse input serialization (fixes future byte-level forensics).
Nothing was changed to reach this diagnosis: no code, no prompts, no instance env, no graph writes; the two throwaway harnesses lived in `/tmp` and are gone with the session.
