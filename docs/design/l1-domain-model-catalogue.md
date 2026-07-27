# Layer-1 Domain Model - Element Catalogue, Audit, and the Mechanism-as-System Correction

*Authoritative reference for the Layer-1 service/system model as built in `agent/recon/analysis/` and `db/neo4j/l1_schema.py`, reconciled with `service-system-model-design_1.md` (the spec) and the operator's 2026-07-19 modelling corrections.
This document supersedes the spec where the two disagree on WHERE a mechanism classification lives (the spec's §5.1 typed-spine table is corrected here), and is the build target for the model-correction work item.
Every element below is grounded in the running code; where the code still reflects the old model the row is marked NEEDS-MIGRATION.*

---

## 0. Operator correction 2026-07-20 - controlled-vocabulary nodes become intrinsic (supersedes L1D-6 for these two)

The operator ratified two corrections that deliberately INVALIDATE `L1D-6` (controlled-vocabulary catalogue nodes) for the two catalogues that had them.
Existing graph data is disposable (re-derived, not migrated).

1. **`SystemKind` becomes a System ATTRIBUTE named `kind`.**
   The `:SystemKind` catalogue node and the `OF_KIND` edge are REMOVED.
   The System's kind now lives as the plain identity attribute **`kind`** on the `:L1System` node.
   **Identity-key decision (applied uniformly):** the identity property was RENAMED `system_kind` -> `kind`, so System identity is `(project_id, kind, discriminator)`.
   The same name `kind` is used everywhere - the Neo4j property, the schema constraint, every Cypher builder, every pydantic delta/proposal field, the curation identity maps, the reads, and the prompts - so there is no dual-naming drift.
   The known kinds are validated against a module-level Python constant (`l1_curator.SYSTEM_KINDS`), the single source of truth; adding a kind is a one-line data edit there, never a migration.

2. **`DataRelationshipKind` becomes the EDGE TYPE.**
   The `:DataRelationshipKind` catalogue node and the generic `DATA_RELATIONSHIP` edge are REMOVED.
   A functional-dependency kind IS the relationship type now, uppercased: `-[:DERIVED_FROM]->`, `-[:EQUALS_HASH_OF]->`, etc.
   Because Neo4j cannot parameterise a relationship type, the value is interpolated into Cypher - so it is guarded by a **FIXED allowlist** (`derived_from`, `reflected_in`, `equals_hash_of`, `copy_of`, `concatenation_of`, `subset_of`) PLUS the `_SAFE_IDENT` identifier check.
   An allowlist miss is a **hard reject** (nothing is written), never a fallback to a generic edge (mirrors how `SYSTEM_EDGE_RELS` is validated).

3. **The missing-systems sweep is redesigned to be stale-L0-asset driven** (§7.2 / `sweep.resolve_stale_owners`).
   The old sweep enumerated `:SystemKind` rows with no instance - which correction 1 removes.
   The new sweep, for each STALE L0 asset (no inbound `AGGREGATES`), asks the analyser LLM which System kind and/or Service it could belong to, grounded PRIMARILY in the existing L1 inventory and SECONDARILY in the known-kinds enumeration.
   It is a fail-open seam (read + prompt + typed result, injected `propose_fn`); it PROPOSES owners and does not yet write them back (that leg is deferred).

Sections 4.2, 4.4, 4.5, 5.2, and 6 below are updated to this corrected model.

---

## 1. The load-bearing principle (what "incomprehension" means here)

A single principle resolves every conflation found in the audit (§3):

> **A cross-cutting mechanism is a `System` node, reached from a `Service` by a typed edge, and it carries its own mechanism attributes as PROPS ON THE SYSTEM.
> A `Service` carries only business-level facets (its business function and its exposure/contract) and NEVER a mechanism classification.**

This is the operator's paradigm stated generally:

> "a service is exposed via (edge) a web-presentation which has rendering and navigation [attributes]".

The failure mode it corrects is storing a mechanism classification (how the UI renders, which API paradigm, which auth method) as a **property of the Service**.
That is wrong for three concrete reasons:

1. **Stage-3 DFS cannot see it.** The attack engineer traverses a Service's System relationships depth-first (spec §8, `DD-4`); a classification stranded as a Service prop is off that traversal, so every signature that branches on it is blind to it.
2. **It duplicates state.** The same fact then exists in two places (the Service prop AND the System kind/edge), which drift apart.
3. **It mis-attributes the adversarial object.** A rendering fault is a fault of the *rendering system*, transferable to every Service that rendering system serves (spec §3.1 identity-by-transfer); pinning it to one Service hides that transfer.

The two dimensions `navigation_model` and `rendering_model` are furthermore **independent** (`L1D-31a`): neither may be inferred from the other (a SPA may use SSR; an MPA may use CSR for a widget).
The old curation code inferred rendering from navigation (SPA -> CSR), which this correction deletes.

---

## 2. The web-presentation correction (the operator's explicit call)

### 2.1 What changes

- **One System, not a kind-per-rendering-mode.** The two seed kinds `RenderingSystem_SSR_UI` and `RenderingSystem_CSR_JSMap` are replaced by a single system kind (`WebPresentation`) that carries BOTH dimensions as independent attributes.
- **The edge is `EXPOSED_VIA`, and `RENDERED_BY` is deleted.** A Service is `EXPOSED_VIA` its web-presentation System exactly as it is `EXPOSED_VIA` a REST/GraphQL API System (the "surfaces through which the Service is reached"). `RENDERED_BY` is removed from the edge taxonomy (`SYSTEM_EDGE_RELS`).
- **Both classifications live on the System as independent props**, each set from its own signals, never inferred from the other.

### 2.2 The term (operator asked for a better word than "webpage")

"Webpage" is wrong for a multi-page app and too narrow for the concept (it is a whole presentation channel, not one page).
The proposed system `kind` is **`WebPresentation`**:

- "Presentation" is the standard architectural name for the layer that both renders views and governs navigation between them (the presentation tier).
- "Web" scopes it to the browser channel (distinct from a REST/GraphQL programmatic exposure).
- It is SPA/MPA/Hybrid-neutral: an MPA and an SPA are both web presentations, differentiated by the `navigation_model` attribute, not by the node's kind.

Alternatives considered and rejected: `Webpage` (a page, not a channel; MPA-ambiguous - the operator's objection), `WebInterface` ("interface" collides with the interface-agreement A/B vocabulary), `WebFrontend`/`WebUI` (colloquially bias toward CSR/SPA), `PresentationTier` (drops the web-channel scoping).

### 2.3 The corrected shape

```
(:L1Service {business_function_slug})
   -[:EXPOSED_VIA]->
(:L1System {kind: "WebPresentation", discriminator: "__singleton__",
            rendering_model: "CSR|SSR|SSG|StreamingSSR|HydratedSSR",
            navigation_model: "SPA|MPA|Hybrid",
            rendering_confidence, rendering_evidence,
            navigation_confidence, navigation_evidence})
```

`rendering_model` and `navigation_model` are set independently by the webpage-profile anatomy skill (which already classifies them independently, `anatomy.py:88-95`); the correction only moves WHERE they are written (System props via the sole-writer, not Service props) and deletes the SPA->CSR inference.

### 2.4 Forward-compat note (Stage-3, out of scope but recorded)

The §9.5 XSS signature keyed its architecture tier on the rendering-system SUB-KIND (`RenderingSystem_CSR_JSMap` -> DOM-XSS vs `RenderingSystem_SSR_UI` -> server-XSS).
Under this correction it reads the `rendering_model` PROP on the `WebPresentation` System instead (a prop read is equivalent to a kind read for the signature, and Stage-3 is out of scope here).
This is the only downstream implication and it is a strict simplification (one system, one prop) not a loss of information.

---

## 3. Audit - every similar conflation found

The web-presentation bug is one instance of storing a mechanism classification on the Service.
Applying the §1 principle across the model surfaces the following.
`_SPINE_KEYS` (`index_card.py:27`) currently lists `api_paradigm, navigation_model, rendering_model, auth_methods, exposure, business_function` as unit spine props; the audit classifies each.

| Spine key | Old (conflated) home | Correct home | Verdict |
|---|---|---|---|
| `business_function` | Service prop (its label/purpose) | Service prop | CORRECT - genuinely a Service-level facet |
| `exposure` (public / authenticated) | Service prop | Service prop (contract facet) | CORRECT - a contract property of the Service, not a mechanism |
| `navigation_model` | Service prop + inferred edge | `WebPresentation` System prop, `EXPOSED_VIA` | NEEDS-MIGRATION (the operator's explicit fix, §2) |
| `rendering_model` | Service prop + `RENDERED_BY` kind | `WebPresentation` System prop, `EXPOSED_VIA` | NEEDS-MIGRATION (§2) |
| `api_paradigm` | Service prop AND the `EXPOSED_VIA -> RESTApi/GraphQLApi` kind | the API System (paradigm IS the kind: `RESTApi` / `GraphQLApi`), reached by `EXPOSED_VIA`; NOT a Service prop | NEEDS-MIGRATION (same conflation: a mechanism duplicated as a Service prop). Keep REST vs GraphQL as SEPARATE kinds - unlike rendering/navigation they are independently-instantiable exposure mechanisms (a Service may expose both) and a finding against one does not transfer to the other (§3.1). |
| `auth_methods` (set) | Service prop | the `AuthenticationMechanism` System, reached by `AUTHENTICATED_BY {realm}` (mechanism = System, `L1D-5`); the Service keeps only its authorization POLICY (`AUTHORIZED_BY {role}`, a contract facet) | NEEDS-MIGRATION (mechanism-as-System; the mechanism/policy split of `L1D-5` already says this - the `auth_methods` Service prop violates it) |

Net principle for the analyser prompt and the curation re-homing: **only `business_function`, `exposure`, and NL contract handles are Service props; `api_paradigm`, `navigation_model`, `rendering_model`, `auth_methods` are System-side and reached by an edge.**

No other node/edge conflations were found: `DataItem` (data as a first-class node, not a Service prop) is correct, and the `AGGREGATES` judgment envelope is correctly on the edge. (The audit also cleared `journeys` as a correctly-shaped light Service membership prop - `identity` was not keyed on it, `L1D-11` - but journey grouping was WITHDRAWN entirely on 2026-07-22 for reasons of judgment quality, not model shape; see AMV-11.)
(The 2026-07-19 audit judged `SystemKind`/`DataRelationshipKind` as catalogue nodes "correct" under `L1D-6`; the operator's 2026-07-20 correction in §0 REVERSES that - the kind is now an intrinsic attribute / edge type, not a catalogue node.)

---

## 4. Node-type catalogue

Every L1 node label, its identity key, its attributes, and what each encodes.
Managed attributes on EVERY node: `project_id` (tenant), `first_seen`/`last_seen` (datetime), `prov_job`/`prov_model`/`prov_prompt_id` (provenance-on-write, `L1D-25`).

### 4.1 `:L1TestableUnit` (supertype) + `:L1Service`

- **Identity:** `(project_id, business_function_slug)` (`L1D-12`).
- **Encodes:** a business function with a service contract - "what the application does for a user" (checkout, sign-in, reward-points).
- **Attributes (props):**
  - `business_function_slug` (identity) - the stable human-legible business-function key; the dedup anchor (two Services are the same iff same slug-intent).
  - `service_contract` (free text) - a brief functional profile of the business function: what it DOES and what it OWNS, written in the application's own domain nouns and action verbs. Written by the **Bootstrapper** at bootstrap (and by the Assigner on a Service it MINTS); the concrete realisation of the "NL contract handles" slot this catalogue previously left unowned.
  - `label` / `salience` - NL name + one-line adversarial salience summary (for the BFS index-card). Phase B; NOT written at bootstrap.
  - `exposure` - contract facet: `public` | `authenticated` (whether the function requires a signed-in principal).
  - MUST NOT carry: `api_paradigm`, `navigation_model`, `rendering_model`, `auth_methods` (those are System-side, §3).

**On `service_contract` (added 2026-07-27, #29).**
It exists to be READ, by the cross-layer Assigner: that agent sees concrete endpoint paths and decides ownership by matching the path's nouns and actions against each candidate Service's contract.
So the contract is written for that consumer, and two rules follow from it.

- It must DISCRIMINATE. A profile true of every Service ("manages platform resources") is useless to a matcher, however accurate it is.
- It must contain NO path, URL, route, query parameter or field name. The operator's knowledge base never states paths, so any path in a contract is a guess by the writing model - and once persisted it is indistinguishable from evidence, anchoring the matcher onto a shape the real application may not have. Domain nouns and verbs carry the whole matching signal; invented syntax adds none.

Absence means not-yet-filled (the same convention as `exposure`); a blank contract is never persisted as an empty string.
A re-bootstrap whose model omits the contract leaves the stored one standing - the idempotent MERGE has nothing to clobber it with.
For the A.2 `SPLIT` op each subordinate leaf MUST get its OWN contract; copying the umbrella's onto every leaf would leave them mutually indiscriminable and defeat the decomposition.

### 4.2 `:L1TestableUnit` + `:L1System`

- **Identity:** `(project_id, kind, discriminator)`; `discriminator` defaults to the non-null sentinel `"__singleton__"` (`L1D-9`). (Corrected 2026-07-20 - the identity key was `system_kind`; see §0.)
- **Encodes:** a cross-cutting technical mechanism that Services lie on (WAF, CDN, API paradigm, auth mechanism, web presentation).
- **Attributes (props):**
  - `kind` (identity) - a plain attribute whose value is one of the known kinds (§6.1), validated against the `l1_curator.SYSTEM_KINDS` constant. No catalogue node, no `OF_KIND` edge (§0).
  - `discriminator` (identity) - `__singleton__` unless the target genuinely has multiple instances of the kind (two CDN products, two API gateways); the reserved slot of `L1D-8`/`NM-6`.
  - kind-specific mechanism attributes, e.g. on `WebPresentation`: `rendering_model`, `navigation_model` (each + `_confidence` + `_evidence`); these are the mechanism classifications that used to be mis-stored on the Service.
  - `salience` / NL handles.

### 4.3 `:L1DataItem`

- **Identity:** `(project_id, item_key)` (flexible semantic key, resolving `L1OP-1`); `identity` NOT keyed on the L0 sites it surfaces at (`L1D-11`).
- **Encodes:** a logical business data record (customer account, shopping basket, order, payment method) - the Tier-1 trust substrate (`L1D-13`).
- **Attributes:**
  - `item_key` (identity) - the semantic slug; the same key is reused for sites judged one logical item.
  - `fields: list[str]` - the concrete fields OBSERVED for this item on the surface (evidence-bound only; speculative fields are forbidden, richer attribution deferred to AMV-10).
  - NL notes.

### 4.4 `:SystemKind` - REMOVED (operator correction 2026-07-20, §0)

The `:SystemKind` catalogue node and the `OF_KIND` edge no longer exist.
A System's kind is the intrinsic `kind` identity attribute on `:L1System` (§4.2), validated against the `l1_curator.SYSTEM_KINDS` Python constant (the single source of truth); the enumeration is second-order data, not a graph structure.

### 4.5 `:DataRelationshipKind` - REMOVED (operator correction 2026-07-20, §0)

The `:DataRelationshipKind` catalogue node no longer exists.
A functional-dependency kind IS the (uppercased) relationship type between two DataItems, drawn from the fixed allowlist in §6.2 and hard-rejected if unknown.

---

## 5. Edge-type catalogue

Every relationship the L1 sole-writer emits, its endpoints, its properties, and what it encodes.
`RENDERED_BY` is REMOVED by this correction (§2).

### 5.1 Cross-layer (L1 -> L0) edges

| Edge | From -> To | Properties | Encodes |
|---|---|---|---|
| `AGGREGATES` | `L1Service` -> L0 node | judgment envelope: `confidence`, `status` (`committed`), `evidence_refs[]`, `prov_*`, `ts`, `endpoint_template` (for Endpoints) | membership/assignment (interface-agreement A, `L1D-25`); N:M; the lazy fetch hop of traversal-then-fetch |
| `SURFACES_AT` | `L1DataItem` -> L0 Parameter/Header/field | `prov_job`, `first/last_seen` | where a logical data item appears on the concrete surface |
| `EVIDENCED_BY` | `L1System` -> L0 node | `prov_job`, `first/last_seen` | the L0 fingerprint evidence for a System (a `Server:` header, a cookie) |

### 5.2 Intra-L1 (L1 -> L1) edges

| Edge | From -> To | Properties | Encodes |
|---|---|---|---|
| `EXPOSED_VIA` | `L1Service` -> `L1System` (API System OR `WebPresentation`) | `prov_*` | the surface/paradigm through which the Service is reached (REST, GraphQL, or web presentation) |
| `PRODUCES` | `L1Service` -> `L1DataItem` | `prov_*` | the Service creates/owns this data record |
| `CONSUMES` | `L1Service` -> `L1DataItem` | `assumption`, `assumption_rationale`, `prov_*` | the Service reads this record AND the trust assumption it makes about it (Tier-1 trust, `L1D-14`) |
| `<KIND>` (e.g. `DERIVED_FROM`, `EQUALS_HASH_OF`) | `L1DataItem` -> `L1DataItem` | `predicate`, `rationale` | a functional-dependency invariant between two records; the kind IS the edge type (§0/§6.2), from the fixed allowlist, uppercased. No generic `DATA_RELATIONSHIP` edge and no `kind` prop. |
| `AUTHENTICATED_BY {realm}` | `L1Service` -> `AuthenticationMechanism` System | `realm`, `prov_*` | which auth MECHANISM/realm mints the principal (mechanism = System, `L1D-5`); replaces the `auth_methods` Service prop |
| `AUTHORIZED_BY {role}` | `L1Service` -> `AuthorizationSystem` | `role`, `prov_*` | the authorization-pyramid projection onto this Service (policy = contract, `L1D-5`); role is part of the edge identity |
| `IDENTIFIED_BY` | `L1Service` -> `IdentificationSystem` | `prov_*` | the cookie/session identification system the Service rides |
| `FRONTED_BY` / `PROTECTED_BY` / `ROUTED_BY` | `L1Service` -> perimeter System (CDN / WAF / ReverseProxy / APIGateway) | `role`, `prov_*` | what perimeter sits in front of the Service (scopes the "what's in front of S" DFS) |
| `SHAPES_DATA_OF` | `L1Service` -> IntegrationSystem | `role`, `prov_*` | CSP/CORS integration shaping the Service's data path |
| `ON_REQUEST_PATH {order}` | `L1System` -> `L1System` (and -> Service origin) | `order`, `enforces[]`, `prov_*` | the ordered request-path chain (Tier-3 composition); System-to-System builder is AMV-7 |
| `DEPENDS_ON` | Service->Service or System->System | `role`, `prov_*` | generic dependency where none of the above fits |

(`OF_KIND` REMOVED - operator correction 2026-07-20, §0: a System's kind is the intrinsic `kind` attribute, so there is no catalogue row to link to.)

Sub-granularity rides on the `role`/`realm`/`order` props, never on new edge labels (`L1D-21`).
Exception (ratified 2026-07-20): the functional-dependency relationship type IS the granularity for `DataItem->DataItem` edges (the fixed six-kind allowlist), not a `role` prop on one generic edge.

---

## 6. Known-kind enumerations (Python constants, not catalogue nodes - §0)

### 6.1 System `kind` values (`l1_curator.SYSTEM_KINDS`)

`WAF`, `CDN`, `ReverseProxy`, `APIGateway`, `RESTApi`, `GraphQLApi`, `IdentificationSystem`, `IntegrationSystem`, `AuthenticationMechanism`, `AuthorizationSystem`, **`WebPresentation`** (rendering_model + navigation_model attributes), `Sitemap` (the discovered site-structure artifact, distinct from `navigation_model`).
REMOVED earlier: `RenderingSystem_SSR_UI`, `RenderingSystem_CSR_JSMap` (merged into `WebPresentation`).
This is the module-level `SYSTEM_KINDS` constant - the single source of truth used to VALIDATE a System's `kind` and to enumerate kinds for the stale-asset sweep prompt. Adding a kind is a one-line edit there, not a schema migration.

### 6.2 DataRelationship kinds -> edge types (`l1_curator.DATA_RELATIONSHIP_KINDS`)

The FIXED allowlist (operator correction 2026-07-20, §0): `derived_from`, `reflected_in`, `equals_hash_of`, `copy_of`, `concatenation_of`, `subset_of`.
Each becomes the uppercased edge TYPE (`DERIVED_FROM`, ...). This is a hard security boundary because the value is interpolated into Cypher: an unknown kind is rejected outright, never written as a generic edge. Extending it is a deliberate code edit (not a runtime data write) precisely because each new value becomes an interpolated relationship type.

---

## 7. Migration checklist (the build target)

1. `l1_curator.SYSTEM_KINDS`: add `WebPresentation`; remove the two `RenderingSystem_*`.
2. `l1_curator.SYSTEM_EDGE_RELS`: remove `RENDERED_BY`.
3. `l1_curator`: allow a System's mechanism attributes (`rendering_model`, `navigation_model`) to be written as props on the `L1System` (they are non-reserved props; already supported by `build_system_cypher` via `props`) - ensure the anatomy commit writes them there.
4. `anatomy.commit_anatomy`: write the two classifications as PROPS on the `WebPresentation` System (via a `SystemDelta` + `EXPOSED_VIA` `SystemEdgeDelta`), NOT as Service props.
5. `curation._REHOME_RULES`: `rendering_model` and `navigation_model` both -> props on the `WebPresentation` System via `EXPOSED_VIA` (delete `_navigation_target`'s SPA->CSR inference and the `RENDERED_BY` targets); extend to re-home `api_paradigm` (already `EXPOSED_VIA`) and `auth_methods` (-> `AUTHENTICATED_BY`) off the Service.
6. `pod._assignment_prompt` + `skills/analysis/analyser/SKILL.md` + `skills/analysis/anatomy/webpage-profile/SKILL.md` + `skills/analysis/curation/SKILL.md`: state the corrected model (a Service is `EXPOSED_VIA` a `WebPresentation` System carrying rendering + navigation; no mechanism classification on a Service).
7. Update tests referencing `RENDERED_BY` / `RenderingSystem_*` to the corrected model.
8. `index_card._SPINE_KEYS` may stay a superset (it is applied per-unit; a System card shows its mechanism attributes, a Service card shows only its own) - no change required, but document that mechanism keys appearing on a Service card indicate a mis-write to be re-homed.
