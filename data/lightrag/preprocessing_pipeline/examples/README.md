# Manual test matrix

Run these after activating the venv and installing the parser dependencies you want to test.

## 1. WSTG Markdown

```bash
lightrag-docprep /path/to/wstg_raw/4-Web_Application_Security_Testing/01-Information_Gathering \
  --profile wstg \
  --output normalized/wstg
```

Check that `document.md` preserves WSTG headings/tables/code and `document.json` contains `native_metadata.wstg_id` / category, with no ontology entities.

## 2. 0xdf HTML writeups

```bash
lightrag-docprep /path/to/writeups_raw/0xdf \
  --profile 0xdf \
  --output normalized/0xdf
```

Check that global Home/About/Tags/footer chrome is absent, technical prose/code remains, and URL/date/tags are stored in JSON when present.

## 3. Generic HTML

```bash
lightrag-docprep page.html --profile generic --output normalized/html
```

Check that the main/article body wins over navigation and footer.

## 4. PDF

Default fallback chain:

```bash
lightrag-docprep paper.pdf --output normalized/pdf
```

Force Docling:

```bash
lightrag-docprep paper.pdf --preferred-pdf-parser docling --output normalized/pdf-docling
```

Force PyMuPDF4LLM:

```bash
lightrag-docprep paper.pdf --preferred-pdf-parser pymupdf4llm --output normalized/pdf-pymupdf
```

Compare headings, tables, code, reading order and noise. For Docling output, also verify that empty `<!-- image -->` placeholders and redundant contents sections are absent, and that numbered headings such as `1`, `1.1`, `1.1.1` form a structural hierarchy. When Docling natively labels footnotes, check that interrupted body text is conservatively rejoined and the exact notes remain as blockquotes. In `document.json`, inspect `page_number`: confident matches should contain 1-based page numbers while ambiguous blocks remain `null`.

## 5. Office files

```bash
lightrag-docprep guide.docx slides.pptx table.xlsx --output normalized/office
```

Docling is attempted first.

## 6. Images

```bash
lightrag-docprep screenshot.png diagram.webp --output normalized/images
```

The output contract is textual; no persistent `assets/` directory should appear.

## 7. Plain text / generic Markdown

```bash
lightrag-docprep notes.txt guide.md --profile generic --output normalized/text
```

## Output checks

```bash
find normalized -type f | sort
find normalized -type d -name assets
```

Each document directory should contain only `document.md` and `document.json`; the second command should return nothing.
