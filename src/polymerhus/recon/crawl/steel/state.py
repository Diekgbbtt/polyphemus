"""The browser state: page instances, the snapshot cache, and ref validity.

Spec: `docs/design/steel-crawl-spec.md` sections 5.1, 5.2, 5.3, 6.5, and 12.

`BrowserState` owns the DOM snapshot cache, the consumed sets, and the visited
set. A page instance is the navigation-tree node the observability platform
records; the cache key is the page key, so a restore hits the cached snapshot by
key instead of re-snapshotting or re-enumerating the DOM.

`DocumentGeneration` is the ref-validity token. A new document (a fresh page
load, which `open_page` registers) mints a new generation and invalidates every
reference captured under an older one. A restore re-activates the generation of
the document it navigates back to, because the cached snapshot is exactly the
document whose references it is about to reuse. A local-state action mints
nothing: it mutates the current document in place, so its references stay valid.

Importing this module performs no I/O (CODING_STANDARD section 6): `open_page`
receives the already-captured snapshot, and `restore` receives the navigation
callable.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict

# The reference-validity token: one number per loaded document. The first
# document is 1, so generation 0 never names a live document.
DocumentGeneration = int

# `navigate_fn(url)`: the one impure seam restore needs. A failed navigation is
# the seam's exception; the state never inspects an envelope.
NavigateFn = Callable[[str], Any]

_DEFAULT_PORTS = {"http": "80", "https": "443"}
_SLASH_RUN = re.compile(r"/{2,}")


def normalize_url(url: str) -> str:
    """Normalize a URL for the cache and state keys, without touching its path.

    Conservative by design: the fragment is dropped, scheme and host are
    lower-cased, the scheme's default port is removed, duplicate path slashes
    collapse, a trailing slash goes except at the root, and the query parameters
    are sorted. Path segments are never decoded or re-encoded, so `%2F` stays
    distinct from a real separator.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = _normalize_netloc(scheme, parts.netloc)
    path = _SLASH_RUN.sub("/", parts.path) or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    query = "&".join(sorted(part for part in parts.query.split("&") if part))
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_netloc(scheme: str, netloc: str) -> str:
    if not netloc:
        return ""
    userinfo, at, hostport = netloc.rpartition("@")
    host, port = _split_port(hostport.lower())
    if port == _DEFAULT_PORTS.get(scheme):
        port = ""
    authority = host + (f":{port}" if port else "")
    return f"{userinfo}@{authority}" if at else authority


def _split_port(hostport: str) -> tuple[str, str]:
    """Split `host:port` without breaking an IPv6 literal's brackets."""
    if hostport.startswith("["):
        host, bracket, rest = hostport.partition("]")
        return host + bracket, rest[1:] if rest.startswith(":") else ""
    host, colon, port = hostport.rpartition(":")
    if not colon:
        return hostport, ""
    return host, port


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(url: str, navigation_path: Sequence[str] = ()) -> str:
    """`sha256(normalized_url + action_fingerprint_path)` (spec 5.1).

    The path is the exact ordered list of navigation fingerprints that yielded
    the page; local-state actions are absent because a restore never replays
    them. The fingerprints are fixed-width hashes, so plain concatenation is
    unambiguous.
    """
    return _sha(normalize_url(url) + "".join(navigation_path))


class SnapshotFacts(BaseModel):
    """The coarse effect signal the state keys a page visit on (spec 5.3).

    `ax_hash` is the sorted hash of `(role, name)` for the visible interactive
    nodes and `overlay_flags` is the set of open dialog titles. `open_page`
    stamps `document_generation` from the state's own counter, so a caller's
    value is ignored: the state, never the caller, mints the ref-validity token.
    """

    model_config = ConfigDict(frozen=True)

    ax_hash: str = ""
    overlay_flags: frozenset[str] = frozenset()
    document_generation: DocumentGeneration = 0


def state_key(url: str, facts: SnapshotFacts) -> str:
    """`sha256(normalized_url + ax_hash + overlay_flags)` (spec 5.3).

    The overlay flags are sorted before hashing, so the visited set never sees
    the same open-dialog set twice under two input orders.
    """
    overlays = "".join(sorted(facts.overlay_flags))
    return _sha(normalize_url(url) + facts.ax_hash + overlays)


class PageInstance(BaseModel):
    """One node in the navigation tree and its observability record (spec 5.1).

    `url` is the navigation target and `final_url` where the browser landed; the
    cache key names the document actually loaded, so a redirect target is the
    page identity. `navigation_path` is the exact ordered list of navigation
    fingerprints that yielded the page; local-state actions never enter it.
    """

    model_config = ConfigDict(frozen=True)

    page_visit_id: str
    url: str
    final_url: str = ""
    title: str = ""
    status: int | None = None
    parent_id: str | None = None
    depth: int = 0
    discovery_source: str = ""
    cache_key: str
    navigation_path: tuple[str, ...] = ()
    document_generation: DocumentGeneration = 0
    state_key: str


class CachedSnapshot(BaseModel):
    """One cache entry: the opaque CLI DOM snapshot and its observed facts."""

    model_config = ConfigDict(frozen=True)

    snapshot: Any
    facts: SnapshotFacts


class Fingerprinted(Protocol):
    """The candidate surface the consumed set needs (SC-05's `Element`)."""

    @property
    def fingerprint(self) -> str: ...


CandidateT = TypeVar("CandidateT", bound=Fingerprinted)


class StaleElement(RuntimeError):
    """The reference belongs to a document generation that is no longer live.

    Spec section 12: recover by consuming the candidate and recording the gap.
    It carries the page visit id and both generations so the action record can
    say exactly which document invalidated the reference. It is deliberately
    not a session error: the session is healthy, the reference is not.
    """

    code = "stale_element"

    def __init__(
        self,
        page: PageInstance,
        generation: DocumentGeneration,
        current_generation: DocumentGeneration,
    ) -> None:
        self.page_visit_id = page.page_visit_id
        self.generation = generation
        self.current_generation = current_generation
        super().__init__(
            f"the element reference belongs to document generation {generation}, "
            f"but the current generation is {current_generation} "
            f"(page {page.page_visit_id!r})"
        )


class BrowserState:
    """The snapshot cache, consumed sets, visited set, and ref-validity token."""

    def __init__(self) -> None:
        self._cache: dict[str, CachedSnapshot] = {}
        self._consumed: dict[str, set[str]] = {}
        self._visited: set[str] = set()
        self._current_generation: DocumentGeneration = 0

    @property
    def visited(self) -> frozenset[str]:
        """The state keys observed so far (spec 5.3)."""
        return frozenset(self._visited)

    def open_page(
        self,
        *,
        page_visit_id: str,
        url: str,
        final_url: str = "",
        title: str = "",
        status: int | None = None,
        parent_id: str | None = None,
        depth: int = 0,
        discovery_source: str = "",
        navigation_path: Sequence[str] = (),
        snapshot: Any,
        facts: SnapshotFacts | None = None,
    ) -> PageInstance:
        """Register a freshly loaded document, cache its snapshot, mint its generation.

        The cache key is the page key, so the consumed set and the cache share
        one identity; the state key is the coarser visited-set identity. A new
        document always mints a new generation, which stales every reference
        captured under an older one.
        """
        path = tuple(navigation_path)
        document_url = final_url or url
        observed = facts if facts is not None else SnapshotFacts()
        self._current_generation += 1
        generation = self._current_generation
        observed = observed.model_copy(update={"document_generation": generation})
        key = cache_key(document_url, path)
        page = PageInstance(
            page_visit_id=page_visit_id,
            url=url,
            final_url=document_url,
            title=title,
            status=status,
            parent_id=parent_id,
            depth=depth,
            discovery_source=discovery_source,
            cache_key=key,
            navigation_path=path,
            document_generation=generation,
            state_key=state_key(document_url, observed),
        )
        self._cache[key] = CachedSnapshot(snapshot=snapshot, facts=observed)
        self._consumed.setdefault(key, set())
        self._visited.add(page.state_key)
        return page

    def cached(self, page: PageInstance) -> CachedSnapshot:
        """The cached snapshot and facts for this page key."""
        return self._cache[page.cache_key]

    def restore(self, page: PageInstance, navigate_fn: NavigateFn) -> Any:
        """Navigate to the page URL and return its cached snapshot (spec 5.2).

        It issues exactly one navigation and touches the cache; it never takes
        or calls a snapshot or enumerate function, so a rollback cannot replay a
        local-state action or rebuild the projection. The restored document is
        now the live one, so its generation becomes current again - that is what
        keeps the cached references usable after backtracking.
        """
        navigate_fn(page.url)
        cached = self._cache[page.cache_key]
        self._current_generation = page.document_generation
        return cached.snapshot

    def consume(self, page: PageInstance, fingerprint: str) -> None:
        """Mark one action fingerprint consumed on this page key (spec 5.1).

        The set is keyed by the cache key, never by the live state signature: a
        local-state action that changes the state key must not re-offer an
        action already taken on the same page.
        """
        self._consumed.setdefault(page.cache_key, set()).add(fingerprint)

    def unconsumed(
        self, page: PageInstance, candidates: Iterable[CandidateT]
    ) -> list[CandidateT]:
        """The candidates this page key has not consumed, in input order."""
        consumed = self._consumed.get(page.cache_key, frozenset())
        return [
            candidate
            for candidate in candidates
            if candidate.fingerprint not in consumed
        ]

    def resolve(
        self, page: PageInstance, generation: DocumentGeneration
    ) -> PageInstance:
        """Prove a reference belongs to the live document, or raise `StaleElement`.

        A reference is valid only inside the generation that captured it, and
        that generation must still be the current one: any new document (a
        navigation, or a re-opened page key) invalidates it. The caller consumes
        the candidate on the failure, so a dead identity is never retried.
        """
        if (
            generation != page.document_generation
            or page.document_generation != self._current_generation
        ):
            raise StaleElement(page, generation, self._current_generation)
        return page


__all__ = [
    "BrowserState",
    "CachedSnapshot",
    "DocumentGeneration",
    "Fingerprinted",
    "NavigateFn",
    "PageInstance",
    "SnapshotFacts",
    "StaleElement",
    "cache_key",
    "normalize_url",
    "state_key",
]



