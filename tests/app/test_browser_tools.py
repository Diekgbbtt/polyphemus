"""Unit tier: the one agent-facing browser tool and its key helpers.

The MCP client is faked at the call boundary. The tool contract, the
session/context key rules, the fail-open behaviour, and the CDP-field strip
are asserted without a pool or a worker.
"""
from __future__ import annotations

import json
import re

import pytest

from polymerhus.app.llm.browser_client import BrowserMcpError, BrowserStart
from polymerhus.app.llm.browser_tools import (
    BROWSER_TOOL_DESCRIPTION,
    BROWSER_TOOL_NAME,
    BrowserArgs,
    BrowserTool,
    browser_context_ref,
    browser_session_name,
    build_browser_tool,
    resolve_browser_context_ref,
)


class FakeClient:
    def __init__(self, *, start_error=None, exec_error=None, end_error=None):
        self.start_error = start_error
        self.exec_error = exec_error
        self.end_error = end_error
        self.calls: list[tuple] = []
        self.closed = False

    def start(self, name, *, url=None, context_ref=None):
        self.calls.append(("start", name, url, context_ref))
        if self.start_error is not None:
            raise self.start_error
        return BrowserStart(
            name=name,
            session_id="steel-1",
            restored={"cookies": 2, "origins": 1, "storage_keys": 3, "warnings": []},
            warnings=(),
            remaining_ms=900_000,
            context_ref=context_ref,
        )

    def exec(self, command):
        self.calls.append(("exec", command))
        if self.exec_error is not None:
            raise self.exec_error
        return {"success": True, "data": {"title": "app"}}

    def end(self, *, persist_context=False):
        self.calls.append(("end", persist_context))
        if self.end_error is not None:
            raise self.end_error
        return {
            "success": True,
            "ended": True,
            "captured": True,
            "saved": True,
            "stopped": True,
            "released": None,
            "context_saved": bool(persist_context),
        }

    def close(self):
        self.closed = True


def _tool(client=None, *, account=None, record_fn=None):
    return BrowserTool(
        client=client,
        session_name_factory=lambda account_name: browser_session_name(
            "proj-1", "hunter", "hunt-1", account_name or account
        ),
        context_ref_resolver=lambda account_name: (
            browser_context_ref("proj-1", account_name or account)
            if (account_name or account)
            else None
        ),
        bound_account=account,
        record_fn=record_fn,
    )


def test_the_surface_is_one_tool_with_three_commands():
    assert BROWSER_TOOL_NAME == "browser"
    schema = BrowserArgs.model_json_schema()
    assert schema["properties"]["command"]["enum"] == ["start", "exec", "end"]
    assert "name" not in schema["properties"]
    assert "session" not in schema["properties"]


def test_the_tool_description_carries_the_usage_contract():
    text = BROWSER_TOOL_DESCRIPTION
    assert "client-side rendered page" in text
    assert "JS-heavy" in text
    assert "native client-side primitive" in text
    assert "url is optional" in text
    assert "first `exec` must be a `navigate`" in text
    assert "session name is internal" in text
    assert "End the session when the browser is not needed anymore" in text
    assert "persist_context" in text
    assert "browser_unavailable" in text
    assert "steel-browser" in text


def test_the_context_ref_is_stable_and_independent_of_the_session_name():
    first = browser_context_ref("proj-1", "alice")
    second = browser_context_ref("proj-1", "alice")
    assert first == second
    assert first.startswith("steel-auth-proj-1-alice")
    assert browser_session_name("proj-1", "hunter", "hunt-1", "alice") != first


def test_the_session_name_binds_project_account_role_and_instance():
    assert browser_session_name("proj-1", "hunter", "hunt-1", "alice") == (
        "steel-proj-1-alice-hunter-hunt-1"
    )
    assert browser_session_name("proj-1", "hunter", "hunt-1") == (
        "steel-proj-1-hunter-hunt-1"
    )


def test_the_session_name_is_safe_and_bounded():
    name = browser_session_name("My Project/One", "agent role", "a" * 200, "A B")
    assert len(name) <= 128
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name)
    assert name == browser_session_name(
        "My Project/One", "agent role", "a" * 200, "A B"
    )


def test_start_binds_the_session_name_and_context_and_hides_the_cdp_endpoint():
    client = FakeClient()
    tool = _tool(client, account="alice")

    result = json.loads(
        tool._run("start", url="https://app.test", account="alice")
    )

    assert result["success"] is True
    assert result["session"]["name"] == "steel-proj-1-alice-hunter-hunt-1"
    assert result["context_ref"] == "steel-auth-proj-1-alice"
    assert "cdp_url" not in result
    assert "cdp_host" not in result
    assert client.calls[0] == (
        "start",
        "steel-proj-1-alice-hunter-hunt-1",
        "https://app.test",
        "steel-auth-proj-1-alice",
    )


def test_url_is_optional_at_start():
    client = FakeClient()
    tool = _tool(client)

    result = json.loads(tool._run("start"))

    assert result["success"] is True
    assert client.calls[0] == (
        "start",
        "steel-proj-1-hunter-hunt-1",
        None,
        None,
    )


def test_exec_requires_a_started_session():
    tool = _tool(FakeClient())

    result = json.loads(tool._run("exec", input="snapshot -i"))

    assert result["success"] is False
    assert result["error"]["code"] == "no_session"


def test_exec_passes_the_bare_command_grammar():
    client = FakeClient()
    tool = _tool(client)
    tool._run("start")

    result = json.loads(tool._run("exec", input="fill '#user' -- alice"))

    assert result["success"] is True
    assert client.calls[-1] == ("exec", "fill '#user' -- alice")


def test_end_is_idempotent_and_reports_the_context_save():
    client = FakeClient()
    tool = _tool(client)
    tool._run("start")

    result = json.loads(tool._run("end", persist_context=True))

    assert result["success"] is True
    assert result["context_saved"] is True
    second = json.loads(tool._run("end"))
    assert second == {"success": True, "ended": False, "reason": "no_session"}


def test_an_unconfigured_pool_is_a_fail_open_tool():
    tool = build_browser_tool(
        project_id="proj-1",
        role="hunter",
        instance_id="hunt-1",
        mcp_url="",
    )

    result = json.loads(tool._run("start"))

    assert result["success"] is False
    assert result["error"]["code"] == "browser_unavailable"
    assert result["error"]["retryable"] is False


def test_a_typed_mcp_error_keeps_its_code_and_retryability():
    client = FakeClient(
        start_error=BrowserMcpError(
            "no worker", code="pool_exhausted", retryable=True
        )
    )
    tool = _tool(client)

    result = json.loads(tool._run("start"))

    assert result["success"] is False
    assert result["error"]["code"] == "pool_exhausted"
    assert result["error"]["retryable"] is True


def test_a_session_loss_on_exec_resets_the_started_state():
    client = FakeClient(
        exec_error=BrowserMcpError(
            "gone", code="no_session", retryable=False
        )
    )
    tool = _tool(client)
    tool._run("start")

    result = json.loads(tool._run("exec", input="snapshot -i"))

    assert result["success"] is False
    assert result["error"]["code"] == "no_session"
    second = json.loads(tool._run("exec", input="snapshot -i"))
    assert second["error"]["code"] == "no_session"
    assert client.calls.count(("exec", "snapshot -i")) == 1


def test_every_command_is_recorded_with_its_result():
    seen: list[tuple] = []
    tool = _tool(
        FakeClient(),
        record_fn=lambda args, result: seen.append((dict(args), dict(result))),
    )
    tool._run("start")
    tool._run("exec", input="snapshot -i")
    tool._run("end")

    assert [entry[0]["command"] for entry in seen] == ["start", "exec", "end"]
    assert all("success" in entry[1] for entry in seen)


def test_close_is_idempotent():
    client = FakeClient()
    tool = _tool(client)

    tool.close()
    tool.close()

    assert client.closed is True


class _Store:
    def __init__(self, value):
        self.value = value
        self.calls: list[str] = []

    def read(self, project_id, path):
        self.calls.append(path)
        return self.value


def test_the_context_ref_reads_the_auth_store_reference():
    store = _Store({"ref": "steel-auth-proj-1-alice"})

    assert resolve_browser_context_ref("proj-1", "alice", store=store) == (
        "steel-auth-proj-1-alice"
    )
    assert store.calls == ["accounts.alice.browser_context"]


def test_the_context_ref_is_deterministic_without_a_stored_reference():
    assert resolve_browser_context_ref(
        "proj-1", "alice", store=_Store(None)
    ) == "steel-auth-proj-1-alice"


@pytest.mark.parametrize(
    "value",
    [None, {}, {"ref": ""}, {"ref": "../bad"}, {"other": "x"}],
)
def test_an_invalid_stored_reference_degrades_to_the_deterministic_one(value):
    assert resolve_browser_context_ref(
        "proj-1", "alice", store=_Store(value)
    ) == "steel-auth-proj-1-alice"


def test_strip_cdp_fields_filters_mappings_lists_and_json_strings():
    payload = {
        "success": True,
        "cdp_url": "ws://172.20.0.5:3000/",
        "cdp_host": "localhost:3000",
        "nested": [{"cdp_url": "ws://x/", "keep": 1}],
    }

    from polymerhus.app.llm.browser_tools import strip_cdp_fields

    stripped = strip_cdp_fields(payload)
    assert "cdp_url" not in stripped
    assert "cdp_host" not in stripped
    assert stripped["nested"] == [{"keep": 1}]
    text = strip_cdp_fields(json.dumps(payload))
    assert "cdp_url" not in text
    assert '"success": true' in text
