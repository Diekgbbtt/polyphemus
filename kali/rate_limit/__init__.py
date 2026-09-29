"""#238 rate-limit measurement inside Kali.

The deterministic rate-mapping controller lives in the recon module
(`polymerhus.recon.control.rate_limit_runner`); THIS package is the Kali-side
execution and artifact plane it drives through the existing `execute_command`
seam:

- `models` - the private-stdin experiment spec and the compact stdout result.
- `store`  - the durable, bounded, atomically published raw-artifact store.
- `runner` - `python -m kali.rate_limit.runner`: Vegeta in, compact JSON out.

Raw per-hit evidence stays on disk (the persistent Kali data root); only
aggregates and an immutable reference ever leave this package.
"""
from __future__ import annotations

from kali.rate_limit.models import (
    KaliExperimentResult,
    KaliExperimentSpec,
    KaliExperimentSpecError,
)
from kali.rate_limit.store import (
    DEFAULT_MAX_BYTES,
    RATE_ARTIFACT_SCHEME,
    REDACTED,
    ArtifactIdentifierError,
    PublishedArtifact,
    RateLimitArtifactStore,
)

__all__ = [
    "ArtifactIdentifierError",
    "DEFAULT_MAX_BYTES",
    "KaliExperimentResult",
    "KaliExperimentSpec",
    "KaliExperimentSpecError",
    "PublishedArtifact",
    "RATE_ARTIFACT_SCHEME",
    "REDACTED",
    "RateLimitArtifactStore",
]
