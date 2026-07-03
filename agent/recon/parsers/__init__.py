from typing import Callable

from agent.recon.types import AssetDelta
from agent.recon.parsers.httpx_parser import parse as parse_httpx

PARSERS: dict[str, Callable[[str], list[AssetDelta]]] = {
    "httpx": parse_httpx,
}


def get_parser(tool: str) -> Callable[[str], list[AssetDelta]]:
    return PARSERS[tool]
