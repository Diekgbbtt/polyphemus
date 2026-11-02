"""The Jev adapter: the synchronous policy over the async TypeSafe client.

Spec: `docs/design/steel-crawl-spec.md` sections 3.1, 6.6, 6.7, 7, 8.2, and 12.

The policy asks three questions - which candidate to remove, which candidate to
exercise, and which catalogue key fills a field - and the provider is TypeSafe's
SystemOne endpoint, which is async. The crawl itself is synchronous, so the
difference lives here and nowhere else:

- `TypeSafeDecisionClient` is the transport adapter. It owns one dedicated
  background event-loop thread, submits the client's `ask` coroutine with
  `asyncio.run_coroutine_threadsafe`, and returns the plain mapping. The typed
  state and questions cross the port unchanged, and the async client's own model
  configuration is the model the endpoint receives.
- `JevPolicy` implements the `Policy` protocol over that port. It builds each
  request with `policy.prompts`, parses `answers[kind]` into a `ChoiceAnswer`,
  and lets the port's selectors validate the answer against the live set. A
  missing or malformed answer is a `PolicyInvalidChoice` protocol error; a
  provider failure is a distinct `PolicyProviderError`; neither executes.

Importing this module performs no I/O and needs no provider key
(CODING_STANDARD section 6): the async client resolves on first use.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import ValidationError

from polymerhus.recon.crawl.steel.enumerate import Element
from polymerhus.recon.crawl.steel.policy.port import (
    ChoiceAnswer,
    DecisionRequest,
    PolicyInvalidChoice,
    select_chosen,
    select_removed,
    select_value,
)
from polymerhus.recon.crawl.steel.policy.prompts import (
    build_choice_request,
    build_removal_request,
    build_value_request,
)
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance

if TYPE_CHECKING:
    from polymerhus.app.llm.typesafe import TypeSafeSystemOne

# One close is bounded: releasing the async client is local work, so a stuck
# close must not hold the crawl's finalize path.
_CLOSE_TIMEOUT_S = 10.0

# The owned loop thread's name, so a run log can name the one bridge thread.
_LOOP_THREAD_NAME = "steel-jev-loop"

# The answered key reported when the response carries no parseable answer: the
# failure names the question and its answer space, because there is no key to
# cite. A missing or malformed answer is a protocol error, never a provider one.
_UNPARSEABLE_ANSWER = "<missing or malformed>"


@runtime_checkable
class DecisionClient(Protocol):
    """The synchronous decision-client port the policy asks.

    One call is one SystemOne request: the compact `state` and the typed
    `questions`, answered by a mapping whose `answers[kind]` carries the one
    answer. The provider's concurrency belongs behind this port, so the crawl
    never sees an event loop (spec 3.1).
    """

    def ask(
        self, state: Mapping[str, Any], questions: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class TypeSafeDecisionClient:
    """Bridge `TypeSafeSystemOne`'s async `ask` onto the synchronous crawl.

    The dedicated daemon loop thread starts lazily on the first ask; each
    coroutine is submitted with `asyncio.run_coroutine_threadsafe` and its result
    awaited synchronously. The client, not the adapter, owns the configured
    model, so this adapter can never disagree with the client about it. `close`
    releases the async client and stops the owned loop thread; a client injected
    but never asked is still closed, on a one-shot loop.
    """

    def __init__(self, client: TypeSafeSystemOne | None = None) -> None:
        self._client = client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._closed = False

    def ask(
        self, state: Mapping[str, Any], questions: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Submit one client `ask` to the owned loop and wait for its answer."""
        if self._closed:
            raise RuntimeError("the TypeSafe decision client is closed")
        client = self._ensure_client()
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(client.ask(state, questions), loop)
        return future.result()

    def close(self) -> None:
        """Close the async client and stop the owned loop thread. Idempotent."""
        if self._closed:
            return
        self._closed = True
        client, loop, thread = self._client, self._loop, self._thread
        self._client = None
        if loop is not None and not loop.is_closed():
            if client is not None:
                future: Any = None
                try:
                    future = asyncio.run_coroutine_threadsafe(client.close(), loop)
                    future.result(_CLOSE_TIMEOUT_S)
                except Exception:  # noqa: BLE001 - close is best-effort
                    if future is not None:
                        future.cancel()
            loop.call_soon_threadsafe(loop.stop)
            if thread is not None:
                thread.join(_CLOSE_TIMEOUT_S)
            # A loop whose thread outlived the close budget is left to the
            # daemon thread: closing a running loop would raise.
            if not loop.is_running():
                loop.close()
        elif client is not None:
            # The client was injected but never asked, so there is no owned loop
            # yet; its close still runs, on a private one-shot loop.
            try:
                asyncio.run(client.close())
            except Exception:  # noqa: BLE001 - close is best-effort
                pass
        self._loop = None
        self._thread = None

    def _ensure_client(self) -> TypeSafeSystemOne:
        if self._client is None:
            from polymerhus.app.llm.typesafe import TypeSafeSystemOne

            self._client = TypeSafeSystemOne()
        return self._client

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=loop.run_forever, name=_LOOP_THREAD_NAME, daemon=True
            )
            thread.start()
            self._loop, self._thread = loop, thread
        return self._loop


class PolicyProviderError(RuntimeError):
    """The decision provider failed; the question is unanswered, not answered wrong.

    Distinct from the protocol errors: a stale or invalid answer is a model
    answer outside the answer space, while a provider error means no answer
    arrived at all. The run records the provider failure and executes nothing.
    The question kind and the original cause ride the error, so the record names
    both without losing the provider's own type.
    """

    code = "policy_provider_error"

    def __init__(self, kind: str, cause: BaseException) -> None:
        self.kind = kind
        self.cause = cause
        super().__init__(f"the {kind} question could not be answered: {cause}")


class JevPolicy:
    """The `Policy` protocol over one synchronous decision client.

    Each question is built by `policy.prompts`, answered once, and validated
    against the live answer space by the port's selector. The policy never
    executes: it returns a candidate or a catalogue key, and the crawl's
    executor owns every action. The optional `BrowserState` is the cached-facts
    source for the removal request's open overlays; the DOM is never re-read.
    """

    def __init__(
        self, client: DecisionClient, *, state: BrowserState | None = None
    ) -> None:
        self._client = client
        self._state = state

    def choose_removed(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        request = build_removal_request(
            page, candidates, overlays=self._overlays(page)
        )
        return select_removed(page, candidates, self._answer(request))

    def choose_chosen(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        request = build_choice_request(page, candidates)
        return select_chosen(candidates, self._answer(request))

    def choose_value(
        self, field: Mapping[str, Any], catalogue: Mapping[str, Any]
    ) -> str | None:
        request = build_value_request(field, catalogue)
        return select_value(catalogue, self._answer(request))

    def _overlays(self, page: PageInstance) -> tuple[str, ...]:
        """The open overlay titles cached for the page, sorted for determinism.

        The state, never the DOM, is the fact source: a restore reuses the
        cached facts, so the removal question must read the same facts.
        """
        if self._state is None:
            return ()
        return tuple(sorted(self._state.cached(page).facts.overlay_flags))

    def _answer(self, request: DecisionRequest) -> ChoiceAnswer:
        """Ask the one question and parse `answers[kind]` into a typed answer.

        The state and the question cross the client port as plain JSON values:
        the typed request is serialized here, so every client sees the same
        shape. A provider raise is a typed failure of the whole question; a
        response without a parseable `answers[kind]` is a protocol error.
        """
        kind = request.kind
        question = request.questions[kind]
        try:
            response = self._client.ask(
                request.state, {kind: question.model_dump(mode="json")}
            )
        except PolicyProviderError:
            raise
        except Exception as error:
            raise PolicyProviderError(kind, error) from error
        return _choice_answer(kind, response, question.criteria)


def _choice_answer(
    kind: str, response: Any, criteria: Mapping[str, str]
) -> ChoiceAnswer:
    """The one answer the response carries, or an invalid-choice protocol error."""
    try:
        payload = response["answers"][kind]
    except (KeyError, TypeError):
        raise PolicyInvalidChoice(
            kind, _UNPARSEABLE_ANSWER, tuple(criteria)
        ) from None
    try:
        return ChoiceAnswer.model_validate(payload)
    except ValidationError as error:
        raise PolicyInvalidChoice(
            kind, _UNPARSEABLE_ANSWER, tuple(criteria)
        ) from error


__all__ = [
    "DecisionClient",
    "JevPolicy",
    "PolicyProviderError",
    "TypeSafeDecisionClient",
]
