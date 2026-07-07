"""Lightweight, env-driven Langfuse tracing for the recon LangGraph runtime.

Design goals (deliberately minimal - see the Stream A observability brief):

- **Tracing only.** No prompt management, no datasets, no evals. We wire the
  standard LangChain `CallbackHandler` and let the LangGraph structure give us
  the trace tree for free: passing a single handler into `run_pipeline` /
  `graph.invoke` / `llm.invoke(config={"callbacks": [...]})` captures, per run,
  (a) every tool call + its response (the Kali MCP `execute_command` calls in
  pods and the `steel_*` tools in the crawl ReAct loop), (b) each role LLM's
  inputs/outputs (configurator / triager / job_orchestrator / crawler
  reasoning dumps), and (c) the phase DAG / job fan-out as the nested-span
  overview of the plan.

- **Env-driven + fail-open.** Tracing is enabled only when all three of
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are present
  in the environment. When any is missing - or the `langfuse` package is not
  installed, or handler construction raises for any reason - this module is a
  silent no-op: `get_langfuse_callbacks()` returns `[]` and NOTHING hard-fails.
  Passing `[]` as `config={"callbacks": []}` is inert in LangChain, so callers
  can wire the return value unconditionally.

The only public surface is `get_langfuse_callbacks() -> list`. Callers do:

    from agent.app.observability import get_langfuse_callbacks
    graph.invoke(state, config={"callbacks": get_langfuse_callbacks()})

Import safety: importing this module performs no network I/O and never
imports `langfuse` at module scope - the import is lazy, inside the factory,
so a runtime without the package (e.g. the offline test venv) imports this
module cleanly and simply gets an empty callback list.
"""
from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)

# The three env vars that gate tracing. All must be present and non-empty.
_REQUIRED_ENV = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")

# Cache the constructed handler(s) so we build the CallbackHandler once per
# process rather than on every graph/LLM invocation. `_INIT_DONE` distinguishes
# "not yet attempted" from "attempted and found unconfigured" (cached []).
_lock = threading.Lock()
_INIT_DONE = False
_CALLBACKS: list = []


def _is_configured() -> bool:
    """True only when every gating env var is present and non-empty."""
    return all(os.environ.get(name) for name in _REQUIRED_ENV)


def _build_callbacks() -> list:
    """Construct the Langfuse LangChain `CallbackHandler`, fail-open.

    Returns a one-element `[handler]` on success, or `[]` if tracing is not
    configured or anything goes wrong (missing package, bad keys, unreachable
    host at construction). Never raises.
    """
    if not _is_configured():
        missing = [n for n in _REQUIRED_ENV if not os.environ.get(n)]
        logger.debug("langfuse tracing disabled: missing env %s", missing)
        return []

    try:
        # Lazy import: the offline runtime does not ship `langfuse`, and we must
        # not turn a missing optional dependency into an import-time failure.
        from langfuse import get_client
        from langfuse.langchain import CallbackHandler

        # `get_client()` reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
        # LANGFUSE_HOST from the environment. auth_check() is best-effort - a
        # failed check only logs; it must not disable tracing (the host may be
        # briefly unreachable at boot while still coming up).
        client = get_client()
        try:
            if not client.auth_check():
                logger.warning(
                    "langfuse auth_check failed; tracing handler still wired "
                    "(verify LANGFUSE_* keys/host)"
                )
        except Exception:  # noqa: BLE001 - auth_check is advisory only
            logger.debug("langfuse auth_check raised; continuing", exc_info=True)

        handler = CallbackHandler()
        logger.info(
            "langfuse tracing enabled (host=%s)", os.environ.get("LANGFUSE_HOST")
        )
        return [handler]
    except Exception:  # noqa: BLE001 - fail-open: tracing never breaks the run
        logger.warning(
            "langfuse tracing could not be initialised; continuing without it",
            exc_info=True,
        )
        return []


def get_langfuse_callbacks() -> list:
    """Return the LangChain callbacks that enable Langfuse tracing.

    - Returns `[handler]` when Langfuse is configured (all three
      `LANGFUSE_*` env vars set) and the handler builds successfully.
    - Returns `[]` otherwise. `[]` is inert as `config={"callbacks": []}`, so
      callers wire it unconditionally into `run_pipeline` / `graph.invoke` /
      `llm.invoke`.

    The handler is built once and cached for the process. Never raises.
    """
    global _INIT_DONE, _CALLBACKS
    if _INIT_DONE:
        return _CALLBACKS
    with _lock:
        if not _INIT_DONE:
            _CALLBACKS = _build_callbacks()
            _INIT_DONE = True
    return _CALLBACKS


def reset_cache() -> None:
    """Clear the cached handler so the next call re-reads the environment.

    Intended for tests that toggle `LANGFUSE_*` env vars; not part of the
    normal runtime path.
    """
    global _INIT_DONE, _CALLBACKS
    with _lock:
        _INIT_DONE = False
        _CALLBACKS = []
