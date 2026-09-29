"""#238 A9 - the Kali runtime capabilities the controller negotiates against.

`kali/http_history/capabilities.py` already ADVERTISES what the companion image
can enforce (supported policy versions, the Vegeta module version, the pinned
wordlist cardinality). This is the CONTROLLER-side reader/validator: it turns
that public `proxy_status` payload into a closed value object and answers one
question - "is this runtime compatible?" - so an incompatible companion refuses
conservatively BEFORE any target traffic instead of being assumed to enforce a
policy it cannot.

This module mirrors the Kali constants deliberately (the recon domain must not
import the Kali package); a contract test ties the wordlist constant to the ffuf
`JobSpec` cost so the two can never drift silently.
"""
from __future__ import annotations

from typing import Mapping

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.domain.rate_limit import TRAFFIC_POLICY_VERSION

FFUF_WORDLIST_PATH = "/usr/share/seclists/Discovery/Web-Content/common.txt"
"""The pinned ffuf wordlist path (mirror of the Kali constant)."""

EXPECTED_VEGETA_VERSION = "v12.13.0"
"""The pinned Vegeta module version (mirror of the Kali constant)."""

EXPECTED_FFUF_WORDLIST_COUNT = 4750
"""The pinned wordlist cardinality the readiness gate verifies against the ffuf
`JobSpec`'s declared request cost."""


class RuntimeCapabilities(BaseModel):
    """What the Kali companion can enforce and prove, closed and secret-free."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    governor_enabled: bool
    supported_policy_versions: tuple[str, ...]
    vegeta_version: str | None = None
    ffuf_wordlist_count: int | None = None
    build_revision: str = "unknown"

    def compatibility_error(self) -> str | None:
        """`None` when compatible, else a short machine-readable reason.

        Every branch fails CLOSED: an unknown or missing capability is treated
        as incompatible, never as "assume it works".
        """
        if not self.governor_enabled:
            return "governor_disabled"
        if TRAFFIC_POLICY_VERSION not in set(self.supported_policy_versions):
            return "policy_version"
        if self.vegeta_version != EXPECTED_VEGETA_VERSION:
            return "vegeta_version"
        if self.ffuf_wordlist_count != EXPECTED_FFUF_WORDLIST_COUNT:
            return "ffuf_wordlist_cardinality"
        return None

    def describe(self) -> str:
        """A short, secret-free description for the admission warning."""
        return (
            f"governor={self.governor_enabled} "
            f"policy_versions={list(self.supported_policy_versions)} "
            f"vegeta={self.vegeta_version} "
            f"ffuf_wordlist={self.ffuf_wordlist_count} "
            f"revision={self.build_revision}"
        )

    @classmethod
    def from_proxy_status(cls, payload: object) -> "RuntimeCapabilities":
        """Build the value object from a `proxy_status` mapping.

        Tolerant of a partial/malformed payload by DEGRADING to an incompatible
        value (missing governor switch -> off; missing wordlist -> None): the
        caller's `compatibility_error()` then refuses. A malformed payload is
        never an invitation to assume the capabilities are present.
        """
        if not isinstance(payload, Mapping):
            return cls(governor_enabled=False, supported_policy_versions=())
        governor = payload.get("traffic_governor") or {}
        build = payload.get("build") or {}
        wordlists = payload.get("wordlists") or {}
        versions = (
            tuple(str(v) for v in (governor.get("supported_policy_versions") or ()))
            if isinstance(governor, Mapping)
            else ()
        )
        count = None
        if isinstance(wordlists, Mapping):
            count = wordlists.get(FFUF_WORDLIST_PATH)
            if count is None:
                present = [v for v in wordlists.values() if isinstance(v, int)]
                count = present[0] if present else None
        return cls(
            governor_enabled=bool(
                governor.get("governor_enabled") if isinstance(governor, Mapping) else False
            ),
            supported_policy_versions=versions,
            vegeta_version=(
                build.get("vegeta_version") if isinstance(build, Mapping) else None
            ),
            ffuf_wordlist_count=count if isinstance(count, int) else None,
            build_revision=(
                str(build.get("revision") or "unknown")
                if isinstance(build, Mapping)
                else "unknown"
            ),
        )


__all__ = [
    "EXPECTED_FFUF_WORDLIST_COUNT",
    "EXPECTED_VEGETA_VERSION",
    "FFUF_WORDLIST_PATH",
    "RuntimeCapabilities",
]
