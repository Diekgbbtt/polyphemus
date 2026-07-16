"""Autonomous credentialed-login wiring: `steel_await_auth` is orphaned from the
autonomous / anonymous agentic loop, and the shared crawl skill no longer tells
the agent a human will log in.

Background (root cause of the peoplecert about:blank run): the credentialed D23
agent received BOTH the autonomous "log in yourself with these credentials"
user message AND a skill that described a HUMAN logging in via
`steel_await_auth`. It also had `steel_await_auth` bound as a callable tool.
Either could make the autonomous agent block on a human that never arrives.

These tests pin the minimal decoupling:
  * the autonomous (credentials) and anonymous paths do NOT bind
    `steel_await_auth` - calling it degrades to an "unknown tool" no-op, the
    tool is never invoked;
  * the interactive pre-created path STILL binds it (parked, not deleted);
  * the skill prompt carries no human-login / "you never handle credentials"
    contradiction, only the autonomous credentialed guidance.

Fully mocked - no live Steel/LLM (mirrors test_crawl_agent.py's fakes).
"""
import asyncio

from agent.recon.crawl import crawl_agent


class _AIMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _ScriptedLLM:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return _AIMessage(self.script.pop(0) if self.script else [])


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
        {"method": "GET", "url": "https://x.com/account", "query": [], "body": [], "status": 200},
    ],
    "js_urls": [],
}


def _toolset(record):
    return [
        _FakeTool("steel_crawl_start", {"crawl_id": "c1", "frontier": []}, record=record),
        _FakeTool("steel_navigate", {"new_links": [], "network_delta": []}, record=record),
        _FakeTool("steel_await_auth", {"authenticated": True}, record=record),
        _FakeTool("steel_crawl_finish", CANNED_MANIFEST, record=record),
    ]


def test_autonomous_credentialed_crawl_does_not_bind_await_auth():
    # The credentialed agent tries steel_await_auth first (as the old skill
    # would have nudged it to). It must NOT be bound: the call degrades to an
    # "unknown tool" no-op, the tool is never invoked, and the loop proceeds.
    record: list[str] = []
    llm = _ScriptedLLM(
        [
            [{"name": "steel_await_auth", "args": {"crawl_id": "c1"}, "id": "1"}],
            [{"name": "steel_crawl_finish", "args": {}, "id": "2"}],
        ]
    )

    result = asyncio.run(
        crawl_agent.run_crawl_credentialed(
            "https://x.com",
            scope=["x.com"],
            credentials={"username": "u", "password": "pw", "login_url": "https://login.x.com/"},
            tools=_toolset(record),
            llm=llm,
            max_iters=10,
        )
    )

    assert "steel_await_auth" not in record
    assert result == CANNED_MANIFEST


def test_anonymous_crawl_does_not_bind_await_auth():
    record: list[str] = []
    llm = _ScriptedLLM(
        [
            [{"name": "steel_await_auth", "args": {"crawl_id": "c1"}, "id": "1"}],
            [{"name": "steel_crawl_finish", "args": {}, "id": "2"}],
        ]
    )

    result = asyncio.run(
        crawl_agent.run_crawl(
            "https://x.com",
            scope=["x.com"],
            tools=_toolset(record),
            llm=llm,
            max_iters=10,
        )
    )

    assert "steel_await_auth" not in record
    assert result == CANNED_MANIFEST


def test_interactive_pre_created_path_still_binds_await_auth():
    # Guard against over-orphaning: the parked interactive path still needs the
    # tool bound so it can detect a human login.
    record: list[str] = []
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
            tools=_toolset(record),
            llm=llm,
            max_iters=10,
            pre_created_crawl_id="pre1",
        )
    )

    assert record[0] == "steel_await_auth"
    assert result == CANNED_MANIFEST


def test_skill_prompt_has_no_human_login_contradiction():
    text = crawl_agent._load_skill()
    lowered = text.lower()
    # No human-in-the-viewer login guidance that would contradict autonomous login.
    assert "a human operator is logging in" not in lowered
    assert "you never handle credentials yourself" not in lowered
    assert "steel_await_auth" not in text
    # The autonomous credentialed-login guidance remains the single auth authority.
    assert "Credentialed login (autonomous)" in text
    assert "authenticate\nyourself" in lowered or "authenticate yourself" in lowered
