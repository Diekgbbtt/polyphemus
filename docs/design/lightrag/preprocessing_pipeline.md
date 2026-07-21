# LightRAG Preprocessing Pipeline

Status: MVP implementation note.

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

The current LightRAG ontology may extract:

```text
AttackTechnique
DefensiveTechnology
EnvironmentalCondition
VulnerabilityClass
```

from those documents, but changing the ontology later should not require
changing the preprocessing strategy. A future ontology can re-index the same
preprocessed documents and extract finer concepts such as payload patterns,
detection signals, trust boundaries, or exploit primitives.

The implementation lives in `agent/lightrag/preprocess.py`.

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
headings, line ranges, code or payload examples, references, and test sections.
It writes one scenario-scoped composite document:

```text
<wstg-id>-methodology.md
.manifest.json
```

`<wstg-id>-methodology.md` is the primary LightRAG input. It contains
deterministic sections for metadata, overview, objectives, attack methods,
prerequisites, defenses, code/payload examples, references, source context, and
relation briefs. This avoids a large number of tiny files while still giving
LightRAG structured headings to chunk against.

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

`ENTITY_EXTRACTION_USE_JSON=false` is deliberate for the current OpenRouter
test route. The first ingestion attempt with `tencent/hy3:free` failed because
the provider behind the route rejected `response_format=json_object` and only
advertised `json_schema`.

The local WSTG preprocessor still runs before LightRAG. LightRAG 1.5 improves
file parsing and chunking, but it does not know which WSTG sections should act
as planner methodology evidence.

## Operational Notes

Indexing WSTG chapters is expected to be slow on free OpenRouter routes. The
first SQL Injection chapter upload produced LightRAG work items like:

```text
C[1/28]: doc-...-chunk-001
```

That means the one composite Markdown document was split into 28 LightRAG chunks,
and each chunk can trigger extraction/model calls. On slow or rate-limited free
models, processing can look stalled even when it is still progressing.

If iteration speed matters more than graph quality, test with a smaller excerpt
or temporarily lower LightRAG chunk size only after clearing
`data/lightrag/rag_storage`. If graph quality matters, keep the scenario
composite intact and wait for indexing to complete.
