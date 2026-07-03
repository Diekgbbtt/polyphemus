"""Pure parser: `whois` stdout (raw key: value text) -> list[AssetDelta].

Ported from Redamon's `main_recon_modules/whois_recon.py::whois_to_dict`.
That function converts a `python-whois` library result object into a
clean dict; only the *set of fields it cares about* (registrar,
creation_date, expiration_date, name servers, ...) is ported here. The
actual parsing strategy differs: Redamon's `whois_lookup` calls the
`python-whois` library and gets back a structured dict-like object, but
this recon pipeline shells out to the `whois` CLI directly, whose stdout
is raw, unstructured `Key: value` text (the classic WHOIS/RDAP text
format). So this parser line-parses that raw text instead of ported
Python-object access, tolerating the field-name variants different
registries emit for the same concept (e.g. "Registry Expiry Date" vs
"Expiration Date" vs "Expiry Date").

Pure, deterministic, tolerant of missing/malformed lines - never raises.
"""

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


def parse(stdout: str) -> list[AssetDelta]:
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

    if not domain_name:
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
        props["name_servers"] = name_servers

    return [
        AssetDelta(
            type="Domain",
            identity={"name": domain_name},
            props=props,
        )
    ]
