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

from agent.recon.parsers._urls import registrable_domain

# Subdomain-discovery jobs suppressed in `exact` mode (D14). Deliberately
# excludes subdomain_takeover (see module docstring) and whois/gau/paramspider
# (registration lookup / passive harvest, not subdomain enumeration).
DISCOVERY_JOBS = frozenset({"subfinder", "amass", "puredns", "dnsx"})

_DEFAULT_APEX = "example.com"


def parse_scope(target: str | None) -> dict:
    """Parse a raw `target_domain` into a scope descriptor.

    Returns `{"apex", "seed_host", "mode"}`:

    - `"*.example.com"` -> `{apex: "example.com", seed_host: "example.com",
      mode: "wildcard"}` - the whole zone is in scope, discovery runs, and the
      apex host itself is still probed (D11).
    - `"example.com"` or `"app.example.com"` -> `{apex: <registrable>,
      seed_host: <the host>, mode: "exact"}` - that single host IS the scope,
      discovery is suppressed, and the host is seeded into the post-discovery
      input set.

    `apex` is the registrable parent (naive last-two-labels, matching the rest
    of the parser fleet); `seed_host` is the exact host to HTTP-probe.
    """
    raw = (target or "").strip().lower()

    # Check the wildcard placeholder before trimming trailing dots, so a bare
    # `*.` is still recognized as (degenerate) wildcard rather than becoming `*`.
    if raw.startswith("*."):
        apex = raw[2:].rstrip(".") or _DEFAULT_APEX
        return {"apex": apex, "seed_host": apex, "mode": "wildcard"}

    raw = raw.rstrip(".")
    if not raw:
        return {"apex": _DEFAULT_APEX, "seed_host": _DEFAULT_APEX, "mode": "exact"}

    return {"apex": registrable_domain(raw), "seed_host": raw, "mode": "exact"}
