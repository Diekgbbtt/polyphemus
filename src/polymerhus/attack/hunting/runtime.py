"""Hunting module runtime entry points (seam contract 3; #110).

The hunting side of the app-module seam (`docs/design/hunting-module-runtime-seam.md`,
ratified 2026-08-11). This module owns the lifecycle entry points the control
plane drives and the tear-down hooks it calls:

  start_hunting            - the bootstrap coroutine: sets the hunting module
                             context for its full duration, opens a `hunting_runs`
                             row (`running`), runs one orchestration pass of the
                             graph engine over the given candidate batch,
                             persists a terminal status (`complete`, or `failed`
                             when the pass degraded), and reaps the run's actor
                             via the module's stop path. Fail-open: a
                             collaborator failure never raises through the
                             control plane - it lands a terminal status.
  stop_hunting             - the phase-1 hard stop: cancels the run's task, reaps
                             the run's actor, persists `stopped` (the append-only
                             store already preserves the partial trail).
  flush_hunting_checkpointer - the tear-down flush hook, fail-open.
  schedule_hunting / cancel_hunting - the marshalling harness: use the control
                             plane's `runtime.schedule` / `runtime.cancel_run`
                             when `polymerhus.app.runtime` has landed; otherwise
                             a local in-process fallback (an asyncio task
                             registry) with a warning - so the module keeps
                             working before the control plane lands.

Per CODING_STANDARD section 6 this module performs no I/O and opens no
connection at import: the orchestration symbols and the runtime manager are
imported lazily inside the functions that need them.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Coroutine

logger = logging.getLogger(__name__)

# The hunting module-context ContextVar (the seam's `module_context("hunting")`).
# `asyncio.to_thread` and concurrent.futures copy the context, so work offloaded
# from hunting code resolves the hunting pool and the hunting checkpointer
# automatically once the runtime-independence control-plane machinery lands.
_MODULE_CTX: contextvars.ContextVar[str | None] = (
    contextvars.ContextVar("hunting-module-context", default=None)
)


@asynccontextmanager
async def hunting_module_context():
    """Set the hunting module context for the entry point's full duration."""
    token = _MODULE_CTX.set("hunting")
    try:
        yield
    finally:
        _MODULE_CTX.reset(token)


def _app_runtime():
    """The control plane's runtime manager, or None when it has not landed."""
    try:
        from polymerhus.app import runtime as app_runtime  # noqa: PLC0415
        return app_runtime
    except ImportError:
        return None


def hunting_control_plane_available() -> bool:
    """True once the control plane's `polymerhus.app.runtime` has landed (the
    hunting LOOP exists to schedule real runs). The API's fail-closed gate: a
    real orchestration pass (LLM turns) must never be smuggled onto the uvicorn
    request loop by the in-process fallback, so the launch surface 503s until
    the control plane is present."""
    return _app_runtime() is not None


def schedule_hunting(coro: Coroutine[Any, Any, Any], *, name: str) -> Any:
    """Schedule a hunting-run coroutine onto the hunting loop (seam 2.2).

    Uses the control plane's `runtime.schedule("hunting", coro, name=name)` when
    it has landed. Until then, the in-process fallback runs the coroutine as a
    task on the caller's event loop; `start_hunting` registers it against its
    `hunting_run_id` so `cancel_hunting` can cancel it."""
    runtime = _app_runtime()
    if runtime is None:
        logger.warning(
            "schedule_hunting: polymerhus.app.runtime has not landed; "
            "running the hunting run in-process (fallback)"
        )
        return asyncio.create_task(coro)
    return runtime.schedule("hunting", coro, name=name)


def cancel_hunting(hunting_run_id: str) -> None:
    """The phase-1 cancellation seam (seam 2.2): `runtime.cancel_run("hunting",
    hunting_run_id)` once the control plane has landed; else cancel the
    registered in-process task (a no-op when none is running)."""
    runtime = _app_runtime()
    if runtime is not None:
        runtime.cancel_run("hunting", hunting_run_id)
        return
    with _ACTIVE_LOCK:
        task = _ACTIVE_TASKS.pop(hunting_run_id, None)
    if task is not None and not task.done():
        task.cancel()


# The in-process fallback registry: `hunting_run_id` -> the running asyncio task.
_ACTIVE_TASKS: dict[str, asyncio.Task] = {}
_ACTIVE_LOCK = threading.Lock()


def _register_active(run_id: str) -> None:
    task = asyncio.current_task()
    if task is not None:
        with _ACTIVE_LOCK:
            _ACTIVE_TASKS[run_id] = task


def _unregister_active(run_id: str) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE_TASKS.pop(run_id, None)


async def start_hunting(
    project_id: str,
    *,
    run_id: str | None = None,
    candidates: list | tuple | None = None,
    tools=None,
    **orchestration_kwargs,
) -> str:
    """The hunting bootstrap entry point (seam 3.1).

    Schedules nothing itself - the control plane (or the marshalling harness)
    drives it onto the hunting loop. Sets the hunting module context for its
    full duration, opens the `hunting_runs` row (`running`), runs ONE
    orchestration pass of the graph engine over `candidates`, persists a
    terminal status (`complete`, or `failed` when the pass degraded), and reaps
    the run's actor via the module's stop path.

    Fail-open: a collaborator failure (PG row, default tools, the pass itself,
    the reap) degrades to a terminal status - this coroutine never raises
    through the control plane. An EXTERNAL cancellation (stop_hunting) is
    re-raised after teardown so `stop_hunting` can stamp `stopped`.

    Returns the `hunting_run_id` - the run's identity, keying both the
    `hunting_runs` row and the hunt store's append-only trail."""
    async with hunting_module_context():
        from polymerhus.app.clients import pg  # noqa: PLC0415
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            OrchestratorTools,
            ReadOnlyGraphView,
            _reap_orchestrator,
            arun_orchestration,
        )
        from polymerhus.attack.hunting.hunt_store import HuntStore  # noqa: PLC0415

        hunting_run_id = run_id
        if hunting_run_id is None:
            try:
                hunting_run_id = pg.create_hunting_run(project_id)
            except Exception:  # noqa: BLE001 - fail-open when PG is down
                logger.warning(
                    "start_hunting: could not open the hunting_runs row; "
                    "running unlogged (fail-open)"
                )
                hunting_run_id = str(uuid.uuid4())
        _register_active(hunting_run_id)

        if tools is None:
            try:
                tools = OrchestratorTools(
                    store_reads=HuntStore(),
                    graph_view=ReadOnlyGraphView(project_id),
                )
            except Exception:  # noqa: BLE001 - fail-open tools default
                logger.warning(
                    "start_hunting: default tools unavailable; the gate will "
                    "ground on the candidate set alone (fail-open)"
                )
                tools = OrchestratorTools(store_reads=HuntStore(), graph_view=None)

        status = "complete"
        try:
            await arun_orchestration(
                project_id, hunting_run_id, candidates or (), tools,
                **orchestration_kwargs,
            )
        except asyncio.CancelledError:
            status = None  # external stop: stop_hunting stamps 'stopped'
            raise
        except Exception:  # noqa: BLE001 - fail-open: land a terminal status
            logger.exception(
                "start_hunting: orchestration pass failed; persisting 'failed'"
            )
            status = "failed"
        finally:
            try:
                await _reap_orchestrator(hunting_run_id)
            except Exception:  # noqa: BLE001 - teardown must never raise
                logger.warning(
                    "start_hunting: actor reap failed for %s (fail-open)",
                    hunting_run_id,
                )
            if status is not None:
                try:
                    pg.set_hunting_run_status(hunting_run_id, status)
                except Exception:  # noqa: BLE001 - fail-open
                    logger.warning(
                        "start_hunting: could not persist %r for %s (fail-open)",
                        status,
                        hunting_run_id,
                    )
            _unregister_active(hunting_run_id)
        return hunting_run_id


async def stop_hunting(hunting_run_id: str) -> None:
    """Phase-1 hard stop (seam 3.1): cancel the run's task on the hunting loop,
    reap the run's actor, and persist `stopped`. The append-only store preserves
    the partial trail. Fail-open: never raises through the control plane."""
    async with hunting_module_context():
        from polymerhus.app.clients import pg  # noqa: PLC0415
        from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
            _reap_orchestrator,
        )

        cancel_hunting(hunting_run_id)
        try:
            await _reap_orchestrator(hunting_run_id)
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: actor reap failed for %s (fail-open)", hunting_run_id
            )
        try:
            pg.set_hunting_run_status(hunting_run_id, "stopped")
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: could not persist 'stopped' for %s (fail-open)",
                hunting_run_id,
            )


def flush_hunting_checkpointer() -> None:
    """The tear-down flush hook (seam 3.1): flush the in-memory checkpointer index
    into the pooled PG saver. The per-module in-memory index + flush lands with
    the runtime-independence control-plane workstream; until then this build's
    pooled `PostgresSaver` writes live, so the hook is a safe no-op - fail-open,
    never raises."""
    try:
        from polymerhus.app.llm import checkpoints as cp  # noqa: PLC0415
        saver = cp.get_session_checkpointer()
        flusher = getattr(saver, "flusher", None)
        if flusher is not None:
            flusher()
            return
        logger.debug(
            "flush_hunting_checkpointer: no in-memory index to flush in this "
            "build; the pooled saver writes live (no-op)"
        )
    except Exception as exc:  # noqa: BLE001 - fail-open hook, never raises
        logger.warning("flush_hunting_checkpointer: flush failed (fail-open): %s", exc)