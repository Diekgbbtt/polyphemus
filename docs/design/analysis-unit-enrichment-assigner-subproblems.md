# Design: the assigner proposer reasoning workflow (analysis-unit-first v2)

*Status: design document, 2026-10-11. Branch `feat/analysis-unit-enrichment`. No Python is changed by this document.*
*Implements step 4 ("per-role workflows + prompts") of `docs/design/analysis-unit-enrichment-plan.md` for the `assigner` role.*

## 1. Why the assigner workflow changes

The bootstrapped L1 is already sufficient on the **Services**.
The pipeline ENRICHES each Service unit.
The assigner is now fed ONE Service per unit, not a raw recon chunk.
It starts from the Service and its `service_contract`, queries the mapped L0 surface BROADLY and AGGRESSIVELY through the read-only `graph_view` Cypher tool with NO asset-name assumption, then judges which L0 `Endpoint`s the Service owns and emits `AGGREGATES` proposals.
It has a dedicated phase that READS prior modelling insights from the analysis `notes` store, and a closure phase that WRITES a modelling-closure note.

The v1 defects this replaces (plan section "Why") are structural: the single global assign pass under-assigns, and it never re-examines a Service whose slice is empty.

The assigner's ONE judgment is unchanged in kind: an `AGGREGATES` edge from one existing `Service` to one L0 `Endpoint`, carrying `confidence` and `evidence_refs`.
The `service_contract` remains the PRIMARY routing evidence (analysis CONTEXT, "Service contract").
Minting stays RETIRED (analysis CONTEXT, "Service minting"); `existing_slugs` stays a VALIDATION set.
`AGGREGATES` membership stays N:M (analysis CONTEXT, "Shared ownership").

## 2. Tools and the constant request shape

Every turn of the assigner binds the SAME tool set, so the provider prompt prefix never toggles (analysis CONTEXT, "Constant request shape"; ADR D26).

- `graph_view` - the read-only L0/L1 Cypher view (`analysis/tools.py`, plan step 1). Returns `{"rows": [...]}` on success and `{"error": ...}` on failure; write-shaped Cypher is refused by the shared guard. The tool enforces no row cap, so the contract documents the `LIMIT` discipline and this workflow instructs it.
- `notes` - the analysis episodic memory read/write over `memory.yaml` (`analysis/memory.py`).
- the role's structured tool `AnalysisTurn` - the ONE envelope carrying `claims` plus every `L1DeltaBatch` delta list.

Which sub-problem USES which tool is declared below.
The bound set is constant; the prose steers the use.

## 3. Base inject sources the body seeds

The assigner body seeds two base sources into `base_artifacts`; every sub-problem `inject` names the subset it needs, rendered VERBATIM (ADR D24).

- `service` - the unit card, rendered as:

  ```
  SERVICE UNIT
  business_function_slug: <slug>
  service_contract: <the contract prose, verbatim>
  exposure: <public | authenticated | ... or "unset">
  already-aggregated endpoints: <METHOD> <path> (<baseurl>); ...
  ```

  The `already-aggregated endpoints` line may be empty; an empty line is the explicit orphan-Service case the v1 pipeline never dispatched (plan section "Why"), so the workflow must still scan the L0 surface.

- `inventory` - the live Service inventory, rendered as the identity block: every live `business_function_slug` with its `service_contract`. This is both the differential's candidate set and the `service_slug` validation set (analysis CONTEXT, "Validation gate").

The L0 surface is NOT a base source.
It is reached only through `graph_view`, because discovering it is the unit's first job.

## 4. The ordered sub-problems

The workflow is one `ReasoningWorkflow` of five `SubProblem`s, one LLM turn each.
The dependency graph is a DAG: every `depends_on` names an earlier sub-problem, and every `emit` is a declared `AnalysisTurn` field.
No `halt_when` is set for this role: an exhausted scan yields an empty `claims` set, and the extraction turn then legitimately emits no `aggregates` (the withholding, analysis CONTEXT "Withholding gate"), which is the correct fail-safe rather than a chain to halt.

| order | `id` | `name` | `emit` | `depends_on` | tools used |
|---|---|---|---|---|---|
| 1 | `surface_scan` | broad L0 surface scan | `claims` | - | `graph_view`, `AnalysisTurn` |
| 2 | `prior_insights` | prior modelling insights | `claims` | `surface_scan` | `notes` (read), `AnalysisTurn` |
| 3 | `candidate_owners` | candidate owners | `claims` | `surface_scan`, `prior_insights` | `graph_view` (follow-up), `AnalysisTurn` |
| 4 | `assign` | assign | `aggregates`, `claims` | `candidate_owners` | `AnalysisTurn` |
| 5 | `closure` | modelling closure | `claims` | `assign` | `notes` (write), `AnalysisTurn` |

### 4.1 `surface_scan` - broad L0 surface scan

- `inject`: `service`.
- `emit`: `claims`.
- `depends_on`: none.
- tools: `graph_view` (several bounded read-only queries), `AnalysisTurn`.

Reflection prose:

> BROAD L0 SCAN - no asset-name assumptions.
> You are given ONE Service (its slug and `service_contract`) and the live Service inventory.
> Before you judge ownership, establish the raw surface of the target.
> Call `graph_view` with bounded read-only Cypher to enumerate the L0 `Endpoint`s this target exposes.
> Do NOT query for a specific path, parameter or asset name you guessed from the contract; enumerate what EXISTS and read it.
> Run at least these queries, every one with a `LIMIT`:
> 1. List every `:BaseURL` in the project.
> 2. For the BaseURLs the Service already reaches through `AGGREGATES` (or every project BaseURL when it reaches none), list every `:Endpoint` with its path, method, baseurl and url, plus the names of its `:Parameter`s.
> 3. List the `:Endpoint`s that ANY Service already `AGGREGATES`, so you can see what is already claimed.
> Read each returned path as surface, not as an answer: name its path segments, the action its method and trailing segment carry, and its parameter names.
> For every `Endpoint` you discover, emit one Claim: `subject` the Endpoint as `METHOD /path`; `assertion` the raw surface facts (path segments, method, trailing segment, parameter names, baseurl); `evidence` the exact Cypher you ran; `verdict` `seen`.
> Do not decide ownership in this turn.
> Emit `claims` only.
> Bound every query with `LIMIT`; state the total count when a query truncates.

### 4.2 `prior_insights` - prior modelling insights

- `inject`: `service`, `surface_scan`.
- `emit`: `claims`.
- `depends_on`: `surface_scan`.
- tools: `notes` (read), `AnalysisTurn`.

Reflection prose:

> PRIOR MODELLING INSIGHTS - read before you enrich.
> Call the `notes` tool with `command="read"` to surface what earlier units already concluded about this Service and about the Services around it.
> Read at least: this Service's own notes (`unit` = the slug); notes whose body mentions the path nouns you found in the scan; and any note naming a Service that may be missing.
> For each note that bears on this unit, emit one Claim: `subject` the note key; `assertion` the recorded insight (an Endpoint already claimed, a refusal, a competing owner, a suspected missing Service); `evidence` the note body excerpt; `verdict` `reuse`, `avoid` or `competing-owner`.
> A run with no prior notes is a valid result - emit no claims and say so.
> Emit `claims` only.

### 4.3 `candidate_owners` - candidate owners

- `inject`: `service`, `inventory`, `surface_scan`, `prior_insights`.
- `emit`: `claims`.
- `depends_on`: `surface_scan`, `prior_insights`.
- tools: `graph_view` (optional targeted follow-up), `AnalysisTurn`.

Reflection prose:

> REASONING - candidate owners.
> For every `Endpoint` from the scan, work the differential out loud against the Service contracts in the inventory:
> 1. RESTATE AS EVIDENCE: quote the exact path segment, trailing segment or parameter name you matched, and the clause of a `service_contract` it matched against. If your evidence restates the slug instead of the surface, the judgment is self-refuting - drop it.
> 2. COMPETING OWNER: name the strongest competing Service and say why it lost. If it genuinely also owns the Endpoint, keep it as a second candidate rather than discarding it. If you cannot name any competitor, that is a thin inventory, not confidence.
> 3. CALIBRATE: state the confidence on the 0..1 scale, whether it clears the bar, and what specific evidence would move it. `AGGREGATES` membership is N:M: one Endpoint may have several genuine owners, each with its own independent confidence.
> Use `graph_view` for any targeted follow-up (parameter names, sibling paths) only after the differential, still bounded with a `LIMIT`.
> Emit one Claim per (Endpoint, candidate owner): `subject` the Endpoint; `assertion` the matched evidence and the strongest competing Service; `evidence` the exact path segment or parameter you matched and the contract clause; `verdict` the owner you would choose and its confidence.
> Emit `claims` only.

### 4.4 `assign` - assign

- `inject`: `service`, `inventory`, `surface_scan`, `candidate_owners`.
- `emit`: `aggregates`, `claims`.
- `depends_on`: `candidate_owners`.
- tools: `AnalysisTurn`.

Reflection prose:

> EXTRACTION - assign.
> RESIDUE first: list every `Endpoint` from the scan that received no candidate above the bar, one line each.
> Then, from the claims, emit the `aggregates`: one per `Endpoint` and owning Service, each with `confidence` (0..1) and `evidence_refs` naming the exact path segment or parameter matched.
> Emit one aggregate for EACH genuine owner - do not pick a winner.
> Use only `service_slug`s listed in the inventory; an invented owner names nothing.
> Leave `services`, `systems`, `system_edges` and every data-modelling list EMPTY.
> Put the residue in `claims`: one Claim per unplaced `Endpoint`, `subject` the Endpoint, `assertion` `not claimed`, `evidence` why it was left, `verdict` `residue`.

### 4.5 `closure` - modelling closure

- `inject`: `service`, `surface_scan`, `assign`.
- `emit`: `claims`.
- `depends_on`: `assign`.
- tools: `notes` (write), `AnalysisTurn`.

Reflection prose:

> CLOSURE - write the modelling-closure note.
> Summarise what this unit closed over: the `Endpoint`s you claimed as `AGGREGATES` (with the Service slug, confidence and the matched evidence), and EXPLICITLY the `Endpoint`s you did NOT claim and why each was left in the stale pool.
> Call the `notes` tool once: `command="write"`, `action="append"`, `unit` = the Service slug, `note_name="modelling-closure"`, `kind="assignment"`, `body` = the closure body in the template below.
> Then emit one Claim recording the closure: `subject` the Service; `assertion` the claimed and unclaimed counts; `evidence` the note key; `verdict` `closed`.
> Emit `claims` only.

#### The modelling-closure note

- `kind`: `assignment` (one of `NOTE_KINDS`, `analysis/memory.py`; the kind the Assigner owns, and the kind the global assign pass already records its backstop with).
- `note_name`: `modelling-closure`.
- key: `<business_function_slug>:modelling-closure`.
- body template (one full sentence per line; `<...>` are filled from the recorded turns, never invented):

  ```
  MODELLING CLOSURE - <service_slug>

  CLAIMED (AGGREGATES emitted this unit):
  - <METHOD> <path>  baseurl=<baseurl>  confidence=<0..1>  evidence=<the path segment / parameter matched>
  - ...
  (if none: "none - no Endpoint cleared the bar for this Service")

  NOT CLAIMED (left in the stale pool; no AGGREGATES emitted):
  - <METHOD> <path>  baseurl=<baseurl>  reason=<which contract clause did not match / withheld below the bar / no candidate contract fit / no owner in the inventory>
  - ...
  (if none: "none - every scanned Endpoint was placed or explicitly withheld")

  COMPETING OWNERS CONSIDERED: <slug(s) and why each lost, or "single fit">
  PRIOR NOTES REUSED: <note keys, or "none">
  ```

The per-unit backstop (`ensure_unit_note`) still writes ONE `open_question` note when the proposer wrote none, under `note_name` `backstop`, so the closure note and the backstop cannot collide (analysis CONTEXT, "Per-unit backstop").

## 5. The Cypher examples the workflow encourages

All are read-only, all carry `project_id`, and all are bounded with `LIMIT`.
The `graph_view` guard refuses any write token (`MERGE`, `CREATE`, `DELETE`, `SET`, `REMOVE`, `FOREACH`, `LOAD CSV`).
L0 labels are `:BaseURL`, `:Endpoint`, `:Parameter`; the L1 label is `:L1Service`; the cross-layer edge is `AGGREGATES`.

**S1. The Service's own card (optional re-read).**

```cypher
MATCH (s:L1Service {project_id: $project_id, business_function_slug: $slug})
RETURN s.business_function_slug AS slug,
       s.service_contract     AS service_contract,
       s.exposure             AS exposure
LIMIT 1
```

**S2. Every BaseURL in the project (the broad anchor, no name assumptions).**

```cypher
MATCH (b:BaseURL {project_id: $project_id})
RETURN b.url          AS baseurl,
       b.host         AS host,
       b.status_code  AS status,
       b.content_type AS content_type
ORDER BY b.url
LIMIT 200
```

**S3. Every Endpoint on the Service's BaseURLs, with its Parameter names.**
`$baseurls` is the set of baseurls the Service already reaches through `AGGREGATES`.
When that set is empty, run the same query with the `WHERE` line removed to cover every project BaseURL.

```cypher
MATCH (b:BaseURL {project_id: $project_id})-[:HAS_ENDPOINT]->(e:Endpoint)
WHERE e.baseurl IN $baseurls
OPTIONAL MATCH (e)-[:HAS_PARAMETER]->(p:Parameter)
RETURN e.baseurl            AS baseurl,
       e.method             AS method,
       e.path               AS path,
       e.url                AS url,
       e.status_code        AS status,
       collect(DISTINCT p.name) AS parameters
ORDER BY baseurl, path, method
LIMIT 500
```

**S4. What every Service already AGGREGATES (the differential anchor).**

```cypher
MATCH (s:L1Service {project_id: $project_id})-[:AGGREGATES]->(e:Endpoint)
RETURN s.business_function_slug AS owner,
       e.method                 AS method,
       e.path                   AS path,
       e.baseurl                AS baseurl
ORDER BY owner, baseurl, path
LIMIT 500
```

**S5. The Endpoints THIS Service already AGGREGATES (the non-empty-seed case).**

```cypher
MATCH (s:L1Service {project_id: $project_id, business_function_slug: $slug})
      -[:AGGREGATES]->(e:Endpoint)
RETURN e.method AS method, e.path AS path, e.baseurl AS baseurl
ORDER BY baseurl, path, method
LIMIT 200
```

**S6. The Parameter names on one Endpoint (targeted follow-up for evidence).**

```cypher
MATCH (e:Endpoint {project_id: $project_id, path: $path, method: $method, baseurl: $baseurl})
      -[:HAS_PARAMETER]->(p:Parameter)
RETURN p.name       AS parameter,
       p.position   AS position,
       p.input_type AS input_type
LIMIT 50
```

**S7. A family probe by path fragment (still no assumed asset name - a substring, not a path).**

```cypher
MATCH (e:Endpoint {project_id: $project_id})
WHERE e.path CONTAINS $fragment
RETURN e.method AS method, e.path AS path, e.baseurl AS baseurl
ORDER BY e.path
LIMIT 100
```

**S8. Endpoint counts per BaseURL (a bounded breadth overview before drilling in).**

```cypher
MATCH (b:BaseURL {project_id: $project_id})-[:HAS_ENDPOINT]->(e:Endpoint)
RETURN b.url AS baseurl, count(e) AS endpoints
ORDER BY endpoints DESC
LIMIT 50
```

The workflow's `surface_scan` prose names S2, S3 and S4 explicitly; S1, S5, S6, S7 and S8 are the follow-ups the prose invites.
`$slug`, `$baseurls`, `$path`, `$method`, `$baseurl` and `$fragment` are bound by the model from the turns already recorded.

## 6. The full updated role prompt (the system prompt string)

The system prompt is the SAME two layers the Bootstrapper uses: `_ROLE_VERBATIM` in code carries the WHAT (identity, the aggregates-only contract, the reference shape, the mandatory scan/read/closure), and `prompts/assigner.md` carries the HOW (the judgment discipline and its worked examples).
The assembled system prompt string is `f"{_ROLE_VERBATIM}\n\n{_load_assigner_skill()}"`.
It stays byte-stable across a run, so the provider prompt-cache prefix holds; the volatile Service card and inventory ride the human turns.

### 6.1 `_ROLE_VERBATIM` (Python string constant)

```python
_ROLE_VERBATIM = (
    "You are the cross-layer Assigner in an attack-surface analyser.\n"
    "ROLE - SERVICE ENRICHMENT. This unit is ONE existing business Service. Your only "
    "output is `aggregates`: each an `AGGREGATES` judgment that this Service owns a "
    "specific L0 `Endpoint`, with a confidence and evidence. You never mint, rename or "
    "re-assign a Service; the Bootstrapper is the sole Service source.\n"
    "HOW YOU GET THE SURFACE: you are NOT handed a frozen chunk. Query the L0 surface "
    "yourself with the read-only `graph_view` tool, BROADLY and with NO asset-name "
    "assumption: enumerate the `:BaseURL`s and their `:Endpoint`s, read each path's "
    "segments, method and parameter names, then judge. Never query for a path or asset "
    "name you guessed from the contract; enumerate what exists. Bound every query with "
    "a `LIMIT`.\n"
    "HOW TO JUDGE OWNERSHIP: read the Service contracts in the inventory - what each "
    "business function DOES and OWNS - and match the concrete nouns and actions in the "
    "Endpoint against them: the path segments, the parameter names, the method. A path "
    "noun that names something a contract says the Service owns is strong evidence; a "
    "merely plausible topical association is not. Cite the specific path or parameter "
    "you matched in `evidence_refs`.\n"
    "SHARED OWNERSHIP IS REAL: more than one Service may genuinely own the same "
    "Endpoint. When two contracts both fit, emit an aggregate for EACH, every one "
    "carrying its own honest confidence. Do not pick a winner and do not discount a "
    "confidence merely because ownership is shared.\n"
    "CONFIDENCE: give each aggregate the confidence you actually hold. A judgment you "
    "would not defend belongs low, and a low one simply produces no edge - that is the "
    "correct outcome, not a failure.\n"
    "USE ONLY THE SLUGS LISTED IN THE INVENTORY. You cannot create a Service: a slug "
    "that is not listed names nothing and its aggregate will be discarded. If surface "
    "fits no listed Service, leave it unassigned rather than inventing an owner; it "
    "stays in the stale pool.\n"
    "BEFORE YOU JUDGE, read prior modelling insights from the `notes` store; AFTER you "
    "judge, write exactly ONE modelling-closure note recording what the unit claimed "
    "and what it did NOT claim.\n"
    "REFERENCING AN ENDPOINT: put the endpoint in `l0.identity` as "
    "`{\"path\": \"/api/Users\", \"method\": \"GET\", "
    "\"baseurl\": \"<the baseurl shown>\"}`, with `l0.label` set to `Endpoint`. "
    "Only reference endpoints that appear in your `graph_view` results; one you invent "
    "names nothing and is discarded.\n"
    "Emit `aggregates` only. Leave services, systems, system_edges and every "
    "data-modelling list EMPTY - other proposers own those."
)
```

### 6.2 `analysis/prompts/assigner.md` (the HOW layer)

```markdown
Your base prompt fixes WHAT you emit; this discipline fixes HOW you decide.
You are given ONE Service and its `service_contract`, and you must find the L0 surface the Service owns.
Every Endpoint is one question: does this Service own it, and would you defend that answer to the architect who wrote the contract?

## Find the surface before you judge it

You are not handed the surface; you query it.
Call `graph_view` and enumerate broadly - every BaseURL, every Endpoint on it, and the parameter names on each - with no assumption about what the paths will be.
Then read each path as surface: its nouns, the action its method and trailing segment carry, the names of its parameters.
Reading the inventory first makes you pick a slug and hunt for a justification, which is exactly how a topical affinity becomes evidence.

## The null hypothesis is that nothing owns it

Begin every judgment from no owner, and make the evidence overturn it.
Assignment is the claim that carries the burden of proof; leaving surface unowned carries none.

This is the direction you are measured to get wrong.
Across live runs roughly a third of assignments were topical guesses no contract supported.
A defensible owner is the goal - never volume, never coverage.

An unowned Endpoint is not lost: it stays in the stale pool, counted and visible, for a later Service nobody has written yet.
An Endpoint hung on the wrong Service is worse than unowned, because it looks answered, and every later phase inherits the mistake.

## Work each Endpoint in four moves

1. **READ THE SURFACE FIRST.**
   Say what the Endpoint alone tells you: the nouns in its path segments, the action carried by the method and the trailing segment, the names of its parameters.
   Do this before you open the inventory.
2. **RUN A DIFFERENTIAL.**
   Hold every candidate Service whose contract touches those nouns or actions, not the first one that fits.
   A candidate that arrived with no competition is usually the first pattern you noticed rather than the best-supported one, so name the runner-up even when you are sure.
3. **DISCRIMINATE.**
   For each candidate ask whether the evidence fits THIS contract and not the others.
   Evidence that fits three Services equally is evidence for none of them - park it at a low confidence, never a confident pick among the three.
   Two contracts that genuinely both reach the Endpoint are two owners rather than a tie to break - emit an aggregate for each, each with its own honest confidence.
4. **CALIBRATE, THEN COMMIT OR WITHHOLD.**
   Give each aggregate the confidence step 3 earned it, and quote the exact path segment or parameter you matched as its evidence.
   Evidence that restates the slug instead of the surface is self-refuting; if the only thing you can say is that the Service sounds related, you have not matched anything.

## Read prior insights, then close

Before step 2, read the `notes` store: an earlier Service may have claimed an Endpoint, refused one, or judged a Service missing.
After you commit or withhold, write ONE modelling-closure note naming what this unit claimed and explicitly what it did NOT claim and why.

## What the confidence numbers mean

Calibrate against the evidence you actually hold, not against how much surface you would like to place.

- **Around 0.9** - a path noun names a record or an action the contract explicitly says that Service owns.
- **Around 0.8** - the method plus a trailing segment or a parameter name matches an action the contract describes, though the noun is generic.
- **Around 0.5** - the Endpoint sits in the same business area as the contract, but no specific noun or action in it matches anything the contract claims.
- **Around 0.2** - the only link is topical or technological proximity: it is an HTTP endpoint on a web application, so a web-ish Service feels adjacent.

A judgment below the bar simply produces no edge, and that is the correct outcome rather than a failure.

## Judge the surface in front of you, freshly

An Endpoint whose owner looks obvious deserves the same four moves as one that does not.
Give every Endpoint you scanned its own differential; a re-judged Endpoint costs nothing, while one waved through on recognition is how a whole unit's precision drops at once.

## Worked examples

These slugs are illustrative and never appear in a real inventory; take the SHAPE of the judgment from them, never the answer.

**1. Clear assignment.**
Inventory has `invoice-settlement - Takes a draft invoice to a settled payment; owns invoices and payment intents.`
Scan returns Endpoint `POST /invoices/42/settle`.
Surface first: nouns *invoice*, action *settle*.
Differential: only `invoice-settlement` claims either.
-> one aggregate, service_slug `invoice-settlement`, confidence 0.93, evidence_refs `["path segment /invoices", "path segment /settle"]`.

**2. Deliberate withholding.**
Inventory has `invoice-settlement` and `brochure-pages - Presents marketing pages and categories.`
Scan returns Endpoint `GET /internal/health`.
Surface first: nouns *internal*, *health*; no business record and no business action.
Differential: neither contract mentions health, probes or internal operations.
-> confidence 0.2, or no aggregate at all.
The low confidence is the right answer, and the Endpoint correctly ends the run with no owner; the closure note records it as NOT CLAIMED.

**3. Shared ownership.**
Inventory has `invoice-settlement - owns invoices` and `parcel-dispatch - owns shipments and the dispatch of settled invoices.`
Scan returns Endpoint `GET /invoices/42/shipment`.
Differential: both contracts name a noun that appears in the path, and neither claim rules the other out.
-> TWO aggregates: `invoice-settlement` at 0.85 (evidence "path segment /invoices") and `parcel-dispatch` at 0.80 (evidence "path segment /shipment").
Both genuinely reach this Endpoint; emit both rather than choosing.
```

## 7. What this design does NOT change

- The five deterministic shaping gates run unchanged after the extraction turn, in order: `narrow_to_assignment` -> `resolve_l0_refs` -> `drop_out_of_inventory` -> `normalise_confidence` -> `withhold_below_bar` (analysis CONTEXT, "Assigner" shaping).
- The `aggregates`-only output contract: the extraction turn emits nothing else, and `narrow_to_assignment` enforces it whatever the model returned.
- `AGGREGATES` remains the only cross-layer edge carrying a graded judgment.
- The `service_slug` must name a live Service; unknown owners become backlog descriptions, not edges.
- `AnalysisTurn` stays the single LLM-facing envelope; `claims` are dropped by `to_delta_batch` before the sole-writer.
