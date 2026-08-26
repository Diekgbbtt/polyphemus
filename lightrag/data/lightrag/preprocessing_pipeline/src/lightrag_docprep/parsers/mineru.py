from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from ..errors import ParserExecutionError, ParserUnavailableError
from ..models import RawParseResult
from .base import ParserAdapter


class MinerUParser(ParserAdapter):
    name = "mineru"
    supported_suffixes = frozenset({
        ".pdf", ".docx", ".pptx", ".xlsx",
        ".png", ".jpg", ".jpeg", ".tiff", ".bmp",
    })

    def is_available(self) -> bool:
        return shutil.which("mineru") is not None

    @staticmethod
    def _select_markdown(output_root: Path, source_stem: str) -> Path:
        candidates = list(output_root.rglob("*.md"))
        if not candidates:
            raise ParserExecutionError("MinerU produced no Markdown output")
        matching = [p for p in candidates if source_stem.lower() in p.stem.lower()]
        pool = matching or candidates
        return max(pool, key=lambda p: p.stat().st_size)

    async def parse(self, path: Path) -> RawParseResult:
        if not self.is_available():
            raise ParserUnavailableError("MinerU CLI is not installed or not on PATH")

        with tempfile.TemporaryDirectory(prefix="lightrag-docprep-mineru-") as tmp:
            output_root = Path(tmp)
            process = await asyncio.create_subprocess_exec(
                "mineru",
                "-p",
                str(path),
                "-o",
                str(output_root),
                "-m",
                "auto",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                message = stderr.decode("utf-8", errors="replace").strip()
                if not message:
                    message = stdout.decode("utf-8", errors="replace").strip()
                raise ParserExecutionError(
                    f"MinerU failed with exit code {process.returncode}: {message[:1000]}"
                )
            markdown_path = self._select_markdown(output_root, path.stem)
            markdown = markdown_path.read_text(encoding="utf-8", errors="replace").strip()

        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            markdown=markdown,
            source_profile="generic",
        )
