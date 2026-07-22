"""FR-ELICIT — bootstrap the L1 Service skeleton from the operator KB.

Step 1 of the analyser pipeline (spec §7.2): before any recon surface exists, the
operator's free-text solution architecture (`settings.recon.operator_kb`) is
projected into an L1 **Service skeleton** — business-function Services plus the
**linchpin auth Systems** (authentication mechanism + authorization system) that
everything later extends. This is a *pure business projection*: it needs no
surface and writes **no L0 references** (no AGGREGATES). Assignment (attaching L0
elements to these Services) is the analyser subgraph's job, later.

`operator_kb` is free text for now (operator decision 2026-07-16); a typed
service-contract template is an after-MVP enhancement (AMV-4). Fail-open
throughout: an LLM or write failure degrades to an empty/partial skeleton and
never raises into the caller.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel

from agent.recon.analysis.analyser_types import L1DeltaBatch, SystemProposal, proposals_to_deltas
from agent.recon.analysis.l1_types import Provenance

logger = logging.getLogger(__name__)

# The linchpin auth Systems that the bootstrap always ensures exist, regardless
# of what the LLM elicits (spec §7.2: "linchpin System nodes (authentication,
# authorization) that everything later extends"). Deterministic so the skeleton
# never lacks the two systems the authorization-pyramid / auth skills extend.
_LINCHPIN_SYSTEMS = ("AuthenticationMechanism", "AuthorizationSystem")


class BootstrapExport(BaseModel):
    """Result of a bootstrap: how many L1 skeleton nodes were written."""

    services_written: int = 0
    systems_written: int = 0
    error: str | None = None


_BOOTSTRAP_INSTRUCTION = (
    "This is the BOOTSTRAP step: you are given the operator's free-text solution "
    "architecture / knowledge base, NOT a recon surface. Project it into the L1 "
    "business skeleton: propose the business-function `services` (sign-in, "
    "checkout, orders, reward-points, cart, reviews, product-introspection, "
    "sales-analysis, ...) and any cross-cutting `systems` the text clearly implies. "
    "Emit NO `aggregates` - there is no Layer-0 surface to assign yet. Propose only "
    "business functions the text actually supports; return empty lists if it "
    "supports none."
)


def default_elicit_fn(operator_kb: str, *, service_slugs: list[str] | None = None) -> L1DeltaBatch:
    """Real collaborator: ask the analyser LLM to elicit the Service skeleton from
    the operator KB. Reuses the analyser role + skill (same structured-output
    pattern as default_analyse_fn); the KB text is the whole input.

    FR-INVENTORY: `service_slugs` are the CURRENT L1 Service identities; rendered
    as the un-truncated EXISTING L1 IDENTITIES reuse block at the top so a
    re-bootstrap reuses an existing slug instead of coining a synonym."""
    from langchain_core.messages import SystemMessage, HumanMessage

    from agent.app.llm.roles import chat_model_for
    from agent.recon.analysis.l1_curator import vocabulary_prompt
    from agent.recon.analysis.pod import (
        _invoke_with_retry,
        _inventory_block,
        _load_analyser_skill,
    )

    llm = chat_model_for("analyser")
    structured_llm = llm.with_structured_output(L1DeltaBatch, method="function_calling")
    inventory = {"services": service_slugs or [], "systems": [], "data_items": []}
    prompt = (
        f"{_inventory_block(inventory)}\n\n{_BOOTSTRAP_INSTRUCTION}\n\n"
        f"{vocabulary_prompt()}\n\nOperator KB (free text):\n{operator_kb}"
    )
    messages = [SystemMessage(content=_load_analyser_skill()), HumanMessage(content=prompt)]
    # Bounded retry, exactly as the analyser pod does. `with_structured_output`
    # intermittently returns None or raises on a truncated provider response
    # (observed live: deepseek returned malformed JSON mid-elicitation). Without
    # the retry a single transient zeroes the ENTIRE bootstrap skeleton - the
    # fail-open then yields services=0 and every downstream stage runs against an
    # empty L1, which looks like a modelling failure rather than a provider blip.
    return _invoke_with_retry(structured_llm.invoke, messages)


def bootstrap_from_kb(
    project_id: str,
    operator_kb: str,
    *,
    run_id: str = "bootstrap",
    elicit_fn=None,
    curate_fn=None,
) -> BootstrapExport:
    """Elicit the Service skeleton from `operator_kb` and write it (services +
    linchpin auth Systems, NO L0 refs) through the L1 sole-writer. Idempotent
    (l1_curate MERGEs on identity). Fail-open.

    `elicit_fn(operator_kb) -> L1DeltaBatch` and
    `curate_fn(services, systems, project_id) -> (int, int)` are injected
    (defaulting to the analyser LLM and l1_curator) so this is testable without a
    live LLM/DB.
    """
    if not operator_kb or not operator_kb.strip():
        logger.info("bootstrap_from_kb: empty operator_kb for project=%s; nothing to elicit", project_id)
        # still ensure the linchpin systems + kind catalogue exist (below)
        batch = L1DeltaBatch()
    else:
        if elicit_fn is None:
            # FR-INVENTORY: seed the default elicitation with the CURRENT service
            # slugs so a re-bootstrap reuses existing identities instead of coining
            # synonyms. read_l1_inventory is fail-open (empty on any read error).
            from agent.recon.analysis.l1_inventory import read_l1_inventory
            _slugs = read_l1_inventory(project_id).get("services", [])

            def elicit_fn(kb):
                return default_elicit_fn(kb, service_slugs=_slugs)
        try:
            batch = elicit_fn(operator_kb)
        except Exception as exc:  # fail-open: an LLM error degrades to no elicited skeleton
            logger.warning("bootstrap_from_kb: elicit (LLM) failed for project=%s", project_id, exc_info=True)
            return BootstrapExport(error=f"elicit: {exc}")
        if batch is None:
            # The bounded retry returns None when EVERY attempt failed. Without this
            # guard that None reaches `batch.systems` below and raises AttributeError
            # straight out of a function contracted to be fail-open. It must also not
            # be mistaken for a successful-but-empty elicitation: an exhausted retry
            # is a provider failure and has to say so, or a run silently proceeds on
            # an empty skeleton and the emptiness gets blamed on the model.
            logger.warning(
                "bootstrap_from_kb: elicit returned no batch after retries for project=%s", project_id
            )
            return BootstrapExport(error="elicit: LLM returned no parseable batch after retries")

    # Always ensure the two linchpin auth Systems exist, whether or not the LLM
    # elicited them (dedup is handled by the singleton MERGE, so adding them when
    # the LLM already proposed them is harmless).
    elicited_kinds = {s.kind for s in batch.systems}
    linchpins = [SystemProposal(kind=k) for k in _LINCHPIN_SYSTEMS if k not in elicited_kinds]
    batch = batch.model_copy(update={"systems": list(batch.systems) + linchpins})

    provenance = Provenance(job=f"bootstrap:{run_id}", model=None, prompt_id=None)
    # Bootstrap is a pure business projection: drop any aggregates the LLM emitted
    # (no L0 surface exists yet) so no AGGREGATES edge is written here.
    services, systems, _aggregates_dropped = proposals_to_deltas(batch, provenance)

    if curate_fn is None:
        from agent.recon.analysis import l1_curator
        # No catalogue seeding: a System's kind is a plain `kind` attribute validated
        # against l1_curator.SYSTEM_KINDS (operator correction 2026-07-20), so there
        # is no `:SystemKind` catalogue to seed.
        def curate_fn(svc, sysd, pid):
            return l1_curator.l1_curate(svc, sysd, pid)

    try:
        services_written, systems_written = curate_fn(services, systems, project_id)
    except Exception as exc:  # fail-open: a write failure never crashes the caller
        logger.warning("bootstrap_from_kb: curate failed for project=%s", project_id, exc_info=True)
        return BootstrapExport(error=f"curate: {exc}")

    return BootstrapExport(services_written=services_written, systems_written=systems_written)


def run_bootstrap(project_id: str, *, load_settings_fn=None, **kwargs) -> BootstrapExport:
    """Convenience: read `operator_kb` from the project's settings and bootstrap.
    `load_settings_fn(project_id) -> dict` defaults to pg.load_settings."""
    if load_settings_fn is None:
        from agent.app.clients import pg
        load_settings_fn = pg.load_settings
    settings = load_settings_fn(project_id) or {}
    operator_kb = settings.get("operator_kb") or ""
    return bootstrap_from_kb(project_id, operator_kb, **kwargs)
