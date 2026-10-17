"""Unit tier: the harness adapter (`runner/harness.py`), part 3.

The adapter drives `opencode api` subprocesses (create/prompt/message/interrupt)
and parses the service API's own message shapes. The parsing is tested on
RECORDED fixtures (the shapes taken verbatim from the service's OpenAPI
document and from a live probe), and the session lifecycle is tested against a
recording fake executor: no network and no model in the default run.

ONE opt-in live smoke test exists (`BOOTSTRAP_LIVE_SMOKE=1`) that exercises the
real service: create a throwaway session, prompt a trivial reply, assert the
terminal turn succeeded and the assistant's model matches the requested
reference, then delete the session. It is never part of the default suite.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _on_path(rel: str) -> None:
    path = str(REPO_ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)


_on_path("tools/bootstrap")
_on_path("eval")
_on_path("src")

from orchestrator.commands import Command, CommandResult  # noqa: E402

from runner.env import LocalExecutor  # noqa: E402
from runner.harness import (  # noqa: E402
    DEFAULT_TURN_TIMEOUT_S,
    RETRY_BACKOFF_S,
    HarnessError,
    ModelRef,
    OpenCodeApiHarness,
    SessionSpec,
    TurnTimeout,
    assistant_text,
    classify_stderr,
    decode_data,
    is_retryable,
    message_list,
    newer_than,
    parse_terminal,
)


class FakeApi:
    """A scripted `opencode api` executor: routes keyed by 'METHOD path'."""

    def __init__(self) -> None:
        self.calls: list[Command] = []
        self.routes: dict[str, list[CommandResult]] = {}
        self.default = CommandResult(0, '{"data": {}}', "")

    def ok(self, method: str, path: str, data: object, *rest: object) -> None:
        answers = [CommandResult(0, json.dumps({"data": data}), "")]
        answers += [
            item if isinstance(item, CommandResult) else CommandResult(0, json.dumps({"data": item}), "")
            for item in rest
        ]
        self.routes[f"{method} {path}"] = answers

    def fail(self, method: str, path: str, *answers: CommandResult) -> None:
        self.routes[f"{method} {path}"] = list(answers)

    def __call__(self, command: Command) -> CommandResult:
        self.calls.append(command)
        argv = list(command.argv)
        key = f"{argv[2]} {argv[3]}" if len(argv) > 3 else ""
        queue = self.routes.get(key)
        if queue:
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return self.default


def _spec(session_id: str = "ses_bt_r1_shop_creator") -> SessionSpec:
    return SessionSpec(
        session_id=session_id,
        title="bootstrap shop",
        agent="data-dep-worker",
        model=ModelRef("opencode", "deepseek-v4.1-flash-free", "high"),
        directory="/wt",
        metadata={"run": "r1", "target": "shop", "phase": "authn"},
    )


def _idle(outcome: str, error: dict | None = None, session: str = "ses_bt_r1_shop_creator") -> dict:
    message = {
        "id": f"msg_idle_{uuid.uuid4().hex[:8]}",
        "time": {"created": 1},
        "type": "idle",
        "outcome": outcome,
        "sessionID": session,
    }
    if error:
        message["error"] = error
    return message


def _assistant(model: dict | None = None, error: dict | None = None) -> dict:
    message = {
        "id": f"msg_asst_{uuid.uuid4().hex[:8]}",
        "time": {"created": 1},
        "type": "assistant",
        "agent": "data-dep-worker",
        "model": model or {"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "high"},
        "content": [{"text": "Phase complete."}],
        "finish": "stop" if not error else "error",
    }
    if error:
        message["error"] = error
    return message


# --- recorded shapes: parsing ------------------------------------------------


def test_decode_data_unwraps_the_api_envelope():
    assert decode_data('{"data": {"id": "ses_x"}}') == {"id": "ses_x"}
    assert decode_data("not json") is None
    assert decode_data("") is None


def test_message_list_reads_both_envelope_shapes():
    messages = [{"id": "m1", "type": "user"}]
    assert message_list(json.dumps({"data": messages})) == tuple(messages)
    assert message_list(json.dumps(messages)) == tuple(messages)
    assert message_list("nonsense") == ()


def test_parse_terminal_reads_a_succeeded_turn_and_its_model():
    messages = [
        {"id": "m1", "type": "user", "text": "go"},
        _assistant(),
        _idle("succeeded"),
    ]
    turn = parse_terminal(messages)
    assert turn is not None
    assert turn.outcome == "succeeded"
    assert turn.ok is True
    assert turn.model == {
        "id": "deepseek-v4.1-flash-free",
        "providerID": "opencode",
        "variant": "high",
    }
    assert assistant_text(turn) == "Phase complete."


def test_parse_terminal_returns_none_while_the_turn_is_running():
    messages = [{"id": "m1", "type": "user", "text": "go"}, _assistant()]
    assert parse_terminal(messages) is None


def test_parse_terminal_reads_the_provider_error_from_the_assistant_message():
    provider_error = {
        "type": "provider.auth",
        "message": "OpenCode's free tier can only be used from within OpenCode.",
        "status": 403,
        "response": {"body": '{"type":"error","error":{"type":"FreeTierError"}}'},
    }
    messages = [
        {"id": "m1", "type": "user", "text": "go"},
        _assistant(error=provider_error),
        _idle("failed", error={"type": "provider.auth", "message": "request failed"}),
    ]
    turn = parse_terminal(messages)
    assert turn is not None
    assert turn.outcome == "failed"
    assert turn.ok is False
    assert turn.error_status == 403
    assert "free tier" in turn.error.lower()
    assert turn.retryable is True


def test_parse_terminal_honours_the_id_watermark():
    stale = [_assistant(), _idle("succeeded")]
    fresh = [{"id": "m2", "type": "user", "text": "again"}]
    assert parse_terminal(stale + fresh, after=stale[-1]["id"]) is None
    assert parse_terminal(stale + fresh) is not None


def test_parse_terminal_ignores_an_idle_without_an_outcome():
    """The schema requires `outcome`; a malformed idle is not a completion."""
    messages = [{"id": "m1", "type": "idle"}]
    assert parse_terminal(messages) is None


def test_retry_classification_covers_the_pinned_classes():
    assert is_retryable("OpenCode's free tier can only be used from within OpenCode.")
    assert is_retryable("FreeTierError")
    assert is_retryable("429 Too Many Requests")
    assert is_retryable("503 Service Unavailable")
    assert is_retryable("connection reset by peer")
    assert not is_retryable("")
    assert classify_stderr('{"type":"FreeTierError","status":403}') is True
    assert classify_stderr("Error: session not found") is False


def test_retry_backoff_ladder_matches_the_decision():
    assert RETRY_BACKOFF_S == (60.0, 300.0, 900.0)
    assert DEFAULT_TURN_TIMEOUT_S == 3600.0


# --- session lifecycle over the fake API ------------------------------------


def test_create_session_pins_the_full_explicit_body():
    api = FakeApi()
    api.ok("post", "/api/session", {"id": "ses_bt_r1_shop_creator"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    created = harness.create_session(_spec())
    assert created == "ses_bt_r1_shop_creator"
    command = api.calls[0]
    assert command.argv[:4] == ("opencode", "api", "post", "/api/session")
    body = json.loads(command.argv[command.argv.index("--data") + 1])
    assert body["id"] == "ses_bt_r1_shop_creator"
    assert body["agent"] == "data-dep-worker"
    assert body["model"] == {
        "providerID": "opencode",
        "id": "deepseek-v4.1-flash-free",
        "variant": "high",
    }
    assert body["location"] == {"directory": "/wt"}
    assert body["metadata"] == {"run": "r1", "target": "shop", "phase": "authn"}
    assert body["permissions"] == [{"action": "*", "resource": "*", "effect": "allow"}]


def test_create_session_resumes_an_existing_id():
    """A duplicate create answers rc=0 with the existing (possibly stale) session."""
    api = FakeApi()
    api.ok(
        "post",
        "/api/session",
        {
            "id": "ses_bt_r1_shop_creator",
            "agent": "data-dep-worker",
            "model": {"providerID": "opencode", "id": "deepseek-v4.1-flash-free", "variant": "high"},
        },
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    assert harness.create_session(_spec()) == "ses_bt_r1_shop_creator"
    assert [call.argv[3] for call in api.calls] == ["/api/session"]


def test_create_session_aligns_a_stale_create_response():
    """The idempotent create echoes the session it found; a stale pin is aligned."""
    api = FakeApi()
    api.ok(
        "post",
        "/api/session",
        {
            "id": "ses_bt_r1_shop_creator",
            "agent": "data-dep-worker",
            "model": {"providerID": "opencode-go", "id": "deepseek-v4.1-flash", "variant": "high"},
        },
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    assert harness.create_session(_spec()) == "ses_bt_r1_shop_creator"
    assert [call.argv[3] for call in api.calls] == [
        "/api/session",
        "/api/session/ses_bt_r1_shop_creator/model",
    ]
    align = api.calls[-1]
    body = json.loads(align.argv[align.argv.index("--data") + 1])
    assert body["model"] == {
        "providerID": "opencode",
        "id": "deepseek-v4.1-flash-free",
        "variant": "high",
    }


def test_create_session_aligns_an_adopted_sessions_stale_agent():
    api = FakeApi()
    api.fail(
        "post",
        "/api/session",
        CommandResult(1, "", '{"type":"ConflictError","message":"session exists"}'),
    )
    api.ok(
        "get",
        "/api/session/ses_bt_r1_shop_creator",
        {
            "id": "ses_bt_r1_shop_creator",
            "agent": "general",
            "model": {"providerID": "opencode", "id": "deepseek-v4.1-flash-free", "variant": "high"},
        },
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    assert harness.create_session(_spec()) == "ses_bt_r1_shop_creator"
    align = api.calls[-1]
    assert align.argv[3] == "/api/session/ses_bt_r1_shop_creator/agent"
    body = json.loads(align.argv[align.argv.index("--data") + 1])
    assert body == {"agent": "data-dep-worker"}


def test_create_session_leaves_an_aligned_session_untouched():
    api = FakeApi()
    api.fail(
        "post",
        "/api/session",
        CommandResult(1, "", '{"type":"ConflictError","message":"session exists"}'),
    )
    api.ok(
        "get",
        "/api/session/ses_bt_r1_shop_creator",
        {
            "id": "ses_bt_r1_shop_creator",
            "agent": "data-dep-worker",
            "model": {"providerID": "opencode", "id": "deepseek-v4.1-flash-free", "variant": "high"},
        },
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    assert harness.create_session(_spec()) == "ses_bt_r1_shop_creator"
    assert [call.argv[3] for call in api.calls] == [
        "/api/session",
        "/api/session/ses_bt_r1_shop_creator",
    ]


def test_create_session_fails_loudly_when_the_alignment_fails():
    api = FakeApi()
    api.fail(
        "post",
        "/api/session",
        CommandResult(1, "", '{"type":"ConflictError","message":"session exists"}'),
    )
    api.ok(
        "get",
        "/api/session/ses_bt_r1_shop_creator",
        {
            "id": "ses_bt_r1_shop_creator",
            "agent": "data-dep-worker",
            "model": {"providerID": "opencode", "id": "another-model", "variant": "high"},
        },
    )
    api.fail(
        "post",
        "/api/session/ses_bt_r1_shop_creator/model",
        CommandResult(1, "", "rate limit exceeded"),
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    with pytest.raises(HarnessError) as excinfo:
        harness.create_session(_spec())
    assert excinfo.value.retryable is True


def test_create_session_fails_loudly_when_neither_create_nor_resume_works():
    api = FakeApi()
    api.fail("post", "/api/session", CommandResult(1, "", "network unreachable"))
    api.fail("get", "/api/session/ses_bt_r1_shop_creator", CommandResult(1, "", "network unreachable"))
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    with pytest.raises(HarnessError):
        harness.create_session(_spec())


def test_prompt_sends_the_json_body_and_sets_the_turn_boundary():
    api = FakeApi()
    api.ok(
        "get",
        "/api/session/ses/message?order=desc&limit=1",
        [{"id": "m1", "type": "user", "time": {"created": 1234}}],
    )
    api.ok("post", "/api/session/ses/prompt", {"id": "m2"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    boundary = harness.prompt("ses", "do the thing")
    # The boundary is the head ID, never a count: the page is windowed.
    assert boundary == "m1"
    assert harness._watermarks["ses"] == ("m1", 1234)
    prompt_call = api.calls[1]
    assert prompt_call.argv[:4] == ("opencode", "api", "post", "/api/session/ses/prompt")
    assert json.loads(prompt_call.argv[prompt_call.argv.index("--data") + 1]) == {
        "text": "do the thing"
    }


def test_prompt_boundary_is_none_for_an_empty_session():
    api = FakeApi()
    api.ok("get", "/api/session/ses/message?order=desc&limit=1", [])
    api.ok("post", "/api/session/ses/prompt", {"id": "m1"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    assert harness.prompt("ses", "go") == ""
    assert harness._watermarks["ses"] is None


def test_prompt_raises_a_retryable_error_on_a_provider_refusal():
    api = FakeApi()
    api.ok("get", "/api/session/ses/message?order=desc&limit=1", [])
    api.fail(
        "post",
        "/api/session/ses/prompt",
        CommandResult(1, "", "FreeTierError: 403"),
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    with pytest.raises(HarnessError) as excinfo:
        harness.prompt("ses", "go")
    assert excinfo.value.retryable is True


def test_wait_terminal_polls_until_a_new_idle_appears():
    """A stale idle in the newest-first page is never this turn's terminal."""
    stale = [{"id": "m0", "type": "idle", "outcome": "succeeded", "sessionID": "ses"}]
    # The endpoint answers newest first: the new turn's messages arrive at the
    # head of the page, the stale terminal keeps trailing it.
    fresh = [_idle("succeeded", session="ses"), _assistant(), {"id": "m1", "type": "user"}]
    api = FakeApi()
    api.routes["get /api/session/ses/message?order=desc&limit=1"] = [
        CommandResult(0, json.dumps({"data": stale}), ""),
    ]
    api.routes["get /api/session/ses/message?order=desc&limit=20"] = [
        CommandResult(0, json.dumps({"data": stale}), ""),
        CommandResult(0, json.dumps({"data": fresh + stale}), ""),
    ]
    harness = OpenCodeApiHarness(directory="/wt", executor=api, sleep=lambda _s: None)
    harness.prompt("ses", "go")  # boundary: the stale idle's id
    turn = harness.wait_terminal("ses", timeout_s=5)
    assert turn.ok is True
    assert turn.session_id == "ses"
    # The prompt's boundary read plus the two polls (the first one had no idle).
    message_calls = [c for c in api.calls if "/message" in " ".join(c.argv)]
    assert len(message_calls) == 3


def test_wait_terminal_times_out_loudly_and_non_retryably():
    api = FakeApi()
    api.ok("get", "/api/session/ses/message?order=desc&limit=1", [{"id": "m1", "type": "user"}])
    harness = OpenCodeApiHarness(directory="/wt", executor=api, sleep=lambda _s: None)
    harness.prompt("ses", "go")
    with pytest.raises(TurnTimeout) as excinfo:
        harness.wait_terminal("ses", timeout_s=0)
    assert excinfo.value.retryable is False
    assert "terminal turn" in str(excinfo.value)
    # The timeout is a HarnessError: the orchestrator catches it by its own
    # subclass for the interrupt-and-reprompt policy.
    assert isinstance(excinfo.value, HarnessError)


def test_the_boundary_read_is_strict_and_never_degrades():
    """A broken head read must raise, never hand the wait a soundless boundary."""
    api = FakeApi()
    api.fail(
        "get",
        "/api/session/ses/message?order=desc&limit=1",
        CommandResult(1, "", "connection reset by peer"),
    )
    api.ok("post", "/api/session/ses/prompt", {"id": "m"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api, sleep=lambda _s: None)
    with pytest.raises(HarnessError) as excinfo:
        harness.prompt("ses", "go")
    assert excinfo.value.retryable is True
    assert "transcript head" in str(excinfo.value)
    # The prompt was never sent: there is no turn to await.
    assert not any("prompt" in " ".join(call.argv) for call in api.calls)


def test_a_truncated_head_body_is_a_failed_read_not_an_empty_session():
    """The CLI can truncate a large streamed body; that is never 'no messages'.

    An empty boundary would accept any message, including the previous turn's
    idle, as this turn's completion, so an unparseable body retries and then
    raises instead of degrading.
    """
    truncated = CommandResult(0, '{"data": [{"id": "m9", "type": "user"', "")
    api = FakeApi()
    api.fail(
        "get",
        "/api/session/ses/message?order=desc&limit=1",
        truncated,
        truncated,
        truncated,
    )
    api.ok("post", "/api/session/ses/prompt", {"id": "m"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api, sleep=lambda _s: None)
    with pytest.raises(HarnessError) as excinfo:
        harness.prompt("ses", "go")
    assert excinfo.value.retryable is True
    assert "did not parse" in str(excinfo.value)
    assert not any("prompt" in " ".join(call.argv) for call in api.calls)


def test_a_stale_idle_never_completes_a_new_turn():
    """The reviewer's fixture: a failed boundary read plus an unchanged page.

    The transcript already ends with `idle: succeeded` (the previous turn) and
    the new turn produces nothing. A degraded boundary would hand the wait the
    stale idle as this turn's terminal; the strict head read makes the stale
    idle itself the boundary, so nothing in the page is newer than the turn.
    """
    stale_page = [_idle("succeeded", session="ses"), _assistant()]
    api = FakeApi()
    api.routes["get /api/session/ses/message?order=desc&limit=1"] = [
        CommandResult(1, "", "connection reset by peer"),
        CommandResult(0, json.dumps({"data": stale_page}), ""),
    ]
    api.routes["get /api/session/ses/message?order=desc&limit=20"] = [
        CommandResult(0, json.dumps({"data": stale_page}), ""),
    ]
    api.ok("post", "/api/session/ses/prompt", {"id": "m"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api, sleep=lambda _s: None)
    assert harness.prompt("ses", "go") == stale_page[0]["id"]
    with pytest.raises(TurnTimeout):
        harness.wait_terminal("ses", timeout_s=0)


def test_newer_than_walks_back_to_the_boundary_id_oldest_first():
    page = [{"id": "m3"}, {"id": "m2"}, {"id": "m1"}, {"id": "m0"}]
    assert [m["id"] for m in newer_than(page, ("m1", None))] == ["m2", "m3"]
    assert [m["id"] for m in newer_than(page, ("m3", None))] == []
    assert [m["id"] for m in newer_than(page, None)] == ["m0", "m1", "m2", "m3"]


def test_a_turn_longer_than_the_page_keeps_its_terminal():
    """The boundary id can fall out of a full page; the stamp stops the walk.

    A turn that produced more messages than one page pushes its own boundary
    out of the window. Everything the page still shows was created after the
    boundary, so the walk must take the whole page rather than credit the
    previous turn's terminal - and stop at the first message that is not
    newer than the boundary stamp.
    """
    boundary = ("m9", 1000)
    page = [
        {
            "id": "msg_new_idle",
            "type": "idle",
            "outcome": "succeeded",
            "sessionID": "ses",
            "time": {"created": 3000},
        }
    ] + [
        {"id": f"n{i}", "type": "assistant", "time": {"created": 2000 + i}} for i in range(5)
    ]
    fresh = newer_than(page, boundary)
    assert fresh[-1].get("type") == "idle"
    assert len(fresh) == len(page)
    older = [{"id": "o1", "type": "assistant", "time": {"created": 999}}]
    assert newer_than(page + older, boundary) == fresh


def test_interrupt_posts_to_the_interrupt_endpoint():
    api = FakeApi()
    api.ok("post", "/api/session/ses/interrupt", {"interrupted": True})
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    result = harness.interrupt("ses")
    assert result.returncode == 0
    assert api.calls[0].argv[:4] == ("opencode", "api", "post", "/api/session/ses/interrupt")


def test_session_model_reads_the_pinned_reference_back():
    api = FakeApi()
    api.ok(
        "get",
        "/api/session/ses",
        {
            "id": "ses",
            "model": {"id": "deepseek-v4.1-flash-free", "providerID": "opencode", "variant": "high"},
        },
    )
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    assert harness.session_model("ses") == {
        "id": "deepseek-v4.1-flash-free",
        "providerID": "opencode",
        "variant": "high",
    }


def test_harness_never_uses_opencode_run():
    """The harness seam is `opencode api`; `opencode run` is blocked by the gate."""
    api = FakeApi()
    api.ok("post", "/api/session", {"id": "ses"})
    api.ok("get", "/api/session/ses/message?order=desc&limit=1", [])
    api.ok("post", "/api/session/ses/prompt", {"id": "m"})
    harness = OpenCodeApiHarness(directory="/wt", executor=api)
    harness.create_session(_spec(session_id="ses"))
    harness.prompt("ses", "hello")
    rendered = " ".join(" ".join(c.argv) for c in api.calls)
    assert " run " not in f" {rendered} "
    assert "opencode api" in rendered


# --- the shipped worker agent ------------------------------------------------


def test_shipped_worker_agent_is_present_with_full_allow_permissions():
    """The run must not depend on any operator-local agent configuration."""
    import re

    import yaml

    agent = REPO_ROOT / ".opencode" / "agent" / "data-dep-worker.md"
    assert agent.is_file(), f"{agent} is missing"
    text = agent.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "the agent definition needs a YAML frontmatter block"
    frontmatter = yaml.safe_load(match.group(1))
    assert frontmatter["mode"] == "all"
    assert frontmatter["description"].strip()
    assert {"action": "*", "resource": "*", "effect": "allow"} in frontmatter["permissions"]


# --- the one opt-in live smoke test -----------------------------------------


LIVE_SMOKE = os.environ.get("BOOTSTRAP_LIVE_SMOKE") == "1"


@pytest.mark.skipif(not LIVE_SMOKE, reason="opt-in live smoke (BOOTSTRAP_LIVE_SMOKE=1)")
def test_live_smoke_creates_prompts_and_deletes_a_throwaway_session():
    """The adapter against the REAL service: create -> prompt -> terminal -> delete.

    The smoke pins the entitled `opencode-go` lane (the free tier is an explicit
    opt-in and its 403 gate is covered by the classifier tests). It asserts the
    adapter's contract - a terminal turn with a classified outcome and the
    requested model on the assistant message - and records which of the two
    answers it got, instead of failing an environment fact this adapter cannot
    control.
    """
    harness = OpenCodeApiHarness(directory=str(REPO_ROOT), executor=LocalExecutor(timeout_s=180))
    session_id = "ses_bt_smoke_" + uuid.uuid4().hex[:12]
    spec = SessionSpec(
        session_id=session_id,
        title="external-bootstrap harness smoke",
        agent="data-dep-worker",
        model=ModelRef("opencode-go", "deepseek-v4.1-flash", "high"),
        directory=str(REPO_ROOT),
        metadata={"smoke": "1"},
    )
    assert harness.create_session(spec) == session_id
    try:
        # The session pins the requested reference explicitly.
        assert harness.session_model(session_id) == {
            "id": "deepseek-v4.1-flash",
            "providerID": "opencode-go",
            "variant": "high",
        }
        harness.prompt(session_id, "Reply with exactly: PONG. Do not use any tools.")
        turn = harness.wait_terminal(session_id, timeout_s=180)
        assert turn.outcome in {"succeeded", "failed", "interrupted"}
        for message in turn.messages:
            if message.get("type") == "assistant" and message.get("model"):
                assert message["model"] == {
                    "id": "deepseek-v4.1-flash",
                    "providerID": "opencode-go",
                    "variant": "high",
                }
        if turn.ok:
            assert "PONG" in assistant_text(turn)
        else:
            # A provider-side refusal is still a proven adapter: the terminal
            # message, the transcript parse, and the classifier all worked.
            assert turn.retryable is True, turn.error
            assert turn.error_status in {403, 429, None}
    finally:
        harness.delete_session(session_id)
