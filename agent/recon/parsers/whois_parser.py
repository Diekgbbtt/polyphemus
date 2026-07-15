"""Pure parser: `whois` stdout (raw key: value text) -> list[AssetDelta].

Cares about a fixed set of fields (registrar, creation_date,
expiration_date, name servers, ...). This recon pipeline shells out to the
`whois` CLI directly, whose stdout is raw, unstructured `Key: value` text
(the classic WHOIS/RDAP text format), so this parser line-parses that raw
text, tolerating the field-name variants different registries emit for the
same concept (e.g. "Registry Expiry Date" vs "Expiration Date" vs "Expiry
Date").

Pure, deterministic, tolerant of missing/malformed lines - never raises.
"""

from urllib.parse import urlparse

from agent.recon.parsers._urls import registrable_domain
from agent.recon.types import AssetDelta

# Field-name variants (lowercased, colon-stripped) -> canonical key.
# Order within each tuple does not matter; first match wins per line.
_FIELD_ALIASES: dict[str, str] = {
    "domain name": "domain_name",
    "registrar": "registrar",
    "creation date": "creation_date",
    "created date": "creation_date",
    "created on": "creation_date",
    "registered on": "creation_date",
    "registry expiry date": "expiration_date",
    "expiration date": "expiration_date",
    "expiry date": "expiration_date",
    "registrar registration expiration date": "expiration_date",
    "updated date": "updated_date",
    "last updated on": "updated_date",
    "name server": "name_server",
    "name servers": "name_server",
}


def _apex_from_target(target_url: str | None) -> str | None:
    """Derive the registrable apex from the queried host (the pod's input asset).

    `target_url` is the host `whois` was run against - a bare host in practice
    (`whois consumes="Domain"`, seeded `{"name": <host>}`), but a full URL is
    tolerated by stripping scheme/port/`www.`. Returns the last-two-labels
    registrable parent (`app.daytona.io` -> `daytona.io`), the deterministic
    zone-level anchor for the Domain node. Returns `None` when no host is given.
    """
    if not target_url:
        return None
    host = target_url.strip().lower()
    if "://" in host:
        host = urlparse(host).netloc or host
    host = host.split("@")[-1].split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    return registrable_domain(host)


def parse(stdout: str, target_url: str | None = None) -> list[AssetDelta]:
    domain_name: str | None = None
    registrar: str | None = None
    creation_date: str | None = None
    expiration_date: str | None = None
    updated_date: str | None = None
    name_servers: list[str] = []

    for line in stdout.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue

        key, _, value = line.partition(":")
        value = value.strip()
        if not value:
            continue

        canonical = _FIELD_ALIASES.get(key.strip().lower())
        if canonical is None:
            continue

        if canonical == "domain_name":
            domain_name = domain_name or value.strip().lower()
        elif canonical == "registrar":
            registrar = registrar or value
        elif canonical == "creation_date":
            creation_date = creation_date or value
        elif canonical == "expiration_date":
            expiration_date = expiration_date or value
        elif canonical == "updated_date":
            updated_date = updated_date or value
        elif canonical == "name_server":
            name_servers.append(value.strip().lower())

    # Anchor the Domain node to the registrable apex derived from the QUERIED
    # host, not the raw `Domain Name:` line (D14b/D11): a non-registrable exact
    # host (e.g. `app.daytona.io`) whose whois text has no parseable
    # `Domain Name:` line would otherwise yield NO Domain node, starving the
    # later-phase Domain consumers (paramspider) of an anchor. The queried host
    # is deterministic and always present in a real run, so it is the reliable
    # anchor; the parsed `Domain Name:` is the fallback only when no queried host
    # is supplied (e.g. a direct parser unit-test call).
    anchor = _apex_from_target(target_url) or domain_name
    if not anchor:
        return []

    props: dict = {}
    if registrar is not None:
        props["registrar"] = registrar
    if creation_date is not None:
        props["creation_date"] = creation_date
    if expiration_date is not None:
        props["expiration_date"] = expiration_date
    if updated_date is not None:
        props["updated_date"] = updated_date
    if name_servers:
        # Registries commonly emit each NS twice (registry + registrar
        # sections); dedup while preserving first-seen order.
        props["name_servers"] = list(dict.fromkeys(name_servers))

    return [
        AssetDelta(
            type="Domain",
            identity={"name": anchor},
            props=props,
        )
    ]
