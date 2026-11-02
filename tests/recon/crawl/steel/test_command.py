"""Seam under test: `CommandMapper` through table-driven cases.

Spec: `docs/design/steel-crawl-spec.md` sections 2.3, 4.4, 4.7, 5.2, 8.1, 8.2,
and 12; seam 6 of `docs/design/steel-crawl-implementation-plan.md` section 3.
Every test drives the public mapper: it asserts the exact command an action
renders to, the typed refusal that stops a bad command before it is built, and
the result envelope. No test reaches into a private method or asserts an
internal call sequence. Expected command shapes come from the spec's command
map (Appendix A) and the skill's worked variadic forms, never from recomputing
the implementation.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from polymerhus.recon.crawl.steel.command import (
    Action,
    ActionFailed,
    CommandMapper,
    IncompleteActionRefused,
    PressKeyRefused,
    SteelResult,
    UnknownVerbRefused,
    VARIADIC_VERBS,
    VariadicBoundaryRefused,
)
from polymerhus.recon.crawl.steel.session import InvalidCommand, SteelSessionClient
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    SnapshotFacts,
    StaleElement,
)
from tests.recon.crawl.steel.fixtures import CliEnvelope, load_cli
from tests.recon.crawl.steel.support import FakeExecFn

SESSION = "crawl-fixture"
HEAD = ["steel", "browser"]
ATTACH_COMMANDS = [
    [*HEAD, "sessions", "--json"],
    [*HEAD, "sessions", "get", "--session", SESSION, "--json"],
]


def _open_page(state: BrowserState, **overrides: Any) -> PageInstance:
    payload: dict[str, Any] = {
        "page_visit_id": "page_1",
        "url": "https://example.test/",
        "final_url": "https://example.test/",
        "snapshot": load_cli("snapshot").data,
        "facts": SnapshotFacts(ax_hash="ax-home"),
    }
    payload.update(overrides)
    return state.open_page(**payload)


class Rig:
    """One attached client, one open page, one mapper, and the recorded commands."""

    def __init__(self, *envelopes: CliEnvelope | dict[str, Any]) -> None:
        self.exec_fn = FakeExecFn(
            load_cli("catalogue"), load_cli("session"), *envelopes
        )
        self.client = SteelSessionClient(exec_fn=self.exec_fn)
        self.client.attach(SESSION)
        self.state = BrowserState()
        self.page = _open_page(self.state)
        self.mapper = CommandMapper(self.client, self.state)


def _action(**overrides: Any) -> Action:
    """An action on the open page's first document; only the test fields vary."""
    payload: dict[str, Any] = {
        "verb": "click",
        "impact": "local_state",
        "capture": "none",
        "document_generation": 1,
    }
    payload.update(overrides)
    return Action(**payload)


def test_every_command_carries_the_verb_the_session_and_json_before_its_selector():
    rig = Rig(load_cli("click"))

    result = rig.mapper.execute(_action(verb="click", selector="@e9"), rig.page)

    assert rig.exec_fn.commands[2] == [
        *HEAD,
        "click",
        "--session",
        SESSION,
        "--json",
        "@e9",
    ]
    assert result.output == {"clicked": "@e9"}


def test_the_result_carries_the_process_facts_from_the_envelope():
    rig = Rig(
        {
            "success": True,
            "data": {"clicked": "@e9"},
            "warning": "the target was slow",
            "steel_events": [{"verb": "click", "returncode": 0}],
            "returncode": 0,
            "stderr": "diagnostic",
            "duration_ms": 37,
        }
    )

    result = rig.mapper.execute(_action(verb="click", selector="@e9"), rig.page)

    assert isinstance(result, SteelResult)
    assert result.output == {"clicked": "@e9"}
    assert result.success is True
    assert result.error is None
    assert result.warning == "the target was slow"
    assert result.steel_events == ({"verb": "click", "returncode": 0},)
    assert result.exit_code == 0
    assert result.stderr == "diagnostic"
    assert result.duration_ms == 37
    assert result.read_back is None


def test_a_fake_envelope_without_process_facts_leaves_them_empty():
    rig = Rig(load_cli("click"))

    result = rig.mapper.execute(_action(verb="click", selector="@e9"), rig.page)

    assert result.exit_code is None
    assert result.stderr == ""
    assert result.duration_ms is None
    assert result.steel_events == ()
    assert result.warning is None


# One row per non-variadic verb, with the exact command the spec's command map
# (Appendix A) and the skill's worked forms require. Options precede every
# positional; the verb's own option tokens trail its positional.
VERB_CASES = [
    (
        "navigate",
        _action(
            verb="navigate",
            value="https://example.test/products?page=2",
            args=("--wait-until", "domcontentloaded"),
            impact="navigate",
            capture="navigation",
        ),
        [
            *HEAD,
            "navigate",
            "--session",
            SESSION,
            "--json",
            "https://example.test/products?page=2",
            "--wait-until",
            "domcontentloaded",
        ],
    ),
    (
        "click",
        _action(verb="click", selector="@e9"),
        [*HEAD, "click", "--session", SESSION, "--json", "@e9"],
    ),
    (
        "press",
        _action(verb="press", value="Enter", impact="read", capture="network"),
        [*HEAD, "press", "--session", SESSION, "--json", "Enter"],
    ),
    (
        "check",
        _action(verb="check", selector="@e5"),
        [*HEAD, "check", "--session", SESSION, "--json", "@e5"],
    ),
    (
        "uncheck",
        _action(verb="uncheck", selector="@e5"),
        [*HEAD, "uncheck", "--session", SESSION, "--json", "@e5"],
    ),
    (
        "clear",
        _action(verb="clear", selector="@e6"),
        [*HEAD, "clear", "--session", SESSION, "--json", "@e6"],
    ),
    (
        "scroll",
        _action(verb="scroll", selector="@e9", args=("down", "300")),
        [
            *HEAD,
            "scroll",
            "--session",
            SESSION,
            "--json",
            "--selector",
            "@e9",
            "down",
            "300",
        ],
    ),
    (
        "hover",
        _action(verb="hover", selector="@e9"),
        [*HEAD, "hover", "--session", SESSION, "--json", "@e9"],
    ),
    (
        "focus",
        _action(verb="focus", selector="@e6"),
        [*HEAD, "focus", "--session", SESSION, "--json", "@e6"],
    ),
    (
        "get",
        _action(
            verb="get",
            selector="@e7",
            args=("value",),
            impact="read",
            capture="network",
        ),
        [*HEAD, "get", "--session", SESSION, "--json", "value", "@e7"],
    ),
    (
        "eval",
        _action(
            verb="eval",
            value="document.title",
            impact="observe",
            capture="none",
        ),
        [*HEAD, "eval", "--session", SESSION, "--json", "document.title"],
    ),
    (
        "wait",
        _action(
            verb="wait",
            args=("--selector", 'a[href="/logout"]', "--timeout", "15000"),
            impact="observe",
            capture="none",
        ),
        [
            *HEAD,
            "wait",
            "--session",
            SESSION,
            "--json",
            "--selector",
            'a[href="/logout"]',
            "--timeout",
            "15000",
        ],
    ),
]


@pytest.mark.parametrize(
    "action, expected",
    [case[1:] for case in VERB_CASES],
    ids=[case[0] for case in VERB_CASES],
)
def test_each_verb_renders_the_exact_spec_command(action, expected):
    rig = Rig()

    assert rig.mapper.commands(action, rig.page) == [expected]


def test_form_submission_is_one_eval_that_prefers_request_submit():
    rig = Rig(load_cli("submit"))

    result = rig.mapper.execute(
        _action(verb="submit", selector="#login", impact="write", capture="network"),
        rig.page,
    )

    commands = rig.exec_fn.commands[2:]
    assert len(commands) == 1
    command = commands[0]
    assert command[:3] == [*HEAD, "eval"]
    assert command[3:6] == ["--session", SESSION, "--json"]
    script = command[6]
    assert json.dumps("#login") in script
    assert "typeof f.requestSubmit" in script
    assert script.index("f.requestSubmit()") < script.index("f.submit()")
    assert 'method:"requestSubmit"' in script
    assert 'method:"submit"' in script
    assert result.output == '{"method":"requestSubmit"}'


def test_the_submit_script_embeds_the_selector_as_a_json_string():
    selector = 'form[data-name="a b"]'
    rig = Rig(load_cli("submit"))

    rig.mapper.execute(
        _action(verb="submit", selector=selector, impact="write", capture="network"),
        rig.page,
    )

    script = rig.exec_fn.last_command[6]
    assert json.dumps(selector) in script


# The variadic verbs (spec 4.7): the selector is the last positional before the
# boundary and every value sits behind exactly one `--`.
VARIADIC_CASES = [
    (
        "fill",
        _action(verb="fill", selector="@e6", value="standard_user"),
        [
            [
                *HEAD,
                "fill",
                "--session",
                SESSION,
                "--json",
                "@e6",
                "--",
                "standard_user",
            ]
        ],
    ),
    (
        "type",
        _action(verb="type", selector="@e6", value="standard_user"),
        [
            [
                *HEAD,
                "type",
                "--session",
                SESSION,
                "--json",
                "@e6",
                "--",
                "standard_user",
            ]
        ],
    ),
    (
        "setvalue",
        _action(verb="setvalue", selector="@e6", value="standard_user"),
        [
            [
                *HEAD,
                "setvalue",
                "--session",
                SESSION,
                "--json",
                "@e6",
                "--",
                "standard_user",
            ]
        ],
    ),
    (
        "select",
        _action(
            verb="select",
            selector="@e7",
            value="books",
            impact="write",
            capture="network",
        ),
        [
            [*HEAD, "select", "--session", SESSION, "--json", "@e7", "--", "books"],
            [*HEAD, "get", "--session", SESSION, "--json", "value", "@e7"],
        ],
    ),
    (
        "upload",
        _action(
            verb="upload",
            selector="@e6",
            value="crawl-upload.txt",
            impact="write",
            capture="network",
        ),
        [
            [
                *HEAD,
                "upload",
                "--session",
                SESSION,
                "--json",
                "@e6",
                "--",
                "crawl-upload.txt",
            ]
        ],
    ),
    (
        "batch",
        _action(
            verb="batch",
            value="snapshot -i",
            args=("fill @e6 -- 42",),
            impact="observe",
            capture="none",
        ),
        [
            [
                *HEAD,
                "batch",
                "--session",
                SESSION,
                "--json",
                "--",
                "snapshot -i",
                "fill @e6 -- 42",
            ]
        ],
    ),
]


@pytest.mark.parametrize(
    "action, expected",
    [case[1:] for case in VARIADIC_CASES],
    ids=[case[0] for case in VARIADIC_CASES],
)
def test_each_variadic_verb_carries_exactly_one_boundary_before_its_value(
    action, expected
):
    rig = Rig()

    assert rig.mapper.commands(action, rig.page) == expected


@pytest.mark.parametrize("verb", sorted(VARIADIC_VERBS))
def test_a_variadic_verb_without_a_value_is_refused_before_execution(verb):
    rig = Rig()
    action = _action(verb=verb, selector="@e6", value=None, args=("ignored",))

    with pytest.raises(VariadicBoundaryRefused) as excinfo:
        rig.mapper.execute(action, rig.page)

    assert excinfo.value.code == "refused:variadic-boundary"
    assert rig.exec_fn.commands == ATTACH_COMMANDS


@pytest.mark.parametrize("verb", sorted(VARIADIC_VERBS))
def test_a_variadic_action_that_already_carries_the_boundary_is_refused(verb):
    rig = Rig()
    action = _action(verb=verb, selector="@e6", value="--")

    with pytest.raises(VariadicBoundaryRefused) as excinfo:
        rig.mapper.execute(action, rig.page)

    assert excinfo.value.code == "refused:variadic-boundary"
    assert rig.exec_fn.commands == ATTACH_COMMANDS


@pytest.mark.parametrize("verb", sorted(VARIADIC_VERBS))
def test_a_boundary_inside_the_extra_args_is_refused_rather_than_doubled(verb):
    rig = Rig()
    action = _action(verb=verb, selector="@e6", value="text", args=("--", "more"))

    with pytest.raises(VariadicBoundaryRefused):
        rig.mapper.commands(action, rig.page)

    assert rig.exec_fn.commands == ATTACH_COMMANDS


def test_select_is_proven_by_its_read_back_not_its_echo():
    rig = Rig(load_cli("select"), load_cli("get_value"))

    result = rig.mapper.execute(
        _action(
            verb="select",
            selector="@e7",
            value="books",
            impact="write",
            capture="network",
        ),
        rig.page,
    )

    assert rig.exec_fn.commands[2:] == [
        [*HEAD, "select", "--session", SESSION, "--json", "@e7", "--", "books"],
        [*HEAD, "get", "--session", SESSION, "--json", "value", "@e7"],
    ]
    assert result.output == {"selected": ["books"]}
    assert result.read_back == "books"


def test_a_select_read_back_mismatch_fails_the_action():
    rig = Rig(load_cli("select"), load_cli("get_value_mismatch"))

    with pytest.raises(ActionFailed) as excinfo:
        rig.mapper.execute(
            _action(
                verb="select",
                selector="@e7",
                value="zzz",
                impact="write",
                capture="network",
            ),
            rig.page,
        )

    assert excinfo.value.code == "action_failed"
    assert excinfo.value.requested == "zzz"
    assert excinfo.value.observed == "first-option"


@pytest.mark.parametrize(
    "key",
    [
        "Enter",
        "Tab",
        "Escape",
        "Backspace",
        "Delete",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Space",
        "a",
    ],
)
def test_press_accepts_one_key(key):
    rig = Rig()

    command = rig.mapper.commands(
        _action(verb="press", value=key, impact="read", capture="network"), rig.page
    )[0]

    assert command == [*HEAD, "press", "--session", SESSION, "--json", key]


@pytest.mark.parametrize(
    "key", ["Control+a", "Shift+Tab", "ab", "Control", "", "+", "Return"]
)
def test_press_refuses_a_chord_or_a_multi_character_string(key):
    rig = Rig()

    with pytest.raises(PressKeyRefused) as excinfo:
        rig.mapper.execute(
            _action(verb="press", value=key, impact="read", capture="network"), rig.page
        )

    assert excinfo.value.code == "refused:press-key"
    assert rig.exec_fn.commands == ATTACH_COMMANDS


def test_a_stale_reference_is_refused_before_any_command_is_built():
    rig = Rig()
    stale_generation = rig.page.document_generation
    _open_page(
        rig.state,
        page_visit_id="page_2",
        url="https://example.test/products?page=2",
        final_url="https://example.test/products?page=2",
        navigation_path=["fp-products"],
    )

    with pytest.raises(StaleElement) as excinfo:
        rig.mapper.execute(
            _action(verb="click", selector="@e9", document_generation=stale_generation),
            rig.page,
        )

    assert excinfo.value.code == "stale_element"
    assert rig.exec_fn.commands == ATTACH_COMMANDS


def test_the_mapper_never_builds_a_command_without_a_session():
    state = BrowserState()
    page = _open_page(state)
    exec_fn = FakeExecFn()
    mapper = CommandMapper(SteelSessionClient(exec_fn=exec_fn), state)

    with pytest.raises(InvalidCommand) as excinfo:
        mapper.execute(_action(verb="click", selector="@e9"), page)

    assert excinfo.value.code == "invalid_command"
    assert exec_fn.commands == []


def test_an_unknown_verb_is_refused_without_a_command():
    rig = Rig()

    # `start` is deliberately outside the map: the crawl never starts a session.
    with pytest.raises(UnknownVerbRefused) as excinfo:
        rig.mapper.commands(_action(verb="start", selector="x"), rig.page)

    assert excinfo.value.code == "refused:unknown-verb"
    assert rig.exec_fn.commands == ATTACH_COMMANDS


def test_a_verb_that_requires_a_selector_refuses_an_empty_one():
    rig = Rig()

    with pytest.raises(IncompleteActionRefused) as excinfo:
        rig.mapper.commands(_action(verb="click", selector=""), rig.page)

    assert excinfo.value.code == "refused:incomplete-action"
    assert rig.exec_fn.commands == ATTACH_COMMANDS


def test_a_navigate_without_a_url_is_refused():
    rig = Rig()

    with pytest.raises(IncompleteActionRefused):
        rig.mapper.commands(
            _action(
                verb="navigate", value=None, impact="navigate", capture="navigation"
            ),
            rig.page,
        )

    assert rig.exec_fn.commands == ATTACH_COMMANDS


def test_a_page_level_scroll_carries_no_selector_option():
    rig = Rig()

    commands = rig.mapper.commands(
        _action(verb="scroll", args=("down", "300")), rig.page
    )

    assert commands == [
        [*HEAD, "scroll", "--session", SESSION, "--json", "down", "300"]
    ]


def test_a_selectorless_get_is_a_valid_read():
    rig = Rig()

    commands = rig.mapper.commands(
        _action(verb="get", args=("url",), impact="read", capture="network"), rig.page
    )

    assert commands == [[*HEAD, "get", "--session", SESSION, "--json", "url"]]
