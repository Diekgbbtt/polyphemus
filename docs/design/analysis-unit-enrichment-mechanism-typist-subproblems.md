# Design: the mechanism-typist reasoning workflow (analysis-unit enrichment v2)

*Status: design document, 2026-10-11. Worktree `polymerhus-unitv2`, branch `feat/analysis-unit-enrichment`.*
*Owning plan: `docs/design/analysis-unit-enrichment-plan.md`. Owning spec: `docs/design/service-sourced-analysis-spec.md` section 3. Owning ADRs: D22 (sub-problems map onto the reflection stages), D23/D24 (Claim and verbatim injection), D26/D34 (constant tool set), D19 (first-definer description compounding).*

This document specifies the REASONING WORKFLOW of the `mechanism_typist` proposer under the v2 analysis-unit-first pipeline.
It is design only.
It does not change Python code.

## 1. Why, and the unit

The bootstrapped L1 is already sufficient on the Services.
It does not map the technical mechanisms each Service relies on.
The `mechanism_typist` ENRICHES a unit by expanding with the Systems the unit rides.

The v2 typist is fed EVERY unit already aggregated to L0 endpoints.
A unit is a Service OR a System.
This supersedes the v1 slice, where the typist received one streamed `service` chunk.

The key changes over the v1 four-sub-problem workflow are:

- A broad L0 query phase at the head, driven by a read-only `graph_view` Cypher tool, with no asset-name assumption.
- A dedicated memory-insight phase that READS prior modelling insights from the `notes` store.
- A closure phase that WRITES one modelling-closure note.
- The unit may be a System, so the workflow handles both unit kinds.

The workflow still emits `L1DeltaBatch{systems, system_edges}` and nothing else.
All System DEEPENING stays Phase B.

## 2. The ordered sub-problems

Seven sub-problems, one `AnalysisTurn` turn each.
Every turn binds the SAME constant tool set `{graph_view, notes, AnalysisTurn}`.
The `emit` field is always a declared `AnalysisTurn` artifact (`claims` for a reasoning turn, a delta list for an extraction turn).

| # | `id` | `name` | covers reflection stage | `emit` | `depends_on` | tools called |
|---|---|---|---|---|---|---|
| 1 | `unit_surface_read` | unit surface read | READ THE UNIT | `claims` | none | `graph_view`, `AnalysisTurn` |
| 2 | `prior_insights` | prior insights | RECALL PRIOR INSIGHTS | `claims` | `unit_surface_read` | `notes` (read), `AnalysisTurn` |
| 3 | `mechanism_hypotheses` | mechanism hypotheses | ORIENT, HYPOTHESISE | `claims` | `unit_surface_read`, `prior_insights` | `AnalysisTurn` |
| 4 | `page_clusters` | page clusters | CLUSTER PAGES | `claims` | `unit_surface_read` | `AnalysisTurn` |
| 5 | `systems_extract` | systems extract | VERIFY-FALSIFY, INTEGRATE | `systems` | `mechanism_hypotheses`, `page_clusters` | `AnalysisTurn` |
| 6 | `link` | link | EMIT | `system_edges` | `systems_extract` | `AnalysisTurn` |
| 7 | `closure` | closure | CLOSE | `claims` | `systems_extract`, `link` | `notes` (write), `AnalysisTurn` |

Base artifacts seeded by the body and available to every `inject`:

- `unit`: the unit identity, its kind (`Service` or `System`), and its description (`service_contract` for a Service, `description` for a System).
- `inventory`: the currently-defined Systems WITH their descriptions, from `read_l1_inventory` (`systems` + `system_descriptions`).
- `vocabulary`: the controlled vocabularies, from `l1_curator.vocabulary_prompt`.
- `candidates`: the Services that ride or aggregate the unit, with the endpoints each owns (the linking context).

The broad query phase and the memory phase populate `claims`, not free text.
A `Claim` is `{subject, assertion, evidence, verdict}`.
The executor injects each dependency's `claims` VERBATIM from the recorded turn, never from the session trail, so compaction can never evict a dependency (ADR D24).

### 2.1 `unit_surface_read` - unit surface read

The broad L0 query phase.

**Reflection prose (the questions it must answer).**
Call `graph_view` to READ THE UNIT.
Enumerate the unit's aggregated L0 endpoints broadly, with NO asset-name assumption: do not filter by any path, URL, or parameter name.
If the unit is a Service, its endpoints are reached by traversing `AGGREGATES`.
If the unit is a System, its endpoints are its own `EVIDENCED_BY` fingerprints plus the `AGGREGATES` endpoints of every Service that rides it.
Read every returned endpoint with the response evidence that discriminates a mechanism: `content_type`, `title`, `status_code`, `server`, `content_length`.
Then call `graph_view` again to fetch the triager Observations anchored to those endpoints, matching each observation on its broad anchor (`BaseURL`, `Subdomain`, `Domain`, `IP`, `Service`).
An observation is never anchored on a narrow `Endpoint`, so look it up on the endpoint's owning BaseURL as well.
For each distinct endpoint, emit one Claim: `subject` the endpoint, `assertion` the mechanism evidence you actually read, `evidence` the response fields, `verdict` a tentative mechanism kind or `unknown`.
Read the surfaces the unit SERVE, not the names the unit CARRIES.

**Injected sources:** base `unit`.
**Emitted artifact:** `claims` (one per aggregated endpoint, plus the anchored observation insight).
**Depends on:** none.
**Tools called:** `graph_view` (the enumeration query and the observation query), `AnalysisTurn`.

### 2.2 `prior_insights` - prior insights

The memory-insight phase.

**Reflection prose (the questions it must answer).**
Call the `notes` tool with `command="read"` on the unit slug, so the read returns the unit's prior modelling notes.
Call it again with `body_keyword` set to each mechanism noun the surface read surfaced (for example `auth`, `session`, `api`, `presentation`), so a note that another earlier unit wrote about a shared mechanism is found even when it is keyed by a different unit.
Read every returned note body and record: which Systems an earlier unit already defined or extended, which Services it already linked, and which questions it left open.
Do not re-derive a mechanism an earlier unit already characterised; reuse that characterisation.
For each reusable insight, emit one Claim: `subject` the prior unit or note key, `assertion` the inherited insight, `evidence` the note key, `verdict` `reuse` or `supersede`.

**Injected sources:** base `unit`; dependency `unit_surface_read`.
**Emitted artifact:** `claims`.
**Depends on:** `unit_surface_read` (so the keyword search is seeded by the mechanisms just read).
**Tools called:** `notes` (`command="read"`), `AnalysisTurn`.

### 2.3 `mechanism_hypotheses` - mechanism hypotheses

ORIENT and HYPOTHESISE.

**Reflection prose (the questions it must answer).**
ORIENT: what technical mechanisms could this unit's surface plausibly evidence?
Read each endpoint with its adversarial observation claim AND its response evidence.
What a path SERVES outweighs what its name suggests: an API-looking path returning `text/html` is a client-routed web-presentation view, not a REST endpoint.
HYPOTHESISE: for each endpoint plus observation, define candidate hypotheses of the form: "this endpoint impacts a System of kind K - newly defined, OR extending currently-defined System X".
Hold more than one candidate kind for an ambiguous endpoint.
Carry forward every prior insight from the memory phase as a constraint or a candidate.
For each endpoint plus observation, emit one Claim: `subject` the endpoint, `assertion` the candidate System kind and whether it is new or an extension, `evidence` the response evidence you read, `verdict` new-vs-extend against the exact defined System key.

**Injected sources:** base `unit`, `inventory`, `vocabulary`; dependency `unit_surface_read`, `prior_insights`.
**Emitted artifact:** `claims`.
**Depends on:** `unit_surface_read`, `prior_insights`.
**Tools called:** `AnalysisTurn`.

### 2.4 `page_clusters` - page clusters

CLUSTER PAGES.

**Reflection prose (the questions it must answer).**
Among the NAVIGABLE `text/html` pages only (content type `text/html`; exclude API, XHR, and JSON responses and static assets), group the pages by rendered similarity: shared title, structure, and size.
A templated set (for example many product pages) is ONE cluster.
A single not-found or error page is ONE cluster, not many.
Note which Service each cluster serves.
Each `(service, cluster)` is one WebPresentation.
For each `(service, cluster)`, emit one Claim: `subject` the service, `assertion` the cluster and its member page paths, `evidence` the shared title, structure, and size, `verdict` the short cluster slug.

**Injected sources:** base `unit`; dependency `unit_surface_read`.
**Emitted artifact:** `claims`.
**Depends on:** `unit_surface_read`.
**Tools called:** `AnalysisTurn`.

### 2.5 `systems_extract` - systems extract

VERIFY-FALSIFY and INTEGRATE.

**Reflection prose (the questions it must answer).**
VERIFY and FALSIFY: test each hypothesis against the evidence actually present.
A framework fingerprint alone is NOT the mechanism in use.
Separate the claim ("System K exists and overlays service S") from its support (the specific header, path, technology, or observation).
Decide new-versus-extend against the currently-defined Systems listed, by their EXACT key.
INTEGRATE the adversarial observation insight into the surviving System's characterisation: what makes that mechanism attackable.
Emit ONE `systems` entry for EACH verified mechanism: a known `kind` with a `discriminator` (default `__singleton__`) and a `description` prop in `props`.
For a System already listed, REUSE its exact key and output an ENRICHED description that folds the new insight in; never blank it, never merely restate it.
A WebPresentation is PER `(service, page-cluster)`: set `discriminator` to `<business_function_slug>::<cluster>` and put the cluster's member `text/html` page paths in a `pages` list in `props`.
Do NOT deep-profile (no rendering or navigation model, no authorization pyramid).

**Injected sources:** base `unit`, `inventory`, `vocabulary`; dependencies `mechanism_hypotheses`, `page_clusters`.
**Emitted artifact:** `systems`.
**Depends on:** `mechanism_hypotheses`, `page_clusters`.
**Tools called:** `AnalysisTurn`.

### 2.6 `link` - link

EMIT.

**Reflection prose (the questions it must answer).**
Connect each System above to the Service or Services it overlays, choosing the exact edge label from `SYSTEM_EDGE_RELS`.
`EXPOSED_VIA` a REST or GraphQL API, or a WebPresentation page-cluster: copy its `<service>::<cluster>` discriminator VERBATIM so the edge hits the right node.
`FRONTED_BY` / `PROTECTED_BY` / `ROUTED_BY` a perimeter.
`IDENTIFIED_BY` / `AUTHENTICATED_BY` / `AUTHORIZED_BY` the identity Systems.
`SHAPES_DATA_OF` the integration System.
Copy each `service_slug` VERBATIM from the candidates block, and prefer the Services that already ride or aggregate this unit.
Emit one `system_edges` entry per `(service, System)` pair with its `rel`.
Leave every other list EMPTY.

**Injected sources:** base `unit`, `candidates`; dependency `systems_extract`.
**Emitted artifact:** `system_edges`.
**Depends on:** `systems_extract`.
**Tools called:** `AnalysisTurn`.

### 2.7 `closure` - closure

CLOSE.

**Reflection prose (the questions it must answer).**
Summarise the unit's outcome: which Systems were DEFINED, which were EXTENDED, and which Service->System edges were linked.
Name each piece of evidence the typing rests on.
Name each mechanism you could not decide, and why.
Call the `notes` tool once with `command="write"`, `action="append"`, `kind="system"`, `note_name="modelling-closure"`, and the body rendered from the template in section 4.
Then emit one Claim: `subject` the unit, `assertion` the count of Systems defined and extended, `evidence` the note key, `verdict` `closed`.
The note is the durable record a later unit reads; write it even when the typing found no System, so the unit's coverage stays auditable.

**Injected sources:** base `unit`; dependencies `systems_extract`, `link`.
**Emitted artifact:** `claims`.
**Depends on:** `systems_extract`, `link`.
**Tools called:** `notes` (`command="write"`), `AnalysisTurn`.

## 3. Define-new versus extend-existing, and Service->System linking

### 3.1 The identity key

A System is keyed on `(project_id, kind, discriminator)`.
The rendered key is `kind` for a singleton (`discriminator == __singleton__`), else `kind:discriminator`.
This is the same render rule `l1_inventory._render_system` uses via `l1_types.elide_singleton`, so a key computed in the workflow matches the inventory's `systems` list exactly.

### 3.2 The discriminative `description` rule

The System-side discriminative attribute is the `description` prop.
The workflow reads the currently-defined Systems WITH their descriptions from `inventory`.
The decision rule is:

- Compute the candidate key `_system_key(kind, discriminator)`.
- If the exact key is present in `inventory.systems`, EXTEND that System: reuse the exact key, and emit an ENRICHED `description` that folds the new insight into the existing description from `inventory.system_descriptions`. Never blank it, never merely restate it.
- If the exact key is absent, DEFINE a new System with a fresh adversarially-oriented `description`.
- WebPresentation is always per `(business_function_slug, cluster)`: its discriminator is `<business_function_slug>::<cluster>`. Define-new per cluster unless that exact key exists, then extend that cluster's description. Never emit a `__singleton__` WebPresentation when a discriminated one exists.

### 3.3 First-definer compounding (ADR D19)

A System's description is compounded only by the Service that FIRST defines it.
A Service that finds the System already present in the live inventory must not overwrite its description.
The body applies `strip_recompounded_descriptions` with `existing_keys` drawn from `inventory.systems`, so such a Service's batch drops the description and the writer's `SET += props` leaves the existing one intact.
A System not yet defined keeps its description, so the one authorised compounding still happens.
This rule is inert on the streamed default, where `existing_keys` is empty.

### 3.4 Service->System linking

The linking sub-problem emits `SystemEdgeProposal{service_slug, kind, discriminator, rel}`.
The `rel` is chosen by the mechanism class:

- `EXPOSED_VIA`: `WebPresentation`, `RESTApi`, `GraphQLApi`.
- `FRONTED_BY` / `PROTECTED_BY` / `ROUTED_BY`: `CDN`, `WAF`, `ReverseProxy`, `APIGateway` (the perimeter).
- `IDENTIFIED_BY`: `IdentificationSystem`.
- `AUTHENTICATED_BY`: `AuthenticationMechanism`.
- `AUTHORIZED_BY`: `AuthorizationSystem`.
- `SHAPES_DATA_OF`: `IntegrationSystem` (CSP / CORS).
- `ON_REQUEST_PATH` / `DEPENDS_ON`: remaining System placement.

The `candidates` base artifact bounds the `service_slug` values: the Services that ride or aggregate the unit.
When the unit is itself a System, the `service_slug` is the Service that rides that System, resolved by `graph_view` in the surface phase and carried in `candidates`.
The deterministic repair `_reconcile_webpresentation` still runs after the two structured turns: it drops any `__singleton__` WebPresentation, snaps a singleton or blank WebPresentation edge to the real per-cluster node of its own service when unambiguous, and coerces a mislabelled WebPresentation edge back to `EXPOSED_VIA`.

## 4. The modelling-closure note

The closure sub-problem writes ONE note through the shared `notes` tool.
The note is keyed `<unit>:modelling-closure`.

- `kind`: `system` (from `NOTE_KINDS` = `assignment`, `system`, `data`, `refusal`, `open_question`). The typist's concern is Systems, so `system` is the correct kind. No phase-3 hunting vocabulary is used.
- `note_name`: `modelling-closure`.
- `unit`: the unit slug for a Service, or the System key (`kind` or `kind:discriminator`) for a System unit.
- `evidence`: the compact list of L0 anchors and Observation refs the typing rests on.
- `body` template:

```
unit: <unit identity>
unit_kind: <Service | System>
outcome: <typed | withheld>
systems_defined:
  - <kind>[:<discriminator>] - <description>
systems_extended:
  - <kind>[:<discriminator>] - <compounded description>
edges:
  - <service_slug> -<REL>-> <kind>[:<discriminator>]
evidence:
  - <L0 anchor or Observation ref>: <what it witnesses>
open_questions:
  - <a mechanism left undecided, and why>
```

The per-unit backstop `ensure_unit_note` remains the coverage guarantee: it writes ONE `open_question` note for the unit when the workflow wrote none. The workflow passes `note_kind="system"` where a kind is needed, so a backstop on this role carries the modelling concern the role owns.

## 5. The full updated role prompt

The role prompt lives at `src/polymerhus/analysis/prompts/technical-system.md`.
It is bound once as the agent's ephemeral leading block through `system_prompt=`, so it never enters the checkpointed trail.
The full updated text follows.

```markdown
You are the **TechnicalSystem mechanism-typist** under the analysis-unit-first pipeline. Your job is to reconstruct, **at breadth**, the cross-cutting technical **`System`s** that one **unit** rides, and to link them to the Services that lie on them.

A **unit** is either a **Service** (a business target) or a **System** (a mechanism already mapped). You are fed one unit at a time. If the unit is a Service, you expand it with the Systems it rides. If the unit is a System, you expand it with the Systems that System itself rides, and you link the result back to the Services that ride it.

A `System` is a **mechanism**: a cross-cutting technical capability many Services share regardless of business function (a WAF, a CDN, a reverse proxy, an API gateway, a REST or GraphQL API paradigm, an identification/session system, an authentication mechanism, an authorization system, a CSP/CORS integration system, a web-presentation channel). A `Service` is a business function; you never emit Services, you never mint a Service, and you never store a mechanism fact as a Service property - a mechanism is a `System`, reached by a typed `Service->System` edge.

You do not test, exploit, or execute anything, and you do **not deep-profile** (no rendering/navigation model, no authorization pyramid - a later phase owns those). You reconstruct *which mechanisms exist, which Services they overlay, and which Systems a System rides*.

## Work in order, and read before you reason

1. **Read the unit broadly.** Query the aggregated L0 endpoints of the unit with NO asset-name assumption. Do not filter by any path, URL, or parameter name. If the unit is a Service, its endpoints are reached by `AGGREGATES`. If the unit is a System, its endpoints are its own `EVIDENCED_BY` fingerprints plus the `AGGREGATES` endpoints of every Service that rides it. Read each endpoint together with the response evidence that discriminates a mechanism: content type, title, status code, server, content length. Then fetch the triager Observations anchored to those endpoints, matching on the broad anchors (`BaseURL`, `Subdomain`, `Domain`, `IP`, `Service`) - an Observation is never anchored on a narrow Endpoint, so look it up on the endpoint's owning BaseURL too.
2. **Recall prior insights.** Read the unit's prior modelling notes, and search the notes by the mechanism nouns the surface surfaced. Reuse a mechanism an earlier unit already characterised; never re-derive it. Carry forward what is still open.
3. **Orient.** What technical mechanisms could this unit's surface plausibly evidence? What a path SERVES outweighs what its name suggests.
4. **Hypothesise (define-hypothesis).** For each endpoint plus observation, state candidate hypotheses of the form: *"this endpoint impacts a System of kind K - either newly defined, or extending currently-defined System X."* For an ambiguous endpoint, hold more than one candidate kind before committing (a `Server:` header could evidence a reverse proxy, a CDN, or a WAF).
5. **Cluster pages (WebPresentation).** Among the navigable `text/html` pages only, group pages by rendered similarity into clusters - a templated set or a single not-found page is ONE cluster, not many. Each `(service, cluster)` is one WebPresentation.
6. **Verify / falsify (debug-hypothesis + critical-thinking).** Test each hypothesis against the evidence actually present. A framework fingerprint alone is *never* the mechanism-in-use. Separate the claim from its support. Decide **new-vs-extend** against the currently-defined Systems you were given: reuse an existing System's exact key rather than minting a synonym.
7. **Integrate the adversarial insight.** Fold each surviving observation's insight into that System's **`description`**.
8. **Emit.** Report the verified **new** and **extended** Systems and their descriptions, then link each to the Service(s) it overlays with the exact edge label.
9. **Close.** Write one modelling-closure note for the unit, and state what you could not decide.

Prefer external signal (the actual headers, technologies, status codes, observations) over your own fluency. A confident-sounding System with no witness in the slice is the failure to avoid; a unit evidencing no mechanism returns nothing.

## Judge each proposal critically

- **Evidence sufficiency.** Is the signal *necessary and specific* to this mechanism, or would it fit three others equally? Weak, non-discriminating evidence is a reason to withhold, not to guess.
- **Surface hidden assumptions.** What must hold for this System to exist? If unverified, say so and prefer the broader, safer reading.
- **No unsupported leaps.** Do not infer an API paradigm from a URL shape alone; do not treat "the tech exists" as "the Service uses it this way."
- **No asset-name assumptions.** A path noun is never evidence; what the endpoint serves is.

## The define-versus-extend rule (the discriminative description)

- Key a System on `(kind, discriminator)`: `kind` for a singleton, else `kind:discriminator`.
- If that exact key is in the currently-defined Systems, EXTEND it: reuse the exact key, and output an ENRICHED `description` that folds your new insight INTO the existing one - never blank it, never merely restate it.
- If that exact key is absent, DEFINE a new System with an adversarially-oriented `description`.
- A WebPresentation is always per `(service, page-cluster)`: set `discriminator` to `<business_function_slug>::<cluster>` and put the cluster's member `text/html` page paths in a `pages` list in `props`. Never emit a `__singleton__` WebPresentation, and never one per raw URL.
- Only the Service that FIRST defines a System compounds its description. If the System is already listed, do not overwrite its description.

## Output contract

- Emit typed proposals only: `systems` (a known `kind` + `discriminator` default `__singleton__`, with a `description` in `props`) and `system_edges` (service_slug + System kind + the exact `rel`). Leave `services`, `aggregates`, and all data lists EMPTY - dedicated proposers own those.
- Edge labels are exactly: `EXPOSED_VIA` (REST/GraphQL API, or a WebPresentation page-cluster), `FRONTED_BY` / `PROTECTED_BY` / `ROUTED_BY` (perimeter: CDN / WAF / reverse proxy / gateway), `IDENTIFIED_BY` (session/cookie identification), `AUTHENTICATED_BY` (authentication mechanism), `AUTHORIZED_BY` (authorization system), `SHAPES_DATA_OF` (CSP/CORS integration), `ON_REQUEST_PATH` / `DEPENDS_ON` (remaining placement). Copy each `service_slug` verbatim from the candidates block.
- You never set provenance or write status; those are stamped by the system. Return empty lists if the unit supports no confident System - an honest empty result is correct; a fabricated one is a defect.

## Worked examples - imitate the REASONING SHAPE, never the domain

**Example 1 - a session cookie (define IdentificationSystem).** Asset: a response `Set-Cookie: sid=…; HttpOnly`. Observation insight: "session id in a cookie, no `Secure` flag." Hypothesise: this evidences an identification/session System. Verify: the cookie is the direct witness. Type: new `IdentificationSystem`, description notes "cookie-based session, missing Secure flag → interceptable over cleartext"; link `IDENTIFIED_BY`.

**Example 2 - a login challenge (define AuthenticationMechanism).** Asset: `WWW-Authenticate: Bearer` on a 401. Observation: "token-based auth challenge." Type: new `AuthenticationMechanism`, "bearer-token auth; token handling is the trust seam"; link `AUTHENTICATED_BY`.

**Example 3 - an edge header (perimeter, disambiguate the kind).** Asset: `Server: cloudflare`, `CF-RAY: …`. Hypothesise BOTH a CDN and a WAF. Verify: `CF-RAY` witnesses the edge network (CDN) specifically; no rule-block evidence for a WAF. Type: new `CDN`, "Cloudflare edge fronting origin; origin IP may be reachable directly"; link `FRONTED_BY`. Withholding the unproven WAF is the correct move.

**Example 4 - a GraphQL endpoint (API paradigm).** Asset: `POST /graphql`, technology "Apollo". Type: new `GraphQLApi`, "single GraphQL surface; introspection/aliasing are the levers"; link `EXPOSED_VIA`.

**Example 5 - EXTEND an existing System (compounding).** Currently-defined: `AuthenticationMechanism :: bearer-token auth`. New asset this unit: `/oauth/authorize` + `Set-Cookie: idp_session=…`. Hypothesise: this EXTENDS the existing mechanism, not a new one. Type: reuse key `AuthenticationMechanism`, output "bearer-token auth AND an OAuth/IdP authorize flow; token issuance now spans two realms → confused-deputy surface"; link `AUTHENTICATED_BY`.

**Example 6 - a role-gated response (define AuthorizationSystem, no deep pyramid).** Asset: `/admin/users` returns 403 for a normal principal. Type: new `AuthorizationSystem`, "role-gated admin surface; the gate itself is the boundary to probe"; link `AUTHORIZED_BY`. Stop at existence plus linkage.

**Example 7 - a System unit that rides another System.** The unit is the System `WebPresentation:checkout::checkout-form`. Its aggregated endpoints are `text/html` pages that carry a session cookie and sit behind a `Server: nginx` edge. Hypothesise: this WebPresentation rides an `IdentificationSystem` and is fronted by a `ReverseProxy`. Verify against the cookie and the `Server` header. Type: extend `IdentificationSystem` if listed, define otherwise; link the Services that ride the WebPresentation to both new Systems with `IDENTIFIED_BY` and `FRONTED_BY`.
```

## 6. The broad query phase Cypher

`graph_view` is a read-only Cypher tool.
It accepts a Cypher string and a params map.
It rejects any write clause (`CREATE`, `MERGE`, `SET`, `DELETE`, `REMOVE`, `DROP`, `CALL`) and returns rows.
These are the two queries the broad query phase runs.
They make NO asset-name assumption: neither filters on any path, URL, or parameter name.

### 6.1 Enumerate the unit's aggregated L0 endpoints

For a Service unit, the endpoints are reached by `AGGREGATES`:

```cypher
MATCH (u:L1Service {business_function_slug: $unit, project_id: $project_id})
      -[:AGGREGATES]->(l0)
WHERE NOT l0:Observation
RETURN labels(l0) AS labels, l0 {.*} AS props
ORDER BY labels(l0)[0], props.path
```

For a System unit, the endpoints are the System's own `EVIDENCED_BY` fingerprints plus the `AGGREGATES` endpoints of every Service that rides it:

```cypher
MATCH (u:L1System {kind: $kind, discriminator: $discriminator, project_id: $project_id})
OPTIONAL MATCH (u)-[:EVIDENCED_BY]->(fp)
WHERE NOT fp:Observation
WITH u, collect(DISTINCT fp) AS fingerprints
OPTIONAL MATCH (svc:L1Service {project_id: $project_id})-[r]->(u)
WITH u, fingerprints, collect(DISTINCT svc) AS services
UNWIND (CASE WHEN services = [] THEN [null] ELSE services END) AS svc
OPTIONAL MATCH (svc)-[:AGGREGATES]->(agg)
WHERE NOT agg:Observation
RETURN fingerprints AS fingerprints,
       svc.business_function_slug AS riding_service,
       labels(agg) AS labels, agg {.*} AS props
```

### 6.2 Fetch the triager Observations anchored to those endpoints

An Observation carries no anchor identity itself; the anchor is the other end of the `(anchor)-[:HAS_OBSERVATION]->(Observation)` edge.
Anchors are restricted to the broad nodes (`Domain`, `Subdomain`, `BaseURL`, `IP`, `Service`), and a narrow finding is re-anchored UP to its owning BaseURL.
So the query matches on the endpoint's owning BaseURL as well as on the Service unit itself:

```cypher
MATCH (u:L1Service {business_function_slug: $unit, project_id: $project_id})
OPTIONAL MATCH (u)-[:AGGREGATES]->(e:Endpoint)
WITH collect(DISTINCT e.baseurl) AS baseurls
MATCH (a)-[:HAS_OBSERVATION]->(o:Observation)
WHERE o.project_id = $project_id
  AND a.project_id = $project_id
  AND ( (a:BaseURL   AND a.url IN baseurls)
     OR (a:Endpoint  AND a.baseurl IN baseurls)
     OR (a:Service   AND a.project_id = $project_id) )
RETURN labels(a) AS anchor_labels, a {.*} AS anchor_props,
       o.macro_kind AS macro_kind, o.severity AS severity,
       o.evidence AS evidence, o.rationale AS rationale
ORDER BY o.severity DESC, o.macro_kind
```

### 6.3 Resolve the candidates for a System unit

When the unit is a System, the linking candidates are the Services that ride it.
This query is the `candidates` seed for such a unit:

```cypher
MATCH (svc:L1Service {project_id: $project_id})-[r]->(u:L1System {
        kind: $kind, discriminator: $discriminator, project_id: $project_id})
RETURN DISTINCT svc.business_function_slug AS service_slug,
       type(r) AS rel
ORDER BY service_slug
```

## 7. Constant request shape and the tool set

Every turn of the workflow binds the SAME tool set: `{graph_view, notes, AnalysisTurn}`.
The request shape therefore never toggles, so the provider prefix cache matches across the whole sub-problem chain (ADR D26 / D34).
The structured tool is derived with the native `OutputToolBinding.from_schema_spec`, never a hand-built look-alike.
`notes` is bound through the session `tools=` seam, never the skills seam (ADR D33).
`graph_view` and the http-history tools are per the plan section 3; this role calls only `graph_view` and `notes`.

## 8. Vocabulary anchors

Every term above is anchored in `src/polymerhus/analysis/CONTEXT.md`.

- **Service**: a business target, keyed `(project_id, business_function_slug)`. A Service *claims* surface elements by business function. This workflow never emits one.
- **System**: a mechanism, keyed `(project_id, kind, discriminator)`. A System *overlays* elements that share a mechanism.
- **Membership direction**: partition-by-purpose is a Service, overlay-a-shared-mechanism is a System.
- **Mechanism-as-System**: a mechanism classification is a property of the mechanism-System, never of the target-Service; reached by an edge.
- **kind**: a System's intrinsic identity attribute, validated against `SYSTEM_KINDS`.
- **WebPresentation**: the System kind for the navigable `text/html` pages a Service renders, PER `(service, cluster)`, discriminator `<business_function_slug>::<cluster>`, member paths on a `pages` prop.
- **EXPOSED_VIA**: the edge from a Service to the System that presents it (WebPresentation, a REST or GraphQL API).
- **AUTHENTICATED_BY / AUTHORIZED_BY**: System edges binding a Service to its authentication and authorization mechanisms.
- **AGGREGATES**: the cross-layer assignment edge from a Service to an L0 node.
- **EVIDENCED_BY**: the cross-layer edge from a System to the L0 node that fingerprints it.
- **Observation**: a Recon low-inference, anchored to a broad node; never anchored to an Endpoint.
- **System description (discriminative attribute)**: a System's adversarially-oriented NL `description` prop, compounded by its sole incremental author.
- **Cross-layer edge**: an edge from an L1 node down onto an L0 node; the L0 target is always MATCHed, never MERGEd.
- **Reasoning workflow / SubProblem / AnalysisTurn / Claim**: the role's ordered chain, its one-turn units, the single structured envelope, and the compact judgment a dependency hands forward.
- **Note kind**: the closed L1-modelling enum in `analysis/memory.py`; this role writes `system` and may leave an `open_question`.

## 9. Open questions

- The unit's aggregated-endpoint query for a System unit spans `EVIDENCED_BY` and the `AGGREGATES` of riding Services. The exact bound on that fan-out is a step-1 implementation detail in `analysis/tools.py`.
- The `candidates` seed for a System unit depends on the typist running after the Services that ride it are already linked. The pipeline order must guarantee at least one pass over the Services first; otherwise the System unit's linking candidates are incomplete.
- Whether the broad surface query returns enough for the model without a paginated cursor is deferred to the step-1 tool design.
