"""The live crawl: real CDP transport, CLI page factory, and job assembly.

Spec: `docs/design/steel-crawl-spec.md` sections 2, 4, 9, 10.4, 11, and 12.

This module is the production wiring between the pure crawl engine and the
runtime. It owns four adapters:

- `LiveCdpTransport` reads the browser-level CDP websocket the Steel API
  returns, attaches to the session's page target, and satisfies the sidecar's
  two-method transport seam. It never sends a browser action; the CLI owns
  every action.
- `LivePageFactory` navigates through the CLI, reads the compact snapshot,
  projects the live forms through one JS expression, and registers the page in
  `BrowserState`. The snapshot keeps the CLI refs; a synthetic form node names
  its CSS selector explicitly.
- `api_session_record` reads the runtime session record the CLI does not
  expose (the websocket and clocks) from the Steel API.
- `run_live_crawl` assembles `CrawlJob` and `CrawlRun` from those adapters and
  returns the terminal job plus the durable paths the caller reads back.

The engine remains the only decision maker. Nothing here chooses a candidate,
executes an action, or rewrites a flow.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from polymerhus.recon.crawl.steel.auth import (
    AuthOracle,
    AuthVerdict,
    session_fetch_fn,
)
from polymerhus.recon.crawl.steel.capture.flow import Flow
from polymerhus.recon.crawl.steel.capture.history import (
    CaptureContext,
    HistoryClient,
)
from polymerhus.recon.crawl.steel.capture.sidecar import CaptureSidecar
from polymerhus.recon.crawl.steel.command import CommandMapper
from polymerhus.recon.crawl.steel.enumerate import (
    ElementMap,
    SnapshotNode,
)
from polymerhus.recon.crawl.steel.forms import FormExecutor, FormLedger
from polymerhus.recon.crawl.steel.frontier import FrontierResult
from polymerhus.recon.crawl.steel.job import (
    ActionRecord,
    CrawlJob,
    JobResult,
    PageRecord,
)
from polymerhus.recon.crawl.steel.ledger import RunLedger
from polymerhus.recon.crawl.steel.manifest import (
    Manifest,
    RunBlock,
    build_manifest_from_output,
    write_manifest,
)
from polymerhus.recon.crawl.steel.policy.jev import (
    JevPolicy,
    TypeSafeDecisionClient,
)
from polymerhus.recon.crawl.steel.policy.select import (
    DEFAULT_VALUE_CATALOGUE,
    ValueCatalogue,
)
from polymerhus.recon.crawl.steel.run import CrawlRun
from polymerhus.recon.crawl.steel.session import SteelSessionClient
from polymerhus.recon.crawl.steel.snapshot import (
    form_projection_script,
    merge_form_projections,
    parse_compact_snapshot,
    parse_form_projections,
)
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    SnapshotFacts,
    normalize_url,
)

logger = logging.getLogger(__name__)

CDP_BODY_LIMIT = 2**24
CDP_TIMEOUT_S = 30.0
SNAPSHOT_COMMAND = ("snapshot", "-i", "-c", "-u")
NAVIGATE_ARGS = ("--wait-until", "domcontentloaded")
MAX_DURATION_S_DEFAULT = 600


class LiveCrawlError(RuntimeError):
    """A runtime component could not be assembled or read."""


class LiveCdpEvent:
    """One inbound CDP event with the two fields the sidecar reads."""

    __slots__ = ("method", "params")

    def __init__(self, method: str, params: Mapping[str, Any]) -> None:
        self.method = method
        self.params = params


class LiveCdpTransport:
    """A synchronous browser-level CDP connection for the passive sidecar.

    The websocket the Steel API returns is the browser-level endpoint. The
    transport attaches to the session's page target once, then every command
    and every event carries that target's flattened session id. The transport
    is read-only: the sidecar owns every command it sends, and the crawl's
    actions reach the browser only through the CLI.
    """

    def __init__(
        self,
        endpoint: Callable[[], tuple[str, str] | None],
        *,
        target_type: str = "page",
        timeout_s: float = CDP_TIMEOUT_S,
    ) -> None:
        if not callable(endpoint):
            raise ValueError("the CDP endpoint must be callable")
        self._endpoint = endpoint
        self._ws = None
        self._reader: threading.Thread | None = None
        self._timeout_s = timeout_s
        self._target_type = target_type
        self._next_id = 0
        self._pending: dict[int, queue.Queue[Mapping[str, Any]]] = {}
        self._events: queue.Queue[LiveCdpEvent] = queue.Queue()
        self._session_id: str | None = None
        self._lock = threading.Lock()
        self._closed = False

    @property
    def session_id(self) -> str | None:
        """The flattened CDP session id the page target was attached under."""
        return self._session_id

    def _connect(self) -> None:
        """Open the socket lazily and present the worker's localhost Host.

        The socket goes to the container address; the URI carries the Host and
        the path. Chrome's CDP proxy rejects any Host that is not localhost.
        """
        if self._ws is not None:
            return
        if self._closed:
            raise LiveCrawlError("the CDP transport is closed")
        endpoint = self._endpoint()
        if not endpoint:
            raise LiveCrawlError(
                "the browser session carries no CDP endpoint; capture is unavailable"
            )
        url, cdp_host = endpoint
        parts = urlsplit(url or "")
        if parts.scheme not in ("ws", "wss") or not parts.hostname:
            raise LiveCrawlError("the browser session carries an invalid CDP URL")
        authority = (cdp_host or "").strip()
        if (
            not authority
            or "://" in authority
            or "/" in authority
            or any(character.isspace() for character in authority)
        ):
            raise LiveCrawlError("the browser session carries an invalid CDP Host")
        if ":" not in authority:
            authority = f"{authority}:{parts.port or (443 if parts.scheme == 'wss' else 80)}"
        uri = f"{parts.scheme}://{authority}{parts.path or '/'}"
        if parts.query:
            uri = f"{uri}?{parts.query}"
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        import socket  # noqa: PLC0415

        try:
            sock = socket.create_connection((parts.hostname, port), timeout=15)
        except OSError as exc:
            raise LiveCrawlError(
                f"the CDP socket to {parts.hostname}:{port} failed: {exc}"
            ) from exc
        from websockets.sync.client import connect  # noqa: PLC0415

        try:
            if parts.scheme == "wss":
                import ssl  # noqa: PLC0415

                self._ws = connect(
                    uri,
                    sock=sock,
                    ssl=ssl.create_default_context(),
                    server_hostname=parts.hostname,
                    max_size=CDP_BODY_LIMIT,
                    open_timeout=15,
                    proxy=None,
                )
            else:
                self._ws = connect(
                    uri,
                    sock=sock,
                    max_size=CDP_BODY_LIMIT,
                    open_timeout=15,
                    proxy=None,
                )
        except Exception as exc:  # noqa: BLE001 - one typed connection failure
            try:
                sock.close()
            except OSError:
                pass
            raise LiveCrawlError(f"the CDP connection failed: {exc}") from exc
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _ensure_page(self) -> None:
        if self._session_id is None:
            self.attach_page()

    def attach_page(self) -> Mapping[str, Any]:
        """Attach to the session's page target and return its target info."""
        self._connect()
        targets = self.send("Target.getTargets").get("targetInfos") or []
        pages = [
            target
            for target in targets
            if isinstance(target, Mapping)
            and target.get("type") == self._target_type
            and not str(target.get("url") or "").startswith("chrome")
        ]
        if not pages:
            raise LiveCrawlError("the Steel session exposes no page target")
        page = pages[-1]
        result = self.send(
            "Target.attachToTarget",
            {"targetId": page.get("targetId"), "flatten": True},
        )
        session_id = result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise LiveCrawlError("the CDP page target could not be attached")
        self._session_id = session_id
        return page

    def send(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        """Send one command and return its result object."""
        if self._closed:
            raise LiveCrawlError("the CDP transport is closed")
        self._connect()
        if self._session_id is None and not method.startswith("Target."):
            # The sidecar's first enable command must reach the page target,
            # not the browser root. The page attach is part of the transport.
            self._ensure_page()
        with self._lock:
            self._next_id += 1
            command_id = self._next_id
            waiter: queue.Queue[Mapping[str, Any]] = queue.Queue(maxsize=1)
            self._pending[command_id] = waiter
            message: dict[str, Any] = {
                "id": command_id,
                "method": method,
                "params": dict(params or {}),
            }
            if self._session_id is not None:
                message["sessionId"] = self._session_id
            self._ws.send(json.dumps(message))
        try:
            response = waiter.get(timeout=self._timeout_s)
        except queue.Empty as exc:
            raise LiveCrawlError(
                f"CDP {method} did not answer within {self._timeout_s}s"
            ) from exc
        finally:
            self._pending.pop(command_id, None)
        error = response.get("error")
        if isinstance(error, Mapping):
            raise LiveCrawlError(
                f"CDP {method} failed: {error.get('message') or error}"
            )
        result = response.get("result")
        return result if isinstance(result, Mapping) else {}

    def replay(self):
        """Yield the queued inbound events, never blocking past the queue."""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            yield event

    def close(self) -> None:
        """Close the websocket and stop the reader."""
        if self._closed:
            return
        self._closed = True
        ws, reader = self._ws, self._reader
        self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001 - close is best-effort
                pass
        if reader is not None:
            reader.join(timeout=5)

    def _read(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            for raw in ws:
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(message, Mapping):
                    continue
                command_id = message.get("id")
                if isinstance(command_id, int) and command_id in self._pending:
                    waiter = self._pending.get(command_id)
                    if waiter is not None:
                        try:
                            waiter.put_nowait(message)
                        except queue.Full:
                            pass
                    continue
                method = message.get("method")
                if not isinstance(method, str):
                    continue
                event_session = message.get("sessionId")
                if (
                    self._session_id is not None
                    and isinstance(event_session, str)
                    and event_session != self._session_id
                ):
                    continue
                params = message.get("params")
                self._events.put(
                    LiveCdpEvent(
                        method,
                        params if isinstance(params, Mapping) else {},
                    )
                )
        except Exception:  # noqa: BLE001 - a closed socket ends the reader
            return


@dataclass
class LiveRunContext:
    """The runtime inputs one live crawl needs, all supplied by its caller."""

    project_id: str
    run_id: str
    session_name: str
    target_url: str
    scope: Sequence[str]
    data_root: str | Path
    auth_probe: str | None = None
    login_url: str | None = None
    account: str | None = None
    edge_url: str | None = None
    edge_token: str | None = None
    browser_mcp_url: str = ""
    max_duration_s: float = MAX_DURATION_S_DEFAULT
    cancel: Callable[[], bool] | None = None
    coverage: Mapping[str, Any] = field(default_factory=dict)
    started_at: str | None = None


@dataclass(frozen=True)
class LiveRunResult:
    """The terminal job and the durable artifacts the caller reads back."""

    job: JobResult
    manifest: Manifest
    run_dir: Path
    ledger_path: Path
    manifest_path: Path
    summary_path: Path
    flow_count: int
    artifact_count: int
    duration_s: float
    verdict: AuthVerdict | None = None


class LivePageFactory:
    """Navigate, snapshot, project forms, and register one page instance."""

    def __init__(
        self,
        *,
        session: SteelSessionClient,
        sidecar: CaptureSidecar,
        state: BrowserState,
        page_prefix: str = "page",
    ) -> None:
        self._session = session
        self._sidecar = sidecar
        self._state = state
        self._page_prefix = page_prefix
        self._counter = 0

    def navigate(self, url: str) -> None:
        """One navigation, with the CLI's own wait; no snapshot is re-read."""
        self._session.execute("navigate", url, *NAVIGATE_ARGS)

    def __call__(
        self,
        url: str,
        parent: PageInstance | None,
        depth: int,
        source: str,
        navigation_path: tuple[str, ...],
    ) -> PageInstance:
        envelope = self._session.execute("navigate", url, *NAVIGATE_ARGS)
        data = envelope.get("data")
        final_url = url
        title = ""
        if isinstance(data, Mapping):
            final_url = str(data.get("url") or url)
            title = str(data.get("title") or "")
        snapshot = self._read_snapshot(final_url)
        forms = self._read_forms()
        roots = merge_form_projections(snapshot, forms)
        status = self._document_status(final_url)
        self._counter += 1
        return self._state.open_page(
            page_visit_id=f"{self._page_prefix}_{self._counter}",
            url=url,
            final_url=final_url,
            title=title,
            status=status,
            parent_id=parent.page_visit_id if parent else None,
            depth=depth,
            discovery_source=source,
            navigation_path=navigation_path,
            snapshot=roots,
            facts=SnapshotFacts(
                ax_hash=_ax_hash(roots),
                overlay_flags=_overlay_flags(roots),
            ),
        )

    def _read_snapshot(self, base_url: str) -> tuple[SnapshotNode, ...]:
        envelope = self._session.execute(*SNAPSHOT_COMMAND)
        data = envelope.get("data")
        text = data if isinstance(data, str) else ""
        return parse_compact_snapshot(text, base_url=base_url)

    def capture_current(
        self, page: PageInstance
    ) -> tuple[tuple[SnapshotNode, ...], SnapshotFacts]:
        """Re-capture the live document after a restore.

        The CLI refs are document-scoped; a restore reloads the document, so
        the executor must project the new refs, not the cached ones.
        """
        base = page.final_url or page.url
        roots = merge_form_projections(
            self._read_snapshot(base), self._read_forms()
        )
        return roots, SnapshotFacts(
            ax_hash=_ax_hash(roots), overlay_flags=_overlay_flags(roots)
        )

    def _read_forms(self):
        envelope = self._session.execute("eval", form_projection_script())
        data = envelope.get("data")
        return parse_form_projections(data)

    def _document_status(self, final_url: str) -> int | None:
        if not self._sidecar.attached:
            return None
        self._sidecar.pump()
        target = _normalize(final_url)
        for flow in reversed(self._sidecar.flows):
            if flow.resource_type != "Document":
                continue
            if _normalize(flow.url) == target and flow.status is not None:
                return flow.status
        return None


def _normalize(url: str) -> str:
    try:
        return normalize_url(url)
    except Exception:  # noqa: BLE001 - a non-URL document has no status
        return url


def _walk(nodes: Sequence[SnapshotNode]):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _ax_hash(roots: Sequence[SnapshotNode]) -> str:
    import hashlib  # noqa: PLC0415

    items = sorted(
        f"{node.role or node.tag}:{node.name or ''}"
        for node in _walk(roots)
        if node.ref
    )
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


def _overlay_flags(roots: Sequence[SnapshotNode]) -> frozenset[str]:
    return frozenset(
        (node.name or "").strip()
        for node in _walk(roots)
        if (node.role or "").lower() in {"dialog", "alertdialog"}
        and (node.name or "").strip()
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_live_crawl(ctx: LiveRunContext) -> LiveRunResult:
    """Assemble and run one live authenticated crawl; never swallow a failure."""
    started = time.monotonic()
    started_at = ctx.started_at or _utcnow()
    project_dir = Path(ctx.data_root) / ctx.project_id
    run_dir = project_dir / "steel-crawl" / ctx.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = run_dir / "ledger.jsonl"
    manifest_path = run_dir / "manifest.json"
    summary_path = run_dir / "summary.json"

    if not (ctx.browser_mcp_url or "").strip():
        raise LiveCrawlError(
            "KALI_BROWSER_MCP_URL is unset; the browser pool is unavailable"
        )
    session = SteelSessionClient.from_mcp(ctx.browser_mcp_url)
    # The transport opens lazily, after the job has mounted the lease and the
    # start result has supplied the container address and the localhost Host.
    transport = LiveCdpTransport(lambda: session.cdp_endpoint)
    sidecar = CaptureSidecar(transport)
    state = BrowserState()
    mapper = CommandMapper(session, state)
    form_ledger = FormLedger()
    page_factory = LivePageFactory(
        session=session, sidecar=sidecar, state=state
    )
    policy_client = TypeSafeDecisionClient()
    policy = JevPolicy(policy_client, state=state)
    catalogue = ValueCatalogue(
        DEFAULT_VALUE_CATALOGUE.entries, run_id=ctx.run_id
    )
    ledger = RunLedger(ledger_path)
    holder: dict[str, Any] = {}
    deadline_at = started + ctx.max_duration_s

    def deadline() -> bool:
        return time.monotonic() >= deadline_at

    def cancel() -> bool:
        return bool(ctx.cancel is not None and ctx.cancel())

    def submit_check(form) -> bool:
        sidecar.pump()
        flows = sidecar.flows
        start = holder.get("seen", {}).get(form.fingerprint, 0)
        holder.setdefault("seen", {})[form.fingerprint] = len(flows)
        return any(
            200 <= (flow.status or 0) < 300 for flow in flows[start:]
        )

    executor = FormExecutor(
        mapper=mapper,
        policy=policy,
        catalogue=catalogue,
        ledger=form_ledger,
        submit_check=submit_check,
    )

    def navigate(url: str) -> None:
        page_factory.navigate(url)

    def submit_form(page, element):
        executor.submit(page, element, generation=state.current_generation)

    def build_crawl() -> CrawlRun:
        """Build the traversal after the job mounted the session.

        The capture context needs the runtime session id, and the id exists
        only after `browser_start`. The job mounts first, then calls `run_fn`.
        """
        attached = session.attached
        return CrawlRun(
            project_id=ctx.project_id,
            capture_context=CaptureContext(
                run_id=ctx.run_id,
                session_id=attached.session_id if attached is not None else "",
            ),
            session=session,
            state=state,
            sidecar=sidecar,
            policy=policy,
            mapper=mapper,
            element_map=ElementMap(),
            ledger=ledger,
            form_ledger=form_ledger,
            page_factory=page_factory,
            navigate=navigate,
            submit_form=submit_form,
            in_scope=_scope_predicate(ctx.scope),
            deadline=deadline,
            cancel=cancel,
            form_executor=executor,
            recapture=page_factory.capture_current,
        )

    def run_fn(root: PageInstance) -> FrontierResult:
        crawl = build_crawl()
        holder["crawl"] = crawl
        return crawl.run(root).frontier

    def auth_fn(root: PageInstance) -> AuthVerdict:
        oracle = AuthOracle(
            fetch_fn=session_fetch_fn(session),
            page_url=root.final_url or root.url,
            probe_url=ctx.auth_probe,
            login_url=ctx.login_url,
        )
        verdict = oracle.check()
        holder["verdict"] = verdict
        return verdict

    def manifest_fn(frontier: FrontierResult | None, stop_reason: str) -> Manifest:
        crawl = holder.get("crawl")
        output = crawl.last_output if crawl is not None else None
        verdict = holder.get("verdict")
        run = RunBlock(
            crawl_run_id=ctx.run_id,
            session_name=ctx.session_name,
            account=ctx.account,
            started_at=started_at,
            stop_reason=stop_reason,
            scope=list(ctx.scope),
            auth={
                "classification": (
                    verdict.classification if verdict is not None else "unknown"
                ),
                "probe_source": verdict.probe_source if verdict is not None else "",
                "probe_url": verdict.probe_url if verdict is not None else "",
            },
        )
        if output is None:
            from polymerhus.recon.crawl.steel.manifest import build_manifest  # noqa: PLC0415

            return build_manifest(run=run)
        return build_manifest_from_output(
            output,
            run=run,
            flows=sidecar.flows,
            scripts=sidecar.scripts,
            realtime=sidecar.realtime,
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def flush_fn(artifacts):
        if not ctx.edge_url or not ctx.edge_token:
            raise LiveCrawlError(
                "no HTTP-history edge is configured; the run is partial"
            )
        client = HistoryClient(ctx.edge_url, ctx.edge_token)
        result = client.ingest(ctx.project_id, ctx.run_id, artifacts)
        holder["flush"] = {
            "created": result.created,
            "duplicates": result.duplicates,
            "rejected": result.rejected,
            "errors": list(result.errors)[:10],
            "cursor": client.cursor,
        }
        return {
            "created": result.created,
            "duplicates": result.duplicates,
            "cursor": client.cursor,
        }

    def ingest_fn(manifest: Manifest):
        write_manifest(manifest_path, manifest)
        return {"ok": True, "path": str(manifest_path)}

    pages: list[PageRecord] = []
    actions: list[ActionRecord] = []
    job = CrawlJob(
        run_id=ctx.run_id,
        session_name=ctx.session_name,
        project_id=ctx.project_id,
        account=ctx.account,
        session=session,
        sidecar=sidecar,
        ledger=ledger,
        prepare_fn=lambda: page_factory(ctx.target_url, None, 0, "seed", ()),
        auth_fn=auth_fn,
        run_fn=run_fn,
        manifest_fn=manifest_fn,
        flush_fn=flush_fn,
        ingest_fn=ingest_fn,
        record_page=pages.append,
        record_action=actions.append,
        coverage=ctx.coverage,
        deadline=deadline,
        cancel=cancel,
    )
    try:
        result = job.run()
    finally:
        policy_client.close()
        try:
            session.close()
        finally:
            transport.close()
    duration_s = time.monotonic() - started
    crawl = holder.get("crawl")
    output = crawl.last_output if crawl is not None else None
    summary = {
        "run_id": ctx.run_id,
        "project_id": ctx.project_id,
        "session_name": ctx.session_name,
        "target_url": ctx.target_url,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "error": result.error,
        "pages": [record.model_dump(mode="json") for record in pages],
        "actions": [record.model_dump(mode="json") for record in actions],
        "flow_count": len(sidecar.flows),
        "artifact_count": sum(1 for _ in ledger.artifacts()),
        "duration_s": duration_s,
        "manifest_path": str(manifest_path),
        "ledger_path": str(ledger_path),
        "verdict": (
            holder["verdict"].model_dump(mode="json")
            if holder.get("verdict") is not None
            else None
        ),
        "removed": (
            [
                {
                    "element_id": element.element_id,
                    "name": element.name,
                    "element_type": element.element_type.value,
                    "impact": element.impact,
                    "fingerprint": element.fingerprint,
                }
                for element in output.removed
            ]
            if output is not None
            else []
        ),
        "forms": (
            [
                {
                    "fingerprint": form.form.fingerprint if form.form else "",
                    "action": form.form.action if form.form else "",
                    "method": form.form.method if form.form else "",
                    "submitted": form.submitted,
                    "skipped": form.skipped,
                }
                for form in output.forms
            ]
            if output is not None
            else []
        ),
        "declared_endpoints": (
            len(output.declared_endpoints) if output is not None else 0
        ),
        "declared_fields": (
            len(output.declared_fields) if output is not None else 0
        ),
        "script_count": len(sidecar.scripts),
        "realtime_count": len(sidecar.realtime),
        "session_closed": bool(
            result.end is not None
            and (result.end.stopped or result.end.released is True)
        ),
        "end": asdict(result.end) if result.end is not None else None,
        "flush": holder.get("flush"),
        "coverage": dict(ctx.coverage),
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return LiveRunResult(
        job=result,
        manifest=result.manifest,
        run_dir=run_dir,
        ledger_path=ledger_path,
        manifest_path=manifest_path,
        summary_path=summary_path,
        flow_count=len(sidecar.flows),
        artifact_count=len(ledger.artifacts()),
        duration_s=duration_s,
        verdict=holder.get("verdict"),
    )


def _scope_predicate(scope: Sequence[str]) -> Callable[[str], bool]:
    """The base host plus its subdomains (spec T2)."""
    hosts = [entry.lower().strip(".") for entry in scope if entry]
    if not hosts:
        return lambda url: False

    def in_scope(url: str) -> bool:
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            return False
        host = host.lower().strip(".")
        return any(host == item or host.endswith("." + item) for item in hosts)

    return in_scope


__all__ = [
    "LiveCdpTransport",
    "LiveCrawlError",
    "LivePageFactory",
    "LiveRunContext",
    "LiveRunResult",
    "run_live_crawl",
]
