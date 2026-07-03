from typing import Callable

from agent.recon.types import AssetDelta
from agent.recon.parsers.httpx_parser import parse as parse_httpx
from agent.recon.parsers.subdomain_parser import parse_subfinder, parse_amass
from agent.recon.parsers.dns_parser import parse_dnsx, parse_puredns
from agent.recon.parsers.whois_parser import parse as parse_whois
from agent.recon.parsers.naabu_parser import parse as parse_naabu

PARSERS: dict[str, Callable[[str], list[AssetDelta]]] = {
    "httpx": parse_httpx,
    "subfinder": parse_subfinder,
    "amass": parse_amass,
    "dnsx": parse_dnsx,
    "puredns": parse_puredns,
    "whois": parse_whois,
    "naabu": parse_naabu,
}


def get_parser(tool: str) -> Callable[[str], list[AssetDelta]]:
    return PARSERS[tool]
