"""The one shared read-only agent tool over the rate-limit posture bucket
(#238 follow-up).

Read-only by construction: the controller is the only writer, so no model can
enlarge a budget by writing here. The contract rides the tool description
verbatim (the AUTH_STORE_CONTRACT / GRAPH_VIEW_CONTRACT precedent).
"""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict

from polymerhus.app.rate_limit.store import (
    PostureRecord,
    PostureUnreadableError,
    RateLimitPostureStore,
)
from polymerhus.recon.config import rate_limit_safety_budget
from polymerhus.recon.domain.rate_limit import RateProfile

RATE_LIMIT_POSTURE_CONTRACT = (
    "Read the project's measured rate-limit posture, one record per target.\n\n"
    "A posture is the traffic shape this project measured against ONE target: "
    "its host patterns, the safe rate per second, the burst, the concurrency "
    "ceiling, when it was measured and when it expires. It is ADVISORY: it is "
    "NOT enforced on your commands. Respect it anyway - it is the only measured "
    "fact about how hard this target may be hit.\n\n"
    "Operations: `list` (targets with a posture), `get` (one target), "
    "`resolve` (given a request host, which posture covers it). Before sending "
    "traffic to a host, `resolve` it. If the answer is `no_posture_for_host`, "
    "the target was never measured: assume the conservative default the tool "
    "returns (1 request per second, burst 1, concurrency 1) and say so in your "
    "reasoning. If the answer is `unreadable`, assume nothing and report it.\n\n"
    "This tool never writes. A posture can only be produced by the run's "
    "deterministic rate mapping."
)


class PostureArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: Literal["list", "get", "resolve"]
    target: str = ""
    host: str = ""


def _render(record: PostureRecord) -> dict:
    policy = record.profile.traffic_policy
    return {
        "target_key": record.target_key,
        "outcome": record.profile.outcome,
        "safe_rate_per_s": record.profile.safe_rate_per_s,
        "burst": policy.burst,
        "max_concurrency": policy.max_concurrency,
        "host_patterns": list(record.profile.host_patterns),
        "measured_at": record.profile.measured_at.isoformat(),
        "expires_at": record.profile.expires_at.isoformat(),
        "fresh": record.fresh,
        "source_run_id": record.source_run_id,
        "advisory": True,
    }


def _conservative_default(target_key: str) -> dict:
    """The value to assume for an unmeasured host. Single-sourced from the
    domain fallback so the tool and the admission can never disagree."""
    profile = RateProfile.conservative(
        target_key, [], rate_limit_safety_budget(),
        "unmeasured target: assume the conservative fallback",
    )
    policy = profile.traffic_policy
    return {
        "rate_per_s": policy.rate_per_s,
        "burst": policy.burst,
        "max_concurrency": policy.max_concurrency,
        "basis": "conservative-fallback",
    }


class RateLimitPostureTool(BaseTool):
    name: str = "rate_limit_posture"
    description: str = RATE_LIMIT_POSTURE_CONTRACT
    args_schema: type[BaseModel] = PostureArgs

    project_id: str = ""
    store: RateLimitPostureStore | None = None

    def _run(self, command: str, target: str = "", host: str = "") -> dict:
        seam = self.store if self.store is not None else RateLimitPostureStore()
        try:
            if command == "list":
                records = [
                    record
                    for record in (
                        seam.read(self.project_id, key)
                        for key in seam.list_targets(self.project_id)
                    )
                    if record is not None
                ]
                if not records:
                    return {"ok": True, "status": "no_postures", "targets": []}
                return {
                    "ok": True,
                    "status": "known_targets",
                    "targets": [_render(record) for record in records],
                }
            if command == "get":
                record = seam.read(self.project_id, target)
                if record is None:
                    return {
                        "ok": True,
                        "status": "no_postures",
                        "target": target,
                        "assumed": _conservative_default(target),
                    }
                return {"ok": True, "status": "known_target", "posture": _render(record)}
            if command == "resolve":
                record = seam.resolve(self.project_id, host)
                if record is None:
                    known = bool(seam.list_targets(self.project_id))
                    return {
                        "ok": True,
                        "status": "no_posture_for_host" if known else "no_postures",
                        "host": host,
                        "assumed": _conservative_default(host),
                    }
                return {"ok": True, "status": "known_target", "posture": _render(record)}
        except PostureUnreadableError as exc:
            return {"ok": False, "status": "unreadable", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            return {"ok": False, "status": "store_unavailable", "detail": str(exc)}
        return {
            "ok": False,
            "status": "invalid_command",
            "detail": "command must be list, get or resolve",
        }


def build_rate_limit_posture_tool(
    project_id: str | None = None, store: RateLimitPostureStore | None = None
) -> RateLimitPostureTool:
    """Build the ONE `rate_limit_posture` tool bound to `project_id`.

    `project_id` defaults to the control-plane project (`config.PROJECT_ID`),
    resolved LAZILY here so import never touches env (CODING_STANDARD §6).
    """
    if project_id is None:
        from polymerhus.app.config import config  # noqa: PLC0415

        project_id = config.PROJECT_ID
    return RateLimitPostureTool(project_id=project_id, store=store)
