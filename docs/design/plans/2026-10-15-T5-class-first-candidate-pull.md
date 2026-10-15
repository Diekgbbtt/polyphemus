# Plan T5: assigner class-first candidate pull + single-candidate direct admits (specified)

Status: specified, not implemented (2026-10-15).
Lineage: T4 of `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md`; the one recommendation in `docs/experiments/assigner-differentiation-assessment.md` section 7, which the operator found underspecified.
Sequencing: the next trial measures T1-T3 on a stable judge (assessment section 9); this change rides the trial AFTER it, per the same section.
Surface under change: ONE file, `src/polymerhus/analysis/prompts/assigner.md` (the HOW layer: read once per process, fail-closed, byte-stable for the provider cache).
No code change, no schema change, no `ROLE_ADMITS` change, no widening-budget change.

## 1. The recommendation being specified

Quote, assessment section 7: "Adopt Move A now, and Move B behind guards 1 and 2. Keep Move C out until a trial measures the first two."

- Move A (class-first candidate pull): add one step before the differential that names the payload CLASS from the recorded response, and pull every contract that names that class, even when no path noun does.
- Move B (single-candidate direct admit): when exactly ONE contract matches both the nouns/actions AND the payload class, admit it without the runner-up requirement and without further widening.
- Move C (route-identity collapse): deferred.

The underspecification this doc closes: which payload class vocabulary, what "names the class" means mechanically, where each change lands in the prompt, what exactly the two-signal guard tests, what the shortcut skips and keeps, and how the next trial measures it.

## 2. Terms (fixed for this spec)

- **payload class**: one or two words naming the SHAPE of the recorded response body - what it IS a map, list, stream or record OF. Examples: folder map, log stream, file listing, external catalog, membership check, stats snapshot. Never the topic, never a route noun restated.
- **surface signal**: a path noun, method-plus-trailing-segment action, or parameter name that the judged Endpoint carries and that the candidate's contract explicitly claims (the existing evidence doctrine, `assigner.md` lines 36-38).
- **class signal**: the payload class read from the body, whose words the candidate's contract explicitly names ("the folder-path map").
- **candidate set**: the union of surface-pulled and class-pulled Services.
- **full differential**: moves 2-4 as written today - candidate pull, runner-up naming, discrimination, grounding.
- **direct admit**: a judgment that skips ONLY the runner-up search and further disambiguation widening; every other discipline stays.
- **artifact**: the recorded transaction body the `get_http_artifact` seam returns.

## 3. Change A - class-first candidate pull (closes the quirk)

Artifact H kept `/experiment/models` on `model-inventory` while `server-diagnostics` - the contract that names the payload class, "the folder-path map" - never entered the differential.
Change A makes the payload class a candidate-generation key, so a class-naming rival always enters.

Three edits in `assigner.md`, drafted verbatim:

### A1. The moves become FIVE; the new move 2 (old 2-4 shift down by one)

The heading "## Work each Endpoint in four moves" becomes "## Work each Endpoint in five moves", and this move is inserted after READ THE SURFACE FIRST:

```md
2. **NAME THE PAYLOAD CLASS.**
   When you hold the Endpoint's recorded response - already read, or read now under the widening seam - name what the payload IS in one or two words: a folder map, a log stream, a file listing, an external catalog, a membership check.
   The class describes the BODY's shape, never its topic and never the path: `/experiment/models` returns model names, but what it IS, is a folder map.
   When no response is held, say `no response held` and run the differential without a class.
```

### A2. The differential pull widens (move 3, formerly move 2)

```md
3. **RUN A DIFFERENTIAL.**
   Hold every candidate Service whose contract touches those nouns or actions, not the first one that fits - and every Service whose contract names the payload class you named in move 2, even when no path noun reaches it.
   A candidate that arrived with no competition is usually the first pattern you noticed rather than the best-supported one, so name the runner-up even when you are sure - unless the single-candidate guard below holds.
```

### A3. The evidence doctrine gains the class clause (section "What the ownership evidence is")

One added bullet:

```md
- A payload class that the contract explicitly names - "the folder-path map" for a folder map, "the external catalog" for an external catalog - is evidence; a payload that contradicts the contract's class words is evidence against. Match the class against what the contract SAYS the Service exposes, not against slug similarity.
```

### Cost and bound

Change A ADDS candidates, so it raises differential work; it saves nothing by itself.
It adds no widening budget: class naming rides reads the widening seam already governs ("a handful of lookups, never a trawl").
For Endpoints with no artifact held, the differential runs as today (surface-only), and move 2 says so.

## 4. Change B - single-candidate direct admit behind the two-signal guard

### The guard (ALL clauses must hold, otherwise the full differential stands)

- **G1 - uniqueness.** The candidate set - surface pull AND class pull together - holds exactly one Service.
- **G2 - two independent signals.** That Service matches on BOTH: a surface signal its contract explicitly claims (cited with the exact segment, action or parameter), AND a class signal its contract explicitly names (cited with the contract's class words).
- **G3 - no class competition.** The payload class is named by no second contract. Two or more contracts naming the class force the full differential and its named runner-up. This is assessment guard 2.
- **G4 - the artifact is held.** The class was read from the recorded response. No artifact, no class signal, no shortcut.
- **G5 - independence.** The class signal may not be the surface signal restated: the class comes from the body's shape, never from the path.

### What the shortcut skips, and what it keeps

Skips: the runner-up search, and further widening for disambiguation.
Keeps: move 1 surface reading, move 2 class naming, discrimination against the one candidate's contract, grounding, the out-of-slice filter, the structural gates, shared ownership, and the no-owner outcome.
Output shape: one aggregate; `evidence_refs` carry BOTH signals; the reasoning carries the label `SINGLE-CANDIDATE ADMIT`.

### The prompt text (new section after the five moves)

```md
## When one candidate is the only reachable owner

The runner-up requirement stops the first pattern you noticed from winning uncontested; when the contest is provably empty, it buys nothing.
Skip it - admitting directly - under ALL of these:

- the candidate set, path pull AND payload-class pull together, holds exactly one Service;
- that Service matches on TWO independent signals, each explicit in its contract: a path noun, action or parameter it claims, AND the payload class it names;
- no second contract names that class (when two do, run the full differential and keep the runner-up);
- you hold the recorded response the class was read from.

Then label the judgment `SINGLE-CANDIDATE ADMIT`, cite BOTH signals in the aggregate's evidence_refs, and widen no further for disambiguation.
One signal is never enough: nouns alone, or a class alone, fall back to the full differential.
Everything else is unchanged - the null hypothesis, the grounding demand, shared ownership, and the no-owner outcome.
```

### One worked example (append to "Worked examples")

```md
**4. Single-candidate admit.**
Inventory has `asset-library - owns the media library; exposes its folder map.`
Endpoint `GET /library/items`; the recorded response is that folder map.
Surface: noun *library* and action *items*, both claimed by `asset-library`. Class: folder map, named by `asset-library` alone.
-> `SINGLE-CANDIDATE ADMIT`; one aggregate, evidence_refs `["path segment /library", "contract: folder map"]`.
```

### What must NOT take the shortcut

- Nouns only, class only, or a class contradicted by the payload.
- A class named by a second contract (G3), however sure the judgment feels.
- A judgment on an Endpoint whose response was never recorded or read (G4).
- Any judgment outside the chunk slice; the out-of-scope filter is untouched.

## 5. Guard set, formalized (mapping the assessment's guards)

| Assessment guard | Mechanism here | Where enforced |
|---|---|---|
| 1 - two independent matches for the shortcut | G2 + G5 | prompt |
| 2 - two contracts naming the class keep the differential | G3 | prompt |
| 3 - Move C groups only on observed payload evidence | NOT IN SCOPE (Move C deferred) | - |
| 4 - the no-owner option stays | unchanged null hypothesis; a class matching no contract yields no aggregate | prompt |
| 5 - shared ownership stays legal | unchanged; the shortcut ADMITS one owner, it never forbids a second aggregate the full path would find | prompt |
| 6 - acceptance signals | section 7 below | eval metrics + census |

## 6. The motivating case under this spec

`GET /experiment/models` (arm H): surface nouns *experiment*, *models*; class from the artifact - folder map.
Candidate set after Change A: surface-pulled (`model-inventory` and the noun-adjacent contracts) UNION class-pulled (`server-diagnostics`, which names "the folder-path map") - at least three Services.
G1 already fails, so the FULL differential runs and the class rival enters; whether the run then writes `model-inventory`, `server-diagnostics`, or both is the differential's outcome, not this spec's.
The quirk is closed by Change A alone; Change B would not have fired on this Endpoint, which is exactly why the recommendation adopts A broadly and B behind guards.
`/folder_paths` (the same payload class on a second route) is untouched: collapsing the two routes into one ownership question is Move C, deferred.

## 7. Measurement plan (the trial after next)

Census source: the assigner turn dump pulled from Langfuse per trace (the method `docs/experiments/assigner-differentiation-assessment.md` used for its tables).

Counters:

- `SINGLE-CANDIDATE ADMIT` label occurrences per turn and per run.
- Candidate-set size per judgment (from the model's per-turn tables).
- Widening calls per admitted endpoint (arm H baseline: 122 calls / 298 admitted = 0.41).

Acceptance (assessment guard 6):

- `endpoint_placement` at or above arm H's 26.9%.
- `gt_service_aggregation` at or above arm H's 71.4%.
- Zero new `out_of_inventory` drops.
- The stale-pool decline rate (193/298 = 64.8% in arm H) is EXPECTED to fall; it is a volume signal, not the precision signal.

Audit: sample 10 labeled `SINGLE-CANDIDATE ADMIT` judgments and verify each against G1-G5 on the dump, before reading the aggregate metrics as earned.

Rollback: a git revert of the prompt edit is the precise lever.
`ASSIGNER_PROMPT_CONFIG=baseline` remains the coarse lever (it drops the whole skill, `assigner.py:409-421`).

## 8. Open decisions for the operator (flagged, not decided here)

- **D1 - degenerate-set artifact trigger.** Option: when the surface-pulled set is empty or single AND an artifact exists, require ONE artifact read before judging, so class blindness cannot persist where it bites. Default in this spec: NOT included (keeps the widening bound flat).
- **D2 - class vocabulary.** Open (the model's own words, bound by the shape-not-topic rule) versus a closed starter list in the prompt. Default here: open, with the examples in A1.
- **D3 - the label.** `SINGLE-CANDIDATE ADMIT` in the reasoning is required here because it is the census hook; it costs one line per eligible judgment.

## 9. Acceptance checklist for the implementation commit

- The prompt edits land in `src/polymerhus/analysis/prompts/assigner.md` only; the five-move structure, A2's class pull, A3's bullet, the single-candidate section, and the worked example are present.
- `tests/integration/test_assigner_contracts.py` gains clause-presence assertions mirroring the C-series prompt-property pattern (move count, "payload class", the G1-G5 clauses, the label).
- `docs/experiments/assigner-differentiation-assessment.md` section 7 links this file.

Files: `src/polymerhus/analysis/prompts/assigner.md`, `tests/integration/test_assigner_contracts.py`, `docs/experiments/assigner-differentiation-assessment.md` (pointer).
blocked_by: none to specify; implementation is sequenced after the T1-T3 trial by assessment section 9.
