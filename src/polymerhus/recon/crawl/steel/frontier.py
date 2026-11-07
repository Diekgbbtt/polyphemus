"""The unified DFS frontier: one traversal over page instances.

Spec: `docs/design/steel-crawl-spec.md` sections 2.2, 5, 5.1, 5.2, 5.3, 6.3,
6.6, and 12.

The frontier owns traversal and nothing else: the page cache and the consumed
sets are `BrowserState`'s, the next action is the `Policy`'s, the execution is
the injected `execute` seam's, and the DOM collection is the `Collector`'s. It is
one depth-first search over page instances with no separate local axis and no
page axis: a navigation is a normal candidate, a local action is a normal
candidate, and the stack of parent pages plus the per-page consumed set drive
the order.

The seams are injected so the whole traversal is exercisable without a browser:

- `project(page)` answers the page's cached projection; the production wiring
  passes `ElementMap.project` over the cached snapshot, so a restored page is
  never re-snapshotted or re-enumerated.
- `restore(page)` rolls the browser back to the page; the production wiring
  passes `BrowserState.restore` with the navigation callable.
- `execute(page, element)` performs the action and reports the observed result;
  the production wiring passes the command mapper. A navigation result carries
  the new page instance, which the loader has already registered.

The run is bounded only by the session: there is no depth limit and no page cap.
It ends at frontier exhaustion, the session deadline, an operator cancel, a lost
session, or a typed error, and the stop reason says which one. The frontier never
starts a session and never continues without one.

The loop restores a page only when the browser is not already live on it: the
seeded root, a popped ancestor, and the rollback before the next choice after a
local action or a skipped navigation result. A successful navigation has already
loaded its result page, so entering it needs no extra navigation. A restore that
fails for a page-level reason is spec 12's `unrecoverable_state`: the page is
recorded as unrecoverable and the nearest ancestor with residue resumes, so only
a lost session ends the traversal from the restore path.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from polymerhus.recon.crawl.steel.enumerate import Channel, Element
from polymerhus.recon.crawl.steel.policy.port import Policy
from polymerhus.recon.crawl.steel.safety import Collector, remove_forbidden
from polymerhus.recon.crawl.steel.session import SessionMissing
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    StaleElement,
)

# The recorded terminal state of one traversal (spec 2.2 T10, section 12). A
# typed failure is `error`, with the failure text carried beside it.
StopReason = Literal[
    "frontier_empty",
    "session_deadline",
    "session_missing",
    "operator_cancel",
    "error",
]

ProjectPage = Callable[[PageInstance], Sequence[Element]]
RestorePage = Callable[[PageInstance], None]
ExecuteAction = Callable[[PageInstance, Element], "ExecutionResult"]


@dataclass(frozen=True)
class ExecutionResult:
    """One executed action's observed outcome.

    `navigated` is the browser's verdict, not the symbolic impact: the element
    map predicts a navigation, but only the executed result says whether the
    document actually changed. A navigation carries the result `page`, already
    registered in the `BrowserState`; `url`, `status`, and `title` are the
    observed document facts.
    """

    navigated: bool
    page: PageInstance | None = None
    url: str = ""
    status: int | None = None
    title: str = ""


@dataclass(frozen=True)
class PageVisit:
    """One entered page instance and the page that discovered it (spec 5.1)."""

    page: PageInstance
    parent: PageInstance | None = None


@dataclass(frozen=True)
class ActionVisit:
    """One executed action, in traversal order (spec 13)."""

    page: PageInstance
    element: Element
    result: ExecutionResult


@dataclass(frozen=True)
class DuplicateVisit:
    """A navigation result that was not entered (spec 5.3, 2.2 T2).

    `duplicate_state` is a result whose state key was already visited; it is
    recorded and never re-explored. `out_of_scope` is a result that left the
    base host and its subdomains; it is recorded and never entered.
    """

    page: PageInstance | None
    url: str
    parent: PageInstance
    element: Element
    reason: Literal["duplicate_state", "out_of_scope"]


@dataclass(frozen=True)
class StaleVisit:
    """One candidate whose reference was stale when the executor resolved it."""

    page: PageInstance
    element: Element
    error: StaleElement


@dataclass(frozen=True)
class FailedVisit:
    """One candidate whose execution raised a typed failure.

    The traversal stops on the failure, but the action is still recorded with
    its true outcome so the action ledger has no silent gap.
    """

    page: PageInstance
    element: Element
    error: str


@dataclass(frozen=True)
class FrontierResult:
    """What one traversal did, in order, and why it stopped (spec 2.2 T10)."""

    stop_reason: StopReason
    page_visits: tuple[PageVisit, ...] = ()
    action_visits: tuple[ActionVisit, ...] = ()
    removed: tuple[Element, ...] = ()
    unrecoverable: tuple[PageInstance, ...] = ()
    duplicates: tuple[DuplicateVisit, ...] = ()
    stale: tuple[StaleVisit, ...] = ()
    failed: tuple[FailedVisit, ...] = ()
    error: str | None = None


class Frontier:
    """One depth-first traversal over page instances, bounded by the session."""

    def __init__(
        self,
        *,
        project: ProjectPage,
        restore: RestorePage,
        execute: ExecuteAction,
        policy: Policy,
        state: BrowserState,
        collector: Collector,
        deadline: Callable[[], bool],
        cancel: Callable[[], bool],
        in_scope: Callable[[str], bool],
    ) -> None:
        self._project = project
        self._restore = restore
        self._execute = execute
        self._policy = policy
        self._state = state
        self._collector = collector
        self._deadline = deadline
        self._cancel = cancel
        self._in_scope = in_scope

    def run(self, root: PageInstance) -> FrontierResult:
        """Traverse from the seeded root page until the frontier is empty."""
        page_visits: list[PageVisit] = [PageVisit(page=root)]
        action_visits: list[ActionVisit] = []
        removed: list[Element] = []
        unrecoverable: list[PageInstance] = []
        duplicates: list[DuplicateVisit] = []
        stale: list[StaleVisit] = []
        failed: list[FailedVisit] = []
        stack: list[PageInstance] = []
        current: PageInstance | None = root
        # The root was just loaded by the page factory; its snapshot and refs
        # are the live document's. A restore before the first projection would
        # reload the page and invalidate those refs for no benefit.
        needs_restore = False

        def finish(
            stop_reason: StopReason, error: str | None = None
        ) -> FrontierResult:
            return FrontierResult(
                stop_reason=stop_reason,
                page_visits=tuple(page_visits),
                action_visits=tuple(action_visits),
                removed=tuple(removed),
                unrecoverable=tuple(unrecoverable),
                duplicates=tuple(duplicates),
                stale=tuple(stale),
                failed=tuple(failed),
                error=error,
            )

        def backtrack() -> FrontierResult | None:
            """Pop to the nearest ancestor with residue, or a typed stop.

            The predicate projects the ancestor from its cached snapshot, so a
            failed projection is a typed traversal failure, never an empty
            residue that silently ends the run.
            """
            nonlocal current
            try:
                current = self._pop_nearest_with_residue(stack)
            except Exception as error:  # noqa: BLE001 - a typed snapshot failure
                return finish("error", _error_text(error))
            return None

        while current is not None:
            # The operator's cancel is checked before the clock: an explicit
            # stop is never reported as a deadline.
            if self._cancel():
                return finish("operator_cancel")
            if self._deadline():
                return finish("session_deadline")
            if needs_restore:
                try:
                    self._restore(current)
                except SessionMissing as error:
                    return finish("session_missing", _error_text(error))
                except Exception:  # noqa: BLE001 - a page-level failure
                    # The page cannot be re-entered, but the session is alive:
                    # spec 12's `unrecoverable_state` pops to the nearest
                    # ancestor with residue instead of ending the run.
                    unrecoverable.append(current)
                    stop = backtrack()
                    if stop is not None:
                        return stop
                    needs_restore = True
                    continue
                needs_restore = False

            try:
                candidates = self._candidates(current)
            except Exception as error:  # noqa: BLE001 - a typed snapshot failure
                return finish("error", _error_text(error))
            if not candidates:
                stop = backtrack()
                if stop is not None:
                    return stop
                needs_restore = True
                continue

            try:
                removal = remove_forbidden(
                    current, candidates, self._policy, self._state, self._collector
                )
            except Exception as error:  # noqa: BLE001 - a typed policy failure
                return finish("error", _error_text(error))
            removed.extend(removal.removed)
            if removal.stale is not None:
                # The removal stage broke protocol: it stopped without resolving
                # the answer, so the run executes nothing (spec 7, 12).
                return finish("error", _error_text(removal.stale))
            if not removal.remaining:
                stop = backtrack()
                if stop is not None:
                    return stop
                needs_restore = True
                continue

            try:
                chosen = self._policy.choose_chosen(current, removal.remaining)
            except Exception as error:  # noqa: BLE001 - a typed policy failure
                return finish("error", _error_text(error))
            if chosen is None:
                stop = backtrack()
                if stop is not None:
                    return stop
                needs_restore = True
                continue

            # The loader registers the result page through `open_page` while
            # the action executes, so the visited set is read before the call:
            # after it, every new page's own state key would look visited.
            visited_before = self._state.visited
            try:
                result = self._execute(current, chosen)
            except StaleElement as error:
                # The reference belonged to a replaced document: consume the
                # dead identity, record the gap, and keep the page current
                # (spec 5.2, 12).
                self._state.consume(current, chosen.fingerprint)
                stale.append(StaleVisit(page=current, element=chosen, error=error))
                continue
            except SessionMissing as error:
                return finish("session_missing", _error_text(error))
            except Exception as error:  # noqa: BLE001 - a typed action failure
                failed.append(
                    FailedVisit(
                        page=current,
                        element=chosen,
                        error=_error_text(error),
                    )
                )
                return finish("error", _error_text(error))
            self._state.consume(current, chosen.fingerprint)
            action_visits.append(
                ActionVisit(page=current, element=chosen, result=result)
            )
            if not result.navigated:
                # A local action mutates the current document: the next choice
                # needs the cached snapshot's surface back, so the loop restores
                # this page before it projects again.
                needs_restore = True
                continue
            page = result.page
            landed = result.url or (
                (page.final_url or page.url) if page is not None else ""
            )
            if landed and not self._in_scope(landed):
                # The action left the base host and its subdomains: the result
                # is recorded, never entered (spec 2.2 T2).
                duplicates.append(
                    DuplicateVisit(
                        page=page,
                        url=landed,
                        parent=current,
                        element=chosen,
                        reason="out_of_scope",
                    )
                )
                needs_restore = True
                continue
            if page is None:
                return finish(
                    "error", "the navigation result carries no page instance"
                )
            if page.state_key in visited_before:
                # The result names a state already observed: record the visit
                # and roll back instead of re-exploring it (spec 5.3).
                duplicates.append(
                    DuplicateVisit(
                        page=page,
                        url=landed,
                        parent=current,
                        element=chosen,
                        reason="duplicate_state",
                    )
                )
                needs_restore = True
                continue
            stack.append(current)
            page_visits.append(PageVisit(page=page, parent=current))
            current = page
            # The navigation loaded this page, so the browser is already live on
            # it: there is nothing to roll back before the next projection.
            needs_restore = False

        return finish("frontier_empty")

    def _candidates(self, page: PageInstance) -> list[Element]:
        """The offer-channel elements this page key has not consumed (spec 5)."""
        offered = [
            element
            for element in self._project(page)
            if element.channel is Channel.OFFER
        ]
        return self._state.unconsumed(page, offered)

    def _pop_nearest_with_residue(
        self, stack: list[PageInstance]
    ) -> PageInstance | None:
        """Pop to the nearest ancestor with an unconsumed candidate (spec 5)."""
        while stack:
            page = stack.pop()
            if self._candidates(page):
                return page
        return None


def _error_text(error: BaseException) -> str:
    """The recorded failure text: the typed code when there is one, then the message."""
    code = getattr(error, "code", "")
    message = str(error) or error.__class__.__name__
    return f"{code}: {message}" if code else message


__all__ = [
    "ActionVisit",
    "DuplicateVisit",
    "ExecuteAction",
    "ExecutionResult",
    "FailedVisit",
    "Frontier",
    "FrontierResult",
    "PageVisit",
    "ProjectPage",
    "RestorePage",
    "StaleVisit",
    "StopReason",
]
