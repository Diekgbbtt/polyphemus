"""#238 follow-up, Task 9 - the deterministic local model provider's protocol.

The functional E2E must drive the REAL actor loop, so model inference is
replaced by a local OpenAI-compatible fixture (`deterministic_llm_provider.py`)
that answers deterministically from the conversation state. These tests pin the
protocol the fixture speaks:

* the exact wire shape the production client emits (captured from
  `polymerhus.app.llm.providers.build_chat_model` - `stream`, `tools`,
  `tool_choice: required`, `provider/model` ids);
* the exact tool-call envelope the fixture returns for each production turn -
  validated against the PRODUCTION pydantic contracts, so a schema drift fails
  here instead of inside a live run;
* byte-equivalent semantics for identical inputs (only generated ids differ);
* a loud 422 for an unknown state that names roles and tool names and never
  echoes message content;
* the absence of every controller-owned key from anything the fixture emits.

Nothing here needs the live stack: the HTTP surface binds an ephemeral local
port. The one live trajectory (`test_public_api_smoke_trajectory_*`) skips
unless the E2E stack is up.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.domain.pod import _ObservationBatch
from polymerhus.recon.domain.rate_limit import MutationSpec, RateLoopVerdict

from tests.e2e import deterministic_llm_provider as provider

REPO_ROOT = Path(__file__).resolve().parents[2]

RATE_PROCEDURE = "performing-api-rate-limiting-bypass"

# The production tool surface, exactly as `ReconOrchestratorActor` binds it
# (`auth_capable_binding` + the Kali exec tools + the two rate tools + the two
# structured-output tools of the negotiated union).
ORCHESTRATOR_TOOL_NAMES = [
    "auth_store", "load_skill", "write_skill", "execute_command", "steel_exec",
    "map_rate_limit", "test_rate_limit_variant", "GatewayVerdict",
    "RateLoopVerdict",
]
TRIAGER_TOOL_NAMES = [
    "auth_store", "load_skill", "write_skill", "_ObservationBatch",
]


def _tools(names):
    return [
        {"type": "function",
         "function": {"name": name, "description": name, "parameters": {"type": "object"}}}
        for name in names
    ]


def _request(messages, *, tools=ORCHESTRATOR_TOOL_NAMES, model=provider.REGISTERED_MODEL,
             stream=False):
    """A wire body shaped exactly like the one the production client emits."""
    return {
        "model": model,
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
    """The production gateway brief (`orchestrator_agent._gateway_human`)."""
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


def _rate_human(target_key="172.28.0.23", url="http://172.28.0.23/canonical",
                project_id="p1"):
    """The production rate brief (`orchestrator_agent._rate_human`)."""
    return {"role": "user", "content": (
        f"Rate-limit mapping for project {project_id}, target {target_key} "
        f"({url}).\n\n"
        "This is the post-authentication rate-limit turn on the same session "
        "as the auth gateway.\n"
        "1. Load the generic `performing-api-rate-limiting-bypass` procedure.\n"
        "2. Call `map_rate_limit` EXACTLY ONCE."
    )}


def _triager_human(tool="ffuf"):
    """The production triager prompt (`pod.default_triage_fn`)."""
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


# The deterministic tool results the production collaborators would return.
AUTH_OVERVIEW = {"ok": True, "command": "read", "path": "overview",
                 "value": {"target": "172.28.0.23", "http-client-replayability": True}}
AUTH_ACCOUNTS = {"ok": True, "command": "read", "path": "accounts",
                 "value": {"accounts": {"alice": {"status": "valid"}}}}
AUTH_WRITE_OK = {"ok": True, "command": "write", "path": "accounts.alice.status",
                 "value": "valid"}
EXEC_OK = {"returncode": 0, "stdout": "auth-gateway-validated\n", "stderr": ""}
SKILL_BODY = "# authn\nSign in and prove the session.\n"
SKILL_WRITE_OK = {"ok": True, "skill": "authn", "target": "procedure"}
MAP_RESULT = {
    "outcome": "mapped", "behaviour": "token_bucket", "scope": "host",
    "threshold_low_per_s": 1.0, "threshold_high_per_s": 2.0,
    "burst_capacity": 1, "recovery_s": 1.0, "confidence": 0.9,
    "signals": ["rate_limited"],
    "experiment_ids": ["exp-baseline", "exp-steady"],
    "traffic_policy": {"target_key": "172.28.0.23", "rate_per_s": 1.0,
                       "burst": 1, "max_concurrency": 1,
                       "version": "traffic-policy/v2"},
}
VARIANT_RESULT = {
    "variant_id": "e2e-endpoint-shape-1", "outcome": "no_bypass",
    "gates": {"canonical_rejected": True, "material_state_change": False,
              "semantic_equivalence": True, "reproduced": False},
    "canonical_experiment_id": "exp-baseline",
    "variant_experiment_ids": ["exp-variant-1"],
    "rationale": "the normalized route shares the canonical bucket",
}


def _tool_result_for(name, args):
    """What the real collaborator returns for the fixture's own tool call."""
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
    if name == "map_rate_limit":
        return MAP_RESULT
    if name == "test_rate_limit_variant":
        return VARIANT_RESULT
    raise AssertionError(f"unexpected tool call from the fixture: {name}")


def _drive(request, *, max_rounds=16):
    """Run the fixture's side of the loop to completion; return the envelopes.

    Each round feeds back the tool result the real collaborator would return,
    exactly as `create_agent` does, so the fixture's state machine sees a real
    production-shaped history.
    """
    messages = list(request["messages"])
    envelopes = []
    for round_index in range(max_rounds):
        # A distinct sequence per round mirrors the served path, whose ids are
        # unique per request (the client treats them as opaque).
        status, body = provider.completion({**request, "messages": messages},
                                           sequence=round_index)
        assert status == 200, body
        message = body["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        if not calls:
            return envelopes, message
        assert len(calls) == 1, "the fixture emits exactly one tool call per turn"
        call = calls[0]
        name = call["function"]["name"]
        args = json.loads(call["function"]["arguments"])
        envelopes.append((name, args))
        if name in provider.TERMINAL_TOOLS:
            # The structured-output tool CLOSES the turn: production executes it
            # inside the agent graph and never asks the model again.
            return envelopes, message
        messages.append(message)
        messages.append(_tool_result(call["id"], _tool_result_for(name, args)))
    raise AssertionError(f"the fixture did not close within {max_rounds} rounds: {envelopes}")


def _final_envelope(envelopes, name):
    matching = [args for tool, args in envelopes if tool == name]
    assert matching, f"no {name} envelope in {[t for t, _ in envelopes]}"
    return matching[-1]


FORBIDDEN_KEYS = frozenset({
    "rate_per_s", "safe_rate_per_s", "threshold_low_per_s",
    "threshold_high_per_s", "burst", "burst_capacity", "concurrency",
    "max_concurrency", "budget", "max_requests", "max_duration_s",
    "duration_s", "requests", "estimated_requests", "cost_class",
    "admission", "admission_decision", "materialized_phases",
    "candidate_phases", "phase_list", "phases", "effective_policy",
    "traffic_policy", "policy",
})


def _keys(value, out=None):
    out = set() if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(key)
            _keys(item, out)
    elif isinstance(value, list):
        for item in value:
            _keys(item, out)
    return out


# --- the gateway turn -----------------------------------------------------------


def test_gateway_turn_grounds_then_closes_on_a_valid_gateway_verdict():
    envelopes, final = _drive(_request([_system(), _gateway_human()]))
    tools = [name for name, _ in envelopes]
    assert tools[0] == "auth_store"
    assert envelopes[0][1] == {"command": "read", "path": "overview"}
    assert "load_skill" in tools
    assert "execute_command" in tools, "the turn must probe before asserting validity"
    assert tools.index("load_skill") < tools.index("execute_command")
    assert tools[-1] == "GatewayVerdict"
    assert final is not None

    verdict = GatewayVerdict.model_validate(_final_envelope(envelopes, "GatewayVerdict"))
    assert verdict.outcome == "authenticated"
    assert verdict.account == "alice"
    assert verdict.branch == "request"
    assert verdict.replayability_resolved is False


def test_gateway_turn_asserts_validity_in_the_store_before_the_verdict():
    envelopes, _ = _drive(_request([_system(), _gateway_human()]))
    writes = [args for tool, args in envelopes
              if tool == "auth_store" and args.get("command") == "write"]
    assert writes, "the assertion act (an auth_store write) is mandatory"
    assert writes[0] == {"command": "write", "path": "accounts.alice.status",
                         "value": "valid"}
    assert [name for name, _ in envelopes].index("GatewayVerdict") > \
        [i for i, (name, args) in enumerate(envelopes)
         if name == "auth_store" and args.get("command") == "write"][0]


def test_browser_only_directive_is_carried_into_the_verdict_branch():
    envelopes, _ = _drive(_request([_system(), _gateway_human(directive="browser_only")]))
    verdict = GatewayVerdict.model_validate(_final_envelope(envelopes, "GatewayVerdict"))
    assert verdict.branch == "browser_only"


# --- the rate turn --------------------------------------------------------------


def test_rate_turn_loads_the_procedure_maps_once_and_closes_on_the_verdict():
    envelopes, _ = _drive(_request([_system(), _rate_human()]))
    tools = [name for name, _ in envelopes]
    assert tools[0] == "load_skill"
    assert envelopes[0][1]["name"] == RATE_PROCEDURE
    assert tools.count("map_rate_limit") == 1
    assert tools[-1] == "RateLoopVerdict"

    verdict = RateLoopVerdict.model_validate(_final_envelope(envelopes, "RateLoopVerdict"))
    assert verdict.outcome == "mapped"
    assert verdict.bypass_outcome == "no_bypass"
    assert verdict.evidence_experiment_ids == [
        "exp-baseline", "exp-steady", "exp-variant-1"]
    assert [s.value for s in verdict.signals] == ["rate_limited"]


def test_a_mapped_limiter_drives_one_typed_variant_probe():
    envelopes, _ = _drive(_request([_system(), _rate_human()]))
    probes = [args for tool, args in envelopes if tool == "test_rate_limit_variant"]
    assert len(probes) == 1, "one bounded variant per hypothesis, never a sweep"
    spec = MutationSpec.model_validate(probes[0]["mutation"])
    assert spec.family == "endpoint-shape"
    assert spec.payload is not None and spec.payload.kind == "path"
    assert spec.identity_mutation is False


def test_a_no_limiter_mapping_probes_no_variant():
    request = _request([_system(), _rate_human()])
    messages = list(request["messages"])
    # Prime the same state machine, but with a mapping that found no limiter.
    messages.append(_assistant_tool_call("c1", "load_skill",
                                         json.dumps({"name": RATE_PROCEDURE})))
    messages.append(_tool_result("c1", SKILL_BODY))
    messages.append(_assistant_tool_call("c2", "map_rate_limit", "{}"))
    messages.append(_tool_result("c2", {**MAP_RESULT, "outcome": "no_limiter",
                                        "signals": [], "experiment_ids": []}))
    envelopes, _ = _drive({**request, "messages": messages})
    assert [name for name, _ in envelopes] == ["RateLoopVerdict"]
    verdict = RateLoopVerdict.model_validate(_final_envelope(envelopes, "RateLoopVerdict"))
    assert verdict.outcome == "no_limiter"
    assert verdict.confirmed_variant_ids == []
    assert verdict.bypass_outcome == "inconclusive"


def test_a_confirmed_variant_is_named_and_never_promoted_into_policy():
    request = _request([_system(), _rate_human()])
    messages = list(request["messages"])
    messages.append(_assistant_tool_call("c1", "load_skill",
                                         json.dumps({"name": RATE_PROCEDURE})))
    messages.append(_tool_result("c1", SKILL_BODY))
    messages.append(_assistant_tool_call("c2", "map_rate_limit", "{}"))
    messages.append(_tool_result("c2", MAP_RESULT))
    messages.append(_assistant_tool_call("c3", "test_rate_limit_variant",
                                         json.dumps({"mutation": {
                                             "variant_id": "e2e-endpoint-shape-1",
                                             "family": "endpoint-shape",
                                             "payload": {"kind": "path",
                                                         "mutation_id": "m1",
                                                         "suffix": "/"}}})))
    messages.append(_tool_result("c3", {**VARIANT_RESULT, "outcome": "confirmed"}))
    envelopes, _ = _drive({**request, "messages": messages})
    verdict = RateLoopVerdict.model_validate(_final_envelope(envelopes, "RateLoopVerdict"))
    assert verdict.bypass_outcome == "confirmed"
    assert verdict.confirmed_variant_ids == ["e2e-endpoint-shape-1"]
    # a finding is EVIDENCE ONLY: nothing in the reply can name a policy
    assert not (FORBIDDEN_KEYS & set(verdict.model_dump()))


# --- the triager turn -----------------------------------------------------------


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
    """Strip only the generated identifiers from a completion body."""
    stripped = json.loads(json.dumps(body))
    stripped.pop("id", None)
    for choice in stripped.get("choices", []):
        for call in choice.get("message", {}).get("tool_calls") or []:
            call.pop("id", None)
    return json.dumps(stripped, sort_keys=True)


@pytest.mark.parametrize("messages,tools", [
    ([_system(), _gateway_human()], ORCHESTRATOR_TOOL_NAMES),
    ([_system(), _rate_human()], ORCHESTRATOR_TOOL_NAMES),
    ([_system("writing-observations"), _triager_human()], TRIAGER_TOOL_NAMES),
])
def test_identical_inputs_produce_semantically_identical_output(messages, tools):
    request = _request(messages, tools=tools)
    first = provider.completion(request)
    second = provider.completion(request)
    assert first[0] == second[0] == 200
    assert _semantic(first[1]) == _semantic(second[1])


def test_nothing_the_fixture_emits_can_carry_controller_authority():
    for messages, tools in (
        ([_system(), _gateway_human()], ORCHESTRATOR_TOOL_NAMES),
        ([_system(), _rate_human()], ORCHESTRATOR_TOOL_NAMES),
        ([_system("writing-observations"), _triager_human()], TRIAGER_TOOL_NAMES),
    ):
        envelopes, _ = _drive(_request(messages, tools=tools))
        for name, args in envelopes:
            leaked = _keys(args) & FORBIDDEN_KEYS
            assert not leaked, f"{name} emitted controller-owned keys: {sorted(leaked)}"


def test_unknown_state_is_a_diagnostic_422_without_message_content():
    secret = "Bearer super-secret-token"
    messages = [_system(), {"role": "user", "content": secret}]
    status, body = provider.completion(_request(messages))
    assert status == 422
    diagnostic = body["error"]["diagnostic"]
    assert diagnostic["roles"] == ["system", "user"]
    assert diagnostic["observed_tools"] == []
    assert set(diagnostic["tools"]) == set(ORCHESTRATOR_TOOL_NAMES)
    serialized = json.dumps(body)
    assert secret not in serialized
    assert "super-secret-token" not in serialized


def test_an_unknown_model_is_refused_loudly():
    status, body = provider.completion(
        _request([_system(), _gateway_human()], model="openai/some-other-model"))
    assert status == 422
    assert body["error"]["diagnostic"]["model"] == "openai/some-other-model"


def test_a_gateway_turn_without_a_candidate_account_is_refused_loudly():
    status, body = provider.completion(
        _request([_system(), _gateway_human(candidate=None)]))
    assert status == 422
    assert body["error"]["type"] == "unknown_state"


def test_streaming_requests_are_answered_with_an_sse_stream():
    request = _request([_system(), _gateway_human()], stream=True)
    frames = list(provider.stream_frames(provider.completion(request)[1]))
    assert frames[-1] == "[DONE]"
    decoded = [json.loads(frame) for frame in frames[:-1]]
    assert all(frame["object"] == "chat.completion.chunk" for frame in decoded)
    tool_deltas = [call for frame in decoded for call in
                   (frame["choices"][0]["delta"].get("tool_calls") or [])]
    assert tool_deltas[0]["function"]["name"] == "auth_store"
    assert decoded[-1]["choices"][0]["finish_reason"] == "tool_calls"


# --- the HTTP surface -----------------------------------------------------------


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
    assert body["status"] == "ok"
    assert body["models"] == [provider.REGISTERED_MODEL]
    assert body["requests"] == 0

    _post(f"{server}/v1/chat/completions", _request([_system(), _gateway_human()]))
    status, body = _get(f"{server}/health")
    assert body["requests"] == 1
    assert body["by_turn"] == {"gateway": 1}


def test_chat_completions_serves_the_plain_and_streaming_transports(server):
    status, body = _post(f"{server}/v1/chat/completions",
                         _request([_system(), _rate_human()]))
    assert status == 200
    assert body["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "load_skill"

    request = urllib.request.Request(
        f"{server}/v1/chat/completions",
        data=json.dumps(_request([_system(), _rate_human()], stream=True)).encode(),
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
        assert json.loads(exc.read().decode())["error"]["type"] == "unknown_path"
    else:  # pragma: no cover - the fixture must not silently serve models
        raise AssertionError("/v1/models must not be served by the fixture")


# --- the live public-API smoke trajectory (skips without the stack) -------------


def _production_agent(server_url, monkeypatch):
    """The REAL production client + agent graph, pointed at the local fixture.

    Only the tools are local stand-ins for Kali/Postgres; the model client, the
    SSE transport, the negotiated structured output and the agent loop are
    production code.
    """
    from langchain.agents import create_agent
    from langchain_core.tools import tool

    from polymerhus.app.llm.providers import build_chat_model
    from polymerhus.app.llm.session import structured_response_format

    store = {
        "overview": {"target": "172.28.0.23", "http-client-replayability": True},
        "accounts": {"accounts": {"alice": {"status": "valid"}}},
    }

    @tool
    def auth_store(command: str, path: str = "", value: object = None) -> dict:
        """The auth store."""
        if command == "write":
            return {"ok": True, "command": "write", "path": path, "value": value}
        return {"ok": True, "command": "read", "path": path,
                "value": store.get(path or "overview", {})}

    @tool
    def load_skill(name: str, refresh: bool = False) -> str:
        """Load a skill."""
        return f"# {name}\nprocedure body"

    @tool
    def write_skill(skill: str, target: str, content: str,
                    source_note_ids: list | None = None) -> dict:
        """Write a skill."""
        return {"ok": True, "skill": skill, "target": target}

    @tool
    def execute_command(command: str, session_id: str = "s", timeout_s: int = 30) -> dict:
        """Run a command on the executor."""
        return {"returncode": 0, "stdout": "auth-gateway-validated\n", "stderr": ""}

    @tool
    def steel_exec(command: str = "", session_id: str = "s") -> dict:
        """Run the browser gateway."""
        return {"returncode": 0, "stdout": "", "stderr": ""}

    @tool
    def map_rate_limit() -> dict:
        """Map the target's limiter."""
        return dict(MAP_RESULT)

    @tool
    def test_rate_limit_variant(mutation: dict) -> dict:
        """Probe one bounded variant."""
        return {**VARIANT_RESULT, "variant_id": mutation.get("variant_id")}

    monkeypatch.setenv("LLM_GATEWAY_URL", f"{server_url}/v1")
    monkeypatch.setenv("API_KEY_OPENAI", "e2e-inert-key")
    model = build_chat_model("openai", provider.MODEL_ID)
    response_format = structured_response_format(
        "job_orchestrator", GatewayVerdict | RateLoopVerdict, tools_bound=True)
    return create_agent(
        model,
        tools=[auth_store, load_skill, write_skill, execute_command, steel_exec,
               map_rate_limit, test_rate_limit_variant],
        response_format=response_format,
        system_prompt="SYS",
    )


def _run_real_turn(agent, brief):
    import asyncio

    async def _go():
        result = None
        async for mode, payload in agent.astream(
                {"messages": [("user", brief)]}, stream_mode=["messages", "values"]):
            if isinstance(payload, dict) and "messages" in payload:
                result = payload
        return result.get("structured_response")

    return asyncio.run(_go())


def test_the_real_production_client_drives_the_fixture_to_both_verdicts(server, monkeypatch):
    """The strongest offline evidence: production `build_chat_model` (SSE +
    `tool_choice=required` + the negotiated union) against the fixture."""
    pytest.importorskip("langchain.agents")
    agent = _production_agent(server, monkeypatch)

    verdict = _run_real_turn(agent, _gateway_human()["content"])
    assert isinstance(verdict, GatewayVerdict), verdict
    assert (verdict.outcome, verdict.account, verdict.branch) == (
        "authenticated", "alice", "request")

    rate = _run_real_turn(agent, _rate_human()["content"])
    assert isinstance(rate, RateLoopVerdict), rate
    assert rate.outcome == "mapped"
    assert rate.bypass_outcome == "no_bypass"
    assert rate.evidence_experiment_ids == [
        "exp-baseline", "exp-steady", "exp-variant-1"]

    status, counters = _get(f"{server}/health")
    assert counters["by_turn"] == {"gateway": 8, "rate": 4}


def test_public_api_smoke_trajectory_calls_the_fixture_for_both_turns():
    """Drive a real run through the public API and prove the REAL actor loop
    called this fixture (never a scripted orchestrator)."""
    from tests.e2e.harness import driver as harness

    reason = harness.stack_unavailable_reason()
    if reason:
        pytest.skip(reason)

    trajectory = harness.smoke_rate_trajectory()
    assert trajectory["provider"]["by_turn"].get("gateway", 0) >= 1
    assert trajectory["provider"]["by_turn"].get("rate", 0) >= 1
    assert trajectory["stats"]["rate_limit"]["version"] == "rate-profile/v2"
    source = Path(__file__).read_text(encoding="utf-8")
    for forbidden in ("_ScriptedOrchestrator", "fake_run_job"):
        assert forbidden not in source
