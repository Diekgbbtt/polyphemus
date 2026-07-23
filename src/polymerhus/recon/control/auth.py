"""FR-AUTH: the per-request auth-context selector (L1D-5 / L1OP-6).

`auth_context` grew from a single flat credential set to a role/realm-tagged set:

    {
      # the unroled default credentials (legacy flat shape, still valid):
      "cookies": [...], "Authorization": "Bearer ...",
      # role-tagged credential sets (each is itself a flat credential set,
      # optionally carrying a `realm` tag - credential vs IdP):
      "roles": {
        "admin":   {"realm": "credential", "cookies": [...]},
        "shopper": {"cookies": [...]},
      },
      "default_role": "shopper"   # optional
    }

`select_auth_context` picks exactly ONE role's credential set for a given request
(a recon job, or an anatomy-skill probe running the same action under a different
role). Every downstream consumer takes a flat credential set, so this is the one
place that resolves role -> credentials. Structural keys (`roles`, `default_role`)
are never returned in the selected set, so they can never be serialised as HTTP
headers.
"""
from __future__ import annotations

# Keys the selector strips from the returned set: the role MAP and the default
# pointer. DELIBERATELY narrower than the header-serialiser's reserved set
# (`pod._RESERVED_AUTH_KEYS`) and the API validator's
# (`routes._RESERVED_AUTH_CONTEXT_KEYS`) - a selected role's set intentionally
# KEEPS `realm` (its own metadata tag) + `cookies`/`credentials`/`scope`; only the
# pod serialiser drops `realm` from HTTP headers. Do NOT add `realm` here.
_STRUCTURAL_KEYS = ("roles", "default_role")


def select_auth_context(auth_context: dict | None, role: str | None = None) -> dict:
    """Return the flat credential set for `role` (cookies + headers + optional
    `realm`), resolving in this order:

    - an explicit `role` -> that role's set under `auth_context.roles` (an empty
      dict if the role is not configured - an unconfigured role gets NO creds,
      never another role's);
    - `role=None` + a configured `default_role` -> the default role's set;
    - `role=None` + no `default_role` -> the flat unroled credentials (the
      legacy top-level shape), with the structural keys stripped.

    Never returns the `roles` / `default_role` structural keys, so the result is
    safe to hand straight to the header serialiser."""
    if not auth_context:
        return {}
    roles = auth_context.get("roles") or {}
    if role is None:
        role = auth_context.get("default_role")
    if role is not None:
        return dict(roles.get(role) or {})
    return {k: v for k, v in auth_context.items() if k not in _STRUCTURAL_KEYS}
