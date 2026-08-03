# LightRAG Preprocessing Pipeline

Status: MVP implementation note. Current WSTG corpus generation updated on
2026-07-30. The live LightRAG store must be rebuilt from a clean store before
the new ontology-query anchors are considered indexed.

## Decision

Before indexing methodology material in LightRAG, raw source documents are
normalized into ontology-agnostic methodology documents.

For generic methodology notes, the primary generated document is:

```text
relation-briefs.md
```

This is the most important final document because it preserves operational
claims that connect methods, defenses, conditions, vulnerability classes, code
examples, and limitations. LightRAG's graph extraction can then derive typed
entities and relations from these source-grounded briefs.

The generic pipeline also generates facet documents:

```text
attack-methods.md
defenses-and-detections.md
prerequisites-and-environment.md
vulnerability-classes.md
code-and-payload-examples.md
source-context.md
.manifest.json
```

## Pipeline

```text
raw Markdown/text source
  -> structural parse by headings, paragraphs, lists, tables, code fences
  -> source fragments with provenance
  -> ontology-agnostic facet classification
  -> relation brief extraction
  -> LightRAG-ready Markdown documents
  -> LightRAG ontology extraction during indexing
```

## Ontology Boundary

The generated documents are not the ontology. They are stable methodology views.

The current LightRAG ontology extracts only:

```text
PreconditionEnvironment
TechnologyStack
DefensiveControl
VulnerabilityClass
AttackGoal
AttackerCapability
AttackTechnique
PayloadPattern
Artifact
ObservableSignal
```

from those documents, but changing the ontology later should not require
changing the preprocessing strategy. A future ontology change requires
re-indexing the same preprocessed documents, not changing the target model.

The implementation lives in `agent/lightrag/preprocess.py`.

## 2026-07-30 Ingestion And Retrieval Decisions

The immediate goal is not to build a query agent. The goal is to produce a
stable WSTG-only LightRAG KB that can answer the kinds of methodology queries
the Attack Engineering Agent will ask after Phase 2 abstraction.

The key retrieval problem observed in benchmark history was weak anchoring:
LightRAG could retrieve related methodology, but it often missed the direct WSTG
scenario ID or drifted into adjacent WSTG cases. The fix is to improve source
shape before indexing, not to compensate with a larger runtime prompt.

Current decisions:

- Keep the ten-type methodology ontology unchanged. Do not add a
  `WSTGScenario` entity type yet.
- Keep WSTG IDs, titles, source paths, and file names as scenario anchors and
  manifest metadata, not as ontology entities.
- Add deterministic `Ontology Query Anchors` inside each selected WSTG scenario
  document. These map likely Phase 2 terms to ontology types such as
  `TechnologyStack`, `PreconditionEnvironment`, `VulnerabilityClass`,
  `AttackTechnique`, `Artifact`, and `ObservableSignal`.
- Add canonical relation anchors that explicitly state how scenario titles,
  categories, canonical vulnerability classes, and ontology anchors map back to
  each WSTG ID.
- Benchmark retrieval context first with `--only-context`, then benchmark answer
  generation separately with `temperature=0`.
- Log ingestion batches and benchmark runs into SQLite so every result can be
  traced back to corpus version, batch, upload track IDs, LightRAG config, and
  query template.

Why not a `WSTGScenario` graph entity now:

- The current entity prompt explicitly forbids WSTG IDs, titles, source files,
  and section names as methodology entities. This keeps the graph focused on
  reusable security concepts rather than document structure.
- Adding `WSTGScenario` would be an ontology migration and would require prompt,
  audit, normalization, test, and full re-index changes.
- Anchor plus manifest gives the needed direct link without expanding the graph
  identity model. If benchmark history later shows that scenario IDs still fail
  after the clean rebuild, `WSTGScenario` can be reconsidered as a deliberate
  ontology v2 change.

### How Ingestion Was Improved

The WSTG corpus is shaped for LightRAG before any model call:

- **Scenario-scoped documents:** each `wstg-*-methodology.md` is one WSTG test
  scenario. This prevents chunks from mixing unrelated WSTG sections and makes
  every chunk carry the same scenario identity.
- **Repeated scenario anchors:** each retained fragment is preceded by an
  anchor line with WSTG ID, title, and category. This gives vector retrieval and
  graph context repeated chances to bind local methodology text back to the
  correct scenario.
- **Ontology query anchors:** high-value Phase 2 terms such as `GraphQL
  Introspection Enabled`, `JWT Stored In LocalStorage`, `CORS Allows Reflected
  Origin`, `Nested JSON Request Body`, `Raw JSON Operators Preserved`,
  `Server-Side URL Fetch Feature`, and `Download By Path Parameter` are written
  in the same document as the relevant WSTG scenario.
- **Relation anchors:** generated statements connect the anchor terms to the
  scenario, e.g. `TechnologyStack anchors REST API, GraphQL API, OpenAPI map to
  WSTG scenario WSTG-APIT-01`.
- **Noise removal:** references, external guide names, scanner/tool lists,
  source names, and placeholder pages are kept out of ingestion Markdown. This
  reduces `UNKNOWN`, `other`, `category`, and source-name graph nodes.
- **Source wording normalization:** generic terms that previously became poor
  nodes are rewritten into methodology wording. Examples include replacing broad
  "endpoint" phrasing with "route location" or "request input field" where the
  text is describing target conditions.
- **Static QA before upload:** `--qa-only --fail-on-qa-issues` blocks missing
  anchors, duplicate/unknown WSTG IDs, missing primary documents, and known
  noise markers before LightRAG indexing spends tokens.
- **Smaller staged batches:** first clean rebuild uses `--batch-size 5` and
  `MAX_PARALLEL_INSERT=1` to reduce worker timeout risk and make failed batches
  cheap to isolate.
- **History logging:** staged ingestion with `--log-ingestion-history` stores
  uploaded files, upload track IDs, processing counts, normalization result,
  graph gate, query gate, and batch metrics in the same SQLite history store
  used by benchmarks.

### Retrieval Shape For Attack Engineering Queries

The Attack Engineering Agent should query from its Phase 2 abstraction, not from
a vague vulnerability name. The preferred template is
`ontology_feature_to_wstg`.

The query should project the observed target profile into ontology buckets:

```yaml
TechnologyStack:
  - GraphQL
  - REST API
  - Browser Storage
PreconditionEnvironment:
  - GraphQL Introspection Enabled
  - Sequential Object Identifier
  - JWT Stored In LocalStorage
Artifact:
  - JWT Access Token
  - GraphQL Schema
ObservableSignal:
  - Adjacent Account ID Accessible
  - Sensitive Token Readable By JavaScript
DefensiveControl:
  - Content-Security-Policy
VulnerabilityClass:
  - Broken Object-Level Authorization
```

Then the prompt asks LightRAG to resolve paths in this order:

```text
TechnologyStack / PreconditionEnvironment / Artifact / ObservableSignal
  -> VulnerabilityClass
  -> AttackTechnique / PayloadPattern / DefensiveControl
  -> WSTG scenario anchor
  -> WSTG ID, title, methodology, probes, evidence, negative controls
```

This structure supports the three likely Attack Engineering query classes:

- **Target-state query:** "Given these technologies, inputs, controls, and
  signals, which WSTG tests and hypotheses are applicable?"
- **Bypass query:** "This technique appears blocked by this defense; which WSTG
  methodology describes bypasses or alternate probes under matching
  conditions?"
- **Chaining query:** "Which methodology can establish a missing prerequisite or
  artifact needed for the next test?"

Production queries should not include `expected_wstg_ids`; those are benchmark
labels only. Diagnostic templates may query exact IDs, titles, or categories,
but only to validate that indexing and anchors work.

## WSTG Profile

OWASP WSTG is treated as a first-class source profile because its scenario
format is stable and methodologically meaningful.

Use:

```bash
python -m agent.lightrag.preprocess --profile wstg \
  path/to/wstg/document/4-Web_Application_Security_Testing/07-Input_Validation_Testing/05-Testing_for_SQL_Injection.md \
  --output-dir data/lightrag/inputs/wstg_preprocessed
```

For the common case, use the fetch-and-preprocess wrapper instead:

```bash
python -m agent.lightrag.wstg_fetch --scenario sql-injection
```

This downloads the official OWASP WSTG Markdown into:

```text
data/lightrag/inputs/wstg_raw/
```

and writes LightRAG-ready composite documents into:

```text
data/lightrag/inputs/wstg_preprocessed/
```

When adding a new scenario that does not have an alias yet, pass the path
relative to the OWASP `document/` directory:

```bash
python -m agent.lightrag.wstg_fetch \
  --path 4-Web_Application_Security_Testing/07-Input_Validation_Testing/05-Testing_for_SQL_Injection.md
```

If the source file is already present locally and only preprocessing should run:

```bash
python -m agent.lightrag.wstg_fetch --scenario sql-injection --skip-download
```

For a full WSTG methodology batch, do not index the whole book. Use the official
repository as the source of truth, but keep only the actionable testing section:

```bash
WSTG_TMP=/tmp/owasp-wstg
WSTG_RAW=data/lightrag/inputs/wstg_raw
WSTG_OUT=data/lightrag/inputs/wstg_preprocessed

rm -rf "$WSTG_TMP"
git clone --depth 1 --filter=blob:none --sparse https://github.com/OWASP/wstg.git "$WSTG_TMP"
git -C "$WSTG_TMP" sparse-checkout set document/4-Web_Application_Security_Testing

mkdir -p "$WSTG_RAW"
rm -rf "$WSTG_RAW/4-Web_Application_Security_Testing"
cp -R "$WSTG_TMP/document/4-Web_Application_Security_Testing" "$WSTG_RAW/"

python -m agent.lightrag.preprocess --profile wstg \
  $(find "$WSTG_RAW/4-Web_Application_Security_Testing" -type f -name '*.md' \
    ! -name 'README.md' \
    ! -path '*/00-*') \
  --output-dir "$WSTG_OUT"
```

This excludes section introductions and overview/objective files such as WSTG
4.0, while keeping the concrete WSTG testing scenarios from Information
Gathering through API Testing.

For each scenario, the preprocessor detects the WSTG ID, scenario title, source
headings, line ranges, code or payload examples, relation candidates, and test
sections. It writes one scenario-scoped composite document:

```text
<wstg-id>-methodology.md
.manifest.json
```

`<wstg-id>-methodology.md` is the primary LightRAG input. It contains
deterministic sections for methodology scope, overview, objectives, attack
methods, prerequisites, defenses, code/payload examples, and relation briefs.
Raw provenance, generic source context, and references remain in `.manifest.json`
or debug files, not in the Markdown sent to LightRAG. This avoids a large number
of tiny files while still giving LightRAG structured headings to chunk against.

Per-facet debug documents can be generated for inspection only:

```bash
python -m agent.lightrag.preprocess --profile wstg --debug-facets \
  path/to/wstg/document/4-Web_Application_Security_Testing/07-Input_Validation_Testing/05-Testing_for_SQL_Injection.md \
  --output-dir data/lightrag/inputs/wstg_preprocessed
```

Debug files are written under:

```text
data/lightrag/inputs/wstg_preprocessed/_debug_facets/
```

The manifest is intentionally written as `.manifest.json` so the local LightRAG
uploader skips it as a dotfile. It is audit metadata, not retrieval content.

When multiple source files share the same WSTG base ID, output filenames remain
deterministic. The first scenario keeps `<wstg-id>-methodology.md`; later
collisions append the source filename stem before `-methodology.md`. This avoids
silently overwriting sub-scenarios during full-book preprocessing.

### Current WSTG Preprocessing Contract

The static WSTG base must be generated from:

```text
data/lightrag/inputs/wstg_raw/
```

into:

```text
data/lightrag/inputs/wstg_preprocessed/
```

with:

```bash
.venv/bin/python -m agent.lightrag.preprocess --profile wstg \
  --output-dir data/lightrag/inputs/wstg_preprocessed \
  --qa \
  --fail-on-qa-issues \
  data/lightrag/inputs/wstg_raw
```

The preprocessing phase before LightRAG ingestion is:

1. Parse raw Markdown by heading, paragraph, list, table, and code fence.
2. Preserve fragment provenance in memory and in `.manifest.json`.
3. Detect WSTG ID, scenario title, source path, heading path, and source line
   ranges.
4. Classify fragments into ontology-agnostic methodology facets:
   `overview`, `test-objectives`, `attack-methods`,
   `prerequisites-and-environment`, `defenses-and-detections`,
   `code-and-payload-examples`, `references`, and `source-context`.
5. Remove ingestion noise before writing the LightRAG Markdown:
   provenance-only WSTG ID fragments, merged or removed placeholder text,
   references, tool-specific reference lists, generic source names, and known
   external reference boilerplate.
6. Normalize source wording that tends to produce poor graph nodes, such as
   generic "endpoint", "parameters", and "attack surface" phrasing.
7. Render one scenario composite file with stable methodology headings.
8. Render ontology query anchors that connect Phase 2 profile terms to the
   active ten-type methodology ontology and back to the WSTG scenario ID.
9. Render relation briefs only when source-grounded relation fragments exist.
10. Skip documents that contain no methodology content after filtering,
   including WSTG merged and removed placeholders.
11. Rewrite stale `wstg-*-methodology.md` outputs during full regeneration so
    removed or skipped scenarios cannot be accidentally reingested.

Validate an already generated WSTG corpus before spending LightRAG indexing
tokens:

```bash
.venv/bin/python -m agent.lightrag.preprocess --profile wstg \
  --qa-only \
  --fail-on-qa-issues \
  --output-dir data/lightrag/inputs/wstg_preprocessed
```

Current generated corpus on 2026-07-30:

```text
raw fragments: 4489
relation briefs: 1078
LightRAG methodology Markdown files: 119
manifest: data/lightrag/inputs/wstg_preprocessed/.manifest.json
static QA: passed
current QA warning: wstg-inpv-05-methodology.md is large enough to increase extraction timeout risk
```

`WSTG-ATHN-01` is skipped in this generated corpus because the local source is a
merged placeholder and does not contain standalone methodology content.
`WSTG-INPV-13` / "Testing for Buffer Overflow" is also skipped because the
current source body is only `This content has been removed`. The preprocessed
directory was also checked for the old noisy markers:

```text
GraphQL Cheat Sheet
OWASP Testing Guide
[merged]
This content has been merged into
This content has been removed
No WSTG relation candidates
wstg-athn-01-methodology
wstg-inpv-13-methodology
```

No matches are expected in the generated ingestion Markdown.

### First Real WSTG Trial

The first real source used to validate the profile is OWASP WSTG SQL Injection:

```text
data/lightrag/inputs/wstg_raw/05-Testing_for_SQL_Injection.md
```

The generated LightRAG input is:

```text
data/lightrag/inputs/wstg_preprocessed/wstg-inpv-05-methodology.md
```

Observed output:

```text
source: 831 lines, 44.8 KB
composite: 2207 lines, 120 KB
fragments: 255
relation briefs: 17
files for ingestion: 1 Markdown document
```

This confirmed the important design correction: per-facet files are useful for
debugging, but the indexing unit should be the scenario composite document.
Otherwise the corpus becomes too many small files and loses scenario-level
context.

## Writeup Overlay Profile

0xdf-style writeups are treated as review-overlay methodology, not validated
base knowledge. The fetcher stores raw HTML plus provenance under:

```text
data/lightrag/inputs/writeups_raw/0xdf/
```

and writes normalized LightRAG overlay documents under:

```text
data/lightrag/inputs/writeups_overlay/0xdf/
```

Use a small first batch:

```bash
python -m agent.lightrag.writeup_fetch --source 0xdf --limit 10 \
  --output-dir data/lightrag/inputs/writeups_overlay/0xdf
```

or fetch a full publication year:

```bash
python -m agent.lightrag.writeup_fetch --source 0xdf --year 2026 \
  --output-dir data/lightrag/inputs/writeups_overlay/0xdf
```

or fetch specific articles:

```bash
python -m agent.lightrag.writeup_fetch --source 0xdf \
  --url https://0xdf.gitlab.io/2022/10/29/htb-trick.html \
  --output-dir data/lightrag/inputs/writeups_overlay/0xdf
```

If the raw HTML already exists and only preprocessing should run:

```bash
python -m agent.lightrag.writeup_fetch --source 0xdf --skip-download \
  --raw-dir data/lightrag/inputs/writeups_raw/0xdf \
  --output-dir data/lightrag/inputs/writeups_overlay/0xdf
```

The generic preprocessor can also run the writeup profile directly:

```bash
python -m agent.lightrag.preprocess --profile writeup \
  data/lightrag/inputs/writeups_raw/0xdf \
  --output-dir data/lightrag/inputs/writeups_overlay/0xdf
```

Each generated writeup document contains a short methodology scope, an
attack-chain summary, technology and preconditions, technique cards, artifacts
and attacker capabilities, defensive controls and bypasses, and relation briefs.
Raw provenance, source URLs, author/source names, file paths, and unmatched
source-context fragments stay in the manifest or raw input tree and are not
included in the Markdown intended for indexing. This keeps ingestion focused on
reusable methodology concepts and reduces generic graph nodes such as document
titles, source names, or section labels.

The generated documents are review overlays. Promotion to the validated base
should happen only after reviewing that the extracted relation briefs are
reusable methodology rather than machine-specific steps.

### 2026-08-03 Overlay Gate

The 0xdf overlay was loaded into a separate LightRAG instance instead of the
validated WSTG base:

```text
http://127.0.0.1:9622
workspace: writeups_0xdf
input: data/lightrag/inputs/writeups_overlay/0xdf
storage: data/lightrag/writeups_rag_storage
```

Ingestion used batches of 10 documents with a batch-and-gate sequence:

1. upload the batch to the overlay API;
2. poll `/documents` until the batch reaches `processed == batch_size` and
   `failed == 0`;
3. run graph audit and deterministic normalization against the canonical WSTG
   entity set;
4. prune CTF-only artifacts, transient local execution paths, source markers,
   and generic command noise;
5. run a mini-smoke query for a technique present in the batch.

Final overlay state after batches 1 through 4:

```text
documents: 39 processed / 39 all / 0 failed
entities: 139
relations: 502
unknown entity types: 0
non-canonical type labels: 0
blocking noise entities: 0
expected type mismatches: 0
embedded marker names: 0
prefix noise names: 0
```

The overlay must keep the same 10 canonical methodology entity types used by
the WSTG base:

```text
PreconditionEnvironment
TechnologyStack
DefensiveControl
VulnerabilityClass
AttackGoal
AttackerCapability
AttackTechnique
PayloadPattern
Artifact
ObservableSignal
```

Any future writeup ingestion must pass the same gate before the data is used by
`RoutedMethodologyRetriever`. Passing the overlay gate does not promote the
content to the validated base; it only makes the material eligible for
conditional retrieval with `source_tier=review_overlay`.

## LightRAG 1.5

The runtime is pinned to `ghcr.io/hkuds/lightrag:v1.5.0rc3`. In this line,
`ENTITY_TYPES` is replaced by `ENTITY_TYPE_PROMPT_FILE`. The methodology entity
profile lives at:

```text
data/lightrag/prompts/entity_type/methodology_entities.yml
```

The compose service uses:

```text
ENTITY_EXTRACTION_USE_JSON=false
ENTITY_TYPE_PROMPT_FILE=methodology_entities.yml
LIGHTRAG_PARSER=*:native-teP,*:legacy-R
```

`ENTITY_EXTRACTION_USE_JSON=false` remains deliberate for the validated WSTG
run. The early OpenRouter `tencent/hy3:free` test route rejected
`response_format=json_object`, and the later SwissAI-backed run was kept on the
same non-JSON extraction mode to avoid changing two variables while stabilizing
the KB.

The local WSTG preprocessor still runs before LightRAG. LightRAG 1.5 improves
file parsing and chunking, but it does not know which WSTG sections should act
as planner methodology evidence.

## Operational Notes

Indexing WSTG chapters is expected to be slow on remote or rate-limited model
routes. The first SQL Injection chapter upload produced LightRAG work items like:

```text
C[1/28]: doc-...-chunk-001
```

That means the one composite Markdown document was split into 28 LightRAG chunks,
and each chunk can trigger extraction/model calls. On slow, busy, or
rate-limited providers, processing can look stalled even when it is still
progressing. Prefer waiting on status counts over using the Web UI as the only
signal; the UI can show files uploaded before graph extraction is complete.

`503 - No provider found for the requested service` is a provider/model routing
failure, not a LightRAG graph-size failure. In the validated WSTG run, this was
handled by keeping the SwissAI provider and switching to a concrete available
model, `apertus-ai/Apertus-v1.5-70B`, then retrying the affected batch.

`Graph nodes are truncated to max nodes` is retrieval-context truncation. It is
controlled by `MAX_GRAPH_NODES` and does not mean the API quota was exceeded.
For the validated WSTG KB, `MAX_GRAPH_NODES=5000` was sufficient: the final
graph has 2,873 entities. If this warning appears again, first check current
entity count and query scope before raising the limit.

If iteration speed matters more than graph quality, test with a smaller excerpt
or temporarily lower LightRAG chunk size only after clearing
`data/lightrag/rag_storage`. If graph quality matters, keep the scenario
composite intact and wait for indexing to complete.

## Smoke Test Automation

The automated WSTG smoke harness lives in `agent/lightrag/smoke.py`. It separates
two checks:

- Graph gate: deterministic checks over the GraphML store. This fails on
  unknown entity types, non-canonical types, noise/source entities, expected
  type mismatches, missing required vulnerability entities, or entities not
  grounded in the expected WSTG file.
- Query gate: templated LightRAG queries with required terms, required source
  files, any-of synonym groups, and forbidden generalizations. This is the
  quality signal for broad and multi-vulnerability retrieval.
- Staged loading: WSTG can be uploaded in batches. The first batch is the
  fixed injection/path/SSRF smoke subset, then the remaining WSTG methodology
  documents are uploaded in sorted batches.

When `--normalize-types` is enabled, the smoke harness applies deterministic
type normalization and deletes graph-audit noise entities. Use
`--keep-noise-entities` only for diagnostics when the raw extracted noise must
be inspected before deletion.

Mini-batch run:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --reset-store \
  --upload-mini-batch \
  --normalize-types \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

Evaluate an already-loaded store:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --normalize-types \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

Staged WSTG loading, first two batches only:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --reset-store \
  --upload-staged-wstg \
  --batch-size 5 \
  --max-batches 2 \
  --normalize-types \
  --log-ingestion-history \
  --run-label wstg-clean-rebuild \
  --skip-diagnostic-queries \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

Full static WSTG loading:

Use conservative indexing for the first clean rebuild:

```bash
MAX_PARALLEL_INSERT=1 docker compose --profile lightrag up -d
```

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --reset-store \
  --upload-staged-wstg \
  --batch-size 5 \
  --normalize-types \
  --log-ingestion-history \
  --run-label wstg-clean-rebuild \
  --skip-diagnostic-queries \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

To evaluate retrieval quality for newly loaded non-injection WSTG chapters,
enable manifest-derived scenario queries and cap the number of LLM calls per
run:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --upload-staged-wstg \
  --start-batch 1 \
  --max-batches 1 \
  --batch-size 5 \
  --normalize-types \
  --log-ingestion-history \
  --run-label wstg-clean-rebuild \
  --query-after-each-batch \
  --include-scenario-queries \
  --scenario-query-limit 5 \
  --skip-diagnostic-queries \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

The raw broad multi-vulnerability query is kept as a non-blocking diagnostic
until it is stable. The broad `wstg_bypass_relations` query is also
non-blocking during staged ingestion: it is useful as a quality signal, but a
partial batch can retrieve semantically useful bypass/control context while
missing one of the broad keyword groups such as WAF, allow list, or command
filter. The blocking quality gate uses the graph gate plus targeted
per-vulnerability retrieval cases, which makes recall failures visible per
source file before generating a combined inventory.

After the staged corpus is fully loaded, benchmark retrieval context first.
The ontology-aware template should be compared against the older feature,
category, and methodology templates before enabling generated answers:

```bash
.venv/bin/python -m agent.lightrag.benchmark_wstg \
  --base-url http://127.0.0.1:9621 \
  --run-label wstg-clean-rebuild-context \
  --modes hybrid mix naive \
  --top-k 10 20 40 \
  --template-types ontology_feature_to_wstg feature_to_threat wstg_category_oriented step_by_step_methodology \
  --only-context
```

Then run the same benchmark without `--only-context` and keep
`--temperature 0` to evaluate generated methodology quality separately from
retrieval quality.

### Ontology Query Benchmark

The routed overlay benchmark harness lives in:

```text
agent/lightrag/benchmark_ontology_queries.py
```

It evaluates three ontology-shaped Attack Engineer queries across three
LightRAG retrieval configurations:

```text
A: base-only OAuth2/OIDC broken access control and session handling
B: JWT weak-signature token forgery and role-claim escalation
C: Java deserialization gadget chains with RMI/JRMP listener constraints

standard: mode=mix, top_k=10, only_need_context=true
deep_graph_retrieval: mode=mix, top_k=20, only_need_context=true
hybrid_search: mode=hybrid, top_k=15, only_need_context=true
```

Example live run:

```bash
.venv/bin/python -m agent.lightrag.benchmark_ontology_queries \
  --base-url http://127.0.0.1:9621 \
  --writeup-url http://127.0.0.1:9622 \
  --fail-on-gate
```

To also save generated LightRAG answers for utility review, add:

```bash
--include-answers
```

The runner writes timestamped JSON records under:

```text
data/lightrag/benchmarks/ontology_query_benchmark_<timestamp>.json
```

Each result records:

```text
test_id
routing_decision.sources_queried
routing_decision.trigger_reason
hyperparameters.mode
hyperparameters.top_k
retrieved_entities_by_type
retrieved_entities_by_role
extracted_relations
source_chunks
raw_context_bytes
lightrag_answer.text
lightrag_answer.raw_source_answers
```

The benchmark has a completeness gate so failures cannot silently disappear
from the output. The top-level summary includes expected and observed run IDs,
missing runs, route mismatches, trigger mismatches, retriever errors, runs
without canonical entities, runs without canonical source context, and runs
without extracted relations.

The validated 2026-08-03 run completed all `3 x 3` cases:

```text
output: data/lightrag/benchmarks/ontology_query_benchmark_20260803T123110Z.json
expected_run_count: 9
run_count: 9
missing_runs: []
error_count: 0
expected_route_mismatches: []
expected_trigger_mismatches: []
runs_without_canonical_entities: []
runs_without_canonical_source_context: []
runs_without_extracted_relations: []
total_raw_context_bytes: 2893542
```

Query C is expected to include both `base_candidates_below_threshold` and
`concept:deserialization` when the query text explicitly contains
deserialization or gadget-chain terms. The gate treats the configured trigger
as required but not exclusive.

The 2026-08-03 generated-answer run saved responses in:

```text
data/lightrag/benchmarks/ontology_query_benchmark_withanswer.json
generated_at: 20260803T124640Z
answer_run_count: 9
answer_error_count: 0
total_answer_bytes: 72681
```

Generated answers are a utility signal, not the canonical gate. The graph and
context checks remain the blocking validation path; answer prose can still need
prompt tuning even when routing and retrieval are correct.

## Previous Validated WSTG KB And Pending Rebuild

As of 2026-07-28, the local LightRAG server is healthy on:

```text
http://127.0.0.1:9621
```

Runtime details observed from `/health`:

```text
core_version: 1.5.0rc3
pipeline_busy: false
pipeline_pending_enqueues: 0
```

The full static WSTG staged corpus has been loaded into the local LightRAG
store under `data/lightrag/rag_storage`. The final document status is:

```text
processed: 119
failed: 0
all: 119
```

The staged corpus has 12 batches: batch `0` is the fixed 9-document smoke
subset, and batches `1` through `11` are sorted 10-document batches. Batch `11`
is the last staged batch:

```text
wstg-sess-02-methodology.md
wstg-sess-03-methodology.md
wstg-sess-04-methodology.md
wstg-sess-05-methodology.md
wstg-sess-06-methodology.md
wstg-sess-07-methodology.md
wstg-sess-08-methodology.md
wstg-sess-09-methodology.md
wstg-sess-10-methodology.md
wstg-sess-11-methodology.md
```

Final graph gate:

```text
graph_gate passed: true
entities: 2873
relations: 2379
unknown/cannot-canonicalize entities: 0
expected type mismatches: 0
blocking noise entities: 0
non-canonical type labels: 0
missing required smoke entities: 0
missing required smoke source files: 0
```

Final smoke core:

```text
passed: true
normalization planned_updates: 0
normalization planned_noise_deletes: 0
normalization failed: 0
blocking targeted queries: passed
wstg_bypass_relations: passed
```

This live validated store predates the 2026-07-30 ontology-query anchor update.
Do not treat the new anchors as available to retrieval until the store has been
reset and rebuilt from `data/lightrag/inputs/wstg_preprocessed`.

The local test suite for the LightRAG package passed after the final gate
updates:

```text
81 passed
```

### Stabilization Notes

The final WSTG run required durable fixes in code rather than manual graph
edits:

- `agent/lightrag/preprocess.py` skips removed-placeholder documents whose
  body is only `This content has been removed`.
- `agent/lightrag/graph_audit.py` contains deterministic aliases and expected
  type mappings for recurring LightRAG extraction variants, including SQL
  dialect entities, file inclusion entities, template/session entities, cookie
  attributes, SameSite values, and session-management testing terms.
- `agent/lightrag/graph_audit.py` also deletes generic graph noise such as
  `Source`, `Target`, `Name`, and `Type` when they are extracted as standalone
  entities.

The `WSTG-INPV-13` "Testing for Buffer Overflow" placeholder was initially
uploaded during batch `10`. After preprocessing was fixed, the stale
`wstg-inpv-13-methodology.md` document was deleted from LightRAG and
`wstg-sess-01-methodology.md` was uploaded to keep the staged batch boundary
aligned with the regenerated corpus. Future full regenerations should not emit
or upload `wstg-inpv-13-methodology.md`.

### Runbook

Example one-batch continuation command, using the repository virtual
environment:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --upload-staged-wstg \
  --start-batch 11 \
  --max-batches 1 \
  --batch-size 5 \
  --normalize-types \
  --log-ingestion-history \
  --run-label wstg-clean-rebuild \
  --query-after-each-batch \
  --include-scenario-queries \
  --scenario-query-limit 5 \
  --skip-diagnostic-queries \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

For a graph-only gate on an already loaded store:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --normalize-types \
  --skip-queries \
  --timeout 1800 \
  --poll 10
```

For the final smoke core after graph stabilization:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --normalize-types \
  --skip-diagnostic-queries \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

If a manual upload or delete was performed and only processing state must be
checked, wait for the expected document count:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --wait-documents 119 \
  --normalize-types \
  --skip-queries \
  --timeout 1800 \
  --poll 10
```

Shell hygiene matters for manual multiline commands. In `zsh`, every continued
line must end with `\`; otherwise options such as `--reset-store` or
`--normalize-types` are executed as separate commands.

## Maintenance Workflow

1. Inspect the current graph audit details if more offline triage is needed:

```bash
.venv/bin/python -m agent.lightrag.graph_audit \
  data/lightrag/rag_storage/graph_chunk_entity_relation.graphml
```

2. Classify each remaining `UNKNOWN`, `concept`, `other`, or
   non-canonical entity type as one of:

```text
preprocessing noise to remove upstream
valid entity requiring deterministic type mapping
acceptable LightRAG extraction that needs a canonicalization alias
```

3. Fix durable causes in `agent/lightrag/preprocess.py`,
   `agent/lightrag/graph_audit.py`, or the entity prompt. Avoid manual graph
   edits as the primary solution.

4. Review `wstg_bypass_relations`. If the answer is semantically good but the
   allow-list term is too strict for the currently loaded corpus, either improve
   source grounding for allow-list controls or split the bypass gate into
   source-specific checks instead of weakening the whole gate.

5. For a full rebuild, reset the store and reload staged WSTG from batch `0`.
   Keep `--timeout 1800` and `--poll 10`; individual batches can take several
   minutes depending on provider throughput:

```bash
.venv/bin/python -m agent.lightrag.smoke \
  --base-url http://127.0.0.1:9621 \
  --reset-store \
  --upload-staged-wstg \
  --batch-size 5 \
  --normalize-types \
  --log-ingestion-history \
  --run-label wstg-clean-rebuild \
  --skip-diagnostic-queries \
  --fail-on-issues \
  --timeout 1800 \
  --poll 10
```

6. Writeups remain overlay material. They should not be mixed into the static
   WSTG base until their generated relation briefs are reviewed and promoted.
   This avoids overfitting the base graph to machine-specific exploitation
   narratives.
