# Source-Aware Document Preprocessing Design

Status: approved architecture draft.

## Goal

Build a preprocessing layer that transforms heterogeneous methodology sources into clean, structurally faithful Markdown and metadata for later LightRAG ingestion.

The preprocessor is responsible for understanding **format and source structure**, not for interpreting methodology semantics.

LightRAG remains responsible for:

- chunking;
- entity extraction;
- relationship extraction;
- ontology application;
- knowledge graph construction.

## Core Principle

> The preprocessor understands the source. LightRAG understands the meaning.

The preprocessing layer may apply deterministic source-specific knowledge when that knowledge is directly observable from the source format or source family.

It must not infer or synthesize semantic methodology concepts that belong to the LightRAG ontology.

## High-Level Flow

```text
SOURCE
  |
  v
Source Router
  |
  +-- WSTG Markdown Adapter
  +-- 0xdf Writeup Adapter
  +-- Generic Markdown Adapter
  +-- Generic HTML Adapter
  +-- PDF Adapter
  +-- DOCX Adapter
  +-- PPTX Adapter
  +-- XLSX Adapter
  +-- Image Adapter
  |
  v
Normalized DocumentModel
  |
  +-- document.md
  +-- document.json
  |
  v
LIGHTRAG
  |
  +-- chunking
  +-- entity extraction
  +-- relationship extraction
  +-- ontology typing
  +-- knowledge graph
```

## Responsibility Boundary

### Preprocessor MUST do

- identify the source type;
- extract the primary document content;
- remove navigation, footer, boilerplate and parser noise;
- preserve headings and hierarchy;
- preserve paragraphs;
- preserve lists;
- preserve tables;
- preserve fenced code and command output;
- preserve formulas where available;
- preserve meaningful captions / image text;
- extract native metadata such as title, source URL, publication date, tags or WSTG ID when directly present;
- normalize encoding and whitespace conservatively;
- keep provenance in JSON;
- emit stable, source-agnostic output.

### Preprocessor MUST NOT do

- chunking for LightRAG;
- entity extraction;
- relationship extraction;
- ontology typing;
- graph construction;
- embeddings;
- semantic rewriting of source material;
- keyword-to-ontology mapping;
- attack-chain synthesis;
- technique-card generation;
- relation-brief generation;
- ontology query anchors;
- vulnerability-class inference;
- payload / artifact / observable-signal classification.

## Existing WSTG Support

The existing WSTG preprocessing logic should be retained only where it reflects deterministic source knowledge.

### Keep

- Markdown parsing;
- WSTG ID detection;
- WSTG category detection when derivable from source/path;
- WSTG title detection;
- heading hierarchy;
- table, list and code preservation;
- source-specific noise cleanup that does not alter meaning;
- source metadata extraction.

### Remove from production preprocessing

- `_WSTG_ONTOLOGY_QUERY_ANCHORS`;
- ontology anchor rendering;
- canonical relation anchor rendering;
- facet classification used to reshape methodology;
- synthetic attack-method / prerequisite / defense documents;
- source rewriting that changes wording or semantic framing;
- hard-coded compact methodology cards for specific WSTG scenarios.

The removed semantic mappings may be retained separately as evaluation fixtures / expected extraction data.

## Existing 0xdf Writeup Support

The existing 0xdf HTML handling should be retained as the preferred adapter for 0xdf writeups.

### Keep

- article/main/content-body extraction;
- removal of script/style/nav/footer;
- HTML-to-Markdown structural conversion;
- heading preservation;
- `<pre>` / command-output preservation;
- list preservation;
- title extraction;
- canonical URL extraction;
- publication date extraction;
- source tag extraction;
- optional manifest metadata merge.

### Remove from production preprocessing

- `WRITEUP_CONCEPT_PATTERNS`;
- ontology-like concept detection;
- semantic facet classification;
- Attack Chain Summary generation;
- Technique Cards;
- Technology And Preconditions synthesis;
- Artifacts And Attacker Capabilities synthesis;
- Defensive Controls And Bypasses synthesis;
- Relation Briefs synthesis.

Those mappings can be moved to evaluation fixtures if useful for regression testing against LightRAG extraction.

## New Source Adapters

### Generic Markdown

Use the existing structural Markdown parser.

Supported:
- `.md`
- `.markdown`
- optionally `.txt` as plain text fallback.

### Generic HTML

Use a conservative main-content extraction strategy:

1. prefer `<article>`;
2. then `<main>`;
3. then `role="main"`;
4. then common content containers;
5. finally fall back to body.

Remove obvious structural noise such as:
- `script`;
- `style`;
- `nav`;
- `footer`;
- `aside` when clearly non-content;
- known modal/cookie boilerplate only through generic heuristics.

Avoid site-specific selectors except in explicit source adapters such as 0xdf.

### PDF

Preferred parser order:

1. MinerU for complex/scanned PDFs when available;
2. Docling for structured document extraction;
3. PyMuPDF4LLM as lightweight fallback.

No parser-generated asset directories are persisted.

### DOCX / PPTX / XLSX

Primary adapter: Docling.

Goal: convert document structure to Markdown while preserving headings, lists, tables and readable text blocks.

### Standalone Images

Use OCR / vision extraction only when the image contains meaningful textual or diagrammatic information.

The final output remains textual. No persistent image assets are required by the preprocessing contract.

## Unified Output Contract

For each source document:

```text
output/
  <doc_id>/
    document.md
    document.json
```

### document.md

Contains only clean source content suitable for LightRAG ingestion.

No parser metadata or pipeline front matter.

### document.json

Contains provenance and structural metadata, for example:

```json
{
  "doc_id": "...",
  "title": "...",
  "source_path": "...",
  "source_type": "...",
  "source_profile": "wstg | 0xdf | generic | null",
  "parser_engine": "...",
  "processed_at": "...",
  "warnings": [],
  "native_metadata": {},
  "sections": []
}
```

`native_metadata` may contain source-observed metadata such as:

- WSTG ID;
- WSTG category;
- canonical URL;
- publication date;
- author;
- tags.

It must not contain inferred ontology entities.

## Router Strategy

Routing should separate **format routing** from **source-profile routing**.

Example:

```text
.md under WSTG corpus
  -> WSTG adapter

.html recognized as 0xdf writeup
  -> 0xdf adapter

other .html
  -> Generic HTML adapter

.pdf
  -> MinerU / Docling / PyMuPDF4LLM fallback chain

.docx/.pptx/.xlsx
  -> Docling

other .md
  -> Generic Markdown adapter
```

Source-profile detection should be conservative and explicit where possible.

A CLI option such as `--profile wstg`, `--profile 0xdf`, or `--profile auto` is acceptable, with `auto` as default only when detection is reliable.

## Evaluation Reuse

The semantic mappings from the old preprocessor should not be discarded.

Move them into a separate evaluation layer, for example:

```text
evaluation/
  wstg_expected_entities.yml
  writeup_expected_entities.yml
  expected_relations.yml
```

They can then be used to compare LightRAG extraction against known expected concepts without leaking those answers into the ingestion corpus.

## Non-Goals

This project does not:

- tune LightRAG prompts;
- configure entity types;
- run LightRAG ingestion;
- generate graph edges;
- evaluate retrieval quality yet;
- rewrite source methodology into synthetic summaries.

## Success Criteria

The preprocessing layer is successful when:

1. WSTG and 0xdf outputs are at least as structurally clean as the existing specialized preprocessor outputs;
2. source-specific boilerplate is removed without losing technical content;
3. code, commands, tables, headings and attack-flow prose survive conversion;
4. PDF/DOCX/PPTX/XLSX/HTML/image sources converge to the same output contract;
5. no ontology entities or relationships are injected before LightRAG;
6. the output remains readable and traceable to its original source.
