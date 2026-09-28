"""Rate-aware recon Configurator: phase offers, contracts, and one stateful turn.

The Configurator decides which canonical jobs become pods for one phase and how
their tool commands are parameterised. It is a `sync leaf + stateful_turn` agent:
run-scoped session memory, no mailbox, no execution capability. The runtime
validates technical executability only; posture compliance is prompt-guided.
"""
from __future__ import annotations

import json
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.traffic_admission import TrafficCostClass

PostureStatus = Literal[
    "known_target",
    "no_posture_for_host",
    "no_postures",
    "unreadable",
    "store_unavailable",
]


class ReconPodProposal(BaseModel):
    """One pod the Configurator proposes to materialize."""

    model_config = ConfigDict(extra="forbid")

    job_name: str
    input_id: str
    command: str | None
    rationale: str


class ConfiguratorDecision(BaseModel):
    """The Configurator's closed, phase-scoped reply."""

    model_config = ConfigDict(extra="forbid")

    phase: int
    target_key: str
    posture_status: PostureStatus
    pods: list[ReconPodProposal]
    rationale: str


class ConfiguratorOffer(BaseModel):
    """One prepared `(job, input)` pair the Configurator may choose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_name: str
    tool: str
    input_id: str
    input_preview: str
    command_template: str
    consumes: str
    produces: list[str]
    cost_class: TrafficCostClass
    estimated_requests_per_input: int
    configurator_mode: Literal["deterministic", "agent"]
    use_auth: bool


class PhaseOffers(BaseModel):
    """The complete offer set for one phase boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: int
    target_key: str
    offers: list[ConfiguratorOffer]


_PROMPT: str | None = None


def _load_configurator_prompt() -> str:
    """Load the role prompt fail-closed from this module's `prompts/` dir."""
    global _PROMPT
    if _PROMPT is None:
        from pathlib import Path  # noqa: PLC0415

        _PROMPT = (
            Path(__file__).resolve().parent
            / "prompts"
            / "rate-aware-configurator.md"
        ).read_text(encoding="utf-8")
    return _PROMPT


def _safe_url(value) -> str:
    """Render a URL without credentials, query string or fragment."""
    text = str(value)
    try:
        parts = urlsplit(text)
    except ValueError:
        return text[:300]
    if not parts.scheme or not parts.netloc:
        return text[:300]
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))[:300]


def _input_preview(input_asset: dict) -> str:
    """A small, secret-free preview of a prepared input asset."""
    asset = input_asset if isinstance(input_asset, dict) else {}
    preview: dict = {}
    for key in ("name", "address", "path", "method", "profile"):
        value = asset.get(key)
        if value not in (None, ""):
            preview[key] = str(value)[:300]
    for key in ("url", "baseurl"):
        value = asset.get(key)
        if value not in (None, ""):
            preview[key] = _safe_url(value)
    if isinstance(asset.get("batch"), list):
        preview["batch_size"] = len(asset["batch"])
    if isinstance(asset.get("endpoints"), list):
        preview["endpoints_size"] = len(asset["endpoints"])
    return json.dumps(preview, sort_keys=True, ensure_ascii=False)[:1000]


def offer_phase_inputs(
    phase: int,
    target_key: str,
    prepared_by_job: dict[str, list[dict]],
    jobs=JOBS,
) -> PhaseOffers:
    """Build the stable `(job, input)` offers for one phase boundary."""
    offers: list[ConfiguratorOffer] = []
    for job_name, prepared in prepared_by_job.items():
        job = jobs.get(job_name)
        if job is None:
            raise ValueError(f"unknown canonical job offered: {job_name!r}")
        cost = job.traffic_cost
        for index, pod_input in enumerate(prepared):
            input_asset = (
                pod_input.get("input_asset", {})
                if isinstance(pod_input, dict)
                else {}
            )
            offers.append(
                ConfiguratorOffer(
                    job_name=job_name,
                    tool=job.tool,
                    input_id=f"{job_name}:{index}",
                    input_preview=_input_preview(input_asset),
                    command_template=job.command_template,
                    consumes=job.consumes,
                    produces=list(job.produces),
                    cost_class=cost.cost_class,
                    estimated_requests_per_input=int(
                        cost.estimated_requests_per_input
                    ),
                    configurator_mode=job.configurator_mode,
                    use_auth=job.use_auth,
                )
            )
    return PhaseOffers(phase=phase, target_key=target_key, offers=offers)


def _offer_message(offers: PhaseOffers) -> str:
    return (
        f"Configure recon phase {offers.phase} for target {offers.target_key}.\n\n"
        "Offered inputs (JSON):\n"
        f"{json.dumps(offers.model_dump(mode='json'), sort_keys=True, ensure_ascii=False)}\n\n"
        "Resolve the posture first, then return one ConfiguratorDecision."
    )


def configure_phase(
    project_id: str,
    run_id: str,
    phase: int,
    target_key: str,
    offers: PhaseOffers,
    *,
    checkpointer=None,
    model_factory=None,
    posture_store=None,
) -> ConfiguratorDecision | None:
    """Run one stateful Configurator turn at a phase boundary."""
    if offers.phase != phase or offers.target_key != target_key:
        raise ValueError("phase offers do not match the requested phase/target")

    from langchain_core.messages import HumanMessage  # noqa: PLC0415

    from polymerhus.app.llm import compaction  # noqa: PLC0415
    from polymerhus.app.llm.session import stateful_turn  # noqa: PLC0415
    from polymerhus.app.llm.session_address import ConfiguratorSession  # noqa: PLC0415
    from polymerhus.app.llm.skills import skill_agent_binding  # noqa: PLC0415
    from polymerhus.app.rate_limit.tool import (  # noqa: PLC0415
        build_rate_limit_posture_tool,
    )

    if checkpointer is None:
        from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
            get_session_checkpointer,
        )

        checkpointer = get_session_checkpointer()

    binding = skill_agent_binding("configurator", project_id=project_id)
    tools = [
        *binding.tools,
        build_rate_limit_posture_tool(project_id, store=posture_store),
    ]
    middleware = [
        compaction.cached_role_compaction_middleware("configurator"),
        *binding.middleware,
    ]
    return stateful_turn(
        "configurator",
        ConfiguratorSession(run_id),
        [HumanMessage(content=_offer_message(offers))],
        checkpointer=checkpointer,
        schema=ConfiguratorDecision,
        system_prompt=_load_configurator_prompt(),
        model_factory=model_factory,
        middleware=middleware,
        context=binding.context,
        tools=tools,
        extra_tags=[run_id],
    )


__all__ = [
    "ConfiguratorDecision",
    "ConfiguratorOffer",
    "PhaseOffers",
    "PostureStatus",
    "ReconPodProposal",
    "configure_phase",
    "offer_phase_inputs",
]
