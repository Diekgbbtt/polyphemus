# LightRAG Document Preprocessor v0.3.4

A **source-aware, semantics-free** preprocessing layer that converts heterogeneous methodology sources into clean Markdown plus provenance for later LightRAG ingestion.

## Responsibility boundary

```text
SOURCE
  -> source/format router
  -> source-aware adapter when appropriate
  -> structural normalization
  -> document.md + document.json
  -> LightRAG
       chunking
       entity extraction
       relationship extraction
       ontology typing
       knowledge graph
```

The preprocessor understands **format and source structure**. LightRAG understands **meaning**.

It does **not** generate ontology entities, relation briefs, attack-chain summaries, technique cards, embeddings, chunks, or graph edges. A model guard rejects ontology-style keys such as `VulnerabilityClass` or `AttackTechnique` if an adapter attempts to place them in `native_metadata`.

## Source profiles

`--profile auto` is the default.

- `wstg`: WSTG Markdown. Keeps original wording and structure; extracts native WSTG ID/category/title.
- `0xdf`: 0xdf HTML writeups. Extracts the article body, removes site chrome/TOC/tag navigation, preserves code, and stores canonical URL/date/tags as native metadata.
- `generic`: disables WSTG/0xdf specialization.
- `auto`: conservatively detects WSTG and 0xdf, otherwise uses generic adapters.

## Supported inputs

The CLI accepts either local files/directories or `http://` / `https://` URLs. URL responses are downloaded to a temporary typed file and then sent through the same router shown below. Type detection prefers HTTP `Content-Type`, then `Content-Disposition`, URL extension, and finally conservative file-signature sniffing.


| Input | Preferred route |
|---|---|
| WSTG `.md/.markdown` | WSTG adapter → Markdown fallback |
| 0xdf `.html/.htm` | 0xdf adapter → generic HTML → Docling fallback |
| Generic `.md/.markdown/.txt` | built-in Markdown/plain-text parser |
| Generic `.html/.htm` | built-in main-content HTML parser → Docling fallback |
| PDF | MinerU → Docling → PyMuPDF4LLM by default |
| DOCX / PPTX / XLSX | Docling → MinerU |
| PNG / JPG / JPEG / TIFF / BMP | Docling → MinerU |
| WEBP | Docling |

Heavy parsers are optional and imported lazily.

## Installation

Core + tests:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e '.[test]'
python -m pytest -q
```

Docling + PyMuPDF4LLM:

```bash
python -m pip install -e '.[all,test]'
```

MinerU is used through its external `mineru` CLI. Install MinerU separately and make sure this works:

```bash
mineru --version
```

## CLI

URL-first usage (no flags required):

```bash
lightrag-docprep "https://example.com/security-guide"
```

The default output root is `./normalized`. A URL may resolve to HTML, PDF, DOCX, PPTX, XLSX, Markdown/text, or a supported image based on HTTP metadata and content detection. Redirects are followed and the final URL is retained as provenance.

Local source (also works without `--output`):

```bash
lightrag-docprep source.pdf
```

Override the output root when desired:

```bash
lightrag-docprep source.pdf --output normalized/
```

Directory recursively:

```bash
lightrag-docprep /path/to/corpus --output normalized/
```

Explicit profiles:

```bash
lightrag-docprep /path/to/wstg --profile wstg --output normalized/wstg
lightrag-docprep /path/to/0xdf --profile 0xdf --output normalized/0xdf
lightrag-docprep page.html --profile generic --output normalized/html
```

PDF parser priority:

```bash
lightrag-docprep paper.pdf --output normalized/pdf --preferred-pdf-parser docling
```

Filename hints still work:

```text
paper.[mineru].pdf
paper.[docling].pdf
paper.[pymupdf4llm].pdf
```

## Output

Every successful source creates exactly:

```text
normalized/
  <doc_id>/
    document.md
    document.json
```

`document.md` contains only clean source content for LightRAG.

`document.json` contains provenance and structure, including:

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

Examples of allowed native metadata are URL provenance (`source_url`, `resolved_url`, `http_content_type`), WSTG ID/category, canonical URL, publication date and source tags. Inferred ontology entities are not allowed there.

## URL ingestion notes

- Only `http://` and `https://` are accepted as web sources.
- HTTP redirects are followed.
- Downloads are streamed and capped at 50 MiB.
- Temporary downloaded files are deleted after parsing, including failure paths.
- URL acquisition does not parse documents; it only materializes a correctly typed temporary source and hands it to the existing parser router.
- JavaScript/browser rendering, crawling, authentication, and LightRAG invocation are intentionally outside this package.

## Parser notes

- Generic HTML prefers `article`, then `main`, then `role=main`, common content containers, then `body`.
- 0xdf has a dedicated adapter so global navigation/footer noise is not sent to LightRAG.
- Parser-generated assets are never persisted by the output contract.
- MinerU runs inside a temporary directory and only its selected Markdown is retained.
- PyMuPDF4LLM is configured not to write or embed images.
- Docling exports its unified document to Markdown.
- Docling output then passes through a Docling-specific structural postprocessor: empty `<!-- image -->` placeholders are removed, redundant `Contents`/`Table of Contents`/`List of Contents` sections are dropped, and numbered heading depth is normalized when a top-level numbered heading anchor is present.
- Docling-native items labelled `FOOTNOTE` are handled conservatively. If one or more labelled footnotes interrupt an obviously unfinished body/list block and the next block begins like a continuation, the surrounding text is rejoined and the exact footnote text is retained immediately after it as a Markdown blockquote. Numeric-looking paragraphs that Docling did not label as footnotes are untouched.
- For paginated Docling documents, per-page Markdown views are used to assign best-effort starting `page_number` values to `document.json` blocks. Matching is monotonic and ambiguous/unmatched blocks remain `null`; page provenance never changes `document.md`.
- Docling list items split by a PDF page break are rejoined only when the list tail is unfinished, the next block is a lowercase-style continuation, and provenance places the two blocks on exactly adjacent pages. Same-page, ambiguous, complete-sentence, uppercase, structural, and cross-heading cases are left untouched.
- Docling postprocessing does not infer footnotes from numbering, rewrite prose, or add ontology semantics.

## Tests

```bash
python -m pytest -q
```

See [`examples/README.md`](examples/README.md) for a practical source-by-source test sequence.
