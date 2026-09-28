"""Protocol tests for the deterministic LLM fixture after the Configurator split."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from polymerhus.recon.control import configurator as C
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.domain.pod import _ObservationBatch

from tests.e2e import deterministic_llm_provider as provider

GATEWAY_TOOL_NAMES = [
    "auth_store", "load_skill", "write_skill", "execute_command", "steel_exec",
    "GatewayVerdict",
]
CONFIGURATOR_TOOL_NAMES = [
    "load_skill", "rate_limit_posture", "ConfiguratorDecision",
]
TRIAGER_TOOL_NAMES = ["load_skill", "_ObservationBatch"]


def _tools(names):
    return [{"type": "function", "function": {
        "name": name, "description": name, "parameters": {"type": "object"},
    }} for name in names]


def _request(messages, *, tools=GATEWAY_TOOL_NAMES, stream=False):
    return {
        "model": provider.REGISTERED_MODEL,
        "messages": messages,
        "tools": _tools(tools),
        "tool_choice": "required",
        "stream": stream,
        "temperature": 0.0,
        "max_completion_tokens": 131072,
    }


def _system(text="SYS"):
    return {"role": "system", "content": text}


def _gateway_human(candidate="alice", directive="request", project_id="p1"):
    selection = (
        f"Candidate account (most recently updated usable): {candidate}."
        if candidate else
        "No usable account on record: mint one through the sign-in procedure."
    )
    return {"role": "user", "content": (
        f"Auth gateway for project {project_id}.\n\n"
        f"Branch directive: {directive}.\n\n{selection}\n\n"
        "Ground (overview read + authn skill load), validate before sign-in, "
        "assert the outcome in the store, run the outer skill-judging loop, "
        "then emit the GatewayVerdict."
    )}


def _configurator_human(phase=3, target_key="t.com"):
    prepared = {
        "httpx": [{"input_asset": {"name": "app.t.com"}, "extra": {}}],
        "ffuf": [{"input_asset": {"url": "https://app.t.com"}, "extra": {}}],
        "steel_crawl": [{"input_asset": {"url": "https://app.t.com"}, "extra": {}}],
    }
    offers = C.offer_phase_inputs(phase, target_key, prepared, jobs=JOBS)
    return {"role": "user", "content": C._offer_message(offers)}


def _triager_human(tool="ffuf"):
    return {"role": "user", "content": (
        f"Tool: {tool}\nCommand stdout:\n/index.php\n"
        "Parsed assets (1 total): []\n"
        "Identify any noteworthy security observations."
    )}


def _assistant_tool_call(call_id, name, arguments):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": name, "arguments": arguments}},
    ]}


def _tool_result(call_id, payload):
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return {"role": "tool", "tool_call_id": call_id, "content": content}


AUTH_OVERVIEW = {"ok": True, "command": "read", "path": "overview",
                 "value": {"target": "t.com", "http-client-replayability": True}}
AUTH_ACCOUNTS = {"ok": True, "command": "read", "path": "accounts",
                 "value": {"accounts": {"alice": {"status": "valid"}}}}
AUTH_WRITE_OK = {"ok": True, "command": "write"}
EXEC_OK = {"returncode": 0, "stdout": "auth-gateway-validated\n", "stderr": ""}
SKILL_BODY = "# authn\nSign in and prove the session.\n"
SKILL_WRITE_OK = {"ok": True, "skill": "authn"}


def _posture_result(safe_rate: float, *, status: str = "known_target") -> dict:
    if status != "known_target":
        return {"ok": status != "unreadable", "status": status}
    return {
        "ok": True,
        "status": "known_target",
        "posture": {
            "target_key": "t.com",
            "outcome": "mapped",
            "safe_rate_per_s": safe_rate,
            "burst": 1,
            "max_concurrency": 1,
            "host_patterns": ["t.com"],
            "measured_at": "2026-09-28T00:00:00+00:00",
            "expires_at": "2099-09-28T00:00:00+00:00",
            "fresh": True,
            "source_run_id": "r1",
            "advisory": True,
        },
    }


def _tool_result_for(name, args, *, posture):
    if name == "auth_store":
        if args.get("command") == "write":
            return AUTH_WRITE_OK
        return AUTH_ACCOUNTS if args.get("path") == "accounts" else AUTH_OVERVIEW
    if name == "load_skill":
        return SKILL_BODY
    if name == "write_skill":
        return SKILL_WRITE_OK
    if name in ("execute_command", "steel_exec"):
        return EXEC_OK
    if name == "rate_limit_posture":
        assert args["command"] == "resolve"
        return posture
    raise AssertionError(f"unexpected tool call from the fixture: {name}")


def _drive(request, *, posture=None, max_rounds=16):
    messages = list(request["messages"])
    envelopes = []
    for round_index in range(max_rounds):
        status, body = provider.completion(
            {**request, "messages": messages}, sequence=round_index
        )
        assert status == 200, body
        message = body["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return envelopes, message
        assert len(calls) == 1
        call = calls[0]
        name = call["function"]["name"]
        args = json.loads(call["function"]["arguments"])
        envelopes.append((name, args))
        if name in provider.TERMINAL_TOOLS:
            return envelopes, message
        messages.append(message)
        messages.append(_tool_result(
            call["id"],
            _tool_result_for(name, args, posture=posture or _posture_result(10.0)),
        ))
    raise AssertionError(f"the fixture did not close: {envelopes}")


def _final_envelope(envelopes, name):
    matching = [args for tool, args in envelopes if tool == name]
    assert matching, f"no {name} envelope in {[t for t, _ in envelopes]}"
    return matching[-1]


# --- gateway ---------------------------------------------------------------------


def test_gateway_turn_grounds_then_closes_on_a_valid_gateway_verdict():
    envelopes, _ = _drive(_request([_system(), _gateway_human()]))
    tools = [name for name, _ in envelopes]
    assert tools[0] == "auth_store"
    assert "load_skill" in tools
    assert "execute_command" in tools
    assert tools[-1] == "GatewayVerdict"
    assert "map_rate_limit" not in tools
    assert "RateLoopVerdict" not in tools

    verdict = GatewayVerdict.model_validate(
        _final_envelope(envelopes, "GatewayVerdict"))
    assert (verdict.outcome, verdict.account, verdict.branch) == (
        "authenticated", "alice", "request")


def test_browser_only_directive_is_carried_into_the_verdict_branch():
    envelopes, _ = _drive(
        _request([_system(), _gateway_human(directive="browser_only")]))
    verdict = GatewayVerdict.model_validate(
        _final_envelope(envelopes, "GatewayVerdict"))
    assert verdict.branch == "browser_only"


# --- Configurator ----------------------------------------------------------------


@pytest.mark.parametrize("safe_rate", [10.0, 1.0])
def test_configurator_reads_posture_before_emitting_a_valid_decision(safe_rate):
    envelopes, _ = _drive(
        _request([_system(), _configurator_human()],
                 tools=CONFIGURATOR_TOOL_NAMES),
        posture=_posture_result(safe_rate),
    )
    tools = [name for name, _ in envelopes]
    assert tools[0] == "rate_limit_posture"
    assert tools[-1] == "ConfiguratorDecision"
    assert "map_rate_limit" not in tools
    assert "RateLoopVerdict" not in tools

    decision = C.ConfiguratorDecision.model_validate(
        _final_envelope(envelopes, "ConfiguratorDecision"))
    assert decision.phase == 3
    assert decision.target_key == "t.com"
    assert decision.posture_status == "known_target"
    assert any(pod.job_name == "httpx" for pod in decision.pods)


def test_high_and_low_posture_produce_different_configurator_plans():
    high, _ = _drive(
        _request([_system(), _configurator_human()],
                 tools=CONFIGURATOR_TOOL_NAMES),
        posture=_posture_result(10.0),
    )
    low, _ = _drive(
        _request([_system(), _configurator_human()],
                 tools=CONFIGURATOR_TOOL_NAMES),
        posture=_posture_result(1.0),
    )
    high_decision = C.ConfiguratorDecision.model_validate(
        _final_envelope(high, "ConfiguratorDecision"))
    low_decision = C.ConfiguratorDecision.model_validate(
        _final_envelope(low, "ConfiguratorDecision"))

    assert {pod.job_name for pod in high_decision.pods} != {
        pod.job_name for pod in low_decision.pods
    }
    assert "ffuf" in {pod.job_name for pod in high_decision.pods}
    assert "ffuf" not in {pod.job_name for pod in low_decision.pods}


def test_unreadable_posture_omits_target_facing_pods():
    envelopes, _ = _drive(
        _request([_system(), _configurator_human()],
                 tools=CONFIGURATOR_TOOL_NAMES),
        posture=_posture_result(1.0, status="unreadable"),
    )
    decision = C.ConfiguratorDecision.model_validate(
        _final_envelope(envelopes, "ConfiguratorDecision"))
    assert decision.posture_status == "unreadable"
    assert decision.pods == []


def test_agentic_offer_uses_command_none():
    envelopes, _ = _drive(
        _request([_system(), _configurator_human()],
                 tools=CONFIGURATOR_TOOL_NAMES),
        posture=_posture_result(10.0),
    )
    decision = C.ConfiguratorDecision.model_validate(
        _final_envelope(envelopes, "ConfiguratorDecision"))
    steel = [pod for pod in decision.pods if pod.job_name == "steel_crawl"]
    assert steel and steel[0].command is None


# --- triager ---------------------------------------------------------------------


def test_triager_turn_returns_an_empty_observation_batch():
    envelopes, final = _drive(
        _request([_system("writing-observations"), _triager_human()],
                 tools=TRIAGER_TOOL_NAMES))
    assert [name for name, _ in envelopes] == ["_ObservationBatch"]
    batch = _ObservationBatch.model_validate(envelopes[0][1])
    assert batch.observations == []
    assert final["content"] in (None, "") or isinstance(final["content"], str)


# --- determinism, authority, and the loud unknown state -------------------------


def _semantic(body):
    stripped = json.loads(json.dumps(body))
    stripped.pop("id", None)
    for choice in stripped.get("choices", []):
        for call in choice.get("message", {}).get("tool_calls") or []:
            call.pop("id", None)
    return json.dumps(stripped, sort_keys=True)


@pytest.mark.parametrize("messages,tools", [
    ([_system(), _gateway_human()], GATEWAY_TOOL_NAMES),
    ([_system(), _configurator_human()], CONFIGURATOR_TOOL_NAMES),
    ([_system("writing-observations"), _triager_human()], TRIAGER_TOOL_NAMES),
])
def test_identical_inputs_produce_semantically_identical_output(messages, tools):
    request = _request(messages, tools=tools)
    first = provider.completion(request)
    second = provider.completion(request)
    assert first[0] == second[0] == 200
    assert _semantic(first[1]) == _semantic(second[1])


def test_unknown_state_is_a_diagnostic_422_without_message_content():
    secret = "Bearer super-secret-token"
    messages = [_system(), {"role": "user", "content": secret}]
    status, body = provider.completion(_request(messages))
    assert status == 422
    diagnostic = body["error"]["diagnostic"]
    assert diagnostic["roles"] == ["system", "user"]
    assert diagnostic["observed_tools"] == []
    assert secret not in json.dumps(body)


def test_an_unknown_model_is_refused_loudly():
    request = _request([_system(), _gateway_human()])
    request["model"] = "openai/some-other-model"
    status, body = provider.completion(request)
    assert status == 422
    assert body["error"]["diagnostic"]["model"] == "openai/some-other-model"


# --- HTTP surface ----------------------------------------------------------------


@pytest.fixture()
def server():
    httpd = provider.create_server(port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, json.loads(response.read().decode())


def test_health_reports_the_registered_model_and_the_request_counters(server):
    status, body = _get(f"{server}/health")
    assert status == 200
    assert body["models"] == [provider.REGISTERED_MODEL]
    assert body["requests"] == 0


def test_chat_completions_serves_the_plain_and_streaming_transports(server):
    status, body = _post(
        f"{server}/v1/chat/completions",
        _request([_system(), _gateway_human()]),
    )
    assert status == 200
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "auth_store"

    request = urllib.request.Request(
        f"{server}/v1/chat/completions",
        data=json.dumps(_request([_system(), _gateway_human()], stream=True)).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = response.read().decode()
    assert payload.rstrip().endswith("data: [DONE]")


def test_an_unknown_path_is_a_loud_404(server):
    try:
        _get(f"{server}/v1/models")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:  # pragma: no cover
        raise AssertionError("/v1/models must not be served")
