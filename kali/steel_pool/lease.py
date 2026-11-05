"""The Steel pool lease machine, heartbeat, TTL, and release hooks.

One lease binds one MCP session to one named browser session on one Steel
worker. The lease is the only place that knows the worker URL; the MCP layer
sees the session name and the Steel session id only.

The manager owns four signals:

* an explicit end, from ``browser_end``;
* an MCP session close;
* an MCP server shutdown or project stop;
* the lease TTL.

The heartbeat is not a release signal. It runs only while the lease is idle,
runs the cheap CLI ``get url`` command, and updates ``last_heartbeat``.
The TTL is authoritative: when neither a browsing command nor a heartbeat has
succeeded for the TTL, the same capture-stop-release path runs.

A failed stop and a failed API release quarantine the worker, so an orphan
session is never leased again in the same run. A failed heartbeat does not
release the lease; the TTL is the backstop.

The module is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import math
import threading
import time
from typing import Protocol

try:  # package layout
    from kali.steel_pool.api import WorkerAPIError
    from kali.steel_pool.cli import (
        CaptureError,
        CapturedContext,
        CliError,
        CliSession,
        RestoreReport,
    )
    from kali.steel_pool.pool import PoolReport, Worker
    from kali.steel_pool.store import (
        BrowserSessionRecord,
        SessionStore,
        SessionStoreError,
        validate_name,
    )
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.api import WorkerAPIError  # type: ignore[no-redef]
    from steel_pool.cli import (  # type: ignore[no-redef]
        CaptureError,
        CapturedContext,
        CliError,
        CliSession,
        RestoreReport,
    )
    from steel_pool.pool import PoolReport, Worker  # type: ignore[no-redef]
    from steel_pool.store import (  # type: ignore[no-redef]
        BrowserSessionRecord,
        SessionStore,
        SessionStoreError,
        validate_name,
    )

DEFAULT_HEARTBEAT_S = 120.0
DEFAULT_LEASE_TTL_S = 600.0
DEFAULT_POOL_WAIT_S = 30.0
DEFAULT_TICK_S = 1.0
_HEARTBEAT_COMMAND = ("get", "url")

__all__ = [
    "DEFAULT_HEARTBEAT_S",
    "DEFAULT_LEASE_TTL_S",
    "DEFAULT_POOL_WAIT_S",
    "DEFAULT_TICK_S",
    "EndReport",
    "HeartbeatRunner",
    "HeartbeatThread",
    "Lease",
    "LeaseError",
    "LeaseManager",
    "LeaseView",
    "PoolExhausted",
]


class LeaseError(RuntimeError):
    """A lease operation is not valid in the current state."""


class PoolExhausted(LeaseError):
    """No healthy worker became free within the bounded pool wait."""


class CliAdapter(Protocol):
    """The CLI adapter slice the lease manager needs."""

    def start(self, name: str) -> CliSession: ...

    def restore(
        self, session: CliSession, record: BrowserSessionRecord
    ) -> RestoreReport: ...

    def exec(self, session: CliSession, args: Sequence[str]) -> dict: ...

    def capture(
        self,
        session: CliSession,
        previous: BrowserSessionRecord | None = None,
    ) -> CapturedContext: ...

    def stop(self, session: CliSession) -> dict: ...

    def release(self, session: CliSession) -> bool: ...


class WorkerSource(Protocol):
    """The worker registry slice the lease manager needs."""

    def refresh(self) -> PoolReport: ...


class HeartbeatRunner(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class LeaseView:
    """The agent-visible lease result. It never carries the worker URL."""

    name: str
    steel_session_id: str
    mcp_session_id: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class EndReport:
    """The outcome of one end path."""

    ended: bool
    reason: str
    captured: bool = False
    saved: bool = False
    stopped: bool = False
    released: bool | None = None
    warnings: tuple[str, ...] = ()


@dataclass
class Lease:
    """One live lease. The manager owns every mutation."""

    mcp_session_id: str
    session_name: str
    worker: Worker
    cli: CliAdapter
    cli_session: CliSession
    previous: BrowserSessionRecord | None
    account: str | None
    created_at: float
    last_activity: float
    last_heartbeat: float
    state: str = "acquiring"
    heartbeat_failures: int = 0
    restore_warnings: tuple[str, ...] = ()
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def view(self) -> LeaseView:
        return LeaseView(
            name=self.session_name,
            steel_session_id=self.cli_session.session_id,
            mcp_session_id=self.mcp_session_id,
            warnings=self.restore_warnings,
        )


def _noop_emit(event: str, **fields: object) -> None:
    return None


def _validate_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validate_positive(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a positive number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive number")
    return number


def _validate_non_negative(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must not be negative")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{label} must not be negative")
    return number


class HeartbeatThread:
    """The per-lease heartbeat task.

    The thread wakes on a short tick and asks the manager whether the lease
    needs a heartbeat or has reached its TTL. A heartbeat or an end that takes
    longer than one tick simply delays the next check; the wake-ups do not
    accumulate.
    """

    def __init__(
        self,
        manager: "LeaseManager",
        lease: Lease,
        *,
        interval_s: float = DEFAULT_TICK_S,
    ) -> None:
        self._manager = manager
        self._lease = lease
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"steel-heartbeat-{lease.session_name}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=5.0)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            try:
                self._manager.tick_lease(self._lease)
            except Exception as exc:  # noqa: BLE001 - the thread must survive
                # An unexpected failure is visible, and the next tick still
                # checks the TTL first. The TTL is the backstop for a broken
                # heartbeat, so the loop must not die on one bad tick.
                self._manager.emit(
                    "lease.heartbeat_error",
                    session=self._lease.session_name,
                    error=f"{type(exc).__name__}: {exc}",
                )


class LeaseManager:
    """Lease, heartbeat, TTL, and release for the browser MCP server."""

    def __init__(
        self,
        registry: WorkerSource,
        store: SessionStore,
        cli_factory: Callable[[Worker], CliAdapter],
        *,
        account: str | None = None,
        pool_wait_s: float = DEFAULT_POOL_WAIT_S,
        heartbeat_s: float = DEFAULT_HEARTBEAT_S,
        ttl_s: float = DEFAULT_LEASE_TTL_S,
        tick_s: float = DEFAULT_TICK_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        emit: Callable[..., None] | None = None,
        runner_factory: Callable[["LeaseManager", Lease], HeartbeatRunner] | None = None,
    ) -> None:
        if not callable(registry.refresh):
            raise ValueError("the worker registry must expose refresh()")
        if not callable(cli_factory):
            raise ValueError("the CLI factory must be callable")
        if account is not None and not isinstance(account, str):
            raise ValueError("the account must be a string or None")
        self._registry = registry
        self._store = store
        self._cli_factory = cli_factory
        self._account = account
        self._pool_wait_s = _validate_non_negative(pool_wait_s, "the pool wait")
        self._heartbeat_s = _validate_positive(heartbeat_s, "the heartbeat period")
        self._ttl_s = _validate_positive(ttl_s, "the lease TTL")
        self._tick_s = _validate_positive(tick_s, "the heartbeat tick")
        self._clock = clock
        self._sleep = sleep
        self._emit = emit or _noop_emit
        self._runner_factory = runner_factory or (
            lambda manager, lease: HeartbeatThread(
                manager, lease, interval_s=manager._tick_s
            )
        )
        self._lock = threading.RLock()
        self._discovery_lock = threading.Lock()
        self._leases: dict[str, Lease] = {}
        self._runners: dict[str, HeartbeatRunner] = {}
        self._reserved: set[str] = set()
        self._starting: set[str] = set()
        self._names: set[str] = set()
        self._quarantined: set[str] = set()
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        mcp_session_id: str,
        name: str,
        url: str | None = None,
    ) -> LeaseView:
        """Mount one named browser session on a free worker.

        A repeated start on the same MCP session returns the existing lease.
        A second MCP session cannot mount the same name: the CLI start would
        replace the first daemon and orphan its API session.
        """
        _validate_id(mcp_session_id, "the MCP session id")
        validate_name(name)
        if url is not None and (not isinstance(url, str) or not url.strip()):
            raise ValueError("the start URL must be a non-empty string")

        with self._lock:
            self._ensure_open()
            existing = self._leases.get(mcp_session_id)
            if existing is not None:
                return existing.view()
            if mcp_session_id in self._starting:
                raise LeaseError(
                    "a browser start is already in progress for this MCP session"
                )
            self._reject_duplicate_name(name)
            if name in self._names:
                raise LeaseError(
                    f"a browser start is already in progress for {name!r}"
                )
            self._starting.add(mcp_session_id)
            self._names.add(name)

        worker: Worker | None = None
        cli: CliAdapter | None = None
        cli_session: CliSession | None = None
        previous: BrowserSessionRecord | None = None
        lease: Lease | None = None
        try:
            worker = self._acquire_worker()
            previous = self._store.load(name)
            cli = self._cli_factory(worker)
            cli_session = cli.start(name)
            now = self._clock()
            lease = Lease(
                mcp_session_id=mcp_session_id,
                session_name=name,
                worker=worker,
                cli=cli,
                cli_session=cli_session,
                previous=previous,
                account=previous.account if previous else self._account,
                created_at=now,
                last_activity=now,
                last_heartbeat=now,
                state="mounting",
            )
            restored = cli.restore(
                cli_session,
                previous if previous is not None else BrowserSessionRecord(name=name),
            )
            lease.restore_warnings = restored.warnings
            lease.state = "active"
            lease.last_activity = self._clock()
            lease.last_heartbeat = lease.last_activity
            if url is not None:
                payload = cli.exec(cli_session, ["navigate", url])
                self._raise_on_command_error(payload, "navigate to the start URL")
                lease.last_activity = self._clock()
            runner = self._runner_factory(self, lease)
            with self._lock:
                self._ensure_open()
                self._leases[mcp_session_id] = lease
                self._runners[mcp_session_id] = runner
                self._reserved.discard(worker.container_id)
                self._starting.discard(mcp_session_id)
                self._names.discard(name)
                runner.start()
            self.emit(
                "lease.mounted",
                session=name,
                worker=worker.container_name,
                warnings=len(lease.restore_warnings),
            )
            return lease.view()
        except BaseException:
            if worker is not None:
                self._abandon_start(worker, cli, cli_session, lease)
            with self._lock:
                self._starting.discard(mcp_session_id)
                self._names.discard(name)
            raise

    def exec(self, mcp_session_id: str, args: Sequence[str]) -> dict:
        """Run one browsing command on the active lease."""
        _validate_id(mcp_session_id, "the MCP session id")
        if isinstance(args, (str, bytes)) or not args:
            raise ValueError("a browser command is required")
        for arg in args:
            if not isinstance(arg, str):
                raise ValueError("a browser command argument is not a string")
        lease = self._active_lease(mcp_session_id)
        with lease.lock:
            if lease.state != "active":
                raise LeaseError("the browser session is not active")
            payload = lease.cli.exec(lease.cli_session, list(args))
            lease.last_activity = self._clock()
            return payload

    def end(self, mcp_session_id: str, *, reason: str = "explicit") -> EndReport:
        """Capture, save, stop, and release one lease.

        Capture and store failures are reported but never block the stop or
        the release. An end with no lease is a no-op.
        """
        _validate_id(mcp_session_id, "the MCP session id")
        with self._lock:
            lease = self._leases.get(mcp_session_id)
        if lease is None:
            return EndReport(ended=False, reason=reason)
        return self._end_lease(lease, reason=reason)

    def close_mcp_session(self, mcp_session_id: str) -> EndReport:
        """The MCP session close hook."""
        return self.end(mcp_session_id, reason="mcp_close")

    def shutdown(self) -> tuple[EndReport, ...]:
        """End every active lease. Safe to call more than once."""
        with self._lock:
            self._closed = True
            leases = list(self._leases.values())
        return tuple(self._end_lease(lease, reason="shutdown") for lease in leases)

    def lease(self, mcp_session_id: str) -> LeaseView | None:
        with self._lock:
            lease = self._leases.get(mcp_session_id)
            return None if lease is None else lease.view()

    def active_count(self) -> int:
        with self._lock:
            return len(self._leases)

    # ------------------------------------------------------------------
    # Heartbeat and TTL
    # ------------------------------------------------------------------

    def tick(self, now: float | None = None) -> None:
        """Run one heartbeat and TTL pass over every lease."""
        with self._lock:
            leases = list(self._leases.values())
        for lease in leases:
            self.tick_lease(lease, now=now)

    def tick_lease(self, lease: Lease, now: float | None = None) -> None:
        """Run one heartbeat and TTL pass for one lease."""
        current = self._clock() if now is None else now
        if lease.state != "active":
            return
        if self._expired(lease, current):
            self._end_lease(lease, reason="ttl")
            return
        if current - max(lease.last_activity, lease.last_heartbeat) >= (
            self._heartbeat_s
        ):
            self.heartbeat(lease, now=current)

    def heartbeat(self, lease: Lease, now: float | None = None) -> bool:
        """Run one idle heartbeat. A failure does not release the lease."""
        current = self._clock() if now is None else now
        with lease.lock:
            if lease.state != "active":
                return False
            if current - max(lease.last_activity, lease.last_heartbeat) < (
                self._heartbeat_s
            ):
                return False
            try:
                payload = lease.cli.exec(lease.cli_session, list(_HEARTBEAT_COMMAND))
            except CliError as exc:
                lease.heartbeat_failures += 1
                self.emit(
                    "lease.heartbeat_failed",
                    session=lease.session_name,
                    failures=lease.heartbeat_failures,
                    error=str(exc),
                )
                return False
            if payload.get("success") is False or payload.get("error"):
                lease.heartbeat_failures += 1
                self.emit(
                    "lease.heartbeat_failed",
                    session=lease.session_name,
                    failures=lease.heartbeat_failures,
                    error=str(payload.get("error") or "the heartbeat command failed"),
                )
                return False
            lease.last_heartbeat = current
            lease.heartbeat_failures = 0
            self.emit("lease.heartbeat", session=lease.session_name)
            return True

    def _expired(self, lease: Lease, now: float) -> bool:
        last = max(lease.last_activity, lease.last_heartbeat)
        return now - last >= self._ttl_s

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._closed:
            raise LeaseError("the lease manager is shut down")

    def _reject_duplicate_name(self, name: str) -> None:
        for lease in self._leases.values():
            if lease.session_name == name:
                raise LeaseError(
                    f"the browser session {name!r} is already mounted"
                )

    def _acquire_worker(self) -> Worker:
        deadline = self._clock() + self._pool_wait_s
        while True:
            with self._discovery_lock:
                report = self._registry.refresh()
            with self._lock:
                self._quarantined.update(
                    worker.container_id for worker in report.unhealthy
                )
                for worker in report.healthy:
                    if worker.container_id in self._quarantined:
                        continue
                    if worker.container_id in self._reserved:
                        continue
                    if any(
                        lease.worker.container_id == worker.container_id
                        for lease in self._leases.values()
                    ):
                        continue
                    self._reserved.add(worker.container_id)
                    return worker
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise PoolExhausted(
                    "no healthy Steel worker is free within the pool wait"
                )
            self._sleep(min(1.0, remaining))

    def _active_lease(self, mcp_session_id: str) -> Lease:
        with self._lock:
            lease = self._leases.get(mcp_session_id)
        if lease is None:
            raise LeaseError("no browser session is mounted for this MCP session")
        return lease

    def _abandon_start(
        self,
        worker: Worker,
        cli: CliAdapter | None,
        cli_session: CliSession | None,
        lease: Lease | None,
    ) -> None:
        """Compensate a failed start and free or quarantine the worker."""
        healthy = True
        if cli is not None and cli_session is not None:
            healthy = self._stop_and_release(cli, cli_session)
        with self._lock:
            self._reserved.discard(worker.container_id)
            if lease is not None:
                if self._leases.get(lease.mcp_session_id) is lease:
                    self._leases.pop(lease.mcp_session_id, None)
                self._runners.pop(lease.mcp_session_id, None)
                lease.state = "released"
            if not healthy:
                self._quarantined.add(worker.container_id)
        self.emit(
            "lease.mount_failed",
            worker=worker.container_name,
            quarantined=not healthy,
        )

    def _end_lease(self, lease: Lease, *, reason: str) -> EndReport:
        with lease.lock:
            with self._lock:
                if lease.state == "released":
                    return EndReport(ended=False, reason=reason)
                lease.state = "ending"
            self._stop_runner(lease.mcp_session_id)
            warnings: list[str] = []
            captured = False
            saved = False
            try:
                captured_context = lease.cli.capture(
                    lease.cli_session, lease.previous
                )
                captured = True
                warnings.extend(captured_context.warnings)
                record = self._record_from_capture(lease, captured_context)
                self._store.save(record)
                saved = True
            except (
                CaptureError,
                CliError,
                WorkerAPIError,
                SessionStoreError,
            ) as exc:
                warnings.append(f"the session state was not saved: {exc}")
            stopped, released, healthy = self._stop_and_release_report(
                lease.cli, lease.cli_session
            )
            with self._lock:
                lease.state = "released"
                self._leases.pop(lease.mcp_session_id, None)
                if not healthy:
                    self._quarantined.add(lease.worker.container_id)
            self.emit(
                "lease.released",
                session=lease.session_name,
                reason=reason,
                captured=captured,
                saved=saved,
                stopped=stopped,
                released=released,
                quarantined=not healthy,
            )
            return EndReport(
                ended=True,
                reason=reason,
                captured=captured,
                saved=saved,
                stopped=stopped,
                released=released,
                warnings=tuple(warnings),
            )

    def _record_from_capture(
        self, lease: Lease, captured: CapturedContext
    ) -> BrowserSessionRecord:
        context = captured.context
        local_storage = context.get("localStorage")
        session_storage = context.get("sessionStorage")
        indexed_db = context.get("indexedDB")
        if captured.source == "cli" and lease.previous is not None:
            # The CLI fallback sees one origin and no sessionStorage or
            # indexedDB. Keep the prior evidence for the rest of the record.
            merged = dict(lease.previous.local_storage)
            if isinstance(local_storage, Mapping):
                merged.update(local_storage)
            local_storage = merged
            if session_storage is None:
                session_storage = lease.previous.session_storage
            if indexed_db is None:
                indexed_db = lease.previous.indexed_db
        kwargs: dict[str, object] = {}
        if lease.previous is not None:
            kwargs["created_at"] = lease.previous.created_at
        return BrowserSessionRecord.from_context(
            lease.session_name,
            {
                "cookies": context.get("cookies") or [],
                "localStorage": local_storage or {},
                "sessionStorage": session_storage or {},
                "indexedDB": indexed_db or {},
            },
            account=lease.account,
            **kwargs,
        )

    def _stop_and_release(
        self, cli: CliAdapter, cli_session: CliSession
    ) -> bool:
        _, _, healthy = self._stop_and_release_report(cli, cli_session)
        return healthy

    def _stop_and_release_report(
        self, cli: CliAdapter, cli_session: CliSession
    ) -> tuple[bool, bool | None, bool]:
        """Return ``(stopped, released, worker_is_healthy)``.

        ``stopped`` means the CLI stop succeeded. ``released`` is ``True``
        when the API release succeeded, ``False`` when the API reported the
        session already gone, and ``None`` when the release was not needed or
        failed. The worker is healthy when the session is provably gone.
        """
        try:
            cli.stop(cli_session)
            return True, None, True
        except Exception as exc:  # noqa: BLE001 - cleanup must not be blocked
            self.emit("lease.stop_failed", error=f"{type(exc).__name__}: {exc}")
        try:
            released = cli.release(cli_session)
        except Exception as exc:  # noqa: BLE001 - cleanup must not be blocked
            self.emit("lease.release_failed", error=f"{type(exc).__name__}: {exc}")
            return False, None, False
        return False, released, True

    def _stop_runner(self, mcp_session_id: str) -> None:
        with self._lock:
            runner = self._runners.pop(mcp_session_id, None)
        if runner is not None:
            runner.stop()

    @staticmethod
    def _raise_on_command_error(payload: Mapping, action: str) -> None:
        if payload.get("success") is False or payload.get("error"):
            message = payload.get("error")
            if isinstance(message, Mapping):
                message = message.get("message") or message.get("code")
            raise LeaseError(f"could not {action}: {message or 'command failed'}")

    def emit(self, event: str, **fields: object) -> None:
        """Emit one structured event. A logger failure never breaks a lease."""
        try:
            self._emit(event, **fields)
        except Exception:
            return None
