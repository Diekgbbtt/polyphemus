"""Target scope descriptor: exact-host vs wildcard-zone (forward decision D14).

The pipeline has historically had NO scope concept: it seeded the root asset as
a bare domain string and subfinder/amass always fanned out to discover
subdomains, regardless of whether the operator meant "this exact host" or "the
whole zone". `parse_scope` gives the raw `target_domain` setting a shape the
pipeline uses to:

- (D14) gate subdomain-discovery jobs on wildcard mode - in exact mode the
  discovery phase (subfinder/amass + the puredns/dnsx expansion that follows)
  is suppressed and recon proceeds on the single seeded host;
- (D11) seed the primary host into the Subdomain input population so its own
  web origin is HTTP-probed (the apex was previously modeled only as a `Domain`
  node, never in httpx's `consumes="Subdomain"` input set, so its BaseURL stayed
  an unenriched stub).

`subdomain_takeover` is deliberately NOT part of `DISCOVERY_JOBS`: using an
out-of-scope asset as a *parameter* to a takeover check is valid, so takeover
scanning stays enabled regardless of the exact/wildcard decision (D14 carve-out).

Pure, deterministic - never raises.
"""
from __future__ import annotations

import ipaddress

from polymerhus.recon.domain.parsers._urls import registrable_domain

# Subdomain-discovery jobs suppressed in `exact` mode (D14). Deliberately
# excludes subdomain_takeover (see module docstring) and whois/gau/paramspider
# (registration lookup / passive harvest, not subdomain enumeration).
DISCOVERY_JOBS = frozenset({"subfinder", "amass", "puredns", "dnsx"})

# Jobs additionally suppressed in `host` (bare-IP) mode (D-HS2): a WHOIS or
# passive-archive harvest keyed on a bare IP is low-to-zero signal and risks
# off-scope fan-out, so neither runs when the seed is an IP.
HOST_MODE_SUPPRESSED = frozenset({"whois", "paramspider"})

# Jobs that run ONLY in `host` mode (D-HS2): the httpx_services Service->BaseURL
# bridge reaches web apps on non-standard ports and would mint host-vs-IP alias
# BaseURLs in a domain run, so it is fenced to bare-IP seeding.
HOST_MODE_ONLY_JOBS = frozenset({"httpx_services"})

_DEFAULT_APEX = "example.com"


def resolve_seed(settings: dict | None) -> str | None:
    """The Project's target seed string, seed-type-agnostic (D-HS1).

    `target_seed` is the canonical key; `target_domain` is the deprecated alias,
    still read so already-persisted projects launch unchanged (regression
    safety). Returns None when neither is set to a non-empty value."""
    s = settings or {}
    return (s.get("target_seed") or s.get("target_domain")) or None


def seed_kind(raw: str | None) -> str:
    """Classify a raw seed as `'ipv4'`, `'ipv6'`, or `'domain'`.

    Pure and non-raising: anything `ipaddress` rejects (a hostname, a malformed
    or partial IP like `1.2.3` or `999.1.1.1`, the empty string) is a
    `'domain'`."""
    s = (raw or "").strip()
    if not s:
        return "domain"
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return "domain"
    return "ipv6" if ip.version == 6 else "ipv4"


def _strip_www(host: str) -> str:
    """Drop a leading `www.` label - www.<x> is the same web content as <x>, so
    seeding either resolves to the same scope (dedup, D-www)."""
    return host[4:] if host.startswith("www.") else host


def _strip_authority(raw: str) -> str:
    """The `host[:port]` part of a raw seed, scheme/path/userinfo removed.

    A Seed may be a bare host, a `host:port`, or a full URL (`http://host:port`);
    the scope keys on the host, so the scheme, path, query, fragment, and
    userinfo are dropped here (the numeric port is dropped by `_bare_host`).
    Never raises."""
    s = raw
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return s.rsplit("@", 1)[-1]


def _bare_host(authority: str) -> str:
    """Bare host from a `host` / `host:port` string: drop a numeric trailing
    port, lowercase, strip a trailing dot. An IPv6 literal is caught by the
    host-mode safety net before this runs, so its colons are not a port."""
    head, sep, tail = authority.rpartition(":")
    if sep and tail.isdigit():
        authority = head
    return authority.rstrip(".").lower()


def seed_probe_target(target: str | None) -> str:
    """The authority-bearing string to HTTP-probe for a raw Seed.

    A Seed may carry a scheme and/or port; `parse_scope`'s `seed_host` is the
    bare host (the scope key and graph identity), so the probe target is carried
    separately here: it preserves the scheme and port so the probe reaches the
    seeded service, while normalizing the host exactly like `parse_scope`
    (lowercase, `www.` and `*.` folded, trailing dot stripped). Pure, never
    raises; returns `""` for an empty seed."""
    raw = (target or "").strip().lower()
    if not raw:
        return ""
    if seed_kind(raw) == "ipv6":
        return raw

    scheme = ""
    rest = raw
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
    rest = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    rest = rest.rsplit("@", 1)[-1]
    if rest.startswith("*."):
        rest = rest[2:]
    head, sep, tail = rest.rpartition(":")
    host, port = (head, tail) if sep and tail.isdigit() else (rest, "")
    host = _strip_www(host.rstrip("."))
    if not host:
        return ""
    authority = f"{host}:{port}" if port else host
    return f"{scheme}://{authority}" if scheme else authority


def parse_scope(target: str | None) -> dict:
    """Parse a raw `target_domain` into a scope descriptor.

    Returns `{"apex", "seed_host", "mode"}`:

    - a bare IP (`"93.184.216.34"`) -> `{apex: <ip>, seed_host: <ip>,
      mode: "host"}` (D-HS2) - the IP IS the scope, subdomain discovery and the
      passive harvesters are suppressed, and the IP is seeded/probed directly.
      An IPv6 also returns `host` mode (never mis-parsed as a domain), but the
      launch guard rejects it before any run starts (D-HS3).
    - `"*.example.com"` -> `{apex: "example.com", seed_host: "example.com",
      mode: "wildcard"}` - the whole zone is in scope, discovery runs, and the
      apex host itself is still probed (D11).
    - `"example.com"` or `"app.example.com"` -> `{apex: <registrable>,
      seed_host: <the host>, mode: "exact"}` - that single host IS the scope,
      discovery is suppressed, and the host is seeded into the post-discovery
      input set.

    A Seed may carry a scheme and/or port (`http://app.example.com:8443`); the
    scope keys on the bare host, so the authority is stripped here (D-SEEDNORM).
    The authority is preserved for the probe by `seed_probe_target`, which the
    pipeline injects into the Subdomain-consuming probes.

    `apex` is the registrable parent (naive last-two-labels, matching the rest
    of the parser fleet), or the IP itself in host mode; `seed_host` is the exact
    host/IP the scope keys on (the authority-reaching probe target is
    `seed_probe_target`).
    """
    raw = (target or "").strip().lower()

    # D-HS3: an IPv6 seed is host mode (safety net), detected before authority
    # parsing - its colons are not a port separator.
    if seed_kind(raw) == "ipv6":
        return {"apex": raw, "seed_host": raw, "mode": "host"}

    # A Seed may carry a scheme and/or port; the scope keys on the bare host.
    authority = _strip_authority(raw)

    # Check the wildcard placeholder before trimming trailing dots, so a bare
    # `*.` is still recognized as (degenerate) wildcard rather than becoming `*`.
    if authority.startswith("*."):
        apex = _strip_www(_bare_host(authority[2:])) or _DEFAULT_APEX
        return {"apex": apex, "seed_host": apex, "mode": "wildcard"}

    host = _strip_www(_bare_host(authority))
    if not host:
        return {"apex": _DEFAULT_APEX, "seed_host": _DEFAULT_APEX, "mode": "exact"}

    if seed_kind(host) == "ipv4":
        return {"apex": host, "seed_host": host, "mode": "host"}

    return {"apex": registrable_domain(host), "seed_host": host, "mode": "exact"}
