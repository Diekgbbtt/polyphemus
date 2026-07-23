from typing import Callable

from polymerhus.recon.domain.types import AssetDelta
from polymerhus.recon.domain.parsers.httpx_parser import parse as parse_httpx
from polymerhus.recon.domain.parsers.subdomain_parser import parse_subfinder, parse_amass
from polymerhus.recon.domain.parsers.dns_parser import parse_dnsx, parse_puredns
from polymerhus.recon.domain.parsers.whois_parser import parse as parse_whois
from polymerhus.recon.domain.parsers.naabu_parser import parse as parse_naabu
from polymerhus.recon.domain.parsers.katana_parser import parse as parse_katana
from polymerhus.recon.domain.parsers.jsluice_parser import parse as parse_jsluice
from polymerhus.recon.domain.parsers.passive_url_parser import parse_gau, parse_paramspider
from polymerhus.recon.domain.parsers.active_param_parser import parse_arjun, parse_ffuf, parse_kiterunner
from polymerhus.recon.domain.parsers.graphql_parser import parse as parse_graphql_cop
from polymerhus.recon.domain.parsers.takeover_parser import parse as parse_subdomain_takeover
from polymerhus.recon.domain.parsers.steel_parser import parse as parse_steel_crawl

PARSERS: dict[str, Callable[[str], list[AssetDelta]]] = {
    "httpx": parse_httpx,
    # Reprofile job (D27): same parser as httpx, so the re-probed BaseURLs get a
    # `profile` via the identical classify_profile path. Reuse, not duplication.
    "httpx_reprofile": parse_httpx,
    "subfinder": parse_subfinder,
    "amass": parse_amass,
    "dnsx": parse_dnsx,
    "puredns": parse_puredns,
    "whois": parse_whois,
    "naabu": parse_naabu,
    "katana": parse_katana,
    "jsluice": parse_jsluice,
    "gau": parse_gau,
    "paramspider": parse_paramspider,
    "arjun": parse_arjun,
    "ffuf": parse_ffuf,
    "kiterunner": parse_kiterunner,
    "graphql-cop": parse_graphql_cop,
    "subdomain_takeover": parse_subdomain_takeover,
    "steel_crawl": parse_steel_crawl,
}


def get_parser(tool: str) -> Callable[[str], list[AssetDelta]]:
    return PARSERS[tool]
