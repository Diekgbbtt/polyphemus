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
                             control plane - it lands a terminal status. The
                             blocking-sync-pg calls (`create_hunting_run`,
                             `set_hunting_run_status`) offload via
                             `asyncio.to_thread` onto the shared executor, never
                             the worker loop.
  stop_hunting             - the phase-1 hard stop: cancels the run's task, reaps
                             the run's actor, persists `stopped` (the per-project
                             store already preserves the partial config/notes trail).
  flush_hunting_checkpointer - the tear-down flush hook (#123): archive the
                             hunting module in-memory checkpointer index into the
                             still-open pooled saver via the shared
                             `flush_module_index("hunting")` seam, fail-open.
  schedule_hunting / cancel_hunting - the marshalling harness: drive the
                             control plane's `runtime.schedule` /
                             `runtime.cancel_run`. Since #122 there is no
                             in-process fallback - `hunting_control_plane_available()`
                             is the fail-closed gate the launch endpoint checks
                             before any real run may boot.

Per CODING_STANDARD section 6 this module performs no I/O and opens no
connection at import: the orchestration symbols and the runtime manager are
imported lazily inside the functions that need them.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Coroutine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def hunting_module_context():
    """Set the hunting module context for the entry point's full duration.

    Delegates to the SHARED `module_context("hunting")` seam
    (`polymerhus.app.llm.checkpoints`), never a private hunting-only var: while
    it is set, `get_session_checkpointer()` resolves the hunting module's
    in-memory index, and `copy_context` carries the var into `asyncio.to_thread`
    and executor work, so offloaded hunting turns resolve the same index."""
    from polymerhus.app.llm.checkpoints import module_context  # noqa: PLC0415

    with module_context("hunting"):
        yield


def _app_runtime():
    """The ACTIVE control-plane runtime manager, or None when it has not landed
    (the module import still fails) or is not active (no manager running).

    The module existing is not enough: `schedule`/`cancel_run` raise when no
    manager is active, so a caller must fail closed unless `get_active_runtime()`
    returns a live manager (#121 regression guard)."""
    try:
        from polymerhus.app.runtime import get_active_runtime
        return get_active_runtime()
    except ImportError:
        return None


def _require_runtime():
    runtime = _app_runtime()
    if runtime is None:
        raise RuntimeError(
            "hunting control-plane runtime is not active; "
            "hunting_control_plane_available() must gate the launch"
        )
    return runtime


def hunting_control_plane_available() -> bool:
    """True once the control plane's `polymerhus.app.runtime` has landed (the
    hunting LOOP exists to schedule real runs). The API's fail-closed gate: a
    real orchestration pass (LLM turns) must never be smuggled onto the uvicorn
    request loop by an in-process fallback, so the launch surface 503s until
    the control plane is present."""
    return _app_runtime() is not None


def schedule_hunting(coro: Coroutine[Any, Any, Any], *, name: str) -> Any:
    """Schedule a hunting-run coroutine onto the worker loop (seam 2.2):
    `runtime.schedule("hunting", coro, name=name)`. No in-process fallback
    since #122 - the launch endpoint's `hunting_control_plane_available()`
    gate already failed closed when no manager is active."""
    return _require_runtime().schedule("hunting", coro, name=name)


def cancel_hunting(hunting_run_id: str) -> None:
    """The phase-1 cancellation seam (seam 2.2):
    `runtime.cancel_run("hunting", hunting_run_id)`. Fail-open: with no active
    runtime, or a run that has already left the registry (completed, or never
    scheduled), cancellation is a safe no-op - so `stop_hunting`'s teardown
    never raises through the control plane."""
    runtime = _app_runtime()
    if runtime is None:
        logger.warning(
            "cancel_hunting: no active runtime; run %s left as-is (fail-open)",
            hunting_run_id,
        )
        return
    try:
        runtime.cancel_run("hunting", hunting_run_id)
    except Exception:  # noqa: BLE001 - already gone is fine
        logger.warning(
            "cancel_hunting: no registered hunting run %s to cancel (no-op)",
            hunting_run_id,
        )


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
    `hunting_runs` row and the project's memory-store folder."""
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
                # Blocking-sync-PG offloads onto the shared executor (#123): the
                # accessor opens/connects a psycopg connection, so it must never
                # block the worker loop.
                hunting_run_id = await asyncio.to_thread(
                    pg.create_hunting_run, project_id
                )
            except Exception:  # noqa: BLE001 - fail-open when PG is down
                logger.warning(
                    "start_hunting: could not open the hunting_runs row; "
                    "running unlogged (fail-open)"
                )
                hunting_run_id = str(uuid.uuid4())

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
                    await asyncio.to_thread(
                        pg.set_hunting_run_status, hunting_run_id, status
                    )
                except Exception:  # noqa: BLE001 - fail-open
                    logger.warning(
                        "start_hunting: could not persist %r for %s (fail-open)",
                        status,
                        hunting_run_id,
                    )
        return hunting_run_id


async def stop_hunting(hunting_run_id: str) -> None:
    """Phase-1 hard stop (seam 3.1): cancel the run's task on the hunting loop,
    reap the run's actor, and persist `stopped`. The per-project store preserves
    the partial config/notes trail. Fail-open: never raises through the control plane."""
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
            await asyncio.to_thread(pg.set_hunting_run_status, hunting_run_id, "stopped")
        except Exception:  # noqa: BLE001 - fail-open
            logger.warning(
                "stop_hunting: could not persist 'stopped' for %s (fail-open)",
                hunting_run_id,
            )


def flush_hunting_checkpointer() -> None:
    """The tear-down flush hook (seam 3.1, #123): archive the hunting module's
    in-memory checkpointer index into the still-open #94 pooled saver via the
    SHARED `flush_module_index("hunting")` seam (`polymerhus.app.llm.checkpoints`),
    never a private hunting-only path. Fail-open: never raises."""
    try:
        from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
            flush_module_index,
        )
        flush_module_index("hunting")
    except Exception as exc:  # noqa: BLE001 - fail-open hook, never raises
        logger.warning("flush_hunting_checkpointer: flush failed (fail-open): %s", exc)