from typing import Callable

from agent.recon.types import AssetDelta
from agent.recon.parsers.httpx_parser import parse as parse_httpx
from agent.recon.parsers.subdomain_parser import parse_subfinder, parse_amass
from agent.recon.parsers.dns_parser import parse_dnsx, parse_puredns

PARSERS: dict[str, Callable[[str], list[AssetDelta]]] = {
    "httpx": parse_httpx,
    "subfinder": parse_subfinder,
    "amass": parse_amass,
    "dnsx": parse_dnsx,
    "puredns": parse_puredns,
}


def get_parser(tool: str) -> Callable[[str], list[AssetDelta]]:
    return PARSERS[tool]
