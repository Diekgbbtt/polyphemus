"""The removal stage: forbidden categories, in-place collection, and the loop.

Spec: `docs/design/steel-crawl-spec.md` sections 2.4, 6.3, 6.7, 7, and 12.

The removal stage is the structural guard against declassification: the policy
answers which one candidate belongs to a forbidden category (auth state,
payment, destruction), and this loop consumes and collects that candidate in
place so it can never be executed. The semantic deny itself lives in the
`choose_removed` instructions (`policy.prompts`); there is no separate
classifier and no second gate.

The loop is sequential and bounded by the candidate count: each answer removes
one candidate, a `none` answer ends the stage, and an answer naming anything
outside the live set is a stale-removal protocol error that stops the stage.
The loop never executes anything - it has no executor, no session, and no
command mapper - and it never mutates the caller's candidate sequence.

Importing this module performs no I/O (CODING_STANDARD section 6): the state
and the collector are injected.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from polymerhus.recon.crawl.steel.enumerate import Element
from polymerhus.recon.crawl.steel.policy.port import Policy, PolicyStaleRemoval
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance


@runtime_checkable
class Collector(Protocol):
    """The in-place DOM collector the removal stage hands a removed candidate.

    Spec 6.3: a removed element is collected in place, so its declared contract
    reaches the graph while its action is never submitted. The collector is a
    seam, not a browser client: the crawl injects the DOM collector.
    """

    def collect(self, element: Element) -> None: ...


@dataclass(frozen=True)
class RemovalResult:
    """What one removal stage did: the live remainder and the removed set.

    `remaining` is the live candidate tuple `choose_chosen` may see - structurally
    free of every removed candidate (spec S4). `removed` is the removal order,
    which is also the collection order. `stale` is the recorded protocol error
    when an answer named a candidate outside the live set; the stage stops there
    and executes nothing (spec S8, 12).
    """

    remaining: tuple[Element, ...]
    removed: tuple[Element, ...]
    stale: PolicyStaleRemoval | None = None


def remove_forbidden(
    page: PageInstance,
    candidates: Sequence[Element],
    policy: Policy,
    state: BrowserState,
    collector: Collector,
) -> RemovalResult:
    """Deplete the forbidden candidates, one answer at a time (spec 7).

    Each iteration removes exactly one candidate, so the loop is bounded by the
    candidate count even if the policy misbehaves: once the live set is empty,
    any non-`none` answer names something outside it and stops the stage. A
    removed candidate is consumed on the page key and collected in place before
    it leaves the live set, so it can never be executed.
    """
    remaining = list(candidates)
    removed: list[Element] = []
    stale: PolicyStaleRemoval | None = None
    while True:
        try:
            candidate = policy.choose_removed(page, tuple(remaining))
        except PolicyStaleRemoval as error:
            stale = error
            break
        if candidate is None:
            break
        index = _index_of(remaining, candidate.element_id)
        if index is None:
            # A policy that answers with a candidate outside the live set has
            # gone stale without raising: record the protocol error and stop,
            # exactly as the port's own selector would (spec 7, 12).
            stale = PolicyStaleRemoval(
                page, candidate.element_id, _live_ids(remaining)
            )
            break
        element = remaining[index]
        state.consume(page, element.fingerprint)
        collector.collect(element)
        remaining.pop(index)
        removed.append(element)
    return RemovalResult(
        remaining=tuple(remaining), removed=tuple(removed), stale=stale
    )


def _index_of(candidates: Sequence[Element], element_id: str) -> int | None:
    """The live candidate the answer names, matched by its stable identity.

    Matching by id (not by object or value equality) keeps the loop on its own
    candidates: a policy answer can never substitute a different element for the
    live one, and the caller's sequence is never searched or mutated. `None`
    means the answer is stale.
    """
    for index, candidate in enumerate(candidates):
        if candidate.element_id == element_id:
            return index
    return None


def _live_ids(candidates: Sequence[Element]) -> tuple[str, ...]:
    return tuple(candidate.element_id for candidate in candidates)


__all__ = [
    "Collector",
    "RemovalResult",
    "remove_forbidden",
]
