"""The private-stdin experiment spec and the compact stdout result.

The controller (recon, Task 4) OWNS every traffic number; this module is the
wire contract it sends down to Kali and the compact answer Kali hands back.
Two properties are load-bearing:

* the spec is CLOSED (`extra="forbid"`): a misspelled traffic knob is a wiring
  defect, never a silently-ignored one;
* the RESULT carries aggregates, fingerprints and an immutable reference -
  never a response body, never a raw hit stream, never a credential. Raw
  evidence lives only in the artifact store.

The spec deliberately mirrors the model-facing `recon.domain.rate_limit`
contracts and carries no body: the replay surface is method+url+headers, so a
credential-bearing request body can never ride this seam.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RESULT_VERSION = "rate-result/v1"
"""The wire version of the compact stdout result."""


class KaliExperimentSpecError(ValueError):
    """The private-stdin spec was missing or malformed - refuse before running
    anything (no process is spawned, nothing is published)."""


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KaliExperimentSpec(_Closed):
    """One admitted experiment, exactly as the controller admitted it.

    `headers` is the authenticated context the run replays. It is
    SECRET-BEARING transport: it reaches Vegeta through a `0600` target file
    and is redacted by the artifact store's manifest writer.
    """

    experiment_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    rate_per_s: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    requests: int = Field(gt=0)
    concurrency: int = Field(default=1, gt=0)
    timeout_s: float = Field(default=30.0, gt=0)
    notes: str = ""

    def vegeta_target(self) -> dict:
        """The single Vegeta target object for this experiment.

        Vegeta's target file is a JSON object (or array of objects) with
        `method`, `url`, `header` and `body`. No body is expressible here by
        design.
        """
        target: dict = {"method": self.method, "url": self.url}
        if self.headers:
            target["header"] = dict(self.headers)
        return target


class KaliExperimentResult(_Closed):
    """The compact stdout envelope: what the harness turns into
    `ExperimentEvidence`.

    `artifact_ref` is the immutable `rate-artifact/v1:<project>/<run>/<exp>`
    coordinate (never an absolute path) and `manifest_sha256` pins the stored
    compressed stream. A `failed` result carries a typed error and publishes
    nothing.
    """

    version: str = RESULT_VERSION
    experiment_id: str
    phase: str
    outcome: Literal["measured", "failed"] = "measured"
    artifact_ref: str | None = None
    manifest_sha256: str | None = None
    count: int = Field(default=0, ge=0)
    duration_s: float = Field(default=0.0, ge=0)
    offered_rate_per_s: float = Field(default=0.0, ge=0)
    concurrent_workers: int = Field(default=1, ge=1)
    status_counts: dict[str, int] = Field(default_factory=dict)
    rejection_ratio: float = Field(default=0.0, ge=0, le=1)
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    burst_accepted: int | None = None
    header_fingerprint: list[str] = Field(default_factory=list)
    body_fingerprint: list[str] = Field(default_factory=list)
    vegeta_version: str = "unknown"
    error: str | None = None

    def failure(self, error: str) -> "KaliExperimentResult":
        """The typed-failure form of this result (nothing published)."""
        return self.model_copy(
            update={
                "outcome": "failed",
                "artifact_ref": None,
                "manifest_sha256": None,
                "count": 0,
                "error": error,
            }
        )


__all__ = [
    "KaliExperimentResult",
    "KaliExperimentSpec",
    "KaliExperimentSpecError",
    "RESULT_VERSION",
]
