"""Target URL normalization for hunting pods (#197).

The seed (`settings.recon.target_seed`, canonical via `resolve_seed`) is a bare
domain by contract. The pod needs a base URL (`scheme://host[:port]/`). This
module derives it defensively and fail-closed: a missing or non-normalizable seed
returns ``None`` so the dispatch seam can INIT-reject instead of guessing a host.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


def normalize_target_seed(seed: str | None) -> str | None:
    """Normalize a raw ``target_seed`` into a pod base URL ``scheme://host[:port]/``.

    Accepts a bare domain (``example.com``), a host:port (``example.com:8080``),
    an already-scheme'd URL (``https://example.com`` or ``http://example.com:8443/path``),
    and whitespace-padded variants. Always returns ``scheme://host[:port]/`` with a
    trailing slash and no path/query/fragment, or ``None`` when the input cannot be
    normalized (empty, whitespace, scheme without host, wildcard, or containing spaces).

    Failure is explicit ``None`` - the caller maps it to an INIT-rejection
    (``technical-infeasibility`` + ``init_validation``), never a guessed host.

    Input -> Output table (exact):

    - ``soupmarket.shop`` -> ``http://soupmarket.shop/``
    - ``example.com:8080`` -> ``http://example.com:8080/``
    - ``192.33.91.87`` -> ``http://192.33.91.87/``
    - ``192.33.91.87:8000`` -> ``http://192.33.91.87:8000/``
    - ``http://example.com`` -> ``http://example.com/``
    - ``https://example.com`` -> ``https://example.com/``
    - ``http://example.com:8443/api`` -> ``http://example.com:8443/`` (path stripped)
    - ``https://soupmarket.shop:443/`` -> ``https://soupmarket.shop:443/``
    - ``  soupmarket.shop  `` -> ``http://soupmarket.shop/`` (trimmed)
    - ``""``, ``None``, ``"   "``, ``"http://"``, ``"://bad"``, ``"example com"``, ``"*.example.com"`` -> ``None``
    """
    if seed is None:
        return None
    raw = str(seed).strip()
    if not raw:
        return None
    if " " in raw or "\t" in raw or "\n" in raw:
        return None
    # Reject wildcard - a zone is not a base URL; apex must be resolved via parse_scope elsewhere.
    if raw.startswith("*."):
        return None
    # Already scheme'd
    if re.match(r"^https?://", raw, re.IGNORECASE):
        try:
            parsed = urlparse(raw)
        except Exception:
            return None
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return None
        netloc = parsed.netloc or ""
        if not netloc or " " in netloc:
            return None
        # ``urlparse`` keeps ``netloc`` for ``http://example.com`` but empty for ``http:///a``
        # - catch degenerate forms.
        if not parsed.hostname:
            return None
        return f"{scheme}://{netloc}/"
    # Bare form: strip any accidental path/query/fragment, keep only hostport.
    hostport = raw.split("/")[0].split("?")[0].split("#")[0].strip()
    if not hostport or " " in hostport or hostport.startswith("*."):
        return None
    # Validate via urlparse with a dummy scheme - hostname must exist and netloc must round-trip.
    try:
        parsed = urlparse(f"http://{hostport}")
    except Exception:
        return None
    if not parsed.hostname:
        return None
    # ``netloc`` must equal the input hostport (catches malformed ``:`` or trailing ``.`` that urlparse normalizes away)
    if parsed.netloc != hostport:
        return None
    return f"http://{hostport}/"
