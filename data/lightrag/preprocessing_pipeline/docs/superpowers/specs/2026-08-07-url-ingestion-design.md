# URL Ingestion Design

**Goal:** Allow the CLI to accept a public `http://` or `https://` URL as its only required argument and produce the same normalized `document.md` and `document.json` artifacts already produced for local files.

## Architecture

Add a thin acquisition layer in front of the existing parser router:

`URL -> URLFetcher -> typed temporary file -> existing ParserRouter -> existing parser/postprocessor -> DocumentModel -> exporters`

`URLFetcher` is responsible only for HTTP retrieval, redirects, bounded download size, and source-type detection. It never interprets document semantics and never duplicates PDF/HTML/Office parsing logic.

## CLI contract

The minimal command is:

```bash
lightrag-docprep "https://example.com/document"
```

`--output` becomes optional and defaults to `normalized`. Existing local-file and directory usage remains supported.

## Type detection

Detection priority:

1. HTTP `Content-Type` when it maps to a supported type.
2. `Content-Disposition` filename extension.
3. Final redirected URL path extension.
4. Original URL path extension.
5. Conservative content sniffing for PDF, HTML, ZIP-based Office formats, and common image signatures.

Unknown content is rejected rather than guessed.

## Provenance

The parser receives a temporary local path but the final model uses the original URL as `source_path`. Structural web provenance is stored in `native_metadata`:

- `source_url`
- `resolved_url`
- `http_content_type`

No semantic metadata is added.

## Safety and robustness

- Only `http` and `https` URLs are accepted.
- Redirects are followed.
- A normal browser-like User-Agent is sent.
- Downloads are streamed and capped at 50 MiB by default.
- Temporary files are deleted after parsing, whether parsing succeeds or fails.
- Existing parser timeout remains separate from HTTP fetch timeout.

## Non-goals

- No browser/JavaScript rendering fallback.
- No crawling of links.
- No authentication/session management.
- No semantic extraction or LightRAG invocation.
- No source-specific web rules beyond the existing WSTG/0xdf profiles.
