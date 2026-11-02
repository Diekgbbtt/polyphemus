"""Action -> Steel CLI command -> SteelResult, with a typed refusal boundary.

Spec: `docs/design/steel-crawl-spec.md` sections 2.3, 4.4, 4.7, 5.2, 8.1, 8.2,
and 12.

The mapper is the one place a browser action becomes a CLI command. It owns the
verb grammar: where the selector sits, which verbs are variadic and so carry
their mandatory `--` boundary, and which verbs are not commands at all but a
rendered `eval` script (form submission). It never chooses an action and never
ranks a candidate; the policy does that.

The option order is fixed here by the session client's builder: `--session` and
`--json` follow the verb, before every positional and before the variadic
boundary. A trailing option would be swallowed by a variadic verb as value
text, and a trailing `--session` would fold the command onto a billable
auto-provisioned `default` session.

A stale reference never reaches the CLI: every command is gated by
`BrowserState.resolve` with the action's document generation, so a reference
captured under a replaced document raises `StaleElement` before the session
client builds anything.

This module performs no I/O (CODING_STANDARD section 6): the injected
`SteelSessionClient` is the only executor.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.crawl.steel.session import SteelSessionClient
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    DocumentGeneration,
    PageInstance,
)

# The impact and capture vocabularies are spec 6.4's. SC-05's element map mints
# the values; the mapper only carries them for the action record.
ImpactClass = Literal[
    "observe",
    "local_state",
    "read",
    "write",
    "navigate",
    "download",
    "external",
    "context_reset",
]
CaptureChannel = Literal["dom", "network", "navigation", "none"]

# The mandatory `--` boundary of a variadic verb (spec 4.7). `upload` and
# `batch` are here even though the crawl mints them only through the form and
# batch paths, so no variadic verb can ever be built without its boundary.
VARIADIC_VERBS = frozenset({"fill", "type", "setvalue", "select", "upload", "batch"})

# Key names `press` accepts: one keystroke, never a modifier chord (spec I9).
# A single character is a keystroke too; a longer string must name a key.
PRESS_KEYS = frozenset(
    {
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "ArrowUp",
        "Backspace",
        "Delete",
        "End",
        "Enter",
        "Escape",
        "Home",
        "Insert",
        "PageDown",
        "PageUp",
        "Space",
        "Tab",
    }
)


class VerbShape(BaseModel):
    """The CLI argument grammar of one verb (spec Appendix A).

    `selector` says where the element selector sits: a positional, the
    `--selector` option (scroll), or nowhere. `value` says the action's value is
    a positional. `variadic` says the verb's value payload sits behind its
    mandatory `--` boundary. `args_first` covers `get`, whose subcommand
    precedes its selector. `requires_*` are the pre-build checks; `get url` and
    a page-level scroll carry no selector, while scroll still accepts one.
    """

    model_config = ConfigDict(frozen=True)

    selector: Literal["positional", "option", "none"] = "positional"
    value: bool = False
    variadic: bool = False
    args_first: bool = False
    requires_selector: bool = True
    requires_value: bool = False


class Action(BaseModel):
    """One chosen browser action, ready to become a CLI command.

    `element_id` is the enumerated identity the action record cites;
    `selector` is the CLI-resolvable ref or CSS selector. `verb` is the CLI
    verb, `value` the variadic/first positional, and `args` the verb's own
    option tokens (for `wait`, `get`, `scroll`, and `navigate`). `impact` and
    `capture` are carried, never re-derived. `document_generation` is the
    ref-validity token the state guard checks before any command exists.
    """

    model_config = ConfigDict(frozen=True)

    verb: str
    impact: ImpactClass
    capture: CaptureChannel
    document_generation: DocumentGeneration
    selector: str = ""
    element_id: str = ""
    value: str | None = None
    args: tuple[str, ...] = ()


class SteelResult(BaseModel):
    """One executed action's typed outcome (spec 4.4).

    `output` is the CLI envelope's `data`; the process facts - exit code,
    stderr, duration, warning, and Steel events - come from the same envelope.
    The session client raises on an error envelope, so `error` is populated only
    for an adapter that returns one without raising. `read_back` is the observed
    value of a `select` read-back and `None` for every other action.
    """

    model_config = ConfigDict(frozen=True)

    output: Any = None
    success: bool = True
    error: str | None = None
    warning: str | None = None
    steel_events: tuple[dict[str, Any], ...] = ()
    exit_code: int | None = None
    stderr: str = ""
    duration_ms: int | None = None
    read_back: str | None = None


class CommandRefused(RuntimeError):
    """The mapper refused to build a command. Nothing reached the CLI."""

    code = "refused"

    def __init__(self, message: str = "") -> None:
        self.message = message or "the action does not map to a valid Steel command"
        super().__init__(self.message)


class VariadicBoundaryRefused(CommandRefused):
    """A variadic verb lacked its boundary, or already carried one.

    Spec 4.7: a missing `--` is `refused:variadic-boundary`, never a retry, and
    the mapper never doubles a boundary the action already encoded.
    """

    code = "refused:variadic-boundary"


class PressKeyRefused(CommandRefused):
    """`press` got a modifier chord or a string that is not one key (I9)."""

    code = "refused:press-key"


class IncompleteActionRefused(CommandRefused):
    """The action omitted a selector or a value its verb requires."""

    code = "refused:incomplete-action"


class UnknownVerbRefused(CommandRefused):
    """The verb is not in the command map, so no command exists to build."""

    code = "refused:unknown-verb"


class ActionFailed(RuntimeError):
    """The command ran, but the action's own proof failed.

    `select` raises this on a read-back mismatch (spec I8): the echo is not
    proof, the observed DOM value is. The requested and observed values ride
    the error so the action record can name both.
    """

    code = "action_failed"

    def __init__(
        self, message: str, *, requested: str | None = None, observed: str | None = None
    ) -> None:
        self.requested = requested
        self.observed = observed
        super().__init__(message)


# The verb map: one row per command the mapper may build (spec Appendix A).
# Options (`--session`, `--json`, and a verb's own option tokens) precede every
# positional; a variadic verb's payload sits behind one `--` boundary.
_VERB_MAP: dict[str, VerbShape] = {
    "navigate": VerbShape(
        selector="none", value=True, requires_selector=False, requires_value=True
    ),
    "click": VerbShape(),
    "press": VerbShape(
        selector="none", value=True, requires_selector=False, requires_value=True
    ),
    "check": VerbShape(),
    "uncheck": VerbShape(),
    "clear": VerbShape(),
    "scroll": VerbShape(selector="option", requires_selector=False),
    "hover": VerbShape(),
    "focus": VerbShape(),
    "get": VerbShape(args_first=True, requires_selector=False),
    "eval": VerbShape(
        selector="none", value=True, requires_selector=False, requires_value=True
    ),
    "wait": VerbShape(selector="none", requires_selector=False),
    "submit": VerbShape(selector="none"),
    "fill": VerbShape(value=True, variadic=True),
    "type": VerbShape(value=True, variadic=True),
    "setvalue": VerbShape(value=True, variadic=True),
    "select": VerbShape(value=True, variadic=True),
    "upload": VerbShape(value=True, variadic=True),
    "batch": VerbShape(
        selector="none", value=True, variadic=True, requires_selector=False
    ),
}


def render_submit_script(selector: str) -> str:
    """One eval script that submits the form and names the route it used.

    Spec I10: `requestSubmit()` when it is a function, because it honours
    submit handlers and native validation; `form.submit()` only as the last
    resort, because it bypasses both. The selector is embedded as a JSON string
    so a quote in it cannot break the JS literal. The script returns a small
    JSON object naming the method; a missing form throws, so the CLI answers a
    typed evaluation error instead of a silent success (spec 8.1).
    """
    form = json.dumps(selector)
    return (
        "(()=>{"
        f"const f=document.querySelector({form});"
        'if(!f)throw new Error("form not found");'
        'if(typeof f.requestSubmit==="function"){'
        "f.requestSubmit();"
        'return JSON.stringify({method:"requestSubmit"})'
        "}"
        "f.submit();"
        'return JSON.stringify({method:"submit"})'
        "})()"
    )


class CommandMapper:
    """Build and execute the exact Steel command for one action."""

    def __init__(self, client: SteelSessionClient, state: BrowserState) -> None:
        self._client = client
        self._state = state

    def commands(self, action: Action, page: PageInstance) -> list[list[str]]:
        """The exact session-bound commands the action maps to, in order.

        The stale guard runs first, so a dead reference is refused before any
        command string exists. `select` maps to two commands: the select and its
        `get value` read-back.
        """
        return [
            self._client.command(verb, *args) for verb, args in self._plan(action, page)
        ]

    def execute(self, action: Action, page: PageInstance) -> SteelResult:
        """Build and run the action through the session client, typed.

        Execution goes through the client's guarded `execute`, so the no-session
        and no-start invariants hold for every verb. A `select` runs its
        read-back and fails the action on a mismatch.
        """
        plan = self._plan(action, page)
        envelopes = [self._client.execute(verb, *args) for verb, args in plan]
        if action.verb == "select":
            observed = _read_back(envelopes[-1])
            if observed != action.value:
                raise ActionFailed(
                    f"the select read-back observed {observed!r}, "
                    f"expected {action.value!r}",
                    requested=action.value,
                    observed=observed,
                )
            return _result(envelopes[0], read_back=observed)
        return _result(envelopes[0])

    def _plan(
        self, action: Action, page: PageInstance
    ) -> list[tuple[str, tuple[str, ...]]]:
        """Validate the action and return its `(verb, args)` sequence, pure.

        The state guard runs before the verb map, so a stale reference is the
        first refusal and no command is built for it.
        """
        self._state.resolve(page, action.document_generation)
        shape = _VERB_MAP.get(action.verb)
        if shape is None:
            raise UnknownVerbRefused(f"no Steel command maps {action.verb!r}")
        _validate(action, shape)
        if action.verb == "submit":
            # Form submission is one rendered eval, never a click on the submit
            # control: the click path cannot prove which submit route ran.
            return [("eval", (render_submit_script(action.selector),))]
        primary = (action.verb, tuple(_command_args(action, shape)))
        if action.verb == "select":
            # The select's echo is not proof (spec I8): read the DOM value back.
            return [primary, ("get", ("value", action.selector))]
        return [primary]


def _validate(action: Action, shape: VerbShape) -> None:
    """Refuse an action the verb's grammar cannot render, before building."""
    if shape.requires_selector and not action.selector:
        raise IncompleteActionRefused(
            f"{action.verb} requires a selector and the action carries none"
        )
    if shape.variadic:
        if action.value is None:
            raise VariadicBoundaryRefused(
                f"{action.verb} is variadic and the action carries no value for "
                "its mandatory `--` boundary"
            )
        if action.value == "--" or "--" in action.args:
            raise VariadicBoundaryRefused(
                f"{action.verb} already carries a `--` boundary; the mapper "
                "never inserts a second one"
            )
    elif shape.requires_value and action.value is None:
        raise IncompleteActionRefused(
            f"{action.verb} requires a value and the action carries none"
        )
    if action.verb == "press":
        _validate_press_key(action.value or "")


def _validate_press_key(key: str) -> None:
    """One key only: a single character or a known key name, never a chord."""
    if key and "+" not in key and (len(key) == 1 or key in PRESS_KEYS):
        return
    raise PressKeyRefused(
        f"press takes one key, not {key!r}: a modifier chord or a "
        "multi-character string is not a key"
    )


def _command_args(action: Action, shape: VerbShape) -> list[str]:
    """Render the verb's positional tail from the action and its shape."""
    payload: list[str] = []
    if shape.value:
        payload.append(action.value or "")
    payload.extend(action.args)
    if shape.selector == "option":
        head = ["--selector", action.selector] if action.selector else []
        return [*head, *payload]
    if shape.args_first:
        head = [action.selector] if action.selector else []
        return [*payload, *head]
    if shape.selector == "positional":
        head = [action.selector]
    else:
        head = []
    if shape.variadic:
        # Exactly one boundary, after the selector and before every value.
        return [*head, "--", *payload]
    return [*head, *payload]


def _result(
    envelope: Mapping[str, Any], *, read_back: str | None = None
) -> SteelResult:
    """Map the CLI envelope's process facts into the typed result."""
    return SteelResult(
        output=envelope.get("data"),
        error=_error_text(envelope.get("error")),
        warning=_optional_text(envelope.get("warning")),
        steel_events=_steel_events(envelope.get("steel_events")),
        exit_code=_optional_int(envelope.get("returncode")),
        stderr=str(envelope.get("stderr") or ""),
        duration_ms=_optional_int(envelope.get("duration_ms")),
        read_back=read_back,
    )


def _read_back(envelope: Mapping[str, Any]) -> str | None:
    """The observed value of a `get value` envelope (an object, not a string)."""
    data = envelope.get("data")
    if isinstance(data, Mapping):
        value = data.get("value")
        return None if value is None else str(value)
    return None if data is None else str(data)


def _steel_events(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(dict(event) for event in value if isinstance(event, Mapping))


def _error_text(error: Any) -> str | None:
    if not error:
        return None
    if isinstance(error, Mapping):
        return str(error.get("message") or error.get("code") or "")
    return str(error)


def _optional_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "Action",
    "ActionFailed",
    "CaptureChannel",
    "CommandMapper",
    "CommandRefused",
    "ImpactClass",
    "IncompleteActionRefused",
    "PRESS_KEYS",
    "PressKeyRefused",
    "SteelResult",
    "VARIADIC_VERBS",
    "UnknownVerbRefused",
    "VariadicBoundaryRefused",
    "VerbShape",
    "render_submit_script",
]
