from __future__ import annotations

from pathlib import Path

from .models import DocumentModel


def render_markdown(document: DocumentModel) -> str:
    body_parts: list[str] = []
    for section in document.sections:
        if section.heading:
            body_parts.append(f"{'#' * max(1, min(section.level, 6))} {section.heading}")
        for block in section.blocks:
            if block.content.strip():
                body_parts.append(block.content.strip())
    body = "\n\n".join(body_parts).rstrip()
    return f"{body}\n" if body else ""


def export_document(document: DocumentModel, output_root: Path) -> Path:
    output_dir = Path(output_root) / document.doc_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "document.md").write_text(render_markdown(document), encoding="utf-8")
    (output_dir / "document.json").write_text(document.model_dump_json(indent=2), encoding="utf-8")
    return output_dir
