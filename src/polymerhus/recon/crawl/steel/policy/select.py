"""The choice and value protocol: one traversal move, and one value per field.

Spec: `docs/design/steel-crawl-spec.md` sections 6.4, 6.6, 8.1, 8.2, and 12.

The impact order and the change-semantics ranking are not implemented here.
They are the prompt-level decision tree `policy.prompts` already carries, and
Jev owns the final choice (spec 6.6): a symbolic ranker in this module would
override the authority the spec gives the model. This module owns the contract
around the answer instead. `decide_choice` reads the chosen element's impact and
names the one move the frontier must make - push the page on a navigation, else
restore it. `choose_field_value` runs the value protocol around the choice: the
single-match shortcut, the Jev question over the catalogue keys, and the decline
at `none`.

Nothing here executes, types, or records. A `ChoiceOutcome` only says which
traversal move the frontier owns, and a `ValueChoice` carries the value the
executor types locally. The value never enters a policy request: the field is
projected to its contract, and `policy.prompts` renders the catalogue as keys,
kinds, and descriptions only (spec 8.2).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from polymerhus.recon.crawl.steel.enumerate import Element
from polymerhus.recon.crawl.steel.policy.port import (
    NONE_CHOICE,
    Policy,
    PolicyInvalidChoice,
    answer_space,
)
from polymerhus.recon.crawl.steel.policy.prompts import FIELD_CONTRACT
from polymerhus.recon.crawl.steel.state import PageInstance

# The catalogue kinds (spec 8.2): the value shape a catalogue entry carries.
ValueKind = Literal["email", "text", "number", "date", "url", "file", "option", "none"]

# The `first` sentinel resolves to the first non-empty option of the field
# (spec 8.2); it is never typed literally.
FIRST_OPTION = "__first_option__"


@dataclass(frozen=True)
class ChoiceOutcome:
    """What one choice asks the frontier to do (spec 6.6, steps 5 and 6).

    `chosen` is the element Jev answered, or `None` when no candidate remains.
    `navigates` means push the current page and make the result current;
    `restores` means record the result and restore the current page. The frontier
    owns the actual push and restore (SC-09); this outcome only says which one.
    """

    chosen: Element | None
    navigates: bool = False
    restores: bool = False


def decide_choice(
    policy: Policy, page: PageInstance, candidates: Sequence[Element]
) -> ChoiceOutcome:
    """Ask Jev for the next element and name the traversal move it implies.

    A `navigate` impact moves to a new document, so the frontier pushes the
    current page; every other impact is exercised on the current page and then
    restored (spec 6.6). A `none` answer leaves neither move to make.
    """
    chosen = policy.choose_chosen(page, candidates)
    if chosen is None:
        return ChoiceOutcome(chosen=None)
    return ChoiceOutcome(
        chosen=chosen,
        navigates=chosen.impact == "navigate",
        restores=chosen.impact != "navigate",
    )


@dataclass(frozen=True)
class ValueEntry:
    """One catalogue entry: the value, its kind, and its description (spec 8.2)."""

    value: str | None
    kind: ValueKind
    description: str


@dataclass(frozen=True)
class ValueCatalogue:
    """The value catalogue: one entry per key, keys in catalogue order (spec 8.2)."""

    entries: Mapping[str, ValueEntry]


# The exact default catalogue of spec 8.2, `none` included. The email's `<run>`
# is the spec's placeholder and stays literal: no run substitution is specified.
DEFAULT_VALUE_CATALOGUE = ValueCatalogue(
    entries={
        "email": ValueEntry(
            value="qa-crawl+<run>@example.test",
            kind="email",
            description="valid email",
        ),
        "search": ValueEntry(
            value="test", kind="text", description="short search term"
        ),
        "name": ValueEntry(value="QA Crawler", kind="text", description="person name"),
        "number": ValueEntry(value="42", kind="number", description="small integer"),
        "date": ValueEntry(value="2026-01-01", kind="date", description="ISO date"),
        "url": ValueEntry(
            value="https://example.test/", kind="url", description="valid URL"
        ),
        "file": ValueEntry(
            value="crawl-upload.txt", kind="file", description="small text file"
        ),
        "first": ValueEntry(
            value=FIRST_OPTION, kind="option", description="first non-empty option"
        ),
        "none": ValueEntry(value=None, kind="none", description="leave empty"),
    }
)

# The field type to catalogue kind map (spec 8.1, 8.2). A missing type is a text
# input by HTML default; an unrecognised type has no safe value shape, so it maps
# to `none` and the field is left empty.
_FIELD_KINDS: dict[str, ValueKind] = {
    "text": "text",
    "search": "text",
    "textarea": "text",
    "email": "email",
    "number": "number",
    "range": "number",
    "date": "date",
    "url": "url",
    "file": "file",
    "select": "option",
    "select-one": "option",
    "select-multiple": "option",
    "radio": "option",
    "checkbox": "option",
    "password": "none",
    "hidden": "none",
    "submit": "none",
    "button": "none",
    "reset": "none",
    "image": "none",
}


def field_kind_for(field: Mapping[str, Any]) -> ValueKind:
    """The catalogue kind a field's type reads as (spec 8.1, 8.2).

    An unknown type has no matching catalogue entry, so the field is skipped;
    that is the fail-closed branch, not a default text fill.
    """
    field_type = str(field.get("type") or "text").strip().lower()
    return _FIELD_KINDS.get(field_type, "none")


def matching_keys(
    field: Mapping[str, Any], catalogue: ValueCatalogue
) -> tuple[str, ...]:
    """The catalogue keys whose kind matches the field, in catalogue order.

    `none` is the decline answer, not a value shape, so it never matches even
    when a field reads as kind `none` (spec 8.2).
    """
    kind = field_kind_for(field)
    return tuple(
        key
        for key, entry in catalogue.entries.items()
        if key != NONE_CHOICE and entry.kind == kind
    )


# Where a `ValueChoice` came from: the shortcut, the Jev question, or the
# protocol's decline. It is evidence for the action record, never a ranking.
ValueSource = Literal["single", "jev", "none"]


@dataclass(frozen=True)
class ValueChoice:
    """One field's value selection: the key, the local value, and the skip flags.

    `value` is what the executor types locally; it never leaves the run. The
    manifest contribution is `manifest_record`, which carries the key only
    (spec 8.2): the chosen `value_keys`, never the values.
    """

    key: str
    value: str | None
    source: ValueSource
    skip_field: bool = False
    skip_form: bool = False

    def manifest_record(self) -> dict[str, str]:
        """The manifest contribution of one field: its chosen key, never its value."""
        return {"value_key": self.key}


def choose_field_value(
    field: Mapping[str, Any],
    catalogue: ValueCatalogue,
    policy: Policy,
) -> ValueChoice:
    """Choose one catalogue key for one field (spec 8.2, steps 2 to 5).

    The single-match shortcut uses the one entry without a Jev call; more than
    one matching entry is the `choose_value` question over the catalogue keys;
    no matching entry declines and skips the field. A required field that is
    skipped skips the form (spec 8.2, step 5).

    The field crosses the policy port as its contract only: a `value` the field
    carries never reaches the model, and the value catalogue is rendered by
    `policy.prompts` as keys, kinds, and descriptions only.
    """
    keys = matching_keys(field, catalogue)
    if not keys:
        return _declined(field)
    if len(keys) == 1:
        key = keys[0]
        return _resolved(field, key, catalogue.entries[key], source="single")
    answer = policy.choose_value(_field_contract(field), catalogue.entries)
    if answer is None or answer == NONE_CHOICE:
        return _declined(field)
    entry = catalogue.entries.get(answer)
    if entry is None:
        raise PolicyInvalidChoice(
            "choose_value", answer, answer_space(catalogue.entries)
        )
    return _resolved(field, answer, entry, source="jev")


def _resolved(
    field: Mapping[str, Any],
    key: str,
    entry: ValueEntry,
    *,
    source: ValueSource,
) -> ValueChoice:
    """The choice for one resolved entry, skipped when it resolves to no value."""
    value = _resolved_value(entry, field)
    if value is None:
        return _skipped(field, key=key, source=source)
    return ValueChoice(key=key, value=value, source=source)


def _resolved_value(entry: ValueEntry, field: Mapping[str, Any]) -> str | None:
    """The value to type: the entry's own, or the field's first non-empty option."""
    if entry.kind == "none" or entry.value is None:
        return None
    if entry.value != FIRST_OPTION:
        return entry.value
    for option in _option_values(field.get("options")):
        if option.strip():
            return option.strip()
    return None


def _declined(field: Mapping[str, Any]) -> ValueChoice:
    """The protocol's decline: nothing is typed, and a required field skips its form."""
    return _skipped(field, key=NONE_CHOICE, source="none")


def _skipped(
    field: Mapping[str, Any], *, key: str, source: ValueSource
) -> ValueChoice:
    """A skipped field, and the form when the field is required (spec 8.2, step 5)."""
    return ValueChoice(
        key=key,
        value=None,
        source=source,
        skip_field=True,
        skip_form=bool(field.get("required")),
    )


def _field_contract(field: Mapping[str, Any]) -> dict[str, Any]:
    """The field contract only: a value the field carries never reaches the model."""
    return {key: field[key] for key in FIELD_CONTRACT if key in field}


def _option_values(options: Any) -> tuple[str, ...]:
    """The option values of a select, radio, or checkbox field, in DOM order."""
    if options is None:
        return ()
    if isinstance(options, str):
        return (options,)
    values: list[str] = []
    for option in options:
        if isinstance(option, Mapping):
            option = option.get("value")
        if option is not None:
            values.append(str(option))
    return tuple(values)


@dataclass(frozen=True)
class ValueValidation:
    """The verdict on one chosen value: valid, or the reason it is not (spec 8.2)."""

    ok: bool
    reason: str = ""


def validate_value(value: str, field: Mapping[str, Any]) -> ValueValidation:
    """Check one chosen value against the field contract (spec 8.2).

    The pattern is a full match; min and max are numeric when the value is
    numeric, and ISO dates when the field is a date; a present options list is a
    closed membership set. A failed check is the executor's signal to skip the
    field, and a required failed field skips the form. A malformed pattern fails
    closed: the value cannot be shown to satisfy a pattern that does not parse.
    """
    pattern = field.get("pattern")
    if pattern:
        try:
            matches = re.fullmatch(str(pattern), value) is not None
        except re.error:
            return ValueValidation(
                False, "the field pattern is not a valid regular expression"
            )
        if not matches:
            return ValueValidation(
                False, f"the value does not match the field pattern {pattern!r}"
            )
    number = _number(value)
    if number is not None:
        minimum = _number(field.get("min"))
        maximum = _number(field.get("max"))
        if minimum is not None and number < minimum:
            return ValueValidation(
                False, f"the value is below the field minimum {field.get('min')!r}"
            )
        if maximum is not None and number > maximum:
            return ValueValidation(
                False, f"the value is above the field maximum {field.get('max')!r}"
            )
    if field_kind_for(field) == "date":
        minimum_date = _iso_date(field.get("min"))
        maximum_date = _iso_date(field.get("max"))
        if minimum_date is not None or maximum_date is not None:
            value_date = _iso_date(value)
            if value_date is None:
                return ValueValidation(
                    False, f"the value is not an ISO date: {value!r}"
                )
            if minimum_date is not None and value_date < minimum_date:
                return ValueValidation(
                    False,
                    f"the value is before the field minimum {field.get('min')!r}",
                )
            if maximum_date is not None and value_date > maximum_date:
                return ValueValidation(
                    False,
                    f"the value is after the field maximum {field.get('max')!r}",
                )
    options = _option_values(field.get("options"))
    if options and value not in options:
        return ValueValidation(
            False, f"the value is not one of the field options: {value!r}"
        )
    return ValueValidation(True)


def _number(value: Any) -> float | None:
    """The value as a number, or `None` when it is not numeric."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _iso_date(value: Any) -> date | None:
    """The value as an ISO date, or `None` when it is not one."""
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_VALUE_CATALOGUE",
    "FIRST_OPTION",
    "ChoiceOutcome",
    "ValueCatalogue",
    "ValueChoice",
    "ValueEntry",
    "ValueKind",
    "ValueSource",
    "ValueValidation",
    "choose_field_value",
    "decide_choice",
    "field_kind_for",
    "matching_keys",
    "validate_value",
]
