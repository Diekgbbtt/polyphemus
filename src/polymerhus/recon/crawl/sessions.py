"""The one-pod, multi-session crawl orchestrator.

One account is one browser session. This module runs one full
`run_live_crawl` lifecycle per session, bounded by the browser-pool size, and
joins every thread before the pod finalizes. A failed session is a recorded
outcome, never a reason to discard the other sessions' manifests: the pod
ingests every successful manifest and emits reduced coverage for the failures.

The module owns no browser, store, or policy. `run_one` is the injected
one-lifecycle callback; the production caller binds it to `run_live_crawl`.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = [
    "CrawlSession",
    "SessionResult",
    "anonymous_session",
    "run_crawl_sessions",
]


@dataclass(frozen=True)
class CrawlSession:
    """One account's crawl input: its privilege surface and its own oracle."""

    account: str | None
    role: str | None
    root_url: str
    auth_probe: str | None
    login_url: str | None
    browser_context_ref: str | None
    anonymous: bool = False

    @classmethod
    def from_descriptor(
        cls, data: Mapping | None, *, target: str
    ) -> "CrawlSession":
        """Build one session from an auth-feed descriptor.

        A descriptor already carries absolute URLs; a relative value is
        resolved against the target origin for defensive compatibility with
        an older feed. A missing account/context/probe is the anonymous
        fallback, unless the descriptor says otherwise.
        """
        source = data if isinstance(data, Mapping) else {}
        account = source.get("account")
        account = account if isinstance(account, str) and account else None
        role = source.get("role")
        role = role if isinstance(role, str) and role else None
        root = source.get("root_url")
        root = root if isinstance(root, str) and root else target
        root_url = _absolute(root, target)
        probe = source.get("auth_probe")
        auth_probe = (
            _absolute(probe, target)
            if isinstance(probe, str) and probe
            else None
        )
        login_url = source.get("login_url")
        login_url = login_url if isinstance(login_url, str) and login_url else None
        context_ref = source.get("browser_context_ref")
        context_ref = (
            context_ref
            if isinstance(context_ref, str) and context_ref
            else None
        )
        anonymous = bool(source.get("anonymous")) or (
            account is None and context_ref is None and auth_probe is None
        )
        return cls(
            account=account,
            role=role,
            root_url=root_url,
            auth_probe=auth_probe,
            login_url=login_url,
            browser_context_ref=context_ref,
            anonymous=anonymous,
        )


@dataclass(frozen=True)
class SessionResult:
    """One lifecycle's terminal manifest or its failure text."""

    session: CrawlSession
    manifest: dict | None = None
    error: str | None = None


def anonymous_session(target: str) -> CrawlSession:
    """The zero-account fallback: a context-less session at the target root."""
    parsed = urlsplit(target)
    root = (
        f"{parsed.scheme}://{parsed.netloc}/"
        if parsed.scheme and parsed.netloc
        else target
    )
    return CrawlSession(
        account=None,
        role=None,
        root_url=root,
        auth_probe=None,
        login_url=None,
        browser_context_ref=None,
        anonymous=True,
    )


def run_crawl_sessions(
    sessions: Sequence[CrawlSession],
    *,
    run_one: Callable[[CrawlSession], dict | None],
    max_workers: int,
) -> list[SessionResult]:
    """Run one lifecycle per session and join every thread.

    `max_workers` is the browser-pool bound. A session that raises is recorded
    with its failure text; the other futures still run to completion. Results
    are returned in the input session order, never completion order, so the
    pod's evidence and coverage observations are deterministic.
    """
    ordered = list(sessions)
    if not ordered:
        return []
    workers = max(1, min(int(max_workers), len(ordered)))
    results: list[SessionResult | None] = [None] * len(ordered)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(run_one, session): index
            for index, session in enumerate(ordered)
        }
        for future in as_completed(futures):
            index = futures[future]
            session = ordered[index]
            try:
                manifest = future.result()
            except Exception as exc:  # noqa: BLE001 - one session never stops the rest
                results[index] = SessionResult(
                    session=session,
                    manifest=None,
                    error=str(exc) or exc.__class__.__name__,
                )
            else:
                results[index] = SessionResult(
                    session=session, manifest=manifest
                )
    return [result for result in results if result is not None]


def _absolute(value: str, target: str) -> str:
    """Resolve a relative session URL against the target origin."""
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return value
    origin = urlsplit(target)
    if not origin.scheme or not origin.netloc:
        return value
    return f"{origin.scheme}://{origin.netloc}/{value.lstrip('/')}"
