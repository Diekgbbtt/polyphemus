"""The module runtime manager (#121): the control plane that gives recon,
analysis, and hunting an INDEPENDENT lifecycle on one shared worker loop.

The ratified topology:

- ONE `asyncio.Runner` worker thread owns the single event loop every module run
  executes on. The API thread never touches that loop directly; it drives the
  modules exclusively through `run_coroutine_threadsafe` / `call_soon_threadsafe`
  (`RuntimeManager.schedule` / `RuntimeManager.call`).
- A module is a plain registry entry (`ModuleHandle`): its runs, its pause/drain
  state, and its per-module pass gate (`ModuleGate`). Nothing about a module is a
  thread or a loop.
- A module's per-unit admission is COOPERATIVE: `ModuleGate.__aenter__` pauses
  the NEXT unit at the dispatch point until `resume`. `pause` holds the next
  unit; `drain` pauses, settles the module's runs, archives via the flush hook,
  and reaches `stopped`; `shutdown` walks every module through the same settle
  (the `ShutdownFanOut`), closes the one shared executor, and stops the worker
  loop.
- PER-SESSION lifecycle (ADR #169 Q12/Q14): every registered run also owns a
  per-run hold event. `hold_session`/`resume_session` pause and release ONE run
  by its session id - its next unit boundary at the module gate waits, sibling
  runs of the same module are unaffected. Session id = coroutine id = registry
  run name: `schedule` keys the run by its `name` argument, and every lifecycle
  verb addresses the same key. `cancel_run` is already per-run by id.
- The hunting dispatch width (ADR #169 Q15): a configurable width, default 20,
  bounds concurrently running hunting sessions through the hunting module's
  `ModuleGate`.

Why this topology (the CORE ticket's rationale): the previous design gave each
module its own dedicated asyncio loop and thread, which multiplied thread counts
and made per-module flow control (pause/resume/stop) impossible. The single
shared loop + cooperative per-module gates keep the process at one worker thread
while still letting each module pause, drain, and stop on its own.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import enum
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_ACTIVE_RUNTIME: "RuntimeManager | None" = None
_ACTIVE_RUNTIME_LOCK = threading.Lock()

_FANOUT_TIMEOUT = 30.0

# The current run's per-session hold signal (ADR #169 Q14), bound by `_tracked`
# for the run's full duration. The shared `ModuleGate` reads it at the unit
# boundary so a dispatch point honours BOTH the module-wide pause AND the
# current run's own hold; child tasks inherit it, so every unit of the run is
# held together (session id = coroutine id = registry run name).
_CURRENT_RUN_HOLD: contextvars.ContextVar[asyncio.Event | None] = (
    contextvars.ContextVar("current-run-hold", default=None)
)


def get_active_runtime() -> "RuntimeManager | None":
    """The process's active control plane, if any. The seams (feed gate, analysis
    lifecycle, project-management API, the hunting marshalling harness) consult
    this to route work through the runtime instead of the pre-#121 fallback
    paths."""
    return _ACTIVE_RUNTIME


def _require_runtime() -> "RuntimeManager":
    runtime = get_active_runtime()
    if runtime is None:
        raise RuntimeError("no active runtime manager")
    return runtime


def schedule(module: str, coro: Any, *, name: str) -> Any:
    """The module-level sanction verb (#121, module-runtime-architecture section
    3): boot a run on the active manager's worker loop and return its outcome
    future. Raises unless a manager is active - callers that must keep working
    without one keep their own in-process fallbacks."""
    return _require_runtime().schedule(module, coro, name=name)


def cancel_run(module: str, run_id: str) -> None:
    """The module-level STOP verb (#121): hard-cancel a registered run via
    `call_soon_threadsafe(task.cancel)`. Raises unless a manager is active."""
    return _require_runtime().cancel_run(module, run_id)


def pause(module: str) -> None:
    return _require_runtime().pause(module)


def resume(module: str) -> None:
    return _require_runtime().resume(module)


def hold_session(module: str, run_id: str) -> None:
    """The module-level per-session HOLD verb (ADR #169 Q14): pause ONE
    registered run by its session id - its next unit boundary waits until
    `resume_session`. Per-session, never module-wide: siblings keep running.
    Raises unless a manager is active."""
    return _require_runtime().hold_session(module, run_id)


def resume_session(module: str, run_id: str) -> None:
    """The module-level per-session RESUME verb (ADR #169 Q14): release a held
    run by its session id. A resume of a not-held run is a no-op. Raises unless
    a manager is active."""
    return _require_runtime().resume_session(module, run_id)


def drain(module: str, *, timeout: float = _FANOUT_TIMEOUT) -> None:
    return _require_runtime().drain(module, timeout=timeout)


class ModuleState(enum.Enum):
    RUNNING = "running"
    PAUSED = "paused"
    DRAINING = "draining"
    STOPPED = "stopped"


class ModuleAdmissionRefused(Exception):
    """`RuntimeManager.schedule` refuses admission while the module is paused,
    draining, or stopped (#121 D1): a paused module never admits new work."""


class RunNotRegistered(Exception):
    """The run_id is not a registered run of the module (nothing to cancel)."""


class ModuleGate:
    """The per-module cooperative admission gate (#121 D4).

    `asyncio.Semaphore(N)` bounds concurrent passes to N, and `_running` holds
    the next unit at the dispatch point when the module is paused (the event is
    CLEARED on pause) until `resume` (the event is SET again). The gate binds to
    the worker loop on first use: the semaphore and the event are only ever
    awaited inside module runs, which execute on the worker loop, and `clear` /
    `set` are only ever delivered via `call_soon_threadsafe`.

    Since the wiring workstream (ADR #169 Q12/Q14) a unit is admitted only when
    BOTH the module-wide `_running` signal AND the CURRENT run's per-session
    hold signal (the `_CURRENT_RUN_HOLD` ContextVar, set by `_tracked` for the
    run's duration) are SET: a held run's next unit waits like a module pause
    would, but ONLY that run - siblings of the same module (each with their own
    hold event) pass through unchanged.
    """

    def __init__(self, width: int):
        self.width = width
        self._sem = asyncio.Semaphore(width)
        self._running = asyncio.Event()
        self._running.set()

    def clear_running(self) -> None:
        self._running.clear()

    def set_running(self) -> None:
        self._running.set()

    def available_permits(self) -> int:
        return self._sem._value

    async def __aenter__(self) -> "ModuleGate":
        await self._sem.acquire()
        try:
            await self._await_admission()
        except BaseException:
            # A cancel/error while waiting on the pause/hold events must not
            # leak the just-acquired permit: __aexit__ is never reached when
            # __aenter__ raises, so release here and re-raise (no permit leak on
            # cancel-while-waiting, #121 AC (c)).
            self._sem.release()
            raise
        return self

    async def _await_admission(self) -> None:
        # The next unit starts only when the module is running AND the current
        # run is not held. Re-checked in a loop so a pause/hold landing while
        # the other signal resolves still gates the unit (Q14: the NEXT unit).
        while True:
            hold = _CURRENT_RUN_HOLD.get()
            running_ok = self._running.is_set()
            hold_ok = hold is None or hold.is_set()
            if running_ok and hold_ok:
                return
            if not running_ok:
                await self._running.wait()
            if hold is not None and not hold.is_set():
                await hold.wait()

    async def __aexit__(self, *exc: Any) -> None:
        self._sem.release()


class ModuleHandle:
    """A registered module: its runs, its state, and its per-module gate.

    The registry is a plain dict guarded by a lock; every mutation happens on the
    worker loop (the run's `finally`), every read from the API thread. `_idle` is
    the emptiness signal the drain / shutdown settle waits on.

    Each registered run also carries a per-session hold event (ADR #169 Q14),
    SET by default: `hold_session` CLEARs it, `resume_session` SETs it. The run
    awaits it at the module gate's unit boundary, so holding one run stops only
    ITS next unit - sibling runs of the module are unaffected. The hold is
    created and reaped on the worker loop (register/unregister), set/cleared via
    `call_soon_threadsafe`, exactly like the gate's `_running` event.
    """

    def __init__(self, name: str, gate: ModuleGate, hooks: dict[str, Any] | None):
        self.name = name
        self.gate = gate
        self.hooks = hooks or {}
        self.state = ModuleState.RUNNING
        self._runs: dict[str, asyncio.Task] = {}
        self._holds: dict[str, asyncio.Event] = {}
        self._runs_lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()

    def register_run(self, run_id: str, task: asyncio.Task) -> asyncio.Event:
        hold = asyncio.Event()
        hold.set()
        with self._runs_lock:
            self._runs[run_id] = task
            self._holds[run_id] = hold
        self._idle.clear()
        return hold

    def unregister_run(self, run_id: str, task: asyncio.Task) -> None:
        with self._runs_lock:
            self._runs.pop(run_id, None)
            self._holds.pop(run_id, None)
            empty = not self._runs
        if empty:
            self._idle.set()

    def get_task(self, run_id: str) -> asyncio.Task | None:
        with self._runs_lock:
            return self._runs.get(run_id)

    def get_hold(self, run_id: str) -> asyncio.Event | None:
        with self._runs_lock:
            return self._holds.get(run_id)

    def live_tasks(self) -> list[asyncio.Task]:
        with self._runs_lock:
            return list(self._runs.values())

    def run_ids(self) -> list[str]:
        with self._runs_lock:
            return list(self._runs.keys())

    def is_idle(self) -> bool:
        return self._idle.is_set()

    def wait_idle(self, timeout: float) -> bool:
        return self._idle.wait(timeout)


class RuntimeManager:
    """The module control plane (#121): one shared worker loop, the module
    registry, cooperative per-module gates, and the shutdown fan-out."""

    def __init__(self, *, gate_widths: dict[str, int] | None = None):
        from polymerhus.app.config import config as app_config

        self._gate_widths: dict[str, int] = {
            "analysis": app_config.ANALYSIS_PASS_GATE_WIDTH,
            "hunting": app_config.HUNTING_DISPATCH_GATE_WIDTH,
        }
        if gate_widths:
            self._gate_widths.update(gate_widths)
        self._handles: dict[str, ModuleHandle] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: asyncio.Runner | None = None
        self._stop: asyncio.Event | None = None
        self._worker_thread: threading.Thread | None = None
        self._started_evt: threading.Event | None = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._started = False

    # --- properties ----------------------------------------------------------

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    @property
    def worker_thread(self) -> threading.Thread | None:
        return self._worker_thread

    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor | None:
        return self._executor

    # --- start / stop --------------------------------------------------------

    def start(self) -> None:
        if self._started:
            return
        from polymerhus.app.config import config as app_config

        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=app_config.WORKER_THREADS,
                thread_name_prefix="runtime-executor",
            )
        self._started_evt = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._worker_main, name="runtime-worker", daemon=True
        )
        self._worker_thread.start()
        if not self._started_evt.wait(timeout=10):
            raise RuntimeError("runtime worker loop failed to start")
        self._started = True
        global _ACTIVE_RUNTIME
        with _ACTIVE_RUNTIME_LOCK:
            _ACTIVE_RUNTIME = self

    def _worker_main(self) -> None:
        self._runner = asyncio.Runner()
        self._loop = self._runner.get_loop()
        self._loop.set_default_executor(self._executor)
        self._stop = asyncio.Event()
        self._started_evt.set()
        try:
            self._runner.run(self._serve())
        finally:
            self._runner.close()

    async def _serve(self) -> None:
        await self._stop.wait()

    def shutdown(self, *, graceful: bool = False) -> None:
        if not self._started:
            return
        ShutdownFanOut(self).run(graceful=graceful)

    # --- module registry -----------------------------------------------------

    def register_module(
        self,
        name: str,
        *,
        hooks: dict[str, Any] | None = None,
        gate_width: int | None = None,
    ) -> ModuleHandle:
        if name in self._handles:
            raise KeyError(f"module {name!r} already registered")
        width = gate_width if gate_width is not None else self._gate_widths.get(name, 1)
        handle = ModuleHandle(name=name, gate=ModuleGate(width), hooks=hooks)
        self._handles[name] = handle
        return handle

    def handle(self, name: str) -> ModuleHandle:
        try:
            return self._handles[name]
        except KeyError:
            raise KeyError(f"module {name!r} not registered") from None

    def gate(self, name: str) -> ModuleGate | None:
        handle = self._handles.get(name)
        return handle.gate if handle is not None else None

    def state(self, name: str) -> ModuleState:
        return self.handle(name).state

    def has_run(self, name: str, run_id: str) -> bool:
        return self.handle(name).get_task(run_id) is not None

    def run_ids(self, name: str) -> list[str]:
        return self.handle(name).run_ids()

    def wait_module_idle(self, name: str, *, timeout: float) -> bool:
        return self.handle(name).wait_idle(timeout)

    # --- driving the worker loop ---------------------------------------------

    def call(self, coro: Any) -> concurrent.futures.Future:
        """Marshal a coroutine onto the worker loop and return its future. The
        only way the API thread's coroutines run is through here."""
        if self._loop is None or self._loop.is_closed():
            raise RuntimeError("runtime worker loop is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def thread_is_worker(self) -> bool:
        return (
            self._worker_thread is not None
            and threading.current_thread() is self._worker_thread
        )

    def schedule(self, module: str, coro: Any, *, name: str) -> concurrent.futures.Future:
        """Boot a run on the worker loop under the module's context. Admission is
        refused while the module is paused, draining, or stopped (#121 D1)."""
        handle = self.handle(module)
        if handle.state is not ModuleState.RUNNING:
            raise ModuleAdmissionRefused(
                f"module {module!r} is {handle.state.value}; admission refused"
            )
        return self.call(self._tracked(handle, coro, name))

    async def _tracked(self, handle: ModuleHandle, coro: Any, name: str) -> Any:
        from polymerhus.app.llm.checkpoints import module_context

        current = asyncio.current_task()
        hold = handle.register_run(name, current)
        # The run's per-session hold signal rides the task context for the whole
        # run: every unit-boundary gate acquisition of THIS run (including child
        # tasks) honours it, and no other run sees it (Q14 per-session scope).
        token = _CURRENT_RUN_HOLD.set(hold)
        try:
            with module_context(handle.name):
                return await coro
        finally:
            _CURRENT_RUN_HOLD.reset(token)
            handle.unregister_run(name, current)

    def cancel_run(self, module: str, run_id: str) -> None:
        """Hard-cancel a registered run via `call_soon_threadsafe(task.cancel)`."""
        handle = self.handle(module)
        task = handle.get_task(run_id)
        if task is None:
            raise RunNotRegistered(run_id)
        self._loop.call_soon_threadsafe(task.cancel)

    def hold_session(self, module: str, run_id: str) -> None:
        """Hold ONE registered run by its session id (ADR #169 Q14): the run's
        NEXT unit boundary at the module gate waits until `resume_session`.
        Per-session, NOT module-wide: sibling runs of the same module keep
        dispatching. Mirrors `cancel_run` on an unregistered run id."""
        handle = self.handle(module)
        hold = handle.get_hold(run_id)
        if hold is None:
            raise RunNotRegistered(run_id)
        self._loop.call_soon_threadsafe(hold.clear)

    def resume_session(self, module: str, run_id: str) -> None:
        """Release a held run by its session id (ADR #169 Q14). A resume of a
        not-held (or never registered) run is a no-op with a logged warning,
        mirroring `resume` on a non-paused module."""
        handle = self.handle(module)
        hold = handle.get_hold(run_id)
        if hold is None or hold.is_set():
            logger.warning(
                "resume_session: run %s of module %s is not held (no-op)",
                run_id,
                module,
            )
            return
        self._loop.call_soon_threadsafe(hold.set)

    # --- per-module flow control ---------------------------------------------

    def pause(self, name: str) -> None:
        handle = self.handle(name)
        if handle.state is ModuleState.STOPPED:
            logger.warning("pause of stopped module %s is a no-op", name)
            return
        handle.state = ModuleState.PAUSED
        self._loop.call_soon_threadsafe(handle.gate.clear_running)

    def resume(self, name: str) -> None:
        handle = self.handle(name)
        if handle.state is not ModuleState.PAUSED:
            logger.warning("resume of non-paused module %s is a no-op", name)
            return
        handle.state = ModuleState.RUNNING
        self._loop.call_soon_threadsafe(handle.gate.set_running)

    def drain(self, name: str, *, timeout: float = _FANOUT_TIMEOUT) -> None:
        handle = self.handle(name)
        if handle.state is ModuleState.STOPPED:
            return
        self._settle_module(handle, timeout=timeout, graceful=True)

    def _settle_module(
        self, handle: ModuleHandle, *, timeout: float, graceful: bool = False
    ) -> None:
        """Stop admission and dispatch for a module, settle its runs to an empty
        registry, archive via the flush hook, and reach `stopped`.

        Graceful settle: after the module's registered termination hook, unblocked
        runs get the grace period to finish naturally; whatever is still in flight
        (typically a run blocked on the now-paused gate) is then hard-cancelled.
        Hard settle (shutdown default): cancel in-flight runs immediately."""
        handle.state = ModuleState.DRAINING
        self._loop.call_soon_threadsafe(handle.gate.clear_running)
        if graceful:
            termination = handle.hooks.get("termination")
            if termination is not None:
                fut = self.call(termination(handle.name))
                try:
                    fut.result(timeout=timeout)
                except (concurrent.futures.TimeoutError, Exception):  # noqa: B014
                    logger.warning(
                        "termination hook for %s did not settle; hard-cancelling",
                        handle.name,
                    )
            handle.wait_idle(timeout=timeout)
        remaining = handle.live_tasks()
        for task in remaining:
            self._loop.call_soon_threadsafe(task.cancel)
        handle.wait_idle(timeout=timeout)
        self._flush_module(handle)
        handle.state = ModuleState.STOPPED

    def _flush_module(self, handle: ModuleHandle) -> None:
        flush = handle.hooks.get("flush")
        if flush is not None:
            flush()
            return
        from polymerhus.app.llm.checkpoints import flush_module_index

        try:
            flush_module_index(handle.name)
        except Exception:
            logger.warning("flush of module %s failed", handle.name, exc_info=True)


class ShutdownFanOut:
    """The ratified shutdown walk (#121 G7c): for EVERY registered module, stop
    admission and dispatch, then close the ONE shared executor, then stop the
    worker loop.

    Per module: pause the gate, invoke the module's registered graceful
    termination feature when requested (default: hard-cancel in-flight runs),
    wait for the module to reach an empty registry, archive via the flush hook,
    and mark the module `stopped`.
    """

    def __init__(self, manager: RuntimeManager):
        self._manager = manager

    def run(self, *, graceful: bool = False, timeout: float = _FANOUT_TIMEOUT) -> None:
        m = self._manager
        if not m._started:
            return
        for handle in list(m._handles.values()):
            m._settle_module(handle, timeout=timeout, graceful=graceful)
        executor = m._executor
        if executor is not None:
            executor.shutdown(wait=True)
        m._executor = None
        m._loop.call_soon_threadsafe(m._stop.set)
        if m._worker_thread is not None:
            m._worker_thread.join(timeout=timeout)
        m._runner = None
        m._loop = None
        m._worker_thread = None
        m._started = False
        global _ACTIVE_RUNTIME
        with _ACTIVE_RUNTIME_LOCK:
            if _ACTIVE_RUNTIME is m:
                _ACTIVE_RUNTIME = None
