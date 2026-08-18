"""TDD for the agentic-crawl adapter (`src/polymerhus/recon/crawl/crawl_agent.py`).

Fully mocked: no live Steel MCP client, no live LLM. The fake `llm`/`tools`
mirror the exact interface the vendored `crawl_agentic._run_agentic_crawl`
loop calls:

  * `llm.bind_tools(tools)` -> an object with `async def ainvoke(messages)`
    returning an "AI message" that exposes a `.tool_calls` list of
    `{"name": str, "args": dict, "id": str}` dicts (langchain's tool-call
    shape).
  * each tool exposes `.name` and `async def ainvoke(args) -> dict` (the
    loop normalizes dict/str/content-block-list results via
    `_payload_from_tool_result`; returning a bare dict is the simplest
    faithful fake).
"""
import asyncio

import pytest

from polymerhus.recon.crawl import crawl_agent


class _AIMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _ScriptedLLM:
    """Fake chat model: `bind_tools` returns self; `ainvoke` pops the next
    scripted tool-call batch from `script` on each call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.script:
            tool_calls = self.script.pop(0)
        else:
            tool_calls = []
        return _AIMessage(tool_calls)


class _LoopingLLM:
    """Fake chat model that always re-emits the same tool-call, never finishing."""

    def __init__(self, tool_call):
        self._tool_call = tool_call
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return _AIMessage([self._tool_call])


class _FakeTool:
    def __init__(self, name, result=None, record=None):
        self.name = name
        self._result = result if result is not None else {}
        self._record = record

    async def ainvoke(self, args):
        if self._record is not None:
            self._record.append(self.name)
        return self._result


CANNED_MANIFEST = {
    "endpoints": [
        {"method": "GET", "url": "https://x.com/api/v1/items", "query": ["id"], "body": [], "status": 200},
    ],
    "js_urls": ["https://x.com/static/app.js"],
}


def test_run_crawl_returns_finish_manifest_on_scripted_sequence():
    calls_log: list[str] = []
    tools = [
        _FakeTool("steel_crawl_start", {"crawl_id": "c1"}, record=calls_log),
        _FakeTool("steel_navigate", {"new_links": [], "network_delta": []}, record=calls_log),
        _FakeTool("steel_crawl_finish", CANNED_MANIFEST, record=calls_log),
    ]
    llm = _ScriptedLLM(
        [
            [{"name": "steel_crawl_start", "args": {}, "id": "1"}],
            [{"name": "steel_navigate", "args": {}, "id": "2"}],
            [{"name": "steel_crawl_finish", "args": {}, "id": "3"}],
        ]
    )

    result = asyncio.run(
        crawl_agent.run_crawl(
            "https://x.com",
            scope=["x.com"],
            tools=tools,
            llm=llm,
            max_iters=10,
        )
    )

    assert result == CANNED_MANIFEST
    assert calls_log == ["steel_crawl_start", "steel_navigate", "steel_crawl_finish"]


def test_run_crawl_bounded_by_max_iters_when_never_finishing():
    tools = [
        _FakeTool("steel_navigate", {"new_links": [], "network_delta": []}),
    ]
    llm = _LoopingLLM({"name": "steel_navigate", "args": {}, "id": "n"})

    result = asyncio.run(
        crawl_agent.run_crawl(
            "https://x.com",
            scope=["x.com"],
            tools=tools,
            llm=llm,
            max_iters=3,
        )
    )

    # Loop terminates (no hang) and, since steel_crawl_start/finish were
    # never invoked, drains to the empty manifest rather than fabricating one.
    assert result == {"endpoints": [], "js_urls": []}
    assert llm.calls == 3


def test_run_crawl_with_pre_created_crawl_id_drives_await_auth_first():
    calls_log: list[str] = []
    # Deliberately omit steel_crawl_start from the toolset: if the loop tried
    # to call it, `by_name.get("steel_crawl_start")` -> None -> "unknown tool"
    # ToolMessage, not a crash - but we assert on calls_log to be explicit.
    tools = [
        _FakeTool("steel_await_auth", {"authenticated": True}, record=calls_log),
        _FakeTool("steel_crawl_finish", CANNED_MANIFEST, record=calls_log),
    ]
    llm = _ScriptedLLM(
        [
            [{"name": "steel_await_auth", "args": {"crawl_id": "pre1"}, "id": "1"}],
            [{"name": "steel_crawl_finish", "args": {}, "id": "2"}],
        ]
    )

    result = asyncio.run(
        crawl_agent.run_crawl(
            "https://x.com",
            scope=["x.com"],
            tools=tools,
            llm=llm,
            max_iters=10,
            pre_created_crawl_id="pre1",
        )
    )

    assert result == CANNED_MANIFEST
    assert calls_log[0] == "steel_await_auth"
    assert "steel_crawl_start" not in calls_log


def test_load_skill_reads_file_next_to_module():
    text = crawl_agent._load_skill()
    assert "Steel Agentic Crawl" in text
    assert "steel_crawl_finish" in text


def test_skill_has_fresh_session_rotation_hard_rule():
    text = crawl_agent._load_skill()
    lower = text.lower()
    # The rotation guidance must be promoted to a top-level hard rule.
    hard_rules_idx = lower.index("## hard rules")
    hard_rules = lower[hard_rules_idx:]
    assert "fresh session" in hard_rules
    assert "steel_crawl_start" in hard_rules
    assert "rotat" in hard_rules
    # It must explicitly cover the login page and the 3-session cap.
    assert "login" in hard_rules
    assert "3" in hard_rules


def test_run_crawl_forwards_auth_cookies_to_get_crawl_tools(monkeypatch):
    # When tools are NOT injected, run_crawl builds them via
    # steel_client.get_crawl_tools and must forward auth_cookies so the default
    # provider seeds the browser context for non-interactive auth.
    from polymerhus.recon.crawl import steel_client

    seen = {}

    async def fake_get_crawl_tools(*, client_factory=None, auth_cookies=None):
        seen["auth_cookies"] = auth_cookies
        return []

    async def fake_run_agentic(body, mcp_manager, build_llm_fn=None, pre_created_crawl_id=None):
        return {"endpoints": [], "js_urls": []}

    monkeypatch.setattr(steel_client, "get_crawl_tools", fake_get_crawl_tools)
    monkeypatch.setattr(crawl_agent, "_run_agentic_crawl", fake_run_agentic)

    asyncio.run(crawl_agent.run_crawl(
        "https://t.example", scope=["https://t.example"], llm=object(),
        auth_cookies=[{"name": "a", "value": "b"}],
    ))
    assert seen["auth_cookies"] == [{"name": "a", "value": "b"}]


def test_credentialed_login_prompt_names_login_url_and_submit_once():
    import asyncio
    from polymerhus.recon.crawl import crawl_agentic

    captured = {}

    class FakeLLM:
        def bind_tools(self, tools): return self
        async def ainvoke(self, messages):
            captured["messages"] = messages
            from langchain_core.messages import AIMessage
            return AIMessage(content="", tool_calls=[])  # no tools -> loop ends fast

    class FakeMgr:
        async def get_tools(self): return []

    body = crawl_agentic.AgenticCrawlRequest(
        target="https://app.example.com", scope=["example.com"], model="crawler",
        max_iterations=1,
        credentials={"username": "u", "password": "pw", "login_url": "https://login.example.com/"},
    )
    asyncio.run(crawl_agentic._run_agentic_crawl(body, FakeMgr(), build_llm_fn=lambda m, u: FakeLLM()))

    text = captured["messages"][1].content  # the HumanMessage
    assert "https://login.example.com/" in text
    assert "credentials" in text.lower()
    assert "u" in text
    assert "once" in text.lower()


def test_credentialed_login_prompt_routes_captcha_to_fresh_session_rotation():
    import asyncio
    from polymerhus.recon.crawl import crawl_agentic

    captured = {}

    class FakeLLM:
        def bind_tools(self, tools): return self
        async def ainvoke(self, messages):
            captured["messages"] = messages
            from langchain_core.messages import AIMessage
            return AIMessage(content="", tool_calls=[])  # no tools -> loop ends fast

    class FakeMgr:
        async def get_tools(self): return []

    body = crawl_agentic.AgenticCrawlRequest(
        target="https://app.example.com", scope=["example.com"], model="crawler",
        max_iterations=1,
        credentials={"username": "u", "password": "pw", "login_url": "https://login.example.com/"},
    )
    asyncio.run(crawl_agentic._run_agentic_crawl(body, FakeMgr(), build_llm_fn=lambda m, u: FakeLLM()))

    text = captured["messages"][1].content  # the HumanMessage
    lower = text.lower()
    # (a) A page-load / bot-wall captcha or 403 must route to a FRESH-session
    #     rotation, not an immediate finish.
    assert "fresh session" in lower or "steel_crawl_start" in text
    assert "rotat" in lower
    assert "new ip" in lower
    # (b) The BLOCKED-and-finish path is still reserved for genuine auth blocks.
    assert "blocked" in lower
    assert "sso" in lower or "oauth" in lower
    assert "second factor" in lower or "one-time" in lower
    # captcha is no longer in the immediate-finish list; the finish path is for
    # SSO/OAuth / 2FA / no login form only.


def test_credentialed_login_prompt_interpolates_password_value():
    import asyncio
    from polymerhus.recon.crawl import crawl_agentic

    captured = {}

    class FakeLLM:
        def bind_tools(self, tools): return self
        async def ainvoke(self, messages):
            captured["messages"] = messages
            from langchain_core.messages import AIMessage
            return AIMessage(content="", tool_calls=[])  # no tools -> loop ends fast

    class FakeMgr:
        async def get_tools(self): return []

    body = crawl_agentic.AgenticCrawlRequest(
        target="https://app.example.com", scope=["example.com"], model="crawler",
        max_iterations=1,
        credentials={"username": "u", "password": "S3ntinelPw!", "login_url": "https://login.example.com/"},
    )
    asyncio.run(crawl_agentic._run_agentic_crawl(body, FakeMgr(), build_llm_fn=lambda m, u: FakeLLM()))

    text = captured["messages"][1].content  # the HumanMessage
    assert "S3ntinelPw!" in text


def test_run_crawl_credentialed_threads_credentials_into_request(monkeypatch):
    import asyncio
    from polymerhus.recon.crawl import crawl_agent

    seen = {}

    async def fake_run_agentic(body, mcp_manager, *, build_llm_fn=None, pre_created_crawl_id=None):
        seen["credentials"] = body.credentials
        seen["target"] = body.target
        return {"endpoints": [{"url": "https://app.example.com/account"}], "js_urls": []}

    monkeypatch.setattr(crawl_agent, "_run_agentic_crawl", fake_run_agentic)

    manifest = asyncio.run(crawl_agent.run_crawl_credentialed(
        "https://app.example.com", scope=["example.com"],
        credentials={"username": "u", "password": "pw", "login_url": "https://login.example.com/"},
        tools=[], llm=object(),
    ))
    assert seen["credentials"]["username"] == "u"
    assert manifest["endpoints"][0]["url"].endswith("/account")


def test_run_crawl_credentialed_best_effort_on_error(monkeypatch):
    import asyncio
    from polymerhus.recon.crawl import crawl_agent

    async def boom(*a, **k): raise RuntimeError("steel down")
    monkeypatch.setattr(crawl_agent, "_run_agentic_crawl", boom)

    manifest = asyncio.run(crawl_agent.run_crawl_credentialed(
        "https://app.example.com", scope=["example.com"],
        credentials={"username": "u", "password": "pw", "login_url": "https://l"}, tools=[], llm=object()))
    assert manifest == {"endpoints": [], "js_urls": []}
