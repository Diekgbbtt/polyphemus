# The data_modeller reasoning workflow (analysis-unit-first v2)

*Status: PARTIALLY SUPERSEDED, 2026-10-12.
Branch `feat/analysis-unit-enrichment`.
Owner: the `data_modeller` proposer of the analysis-unit-first v2 pipeline.
This document specifies the reasoning workflow only.
It does not change any Python code; the implementation is a later ticket.*
*The PRE-FED-surface sources specified below are superseded by `batched-l1unit-first-adr.md` (T3): the eight sub-problem ids survive, but no whole-streamed-surface list is fed. The base sources are the `service` unit block (slug + `service_contract` + aggregated Endpoints), the known `inventory` DataItems, the FULL live `services` inventory and the `observations`; the survey is DISCOVERED through `graph_view` and the HTTP-history pair. The implementation lives in `src/polymerhus/analysis/data_modeller.py` and the prompt file `prompts/data-plane-batched-l1unit-first.md`. Sections below are retained as the historical design record.*

The owning decision record is `docs/design/dataplane-A1-decisions.md`.
This document extends it from the streamed per-chunk pipeline to the unit-first pipeline.
Every term is taken verbatim from `src/polymerhus/analysis/CONTEXT.md`.

---

## 0. Scope and vocabulary anchors

The `data_modeller` is the **DataPlane Analyser**.
It is the sole owner of the Tier-1 data substrate.
In v2 it is not fed a streamed chunk of the whole surface.
It is fed **one Service** - the pipeline unit - with that Service's aggregated surface.

Its job is to **enrich** that **Service**.
It lifts and compounds the logical **DataItem**s the Service exchanges.
It binds each item to the **L0** sites where it appears with **SURFACES_AT**.
It maps the **PRODUCES** / **CONSUMES** flows onto the settled Service model.
It maps surface-observable **DATA_RELATIONSHIP** edges between **DataItem**s.
It emits `L1DeltaBatch{data_items, surfaces_at, data_flows, data_relationships}` and nothing else.

The **Service (L1)** is a **target**, individuated by business purpose and keyed on `business_function_slug`.
The **DataItem** is a logical data record, keyed on a semantic `item_key`, with identity independent of the **L0** sites it surfaces at.
The **AGGREGATES** edge is the cross-layer hinge from a Service to its **L0** surface.
**SURFACES_AT** targets a **Parameter** / **Header** / **Secret**, never an **Endpoint**: a path noun alone never grounds a lift.

Two **L0** reads ground the lift in v2:

- the mapped **L0** surface, read **broadly** through the read-only Cypher tool `graph_view`, with no asset-name assumption;
- the recorded **HTTP history** of the project, read through `search_http_history` and then `get_http_artifact`.

The episode memory is the **analysis episodic memory** (`data/<project_id>/analysis/memory.yaml`).
The memory holds **note** records keyed `<unit>:<note_name>`, with a **note kind** from the closed enum `NOTE_KINDS`.

The reasoning is a **ReasoningWorkflow**: an ordered list of **SubProblem**s, one LLM turn each.
Every turn speaks the one envelope **AnalysisTurn**.
A reasoning sub-problem populates **Claim**s; an extraction sub-problem populates the delta lists.
A **Claim** carries `subject`, `assertion`, `evidence`, `verdict`.
Dependencies are injected **verbatim** from the recorded turns, never from the session trail.

The **Ground** mechanism substitutes for the Assigner's **Withhold** on this path.
The four data proposal shapes carry no `confidence` field (the **Judgment envelope** asymmetry).
An ungrounded lift is dropped by code (`enforce_groundedness`), never merely discouraged by prompt.
The **observed-only fields** rule is enforced by code (`bind_fields_to_observed`).
The **per-unit backstop** (`ensure_unit_note`) writes one note per unit when the proposer wrote none.

---

## 1. Position in the pipeline

The v2 per-Service loop runs `mechanism_typist` then `data_modeller` over the Service's slice.
The `data_modeller` runs LAST, so its Parameter-to-owning-Service join has a live **AGGREGATES** answer.

The body (`model_data`) is fed:

- the Service unit (`business_function_slug`, `service_contract`, exposure), from the live **L1** inventory;
- the Service's aggregated **L0** surface, from the live aggregation view;
- the live **L1** inventory of **DataItem**s with their `fields` and `notes`, for **reuse-vs-coin**;
- the live **Service** inventory with contracts, for the flow direction (**candidates**).

The body seeds a small set of volatile base sources.
The agent then acts: it reads the surface broadly, reads the request shapes, reads prior insights, reasons, and emits.

---

## 2. The base sources the body seeds

These are rendered verbatim into the injected (`inject`) slots.
They are the only context the body forces.
Everything else the agent fetches through its tools.

- `service` - the Service unit card: the `business_function_slug`, the `service_contract`, and the aggregated Endpoint count.
- `endpoints` - the aggregated **L0** **Endpoint**s: `baseurl`, `method`, `path`, `url`.
  It is the SEED, never the authority: the agent enumerates the full detail through `graph_view`.
- `inventory` - the currently-known **DataItem**s with their `fields` and `notes`.
  Drives **reuse-vs-coin** and compounding.
- `candidates` - the live **Service**s with their `service_contract`s.
  The only legal source of a `data_flows.service_slug`.
- `request_shapes` - the deterministic request-shape read for this unit's aggregated endpoints.
  It is the sanitized summary rows and inspected shapes from the **HTTP history**.
  See section 4 for why the body reads it deterministically.

---

## 3. The ordered sub-problems

The workflow has eight sub-problems.
Their order is load-bearing; each depends on the ones before it.

The eight map one-to-one onto the eight **reflection stages** below (the ADR D22 mapping).
The stages use the shared names ORIENT, HYPOTHESISE, VERIFY/FALSIFY, INTEGRATE, SHAPE, EMIT/WITHHOLD, extended for v2.

```
_REFLECTION_STEPS (v2) =
  0 SURVEY      - ORIENT over the mapped L0 surface, broadly and without asset-name assumption.
  1 READ SHAPES - read the recorded request shapes to the Service's aggregated endpoints.
  2 RECALL      - read prior modelling insights from the notes store and reconcile them.
  3 HYPOTHESISE - hypothesise, verify and falsify the records the Service exchanges.
  4 INTEGRATE   - integrate the adversarial insight; lift or compound; bind SURFACES_AT and fields.
  5 SHAPE FLOWS - shape the PRODUCES/CONSUMES flows, trust assumptions and record-to-record relations.
  6 EMIT FLOWS  - emit the flows and relationships the surface shows, and name what was withheld.
  7 CLOSE       - write the modelling-closure note for the Service.
```

**The constant bound tool set (load-bearing).**
Every turn binds the SAME tools: `graph_view`, `search_http_history`, `get_http_artifact`, `notes`, and the structured `AnalysisTurn` tool.
The tool set never toggles across the eight turns, so the provider prefix cache always matches (the constant-request-shape rule, ADR D26/D34).
The "tools called" column below names the tools a sub-problem is EXPECTED to use; the bound set is always all five.

**The fail-closed gate.**
`halt_when` halts the chain when the `record_hypotheses` turn exhausts (`turn is None`).
A `None` earlier turn is rendered empty (a soft pass-through); the chain runs on.
When `record_hypotheses` exhausts, the body fails CLOSED to an empty outcome with `reflection_exhausted=True`.
This mirrors the v1 gate.

**The ordered sub-problem list (summary).**

| # | `id` | `name` | `emit` | `depends_on` | tools called |
|---|------|--------|--------|--------------|--------------|
| 1 | `surface_survey` | surface survey | `claims` | (none) | `graph_view` |
| 2 | `request_shapes` | request shapes | `claims` | `surface_survey` | `search_http_history`, `get_http_artifact` |
| 3 | `insight_recall` | insight recall | `claims` | `surface_survey`, `request_shapes` | `notes` (read) |
| 4 | `record_hypotheses` | record hypotheses | `claims` | `surface_survey`, `request_shapes`, `insight_recall` | `graph_view`, `notes` (read) |
| 5 | `data_extract` | data extract | `data_items`, `surfaces_at` | `record_hypotheses` | `graph_view`, `notes` (read) |
| 6 | `flow_shape` | flow shape | `claims` | `data_extract` | `graph_view`, `notes` (read) |
| 7 | `flow_extract` | flow extract | `data_flows`, `data_relationships` | `flow_shape`, `data_extract` | `graph_view`, `notes` (read) |
| 8 | `closure_note` | modelling closure | `claims` | `flow_extract` | `notes` (write) |

The bound tool set is always all five tools (`graph_view`, `search_http_history`, `get_http_artifact`, `notes`, `AnalysisTurn`); the table names the tools each sub-problem is expected to call.

### 3.1 `surface_survey` - "surface survey"

- **id**: `surface_survey`
- **name**: `surface survey`
- **emit**: `claims`
- **inject**: `service`, `endpoints`
- **depends_on**: (none)
- **tools called**: `graph_view`

**Reflection prose (the exact task text):**

> SURVEY - ORIENT over the mapped L0 surface of this Service, BROADLY.
> Do not assume anything from an asset name.
> Navigate from the Service down to its attack surface.
> Enumerate the Service's aggregated Endpoints, and for each Endpoint its Parameters, the Headers and Secrets on the BaseURL it lives on, and any existing DataItems already flowed to or from this Service.
> Use `graph_view` with read-only Cypher; a path is the address you interrogate, never a place data appears.
> For each surface sighting, emit one Claim: `subject` the Service or the endpoint, `assertion` what the surface alone tells you (the concrete Parameters, Headers and Secrets you found, and their transport position), `evidence` the exact Cypher-returned identity, `verdict` whether this is a surface site that could witness a business record.
> A name that merely sounds like a record is not evidence yet; record the sighting, do not judge it here.
> Emit `claims` only; do not emit deltas yet.

**Why this phase exists.**
The body seeds only the aggregated Endpoints (the `endpoints` base source).
The Parameters, Headers and Secrets are reached by the agent's own broad query.
This is the "no asset-name assumption" rule: the agent enumerates `(Endpoint)-[:HAS_PARAMETER]->(Parameter)` and `(BaseURL)-[:HAS_HEADER|HAS_SECRET]->(...)` rather than trusting a seeded list.

### 3.2 `request_shapes` - "request shapes"

- **id**: `request_shapes`
- **name**: `request shapes`
- **emit**: `claims`
- **inject**: `service`, `endpoints`, `request_shapes`, `surface_survey`
- **depends_on**: `surface_survey`
- **tools called**: `search_http_history`, `get_http_artifact`

**Reflection prose (the exact task text):**

> READ SHAPES - read the RECORDED REQUEST SHAPES to this Service's aggregated endpoints.
> The mapped L0 surface names the inputs; the HTTP history shows how they are actually sent.
> Call `search_http_history` with a conjunctive filter over the request side for each aggregated endpoint (filter on `url` containing the endpoint path), then call `get_http_artifact` on the returned `artifact_id` to inspect one recorded transaction.
> Read the `request` object: `{method, url, headers, cookies, query, form}`.
> Body content is never visible and secret-bearing values are redacted; the KEYS are what matter.
> For each request-shape observation, emit one Claim: `subject` the endpoint, `assertion` the request keys actually sent and their transport (query, form, header, cookie), `evidence` the `artifact_id` and the exact key names, `verdict` which mapped surface site the shape corroborates.
> A recorded request is a candidate, never a verification; it corroborates a sighting, it does not by itself ground a DataItem.
> Emit `claims` only; do not emit deltas yet.

**Why this phase exists.**
An HTTP artifact is ONE immutable recorded transaction of this project.
It is a lower-rung witness than an analyst judgment: it shows the request the endpoint actually received.
It raises the evidence quality of the records the Service exchanges, and it reveals request shapes the mapped surface alone under-determines.
See section 4 for the exact grounding interaction.

### 3.3 `insight_recall` - "insight recall"

- **id**: `insight_recall`
- **name**: `insight recall`
- **emit**: `claims`
- **inject**: `service`, `inventory`, `surface_survey`, `request_shapes`
- **depends_on**: `surface_survey`, `request_shapes`
- **tools called**: `notes` (read)

**Reflection prose (the exact task text):**

> RECALL - read the PRIOR MODELLING INSIGHTS from the notes store before you enrich.
> Call `notes` with `command="read"` for this Service's unit slug, and again with a `body_keyword` for the modelling closures of other Services that may share a record or a flow.
> Reconcile what prior runs concluded against the surface you just surveyed: a prior `data` item that still fits is a REUSE target; a prior `open_question` that the request shapes now answer is settled here; a prior insight the survey contradicts is named and set aside.
> For each prior insight you carry forward, emit one Claim: `subject` the prior item or question, `assertion` how the current survey confirms or corrects it, `evidence` the note key and the surface corroboration, `verdict` reuse, compound, or set aside.
> Emit `claims` only; do not emit deltas yet.

**Why this phase exists.**
Read-back is within-run and cross-run: a later Service reads earlier Services' notes, and the store is per-project and durable.
The dedicated read phase is what makes prior modelling insight an input to enrichment rather than a prompt instruction the model may skip.

### 3.4 `record_hypotheses` - "record hypotheses"

- **id**: `record_hypotheses`
- **name**: `record hypotheses`
- **emit**: `claims`
- **inject**: `service`, `inventory`, `candidates`, `surface_survey`, `request_shapes`, `insight_recall`
- **depends_on**: `surface_survey`, `request_shapes`, `insight_recall`
- **tools called**: `graph_view` (targeted verification), `notes` (optional read)

**Reflection prose (the exact task text):**

> HYPOTHESISE - for each surface sighting, state candidate hypotheses of the form "this name witnesses business record R".
> For an ambiguous name (`id`, `token`, `ref`) hold MORE THAN ONE candidate record, and state "this witnesses no business record" as an explicit candidate among them, never an unstated default.
> VERIFY / FALSIFY - test each hypothesis against the evidence actually present.
> Separate the claim from its support: the exact name, the exact path, the exact endpoint it hangs off, and the exact recorded request shape that carries it.
> A name that merely sounds like a record, with no request-shape corroboration, is topical proximity, not evidence; reject it.
> Decide REUSE-vs-COIN here, against the currently-known DataItems and their notes and fields: an existing item_key with matching notes and fields wins over minting a synonym.
> For each record, emit one Claim: `subject` the record, `assertion` the candidate record it witnesses or "no record" explicitly, `evidence` the exact name, endpoint, and the request-shape artifact_id that corroborates it, `verdict` reuse-vs-coin against the known DataItems.
> Emit `claims` only; do not emit deltas yet.

**Why this phase exists.**
This is the crux reasoning turn and the fail-closed gate.
It carries the null hypothesis explicitly, so withholding is the loop's demonstrated conclusion.

### 3.5 `data_extract` - "data extract"

- **id**: `data_extract`
- **name**: `data extract`
- **emit**: `data_items`, `surfaces_at`
- **inject**: `inventory`, `surface_survey`, `record_hypotheses`
- **depends_on**: `record_hypotheses`
- **tools called**: `graph_view` (confirm the exact L0 site identity), `notes` (optional read)

**Reflection prose (the exact task text):**

> INTEGRATE - fold the origin's adversarial insight into the surviving record's `notes`: what it is, whose trust it carries, what breaks.
> This is an adversarial CHARACTERISATION only: no named payload, no named technique, no named vector.
> EXTRACT THE DATA ITEMS - from the reasoning above, fill `data_items` and `surfaces_at` for every record it verified.
> For a record already listed in the inventory, REUSE its exact `item_key` and output the COMPOUNDED `fields` and `notes` (fold new insight in, never blank or merely restate).
> Coin a new `item_key` only for a record no existing key covers.
> Reference a surface site in `surfaces_at.l0` as `{"label": "Parameter"|"Header"|"Secret", "identity": {... the exact identity shown ...}}`; NEVER an Endpoint.
> `fields` names ONLY fields you actually OBSERVED on the surface shown, including the request-shape keys you read from the HTTP history; never a speculative attribute.
> Emit `data_items` and `surfaces_at` only.

**Why this phase exists.**
It is the only extraction turn for the surface half of the delta.
The `fields` and `SURFACES_AT` shapes are transcribed from what verification already settled.

### 3.6 `flow_shape` - "flow shape"

- **id**: `flow_shape`
- **name**: `flow shape`
- **emit**: `claims`
- **inject**: `candidates`, `surface_survey`, `record_hypotheses`, `data_extract`
- **depends_on**: `data_extract`
- **tools called**: `graph_view`, `notes` (optional read)

**Reflection prose (the exact task text):**

> SHAPE FLOWS - for each verified record, name the surface sites it appears at, and which Service produces it and which consumes it.
> Choose service slugs ONLY from the candidate list you were given; a slug you invent names nothing.
> For a CONSUMES whose producing Service differs from the consuming Service, state the falsifiable predicate the consumer holds about that data, in one surface-readable sentence (the trust assumption).
> Relate - only where the surface itself shows it, state a record-to-record dependency using one of the allowed kinds, with a shallow predicate.
> For each record, emit one Claim: `subject` the record, `assertion` the producing and consuming Service and the shared surface site, `evidence` the candidate list you copied the slugs from and the shared-surface relation, `verdict` the trust assumption predicate and any record-to-record relation.
> Emit `claims` only; do not emit deltas yet.

**Why this phase exists.**
The flow direction needs the extraction result.
The producing Service is normally this unit; the consuming counterpart comes from the candidate list.

### 3.7 `flow_extract` - "flow extract"

- **id**: `flow_extract`
- **name**: `flow extract`
- **emit**: `data_flows`, `data_relationships`
- **inject**: `candidates`, `data_extract`, `flow_shape`
- **depends_on**: `flow_shape`, `data_extract`
- **tools called**: `graph_view`, `notes` (optional read)

**Reflection prose (the exact task text):**

> EMIT FLOWS - from the shape above, fill `data_flows` (`service_slug` copied VERBATIM from the candidate list) and `data_relationships` (a fixed allowlist `kind`) for every relation the surface itself shows.
> Name what you WITHHELD and why, so withholding is the demonstrated conclusion.
> Emit `data_flows` and `data_relationships` only.

**Why this phase exists.**
It is the only extraction turn for the flow half of the delta.

### 3.8 `closure_note` - "modelling closure"

- **id**: `closure_note`
- **name**: `modelling closure`
- **emit**: `claims`
- **inject**: `service`, `record_hypotheses`, `data_extract`, `flow_extract`, `request_shapes`
- **depends_on**: `flow_extract`
- **tools called**: `notes` (write)

**Reflection prose (the exact task text):**

> CLOSE - write the modelling-closure note for this Service.
> Call `notes` with `command="write"`, `action="append"`, `unit` the Service slug, `note_name="modelling-closure"`, `kind="data"`, and the body summarising this enrichment.
> The body MUST name: the DataItems lifted and compounded (item_key, fields, anchors, flows), the records reused, what you WITHHELD or FALSIFIED and why, the recorded request shapes consulted, and any open question the surface left unresolved.
> Then emit one Claim summarising the closure: `subject` the Service, `assertion` the enrichment result, `evidence` the note key, `verdict` the residual open question or "resolved".
> Emit `claims` only.

**Why this phase exists.**
It makes the modelling closure explicit and auditable.
It writes the `data` note through the shared `notes` tool.
The per-unit backstop remains the safety net; see section 5.

---

## 4. Request-shape evidence and how it grounds a DataItem lift

This section is the load-bearing decision of the v2 workflow.

### 4.1 What the request shapes are

The HTTP history stores one immutable recorded transaction per artifact, addressed by `artifact_id` (prefix `http_`).
The sanitized projection exposes `request {method, url, headers, cookies, query, form}`.
Body content is never in the store; secret-bearing values are `[redacted]`; `source_ip` is excluded.
The KEYS of `query`, `form`, `headers` and `cookies` are visible.
A request shape for an endpoint is therefore the set of input names that endpoint actually received, with their transport.

### 4.2 The grounding channel (decision)

The request shape is a CORROBORATING grounding channel, never a new anchor type.

- The request shape widens the **observed vocabulary** for `fields`.
  A name witnessed in a recorded request to an aggregated endpoint is a name the unit could actually have observed.
- The request shape widens the **site index** only for sites that canonicalise onto a real **L0** node.
  A `query` or `form` key canonicalises to `Parameter{name, position, endpoint_path, baseurl}`; a header or cookie name canonicalises to `Header{name, baseurl}`.
- The **groundedness** gate is UNCHANGED in force.
  A NEW **DataItem** still needs a surviving **SURFACES_AT** to a real **L0** **Parameter**/ **Header**/ **Secret**.

The reason is that a `SURFACES_AT` edge is MATCHed, never MERGEd, by the sole-writer.
A request-shape name that no recon tool mapped to an **L0** node has no node to MATCH; the edge is a no-op.
So HTTP history raises the evidence quality and the field coverage; it cannot manufacture an **L0** anchor.

### 4.3 Interaction with the observed-only-fields gate

The gate (`bind_fields_to_observed`) intersects each proposed `fields` list with the observed vocabulary, then UNIONs the survivors with the item's already-persisted `fields`.

The observed vocabulary becomes the UNION of:

- the names of the admitted **Parameter**/ **Header** assets in the unit slice, and their non-identity `props` keys (`observed_vocabulary`); and
- the request-shape keys read from the **HTTP history** for the Service's aggregated endpoints.

Without the second half, the HTTP read could only corroborate names already mapped as **L0** **Parameter**s, which makes it near-redundant.
With it, a field witnessed in a recorded request is admissible even when the corresponding **L0** **Parameter** node was not mapped.
The rule stays observed-only: the name must be witnessed in a recorded request to an aggregated endpoint, never merely plausible.

### 4.4 Interaction with the groundedness gate

The gate (`enforce_groundedness`) drops every NEW **DataItem** with no surviving **SURFACES_AT**.
The reference gate (`resolve_surface_refs`) canonicalises the `surfaces_at.l0` against the site index and drops a ref that names no site.

The site index becomes the UNION of:

- the admitted **Parameter**/ **Header**/ **Secret** sites (`site_index`); and
- the request-shape-derived sites, canonicalised to the same shapes.

A request-shape-derived **Parameter** site carries the SAME identity shape as a mapped one: `{name, position, endpoint_path, baseurl}`.
So when the **L0** node exists, the **SURFACES_AT** MATCHes and grounds the lift.
When the node does not exist, the edge is a no-op at the writer, and the item is dropped by `enforce_groundedness` unless another real site grounds it.
This keeps the gate's guarantee: a surviving **SURFACES_AT** means a real anchor.

### 4.5 Why the body reads the shapes deterministically

Correctness must never depend on the model's formatting.
The gates run in code after the LLM turn.
So the body performs a deterministic request-shape pre-read for the unit's aggregated endpoints through the injected `search_http_history`/`get_http_artifact` seams.
It builds `observed_request_names` and `request_site_index` from that read and passes them to `shape_proposal`.
The same read is rendered as the `request_shapes` base source, so the model starts from the shapes the gates will honour.
The model's own `search_http_history`/`get_http_artifact` calls are for deeper inspection (one endpoint, one artifact), never the gate's source of truth.

### 4.6 Rejected alternatives

- **HTTP history as a new anchor type.**
  Rejected: `SURFACES_AT` is defined against **L0** nodes; an artifact is not an **L0** node, and a new node type would break the cross-layer taxonomy.
- **Corroboration only, no vocabulary widening.**
  Rejected: it makes the HTTP read near-redundant and does not answer the under-determined case, which is the reason the read exists.
- **Trusting the model's reported request keys.**
  Rejected: it makes the grounding gate depend on the model's formatting, the defect class that wrote zero of 114 sound assignments and silently voided the confidence bar.

---

## 5. The modelling-closure note

Every finished Service leaves one note, so coverage is auditable.

- **store**: the **analysis episodic memory** at `data/<project_id>/analysis/memory.yaml`.
- **key**: `<service_slug>:modelling-closure`.
- **`unit`**: the Service slug.
- **`note_name`**: `modelling-closure`.
- **`kind`**: `data` (one of `NOTE_KINDS`: `assignment`, `system`, `data`, `refusal`, `open_question`).
- **written by**: the `closure_note` sub-problem through the shared `notes` tool (`command="write"`, `action="append"`).
- **backstop**: `ensure_unit_note` writes one note for the unit when the closure turn wrote none.
  The body passes `note_kind="data"`, so the backstop's coverage note carries the kind this role owns.
  The backstop is fail-open and runs in a `finally`, so the coverage property holds on the failure path too.

**Body template:**

```
modelling closure - Service <service_slug>
Enriched endpoints: <n>
DataItems lifted: <item_key> :: fields=[<...>]; anchors=<label:identity, ...>; flows=<produces|consumes -> <service_slug>>
DataItems compounded: <item_key> :: <new fields/notes folded in>
Withheld / falsified: <name> - <reason, e.g. pagination cursor, CSRF token, framework header>
Request shapes consulted: <n> recorded transactions across <endpoint paths> (artifact_ids: <...>)
Trust boundaries: <consumer <- data <- producer>:: <trust assumption predicate>
Open questions: <...>
```

The template is a shape, not a schema.
The body is prose; the structured refs (the request `artifact_id`s) live in the note's `provenance`, written by the code, never authored by the model.

---

## 6. The full updated role prompt text

The role prompt is TWO layers, mirroring the Bootstrapper and the Assigner.
The base layer in code (the WHAT) holds with no prompt file and carries the hard output contract.
The skill file `prompts/data-plane.md` (the HOW) carries the reasoning discipline and the worked examples.

### 6.1 The base layer in code (`_ROLE_VERBATIM`)

```
You are the DataPlane Analyser (data_modeller) in an attack-surface analyser.
ROLE - DATA MODELLING. You are fed ONE Service and its aggregated attack surface. You judge which logical business records (DataItems) the Service exchanges, where each one appears (`surfaces_at`), which Service produces and consumes it (`data_flows`), and the shallow record-to-record dependencies the surface shows (`data_relationships`). You emit these four lists and nothing else - never `services`, `systems`, `aggregates`, or `system_edges`.
A DataItem is a business record BEHIND the surface (customer account, product listing, shopping basket, order, delivery address, payment method, coupon), NOT an endpoint or a parameter itself. A parameter that witnesses no business record (a pagination cursor, a CSRF token, a framework header) is correctly left alone.
SURVEY THE MAPPED SURFACE BROADLY. Navigate from the Service to its Endpoints with `graph_view` (read-only Cypher) and enumerate the Parameters, Headers and Secrets without assuming anything from an asset name. A path is the address you interrogate, never a place data appears.
READ THE RECORDED REQUEST SHAPES. Use `search_http_history` to find recorded transactions to the Service's endpoints, then `get_http_artifact` to inspect one. Read the request `{method, url, headers, cookies, query, form}` keys - body content is never visible and secret-bearing values are redacted. The recorded shape corroborates a lift; it does not by itself anchor one.
RECALL PRIOR INSIGHT. Use `notes` (command="read") to read this Service's prior modelling notes and other Services' closures before you enrich. Reuse a prior item that still fits; settle an open question the surface now answers.
REFERENCING A SURFACE SITE: put the site in `surfaces_at.l0` as {"label": "Parameter"|"Header"|"Secret", "identity": {...the exact identity shown to you...}}. NEVER reference an Endpoint - a path noun alone never grounds a lift.
`fields` on a DataItem name ONLY fields you actually OBSERVED on the surface shown, including the request-shape keys you read from the HTTP history; never a speculative or merely-plausible field.
`data_flows.service_slug` is copied VERBATIM from the candidate owning-Services list you are given - never a slug you invent.
`data_relationships.kind` is one of the fixed allowlist; anything else is discarded.
CLOSE with a modelling-closure note: call `notes` (command="write", action="append", unit=the Service slug, note_name="modelling-closure", kind="data") summarising the DataItems you lifted and compounded, what you withheld and falsified and why, the request shapes you consulted, and any open question.
You never set provenance or write status; those are stamped by the system.
```

### 6.2 The skill layer (`prompts/data-plane.md`)

```
You are the DataPlane Analyser (data_modeller). You are fed ONE Service and its aggregated attack surface. Your job is to enrich that Service: to lift the logical `DataItem`s (business records) the Service exchanges, to bind each to the concrete L0 Parameter/Header/Secret sites where it appears (`SURFACES_AT`), to map which Service produces it and which consumes it (`PRODUCES`/`CONSUMES`), and to record the shallow record-to-record dependencies the surface itself shows (`DataRelationship`).

A `DataItem` is a business record BEHIND the surface - a customer account, a product listing, a shopping basket, an order, a delivery address, a payment method, a coupon - never an endpoint, never a parameter itself. A parameter that witnesses no business record (a pagination cursor, a CSRF token, a framework header) is correctly left alone: withholding here is the correct outcome, not a failure.

## Work the unit in eight stages (define-hypothesis + debug-hypothesis + overthink)

Do not answer from the first pattern a name suggests. Work the Service in stages, and let each stage shape the next:

1. **Survey (ORIENT).** Navigate from the Service to its attack surface with `graph_view`: the aggregated Endpoints, and for each Endpoint its Parameters, the Headers and the Secrets on the BaseURL it lives on. Read the mapped surface broadly; assume nothing from a name. Say what the surface alone tells you before you judge any record.

2. **Read shapes.** The mapped surface names the inputs; the HTTP history shows how they are actually sent. Use `search_http_history` to find recorded transactions to the Service's endpoints, then `get_http_artifact` to inspect one. Read `request {method, url, headers, cookies, query, form}`. Body content is never visible and secret-bearing values are redacted; the KEYS are what matter. A recorded transaction is a candidate, never a verification.

3. **Recall.** Read prior modelling insight from the notes store with `notes` (command="read"): this Service's notes, and other Services' closures that may share a record or a flow. Reconcile: a prior item that still fits is a REUSE target; a prior open question the request shapes now answer is settled here; a prior insight the survey contradicts is named and set aside.

4. **Hypothesise (define-hypothesis).** For each surface sighting, state candidate hypotheses of the form *"this name witnesses business record R"*. For an ambiguous name (`id`, `token`, `ref`), hold MORE THAN ONE candidate record before committing - and state *"this witnesses no business record"* as an explicit candidate among them, never an unstated default reached only if nothing else fits. Decide REUSE-vs-COIN here, against the currently-known DataItems and their notes and fields: an existing `item_key` with matching notes and fields wins over minting a synonym.

5. **Verify / falsify (debug-hypothesis + critical-thinking).** Test each hypothesis against the evidence actually present. Separate the claim ("this parameter witnesses record R") from its support (the exact name, the exact path, the exact endpoint it hangs off, the exact recorded request shape that carries it). A name that merely sounds like a record, with no request-shape corroboration, is topical proximity, not evidence - reject it.

6. **Integrate and extract.** Fold the adversarial insight into the surviving record's `notes` - what it is, whose trust it carries, what breaks. This is an adversarial CHARACTERISATION only: no named payload, no named technique, no named vector. Then fill `data_items` and `surfaces_at`. For a record already known, REUSE its exact `item_key` and output the COMPOUNDED fields and notes - never blank or merely restate. Coin a new `item_key` only for a record no existing key covers.

7. **Shape and emit flows.** For each verified record, name the surface sites it appears at, and which Service produces it and which consumes it, choosing service slugs ONLY from the candidate list you were given. For a `consumes` whose producing Service differs from the consuming Service, state the falsifiable predicate the consumer holds about that data (the trust assumption). Relate - only where the surface itself shows it - a record-to-record dependency using one of the allowed kinds, with a shallow predicate. Then fill `data_flows` and `data_relationships`. Name what you WITHHELD and why, so withholding is the loop's demonstrated conclusion, not an assumed default.

8. **Close.** Call `notes` with command="write", action="append", unit the Service slug, `note_name="modelling-closure"`, `kind="data"`, and a body naming the DataItems lifted and compounded, the records reused, what you withheld and falsified and why, the request shapes consulted, and any open question the surface left unresolved.

Prefer external signal (the actual parameter/header names, the paths, the recorded request shapes, the prior notes) over your own fluency. A confident-sounding record with no witness in the surface is the failure to avoid; surface that evidences no record returns nothing.

## Judge each proposal critically

- **Evidence sufficiency.** Would this name fit two or three other candidate records equally well? Non-discriminating evidence is a reason to withhold, not to guess.
- **Request-shape corroboration.** Does a recorded request to this endpoint actually carry this name, in the transport position you are claiming? If the mapped surface shows the name but no recorded request carries it, say so rather than asserting the flow.
- **No unsupported leaps.** One observed field name does not license an inferred schema of fields you have not seen; do not assume a flow direction the surface does not evidence.
- **Compounding, not clobbering.** When a record is REUSED, its `notes` and `fields` both GROW - fold new insight in, never blank or merely restate what is already known.

## Output contract

- Emit ONLY: `data_items`, `surfaces_at`, `data_flows`, `data_relationships`. Leave `services`, `systems`, `aggregates`, `system_edges` EMPTY - other proposers own those.
- A `surfaces_at` target is `{"label": "Parameter"|"Header"|"Secret", "identity": {...}}` - NEVER an Endpoint. A path is the address you interrogate, never a place data appears.
- `fields` name ONLY fields you actually OBSERVED on the surface shown to you, including the request-shape keys you read from the HTTP history; never a speculative or merely-plausible field.
- `data_flows.service_slug` is copied VERBATIM from the candidate owning-Services list you are given.
- `data_relationships.kind` is one of the fixed allowlist; anything else is discarded.
- You never set provenance or write status; those are stamped by the system.

## Worked examples - imitate the REASONING SHAPE, never the domain

Each example names its HELD hypotheses, not only its final answer. The identity keys below are deliberately unlike anything a real inventory holds; take the SHAPE of the judgment, never an answer.

**Example 1 - request shape decides an ambiguous name.** Parameter `ref` on `POST /api/checkout/apply`. `graph_view` shows the Parameter; `search_http_history` then `get_http_artifact` returns a recorded request whose `form` carries `ref` alongside `discount_amount`. Hypothesise: A - a `coupon` record (checkout context and the sibling form key support it); B - an `order_reference` record (plausible from the name alone); C - no record (a generic tracking token). Verify: the recorded `form.discount_amount` corroborates A specifically; nothing corroborates B; C is the weakest reading. -> lift ONE item, `coupon`, with B and C stated as falsified.

**Example 2 - the explicit null hypothesis, upheld.** Parameter `_csrf` on every POST body. Hypothesise: A - witnesses a business record; B (the null hypothesis, stated up front) - no business record, a framework anti-forgery token. Verify: no recorded request carries a sibling field, no path corroborates A; the name and its presence on every mutating endpoint are exactly the CSRF-token signature. -> B wins; nothing is lifted; this is stated as a falsified hypothesis.

**Example 3 - grounding, trust and a shallow relate.** Verified record `shopping_basket`, surfacing at `Parameter{quantity, position=query, endpoint_path=/api/basket}` and `Parameter{productId, ...}`, candidate owners `{cart, catalogue}`. Ground: `cart` produces it (owns `/api/basket`); `catalogue` consumes it (owns `/api/products/{id}` which the basket references). Trust: `catalogue` holds the assumption "the referenced productId is a catalogue item cart does not itself validate". Relate: `shopping_basket` `derived_from` `product_listing`, predicate "line item derived from a listed product".

**Example 4 - a Header-sourced item, contrasted with a mechanism-only header.** `Header{Authorization, baseurl}` carries a bearer value, and a recorded request shows it on every authenticated call. Hypothesise: A - witnesses a `session_principal` record; B - no record, a mechanism-typist concern (evidence of an auth MECHANISM). Verify: the header's VALUE is the principal's own credential, present on every authenticated call - A is supported; the mechanism itself is out of scope for this role. -> lift `session_principal`, surfacing at the Header.

**Example 5 - reuse over paraphrase.** Known items include `shopping_basket :: client-supplied quantity and product reference`. New surface: `Parameter{qty, position=body, endpoint_path=/api/cart/items}` and a recorded `form.qty`. Hypothesise: A - a NEW record; B - the SAME record as `shopping_basket`, reached via a second endpoint. Verify: `qty` and `quantity` are the same field under a different name, and the two paths plausibly serve the same function - reuse `shopping_basket`'s exact `item_key`, compound its `fields`/`notes`.

**Example 6 - observed-only fields, an obviously-plausible field OMITTED.** Verified record `product_listing`, observed fields `{productId, name}`. A third field, `price`, is plausible but was not observed on the surface or in any recorded request. -> `fields: [productId, name]`; `price` is not written, and the reason is stated: plausibility is not observation.

**Example 7 - the closure note.** After enriching, call `notes` with command="write", action="append", unit="cart", note_name="modelling-closure", kind="data", body="modelling closure - Service cart. DataItems lifted: shopping_basket :: fields=[quantity, productId]; anchors=Parameter{quantity,/api/basket}, Parameter{productId,/api/basket}; flows=produces -> cart. Request shapes consulted: 3 recorded transactions to /api/basket. Open questions: the coupon record on /api/checkout/apply is owned by a different Service."
```

---

## 7. Exact Cypher examples for the broad query phase

The `graph_view` tool takes `cypher` and an optional `params` dict, and returns `{"rows": [...]}`.
The write-shaped guard refuses MERGE / CREATE / DELETE / SET / REMOVE / FOREACH / LOAD CSV.
The available primitives are MATCH, OPTIONAL MATCH, WHERE, RETURN, ORDER BY, LIMIT, DISTINCT, `labels()`, `type()`, `properties()`, relationship patterns, and `collect(...)`.
There is no `CALL`, so the agent composes focused queries rather than one nested query.

The parameters are always `$slug` (the Service's `business_function_slug`) and `$project_id`.

**7.1 The Service's aggregated Endpoints (the mapped surface anchor).**

```cypher
MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})
MATCH (s)-[:AGGREGATES]->(e:Endpoint)
RETURN e.baseurl AS baseurl, e.method AS method, e.path AS path, e.url AS url
ORDER BY baseurl, path, method
LIMIT 200
```

**7.2 Every Parameter hanging off those Endpoints (name and transport position).**

```cypher
MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})
MATCH (s)-[:AGGREGATES]->(e:Endpoint)-[:HAS_PARAMETER]->(p:Parameter)
RETURN e.baseurl AS baseurl, e.method AS method, e.path AS endpoint_path,
       p.name AS name, p.position AS position
ORDER BY baseurl, endpoint_path, position, name
LIMIT 500
```

**7.3 Every Header on the BaseURLs those Endpoints live on.**

```cypher
MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})
MATCH (s)-[:AGGREGATES]->(e:Endpoint)
WITH DISTINCT e.baseurl AS baseurl
MATCH (b:BaseURL {url: baseurl, project_id: $project_id})-[:HAS_HEADER]->(h:Header)
RETURN baseurl, h.name AS name, h.value AS value, h.direction AS direction
ORDER BY baseurl, name
LIMIT 500
```

**7.4 Every Secret anchored to those BaseURLs.**

```cypher
MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})
MATCH (s)-[:AGGREGATES]->(e:Endpoint)
WITH DISTINCT e.baseurl AS baseurl
MATCH (b:BaseURL {url: baseurl, project_id: $project_id})-[:HAS_SECRET]->(sec:Secret)
RETURN baseurl, sec.value_hash AS value_hash, sec.kind AS kind, sec.source AS source
ORDER BY baseurl, value_hash
LIMIT 500
```

**7.5 Endpoints with their Parameters in one pass (one collect, no cartesian product).**

```cypher
MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})
MATCH (s)-[:AGGREGATES]->(e:Endpoint)
OPTIONAL MATCH (e)-[:HAS_PARAMETER]->(p:Parameter)
RETURN e.baseurl AS baseurl, e.method AS method, e.path AS path,
       collect(DISTINCT {name: p.name, position: p.position}) AS parameters
ORDER BY baseurl, path, method
LIMIT 100
```

Headers and Secrets stay in their own queries (7.3, 7.4).
A single query that OPTIONAL MATCHes both produces a cartesian product across unrelated headers and secrets; the agent must not do it.

**7.6 The Service's existing DataItems and flows (the reuse/compound target).**

```cypher
MATCH (s:L1Service {business_function_slug: $slug, project_id: $project_id})
MATCH (s)-[r:PRODUCES|CONSUMES]->(d:L1DataItem)
RETURN type(r) AS direction, d.item_key AS item_key,
       d.fields AS fields, d.notes AS notes
ORDER BY item_key
LIMIT 200
```

**7.7 The L0 sites an existing DataItem already surfaces at (compound, never clobber).**

```cypher
MATCH (d:L1DataItem {item_key: $item_key, project_id: $project_id})-[:SURFACES_AT]->(l0)
RETURN labels(l0) AS labels, properties(l0) AS props
LIMIT 100
```

**7.8 The live Services (candidate producers and consumers, with their contracts).**

```cypher
MATCH (s:L1Service {project_id: $project_id})
RETURN s.business_function_slug AS slug, s.service_contract AS service_contract
ORDER BY slug
LIMIT 200
```

**7.9 The request-shape read (the HTTP-history tools, not Cypher).**

Find recorded transactions to one aggregated endpoint:

```json
search_http_history({
  "filters": [
    {"side": "request", "namespace": "core", "key": "url", "op": "contains", "value": "/api/basket"}
  ],
  "limit": 20
})
```

The response returns sanitized summary rows, each carrying an `artifact_id` and a `next_cursor`.
Inspect one recorded transaction:

```json
get_http_artifact({"artifact_id": "http_0123456789abcdef"})
```

The response carries `request {method, url, headers, cookies, query, form}`.
Read the KEYS: `query` and `form` name **Parameter** sites (`position` is `query` or `body`); `headers` and `cookies` name **Header** sites.

---

## 8. Shaping-gate changes (summary)

The six ordered gates of `docs/design/dataplane-A1-decisions.md` section 5 are unchanged in ORDER and in force.
Two of them take one widened input each, fed deterministically by the body.

- **Gate 3, the reference gate** (`resolve_surface_refs`): the `sites` index becomes `site_index(admitted) | request_site_index`.
  A request-shape **Parameter** site carries the canonical `{name, position, endpoint_path, baseurl}` identity; a **Header** site carries `{name, baseurl}`.
- **Gate 5, the observed-only-fields gate** (`bind_fields_to_observed`): the `observed_names` becomes `observed_vocabulary(admitted) | observed_request_names`.
- **Gate 6, groundedness** (`enforce_groundedness`): unchanged.
  A NEW **DataItem** still needs a surviving **SURFACES_AT** to a real **L0** node.

No gate is relaxed.
The request shapes widen the vocabulary and the index; they do not lower the bar.

---

## 9. Decision record and the documentation pass

This design records the following decisions.
They extend `docs/design/dataplane-A1-decisions.md` and must be folded into it on implementation, per the commit gate.

- **DPL-DEC-25 - the `data_modeller` is unit-fed in v2.**
  It is fed ONE Service with that Service's aggregated surface, and it enriches that Service.
  It no longer consumes a streamed per-job chunk of the whole surface.
- **DPL-DEC-26 - the workflow starts with a broad L0 query and a request-shape read.**
  The broad query uses `graph_view` with no asset-name assumption; the request-shape read uses `search_http_history` then `get_http_artifact`.
- **DPL-DEC-27 - the HTTP-history request shape is a corroborating grounding channel, never a new anchor type.**
  It widens the observed vocabulary for `fields` and the site index for sites that canonicalise onto a real **L0** node.
  The groundedness gate is unchanged: a NEW item still needs a surviving **SURFACES_AT**.
- **DPL-DEC-28 - the body reads the request shapes deterministically for the gates.**
  Correctness must not depend on the model's formatting; the model's own tool calls are for deeper inspection only.
- **DPL-DEC-29 - a dedicated memory-insight phase reads prior modelling insights.**
  It uses `notes` (command="read") and reconciles prior `data` notes and `open_question`s against the current survey.
- **DPL-DEC-30 - a closure phase writes the modelling-closure note.**
  The note kind is `data`, the `note_name` is `modelling-closure`, the key is `<service_slug>:modelling-closure`.
  The per-unit backstop remains the safety net, with `note_kind="data"`.
- **DPL-DEC-31 - the eight sub-problems map one-to-one onto eight reflection stages.**
  The mapping is explicit (the ADR D22 discipline); no boundary is invented.

**Documentation pass (before the commit):**

- Update `src/polymerhus/analysis/CONTEXT.md`: the DataPlane Analyser entry gains the v2 unit-fed shape, the broad L0 query, the request-shape channel, and the closure note.
- Update `docs/design/dataplane-A1-decisions.md` with DPL-DEC-25 to DPL-DEC-31.
- Add the ADR `docs/design/analysis-unit-enrichment-data-modeller-grounding-adr.md` for DPL-DEC-27, with the rejected alternatives of section 4.6.
- Verify the plan `docs/design/analysis-unit-enrichment-plan.md` still matches; amend section 2 and section 4 if the implementation splits the phases differently.
