# Vuln-testing remediation map

*Status: working map (2026-10-03). Records the operator-green-lit decisions and the critical-defect register from the W7 synthesis / W8 critic review of the vuln-groundtruth corpus. Implementation is gated by the technical-mechanisms assessment and the simplicity scoring gate. This document authorises no code change by itself; tickets are filed after the map is coherent.*

Provenance: operator session 2026-10-03.
Corpus: `/Users/diekgbbtt/.local/share/polymerhus/vuln-groundtruth/` (`synthesis/REPORT.md`, `critic/report.md`).
Code read for grounding: `src/polymerhus/attack/hunting/` (pod, prompts, tools), `src/polymerhus/recon/` (auth feed, parsers), `src/polymerhus/analysis/`, `src/polymerhus/app/llm/skills.py`, `data/hunting/fault-kb.yaml`, `skills/`.

## 1. Green-lit decisions (direction accepted; implementation gated)

### D1 - Typed Finding closure on PodExport

Decision: add a typed closure to `PodExport` with these slots: intended payload, vector, impacted surface references (L0/L1), post-state, leaked information, assumed privilege, matched symptom id, evidence references.
Source of the field list: every `hunting/pod_export.gaps.md` in the corpus names these as required-but-unrepresented (CM-01, critic MF-1).
The closure is required when the derived verdict is `successful`; the corpus validator must enforce it, which removes the false assurance described by DS-A.
The eval assessor consumes the closure instead of re-deriving the answer key from raw artifacts (`eval/prompts/assessment.md`).
Chained with D2: the closure references one or more HTTP-history artifacts by id instead of inlining request and response bytes.
Open points: exact schema; whether an effect-class field rides the closure; who populates it (triager terminal versus deterministic terminal); optionality per fault class.

### D2 - One emitter contract aligned with the artifact model

Decision: pick one `RawObservation` contract and enforce it on both the emitter and the corpus.
Current drift (CM-20, DS-B): the live exec tool writes `request={"command", "exec_id"}` and never sets `RawObservation.headers` (`pod/tools.py:298-311`, twin at `pod/graph.py:469-479`), while the corpus authors parsed `{method, url}` records with response headers and bodies.
The `http-artifact/v1` model already carries request `{method, url, headers, cookies, query, form}`, response `{status, reason, headers, cookies}`, and per-body `capture_state` (`http_history_contract.py:35-49`).
The `replay` tool is bound to the pod runner but records nothing into the D6 log (`pod/agents.py:241-245`).
Recommended shape: the parsed-HTTP contract, populated from the capture plane, because D1 references artifacts and the benchmark evidence shape expects requests.
Open point: whether the export embeds the projection or only the artifact ids plus a typed summary.

### D3 - Drop `payload_vector_space`; ground the runner in HTTP history and skills

Decision: remove the deterministic-space concept.
The design principle is rejected: a space whose size and features cannot be known beforehand must not be enumerated deterministically.
The runner explores payloads, vectors, and procedure variants freely, chaining evidence.
The grounding contract for each step: first grep the HTTP history for request and response shapes on the same surface parts or interaction patterns, then follow the procedure in the relevant skill.
Typed-surface change: drop `payload_vector_space`, absorb the sparse `interpretation_guidance`, and add a `skills` field plus test-design attributes.
The candidate test-design attributes: concrete target attack surface (L0/L1, deliberately broad and without concrete endpoints); exploited web-application primitives; required authorization state; target-specific logic and data-flow walkthrough, including technologies, frameworks, and protocols; target-specific failure mode; concrete vulnerability framing with a technical framework.
The skills entities to cover: key vulnerability, attack surface, reconnaissance, adversarial capabilities, bypass techniques, vulnerability chaining, detection channels, pro tips, advanced techniques.
Coverage check: all listed entities map to sections in `docs/design/skills-ontology.md` section 3, so the attribute design is compatible with the landed ontology.
The `#196` replay carrier (`request_ref`, `mutations`) is nested inside `payload_vector_space` today and must relocate.
The HTTP-history read pair (`search_http_history`, `get_http_artifact`) is hunter-only today (`http_history_contract.py:6-16`); the runner grounding step requires it on the pod runner.
The three canonical descriptions in `http_history_contract.py` teach `payload_vector_space.request_ref` and must be rewritten.
The runner and hunter workflow changes are owned by the parallel workstream (W5/C5, artifact `skills` field and `load_skill`).
Open points: final attribute set and their names; whether any concrete seed survives; the contract-tier replacement for `default_probe_from_spec`; the binding semantics of the `skills` field.

### D4 - Drop the symbolic verdict layer temporarily

Decision: remove the symbolic symptom layer from the production verdict path and the contract tier.
The eval assessor implements the reliable oracle from the ground truth plus the `PodExport` (D1).
Correction to the premise: the layer IS wired in production, not unwired. `pod/graph.py:497-522` runs `evaluate_symptom` before the LLM triager and can terminate `successful` on a status or body predicate alone.
The module also drives the contract tier through `default_probe_from_spec` (`pod/agents.py:67-84`).
Impact map: section 2.
Note to revive: the symbolic layer remains a plausible passive tracking feature, never a verdict authority. File the revival as its own ticket.

### D5 - Skills coverage classification pass

Decision: for each mechanism named by the corpus, apply the two-half test from `docs/design/skills-variant-boundary.md` and output one of three verdicts: covered extension (surgical enrichment), genuine variant proposal (report to W7), or KB/technology fact.
Route variants through the W7 enrichment stream and the `#278` bypass/proxy families.
No stub injection, and no near-empty variants: the boundary's stability criterion excludes technology-stack facts (`skills-variant-boundary.md:50,212`) and the suite's abstraction rule forbids product and payload literals (`skills-unspurious/README.md:55-60`).

### D6 - KB coverage measurement gated on a grounded oracle

Decision: live query and measurement of the methodology KB is the right principle but is deceptive today.
The response producer agent has an ungrounding qualitative defect: it fabricates content that is not present in the retrieved KB responses.
Any response assessment must therefore oracle on a framework, technology, or protocol-specific ground truth researched on the web beforehand, and must account for fabrication explicitly.
The `kb.yaml` statuses are a desk-authored gap catalogue, not a measurement (critic DS-C), and stay treated as such until measured.
This is recorded as a KB quality defect with its own ticket.

## 2. Symbolic layer impact map (D4)

Production wiring:
- `pod/graph.py:93` (import), `:497` (call), `:515-522` (fast path: confirmed, infeasibility, else the LLM triager).
- `pod/symbolic.py:132-161` (`evaluate_symptom`), `:43-75` (`default_probe_from_spec`), `:78-107` (`mutations_from_pvs`).
- `pod/agents.py:67-84` (`symbolic_runner_step_fn`, the LLM-free contract tier), `:72-81` (default probe).
- `pod/verification.py:58-60` (`validate_spec` requires `payload_vector_space` to be a dict).

Tests that exercise the symbols:
- `tests/attack/pod/test_symbolic.py` (direct unit tests of both functions).
- `tests/attack/pod/test_graph.py` (contract-tier lane throughout, many call sites).
- `tests/attack/pod/test_compaction_seam.py` (contract-tier lane).
- `tests/attack/pod/test_differential_removal.py` (lane sweep).
- `tests/integration/test_test_executor_pod_contracts.py` (contract-tier predicates).
- `tests/attack/pod/test_request_ref.py` and `tests/attack/pod/test_verification.py` (probe and spec validation).
- `tests/attack/pod/test_tools.py`, `test_prompt_memory.py`, `test_react_seams.py`, `test_predicates.py`, `test_note_tool.py` (shared `VALID_SPEC` fixtures carry the vector space).

Other readers:
- The older deterministic `HuntingHttpPod` (`hunting_pod.py`) reads the vector space directly. It has no production references in the hunting module; only tests import it.
- The corpus templates (`_templates/symptoms.md.tmpl`, `_templates/hunting/test_spec.yaml.tmpl`) restate the symbolic regex families and need rewording.

Assessment:
- Production removal is a small, local change: always route the triager node to the LLM triager.
- The contract tier loses its LLM-free verdict path; injected runner fakes already exist and are the replacement pattern.
- The distinct `infeasibility-signal` fast path moves to the LLM triager's terminal vocabulary.
- The change is entangled with D3: the default probe dies with the vector space, so the two land in one migration.
- Recommendation: proceed with the removal, note the revival, and keep the removal out of the ticket that reintroduces any passive tracking.

## 3. Critical defect register (explained; decision pending)

### CD-1 - CM-12/MF-6: authenticated session acquisition

What it is: 82 of 110 bundles need an authenticated session, and the hunting-side artifacts carry that need only as prose.
What exists (correction to the critic's framing): the recon side is substantially built. The auth store (#220) holds per-project credentials and an overview; the auth gateway (#223) runs an authn loop before phase 0 and selects an account; the auth feed projects request material into `use_auth` jobs and mounts Steel profiles (`recon/control/auth_feed.py`).
The pod runner is also more armed than the corpus assumes: `default_runner_step_fn` binds `auth_capable_binding("pod_runner")` (`pod/agents.py:127-136`), and because `ROLE_SKILLS["pod_runner"]` is non-empty the binding carries the `auth_store` read tool plus the per-project `authn` skill (`app/llm/skills.py:231`, `app/auth/seams.py:36-63`).
The runner additionally carries the `steel-browser` skill.
The residual defect: the hunting side has no typed session contract. `TestImplementationSpec` carries `assumptions` as natural language only; `HuntConfig.preconditions` is natural language; the runner prompt P0 says to hold the authorization level from the spec, but the spec cannot name an account or a role mechanically.
The recon gateway's selected account does not cross into hunts.
Failure shape: the hunter describes a login requirement in English, the runner must guess the account, the role, and the acquisition procedure, and the eval's seeded auth context is never referenced by the artifact.
Remedy options:
- A typed `session` block on the spec: account reference, role, an acquisition step, and the expected state (cookie or token).
- Carry the selected account identifier into `HuntConfig` or the spec.
- A runner workflow step that acquires and validates the session as a dependency step before the core steps.
- For hunting-entry trials the store is already seeded, so the spec can reference the account by name.
Open points: who selects the account (orchestrator or hunter), and whether acquisition is a spec field or a runner procedure.

### CD-2 - CM-08/MF-8: fault-KB materialisation and folds

What it is: the fault catalogue has two reads. The selection tier matches units to faults through `applies_if` and `enum_kinds`. The materialisation tier supplies the natural-language reflection content per CWE.
One entry exists per CWE id in `data/hunting/fault-kb.yaml`.
A folded Variant carries `fold_parent` pointing at its nearest retained Base or Class ancestor.
Missing materialisations: CWE-200, CWE-1392, CWE-284, and CWE-287 have no entry at all. A direct search returns no match.
Consequence: the 16 bundles carrying those fault classes cannot be minted by the fault-driven selection path, and the CWE bridge has nothing to join.
Mismatched folds: CWE-639's only fold child is CWE-566, which is the SQL-primary-key variant. The benchmark's IDOR faults are path-id or delete swaps, so the fold-family material shown to the orchestrator gate is SQL-specific and misleading.
CWE-89's only fold child is CWE-564, a Hibernate-specific variant that does not describe a native SQLite concatenation.
CWE-917 exists in the catalogue but not in the `cwes.yaml` bridge, so the precise expression-language fault cannot be selected for the CWE-94 bundles.
Remedy options:
- Author the four missing materialisations from the CWE catalogue content.
- Add a fold-compatibility check to the curation script: a child folds only under a parent that shares its mechanism or `applies_if`; otherwise promote or re-parent it.
- Extend the bridge with a mechanism discriminator, because the declared benchmark type and the demonstrated mechanism can diverge (CM-17).
Open points: the authoring source for the new entries, the fold policy (promote versus re-parent versus merge), and whether the bridge discriminator lands now or later.

### CD-3 - CM-04/MF-9: recon carriers

What it is: recon cannot witness some carrier shapes, so the corpus authors them instead of observing them.
How input is modelled today: a Parameter node hangs off an Endpoint with identity `{name, position, endpoint_path, baseurl}`. The positions emitted today are `query` and `body` (`recon/domain/parsers/_urls.py:110-120`, `jsluice_parser.py:55-56`, `steel_parser.py:44`, `active_param_parser.py:126`).
The Endpoint identity is path plus method plus baseurl.
Three failure shapes:
- Path-position carriers: segments such as `{realm}`, `{id}`, and `{orderId}` are not a Parameter position, so recon never discovers them.
- Nested body fields: a body Parameter is one opaque string, so nested fields such as `filteringRules.rules[].condition`, `roles[]`, and `_elementor_data` blobs are not addressable.
- Dispatcher and route-in-query: WordPress hides the route in `?rest_route=/...`; PrestaShop collapses every admin action onto one path; JetLinks uses runtime-generated path ids. The Endpoint identity cannot carry the dispatch target.
Consequence: the carrier under test is authored answer-key content, which contaminates any discovery claim. The synthesis classifies 37 of 110 bundles in this family.
Remedy options:
- Add `position: path` Parameters carrying the segment template.
- Add a structured body map (JSON pointer to field) beside the opaque body string.
- Add a dispatcher and route model so Endpoint identity can carry the dispatch target.
Open point: which carrier class lands first, and whether the route model belongs in Endpoint identity or an adjacent node.

### CD-4 - CM-07/MF-5: L1 authorization, taint, and trust-boundary facets

What it is: L1 cannot express the exact facets that the highest-value benchmark classes test.
What exists: Service, System, and DataItem nodes; a `CONSUMES` data-flow edge that may carry an `assumption` string predicate plus a rationale (`analysis/l1_types.py:139-152`); DataRelationship edges with a six-value kind allowlist and an optional predicate; System edges carrying `AUTHENTICATED_BY` and `AUTHORIZED_BY` (`l1_types.py:176-190`).
What is missing: no taint flag (`user_controlled`) on a Parameter or DataItem; no object-key-to-principal binding; no validate-vs-use facet (the value a sink used differs from the value it validated); no destination-validation facet; and the `CONSUMES` assumption is an unparsed string, not a typed predicate the projection can render.
Consequence: IDOR and BOLA (13 bundles), access control (5), authentication bypass (1), and validate-vs-use RCE and XXE faults are trust-boundary and data-invariant faults. The candidate generator reasons over the typed spine, so an absent facet makes the fault invisible rather than merely under-informed. The synthesis classifies 57 of 110 bundles in this family.
Cross-link: the skills ontology names `## Trust Assumptions` as the generative layer of every variant (`skills-ontology.md:62-68`). The L1 facet is the runtime binding of that layer, and the new spec test-design attributes from D3 are its hunter-side projection.
Remedy options:
- Add typed optional facets to DataItem and `CONSUMES`: `taint`, `authorization_binding`, `trust_boundary`, `validate_vs_use`.
- Render them in `_render_projection` so `graph_view` and the spec writer can key on them.
- Promote the `CONSUMES` assumption string to a typed predicate.
Open points: the facet vocabulary, which facets render, and who authors them (an analyser proposer or the operator KB).

## 4. Overlaps and sequencing

Contract group: D1 and D2 land together first. They feed the assessor and make the answer key round-trip.
Spec group: D3 and D4 land in one migration, because the default probe dies with the vector space. D3 also depends on the parallel W5 `skills` field workstream.
Witness group: the effect-class witness table from the July review feeds D1's matched symptom and impact fields.
Coverage group: D6 (measurement with a grounded oracle) precedes D5 authoring. W7 and `#278` own the skill variants.
Defect group: CD-1 and CD-2 are small and unblock many bundles, so they can ride early tickets. CD-3 and CD-4 are structural and deserve their own tickets after the contract migration.

## 5. Ticket candidates

1. PodExport Finding closure, validator enforcement, and assessor consumption (D1).
2. RawObservation and artifact-model alignment with a round-trip test (D2).
3. Spec v2: drop `payload_vector_space`, add `skills` and the test-design attributes, bind the HTTP-history read pair to the runner, rewrite the `#196` contract texts, replace the contract-tier probe (D3).
4. Symbolic layer removal and revival note (D4), bundled with ticket 3.
5. Session contract for hunting: account reference, acquisition step, validation (CD-1).
6. Fault-KB: four materialisations plus a fold-compatibility check and the bridge discriminator (CD-2).
7. Recon carriers: path position, structured body map, dispatcher route model (CD-3).
8. L1 facets: taint, authorization binding, trust boundary, validate-vs-use, rendered in the projection (CD-4).
9. Skills coverage classification pass into W7 and `#278` (D5).
10. KB grounded-measurement oracle plus the response-producer fabrication defect (D6).

## 6. Open questions for the grilling round

1. Finding closure: minimal eight fields plus an effect class, or a wider finding primitive?
2. Spec v2: confirm the six test-design attributes and the `skills` field; does any concrete seed request survive?
3. HTTP-history grounding: bind the read pair to the pod runner and rewrite the `#196` contract texts?
4. Symbolic removal: confirm the drop and the separate revival ticket?
5. Assessor oracle: benchmark-agnostic closure plus a per-benchmark adapter?
6. KB: fix the response-producer fabrication defect before any coverage measurement?
7. Defects CD-1 to CD-4: green-light the remedy directions, and in what order?
