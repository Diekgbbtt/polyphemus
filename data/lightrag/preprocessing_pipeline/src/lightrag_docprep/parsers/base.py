from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import RawParseResult


class ParserAdapter(ABC):
    name: str
    supported_suffixes: frozenset[str]

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def parse(self, path: Path) -> RawParseResult:
        raise NotImplementedError

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_suffixes
