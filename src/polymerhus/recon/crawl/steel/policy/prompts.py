"""The prompt contract: the three questions and the compact state they read.

Spec: `docs/design/steel-crawl-spec.md` sections 6.5 to 6.7, 7, 8.2, and
Appendix B.

Every request is built here, so the model sees one stable shape per question
kind: a compact state (the page, the candidates or the catalogue, the forbidden
categories) and one typed choice question (the instructions and the bounded
answer space). The builders are pure - a request value out, no client and no I/O.

Candidate criteria are bounded on purpose: identity, type, label, impact,
capture, href, action, and the change semantics the element map already computed.
The full DOM never enters a request. The value catalogue enters as keys, kinds,
and descriptions only: a value is typed locally by the executor and never leaves
the run (spec 8.2, Appendix B).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.crawl.steel.command import CaptureChannel, ImpactClass
from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementType,
)
from polymerhus.recon.crawl.steel.policy.port import (
    NONE_CHOICE,
    ChoiceQuestion,
    DecisionRequest,
    QuestionKind,
)
from polymerhus.recon.crawl.steel.state import PageInstance

# The forbidden categories (spec 2.4, 6.7). The removal stage is the sole owner
# of the semantic deny; there is no separate classifier and no extra gate.
FORBIDDEN_CATEGORIES: tuple[str, ...] = ("auth state", "payment", "destruction")

# Registration is a safe write, and the one explicit exception to the deny. The
# authz residual risk is accepted, so the prompt gains no further examples.
SAFE_EXCEPTION = "account registration is a safe write, not auth state"

REMOVAL_INSTRUCTIONS = (
    "You are removing unsafe elements from the crawl candidate set.\n"
    "Forbidden categories: auth state, payment, destruction.\n"
    "Keywords: login, logout, signin, signout, password, reset, mfa, otp, "
    "pay, purchase, checkout, donate, delete, destroy, deactivate, close account, "
    "purge, revoke.\n"
    "Account registration is a safe write, not auth state.\n"
    "Do not remove a registration form.\n"
    "Choose the single candidate that belongs to a forbidden category.\n"
    "Choose none if no candidate belongs to a forbidden category.\n"
    "Do not choose a candidate for any other reason."
)

# The offer order of the impact classes (spec 6.4, 6.6): the soft prior the
# choice question ranks by. The instance impact stays authoritative.
IMPACT_ORDER: tuple[ImpactClass, ...] = (
    "observe",
    "local_state",
    "read",
    "write",
    "navigate",
)

CHOICE_INSTRUCTIONS = (
    "You are choosing the next element to exercise on the current page.\n"
    "Impact order: observe, local_state, read, write, navigate.\n"
    "Choose the lowest non-empty impact class.\n"
    "Within the class, prefer known change semantics, then a candidate whose "
    "control facts show a hidden target with unconsumed candidates.\n"
    "Choose none if no candidate remains."
)

VALUE_INSTRUCTIONS = (
    "Choose one catalogue key for the form field.\n"
    "The field contract is in the state.\n"
    "If more than one catalogue entry matches the field kind, choose the key "
    "that best fits the field.\n"
    "Choose none to leave the field empty.\n"
    "The value never enters the request: the executor types the chosen value "
    "locally.\n"
    "Answer with a catalogue key, never a value."
)

# The field contract of an offered form (spec 8.1), in the order the request
# renders it. A field value is never one of these keys, so projecting the
# contract keeps every value out of the request.
_FIELD_CONTRACT = (
    "name",
    "type",
    "label",
    "options",
    "pattern",
    "min",
    "max",
    "checked",
    "selector",
)

# Bounds on the compact text a request carries. A page can never make one
# criterion grow without bound, and the DOM never enters the request.
_MAX_TEXT = 60
_MAX_URL = 200

# The `none` criterion per question: declining is always answerable (spec 6.6,
# 7, 8.2).
_NONE_REMOVAL = "no forbidden element remains"
_NONE_CHOICE = "no candidate remains"
_NONE_VALUE = "leave the field empty"


class CandidateCriterion(BaseModel):
    """One candidate, bounded to the facts a decision reads (spec 6.5, 6.7).

    Identity, type, label, impact, capture, href, action, and the change
    semantics the element map computed - including its control facts, which are
    already bounded to each controlled target's compact projection. The raw DOM
    node and its attributes never enter a request.
    """

    model_config = ConfigDict(frozen=True)

    element_id: str
    element_type: ElementType
    label: str = ""
    impact: ImpactClass
    capture: CaptureChannel
    href: str | None = None
    action: str | None = None
    change: ChangeSemantics

    @classmethod
    def of(cls, element: Element) -> CandidateCriterion:
        return cls(
            element_id=element.element_id,
            element_type=element.element_type,
            label=_bounded(element.name or element.text, _MAX_TEXT),
            impact=element.impact,
            capture=element.capture,
            href=_bounded(element.href, _MAX_URL) if element.href else None,
            action=_bounded(element.action, _MAX_URL) if element.action else None,
            change=element.change,
        )

    @property
    def description(self) -> str:
        """The one-line criterion the question's answer space carries."""
        label = self.label or self.element_type.value.lower()
        return (
            f'{self.element_type.value.lower()} "{label}" '
            f"impact={self.impact} capture={self.capture}"
        )


def build_removal_request(
    page: PageInstance,
    candidates: Sequence[Element],
    *,
    overlays: Iterable[str] = (),
) -> DecisionRequest:
    """The removal question: which one candidate is forbidden, or `none` (spec 7).

    The state carries what the deny needs - the page, the open overlays that
    change what is reachable, the forbidden categories, the safe exception, and
    the bounded candidates. The instructions carry the semantic deny itself; the
    answer space is the candidate ids plus `none`.
    """
    bounded = _candidates(candidates)
    state = {
        "page": _page_state(page),
        "overlays": _overlays(overlays),
        "forbidden": list(FORBIDDEN_CATEGORIES),
        "safe_exception": SAFE_EXCEPTION,
        "candidates": _candidates_state(bounded),
    }
    return _request(
        "choose_removed",
        state,
        REMOVAL_INSTRUCTIONS,
        _criteria(bounded, _NONE_REMOVAL),
    )


def build_choice_request(
    page: PageInstance, candidates: Sequence[Element]
) -> DecisionRequest:
    """The choice question: the next element to exercise, or `none` (spec 6.6).

    The state carries the page, the impact order as the soft prior, and the
    bounded candidates with their change semantics. The instructions carry the
    decision tree; the answer space is the remaining candidate ids plus `none`.
    """
    bounded = _candidates(candidates)
    state = {
        "page": _page_state(page),
        "impact_order": list(IMPACT_ORDER),
        "candidates": _candidates_state(bounded),
    }
    return _request(
        "choose_chosen",
        state,
        CHOICE_INSTRUCTIONS,
        _criteria(bounded, _NONE_CHOICE),
    )


def build_value_request(
    field: Mapping[str, Any], catalogue: Mapping[str, Any]
) -> DecisionRequest:
    """The value question: one catalogue key for one field, or `none` (spec 8.2).

    The state carries the field contract and the catalogue as keys, kinds, and
    descriptions. The instructions carry the value protocol. The value itself is
    typed locally by the executor and never enters the request, so the model
    chooses a key and can only choose a key.
    """
    entries = _catalogue_state(catalogue)
    state = {"field": _field_state(field), "catalogue": entries}
    criteria = {entry["key"]: entry["description"] for entry in entries}
    criteria.setdefault(NONE_CHOICE, _NONE_VALUE)
    return _request("choose_value", state, VALUE_INSTRUCTIONS, criteria)


def _request(
    kind: QuestionKind,
    state: Mapping[str, Any],
    instructions: str,
    criteria: Mapping[str, str],
) -> DecisionRequest:
    """One request with exactly one typed choice question, keyed by its kind."""
    return DecisionRequest(
        kind=kind,
        state=state,
        questions={
            kind: ChoiceQuestion(instructions=instructions, criteria=dict(criteria))
        },
    )


def _page_state(page: PageInstance) -> dict[str, str]:
    """The document the candidates came from, after any redirect."""
    return {"url": page.final_url or page.url, "title": page.title}


def _overlays(overlays: Iterable[str]) -> list[str]:
    """The open overlay titles in first-seen order, without duplicates."""
    return list(dict.fromkeys(title.strip() for title in overlays if title.strip()))


def _field_state(field: Mapping[str, Any]) -> dict[str, Any]:
    """The field contract only: a value the field carries never reaches the model."""
    return {key: field[key] for key in _FIELD_CONTRACT if key in field}


def _catalogue_state(catalogue: Mapping[str, Any]) -> list[dict[str, str]]:
    """The catalogue as keys, kinds, and descriptions - never a value."""
    return [
        {
            "key": key,
            "kind": _bounded(_entry_field(entry, "kind"), _MAX_TEXT),
            "description": _bounded(_entry_field(entry, "description"), _MAX_TEXT),
        }
        for key, entry in catalogue.items()
    ]


def _entry_field(entry: Any, name: str) -> str:
    """Read one catalogue entry field from a mapping or from a typed entry."""
    if isinstance(entry, Mapping):
        value = entry.get(name)
    else:
        value = getattr(entry, name, None)
    return "" if value is None else str(value)


def _candidates(candidates: Sequence[Element]) -> list[CandidateCriterion]:
    return [CandidateCriterion.of(candidate) for candidate in candidates]


def _candidates_state(criteria: Sequence[CandidateCriterion]) -> list[dict[str, Any]]:
    return [criterion.model_dump(mode="json") for criterion in criteria]


def _criteria(
    criteria: Sequence[CandidateCriterion], none_description: str
) -> dict[str, str]:
    """The answer space: one key per criterion, plus `none` last."""
    answer_space = {
        criterion.element_id: criterion.description for criterion in criteria
    }
    answer_space.setdefault(NONE_CHOICE, none_description)
    return answer_space


def _bounded(value: str, limit: int) -> str:
    """Collapse whitespace and truncate, so one long value cannot grow the state."""
    text = " ".join(value.split())
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


__all__ = [
    "CHOICE_INSTRUCTIONS",
    "FORBIDDEN_CATEGORIES",
    "IMPACT_ORDER",
    "REMOVAL_INSTRUCTIONS",
    "SAFE_EXCEPTION",
    "VALUE_INSTRUCTIONS",
    "CandidateCriterion",
    "build_choice_request",
    "build_removal_request",
    "build_value_request",
]
