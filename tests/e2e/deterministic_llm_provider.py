"""The deterministic local model provider for the functional E2E (#238 Task 9).

The functional tier must traverse the REAL actor loop, so only model inference
is replaced: this process speaks the OpenAI-compatible surface the production
client already talks (`POST /v1/chat/completions`, `GET /health`) and answers
from the conversation state alone.

What makes it deterministic:

* it reads the request exactly as `langchain_openai.ChatOpenAI` emits it
  (`model`, `messages`, `tools`, `tool_choice`, `stream`), and it never accepts
  a test-side hint - no `e2e_turn` field, no per-test scripting;
* the next envelope is a pure function of (bound tool names, the last user
  brief, the observed tool calls and their structured results), so identical
  inputs produce identical semantics (only the generated completion/ tool-call
  ids differ, which every client treats as opaque);
* both transports are served: the buffered JSON body and the SSE stream the
  session seam's `agent.astream(...)` actually requests.

What it deliberately is NOT:

* it never states a policy, a rate, a concurrency, a budget, an admission
  decision or a phase list. The controller owns every one of those, and the
  fixture's replies are checked against that boundary by its own tests;
* it never echoes message content back. A state it does not implement is a
  loud `422` naming the message roles and the tool names, nothing else.

The fixture mirrors production shapes, so a production change to the message
shape or the tool names must update `tests/e2e/test_deterministic_llm_provider.py`
in the same commit - that is the protocol contract, not a mock.
"""
from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

# --- identity -------------------------------------------------------------------

MODEL_ID = "rate-admission-fixture"
"""The model id the operator configures (`LLM_JOB_ORCHESTRATOR`, `LLM_TRIAGER`)."""

REGISTERED_MODEL = f"openai/{MODEL_ID}"
"""The REGISTERED name the production client sends in gateway mode
(`sync_mapping.registered_model_name("openai", MODEL_ID)`). The fixture accepts
this one identifier and refuses everything else loudly."""

# --- the production tool names --------------------------------------------------

AUTH_TOOLS = ("auth_store", "load_skill", "write_skill")
KALI_EXEC_TOOLS = ("execute_command", "steel_exec")
RATE_TOOLS = ("map_rate_limit", "test_rate_limit_variant")
#: The two structured-output tools of the negotiated `GatewayVerdict | RateLoopVerdict`
#: union (`langchain.agents.structured_output.ToolStrategy` names each variant after
#: its class), plus the triager's own single-schema tool.
ORCHESTRATOR_VERDICT_TOOLS = ("GatewayVerdict", "RateLoopVerdict")
TRIAGER_SCHEMA_TOOL = "_ObservationBatch"

ORCHESTRATOR_TOOLS = frozenset(
    (*AUTH_TOOLS, *KALI_EXEC_TOOLS, *RATE_TOOLS, *ORCHESTRATOR_VERDICT_TOOLS)
)
TRIAGER_TOOLS = frozenset((*AUTH_TOOLS, TRIAGER_SCHEMA_TOOL))

RATE_PROCEDURE = "performing-api-rate-limiting-bypass"
AUTH_SKILL = "authn"

#: The target alias that makes the rate turn fail at the model boundary. It is a
#: property of the CONVERSATION (the brief names the target), never a test-side
#: switch and never a production fault flag: the E2E exercises the production
#: actor's failure path by aiming a run at this alias, exactly as it would aim
#: one at any other target.
RATE_STAGE_ERROR_TARGET = "rate-stage-error"

# --- the turn vocabulary --------------------------------------------------------

TURN_GATEWAY = "gateway"
TURN_RATE = "rate"
TURN_TRIAGER = "triager"

_GATEWAY_BRIEF = "Auth gateway for project"
_RATE_BRIEF = "Rate-limit mapping for project"
_CANDIDATE_RE = re.compile(
    r"Candidate account \(most recently updated usable\): (.+?)\.(?=\s|$)")
_DIRECTIVE_RE = re.compile(r"Branch directive: (\w+)\.")

#: The structured-output tools that TERMINATE their turn (the negotiated union's
#: two variants and the triager's own batch schema).
TERMINAL_TOOLS = frozenset((*ORCHESTRATOR_VERDICT_TOOLS, TRIAGER_SCHEMA_TOOL))

#: The one prose the rate turn closes with. Deliberately contains no number: the
#: controller measured everything, and a model-authored figure is not a fact.
_RATE_INTERPRETATION = (
    "The controller mapped the target's limiter and bounded the bypass probes; "
    "any confirmed variant is recorded as evidence only and never applied to "
    "this run's traffic."
)


class UnknownState(Exception):
    """A request the fixture does not implement. Carries a CONTENT-FREE
    diagnostic: message roles and tool names, never a message body."""

    def __init__(self, message: str, diagnostic: dict[str, Any]):
        super().__init__(message)
        self.message = message
        self.diagnostic = diagnostic


class ServiceUnavailable(Exception):
    """The deterministic upstream failure of the `rate-stage-error` target.

    The production client classifies a 5xx as retryable, so this is what
    exercises the actor's bounded escalation and its conservative fallback -
    without a fault flag anywhere in production.
    """

    def __init__(self, message: str, diagnostic: dict[str, Any]):
        super().__init__(message)
        self.message = message
        self.diagnostic = diagnostic


# --- request parsing ------------------------------------------------------------


def _tool_names(request: dict) -> list[str]:
    names = []
    for entry in request.get("tools") or []:
        function = entry.get("function") if isinstance(entry, dict) else None
        name = (function or {}).get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _role(message: dict) -> str:
    role = message.get("role")
    return role if isinstance(role, str) else "?"


def _calls(messages: list[dict]) -> list[tuple[str, dict]]:
    """Every observed assistant tool call, in order, as `(name, args)`.

    `arguments` arrives as a JSON string (the OpenAI wire shape); a call whose
    arguments do not parse is reported with `{}` so the state machine moves on
    rather than crashing the loop.
    """
    observed: list[tuple[str, dict]] = []
    for message in messages:
        if _role(message) != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name")
            if not isinstance(name, str):
                continue
            raw = function.get("arguments")
            try:
                args = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
            except json.JSONDecodeError:
                args = {}
            observed.append((name, args if isinstance(args, dict) else {}))
    return observed


def _results(messages: list[dict]) -> dict[str, Any]:
    """`tool_call_id -> parsed tool result` for every `tool` message."""
    results: dict[str, Any] = {}
    for message in messages:
        if _role(message) != "tool":
            continue
        call_id = message.get("tool_call_id")
        if not isinstance(call_id, str):
            continue
        content = message.get("content")
        try:
            results[call_id] = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            results[call_id] = content
    return results


def _paired_results(messages: list[dict], name: str) -> list[Any]:
    """The results of every observed call to `name`, in order.

    Pairing is FIFO over the pending calls, falling back to position when two
    calls share a generated id (which the wire permits and a duplicated id
    would otherwise collapse onto one another).
    """
    results = _results(messages)
    pending: list[tuple[str | None, str]] = []
    paired: list[Any] = []
    for message in messages:
        role = _role(message)
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                call_name = (call.get("function") or {}).get("name")
                if isinstance(call_name, str):
                    pending.append((call.get("id"), call_name))
        elif role == "tool":
            call_id = message.get("tool_call_id")
            index = next((i for i, (pending_id, _) in enumerate(pending)
                          if pending_id == call_id), 0)
            if not pending:
                continue
            _, call_name = pending.pop(index)
            if call_name == name:
                paired.append(results.get(call_id))
    return paired


def _last_user_brief(messages: list[dict]) -> str:
    for message in reversed(messages):
        if _role(message) == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def classify_session(tool_names: list[str]) -> str | None:
    """`orchestrator`, `triager`, or None for a tool surface this fixture does
    not serve. The surface - not the prompt - is the authority: the actor binds
    the two rate tools, the pod's triager binds its own schema tool."""
    bound = set(tool_names)
    if set(RATE_TOOLS) & bound:
        return "orchestrator"
    if TRIAGER_SCHEMA_TOOL in bound:
        return "triager"
    return None


def classify_turn(request: dict) -> str:
    """Which production turn this request belongs to."""
    session = classify_session(_tool_names(request))
    messages = request.get("messages") or []
    if session == "triager":
        return TURN_TRIAGER
    if session == "orchestrator":
        brief = _last_user_brief(messages)
        if _RATE_BRIEF in brief:
            return TURN_RATE
        if _GATEWAY_BRIEF in brief:
            return TURN_GATEWAY
        raise UnknownState(
            "orchestrator request carries neither the auth-gateway nor the "
            "rate-limit brief",
            _diagnostic(request, session="orchestrator", turn=None),
        )
    raise UnknownState(
        "the request binds a tool surface this fixture does not serve",
        _diagnostic(request, session=session, turn=None),
    )


def _diagnostic(request: dict, *, session: str | None, turn: str | None,
                reason: str | None = None) -> dict[str, Any]:
    """Roles and tool names ONLY - never a message body."""
    messages = request.get("messages") or []
    diagnostic: dict[str, Any] = {
        "model": request.get("model"),
        "session": session,
        "turn": turn,
        "roles": [_role(m) for m in messages if isinstance(m, dict)],
        "last_role": _role(messages[-1]) if messages and isinstance(messages[-1], dict) else None,
        "tools": _tool_names(request),
        "observed_tools": [name for name, _ in _calls(messages)],
    }
    if reason:
        diagnostic["reason"] = reason
    return diagnostic


# --- the gateway turn -----------------------------------------------------------


def _has(calls, tool_name, **match) -> bool:
    return any(
        tool == tool_name and all(args.get(key) == value for key, value in match.items())
        for tool, args in calls
    )


def _count(calls, name) -> int:
    return sum(1 for tool, _ in calls if tool == name)


def _gateway_candidate(brief: str) -> str:
    match = _CANDIDATE_RE.search(brief)
    if not match:
        raise UnknownState(
            "the gateway brief names no candidate account and the fixture does "
            "not implement the sign-in (generation) branch",
            {"reason": "no_candidate_account"},
        )
    return match.group(1).strip()


def _gateway_branch(brief: str) -> str:
    match = _DIRECTIVE_RE.search(brief)
    directive = match.group(1) if match else "request"
    if directive == "browser_only":
        return "browser_only"
    if directive in ("request", "request_browser_first"):
        return "request"
    raise UnknownState(
        f"the gateway directive {directive!r} (resolve_in_loop) is not "
        "implemented by the fixture",
        {"reason": "unsupported_directive", "directive": directive},
    )


def _gateway_envelope(messages: list[dict], brief: str) -> tuple[str, dict]:
    # The brief is validated UP FRONT: a state the fixture does not implement
    # (no candidate account -> the generation branch, an unsupported directive)
    # is a loud refusal on the first request, never four tool calls later.
    candidate = _gateway_candidate(brief)
    branch = _gateway_branch(brief)
    calls = _calls(messages)
    if not any(
            tool == "auth_store" and args.get("command") == "read"
            and args.get("path") in ("", "overview")
            for tool, args in calls):
        return "auth_store", {"command": "read", "path": "overview"}
    if not _has(calls, "load_skill", name=AUTH_SKILL):
        return "load_skill", {"name": AUTH_SKILL}
    if not _has(calls, "auth_store", command="read", path="accounts"):
        return "auth_store", {"command": "read", "path": "accounts"}
    if not any(tool in KALI_EXEC_TOOLS for tool, _ in calls):
        return "execute_command", {
            "command": "echo auth-gateway-validated",
            "session_id": "e2e-auth-gateway",
            "timeout_s": 30,
        }
    if not any(tool == "auth_store" and args.get("command") == "write"
               and str(args.get("path", "")).endswith(".status")
               for tool, args in calls):
        return "auth_store", {
            "command": "write", "path": f"accounts.{candidate}.status",
            "value": "valid",
        }
    if _count(calls, "load_skill") < 2:
        return "load_skill", {"name": AUTH_SKILL}
    if not _has(calls, "write_skill"):
        return "write_skill", {
            "skill": AUTH_SKILL, "target": "procedure",
            "content": (
                "The E2E gateway validated the stored account against the "
                "deterministic fixture target and asserted it valid before "
                "any sign-in attempt."
            ),
        }
    return "GatewayVerdict", {
        "outcome": "authenticated",
        "account": candidate,
        "branch": branch,
        "replayability_resolved": False,
        "replayability": None,
        "rationale": (
            "The stored account's request state was replayed against the "
            "target with the exec capability, the outcome was asserted in the "
            "store, and the reusable part was written back to the authn skill."
        ),
    }


# --- the rate turn --------------------------------------------------------------

#: The ONE bounded variant the fixture probes when the mapping reports a limiter.
#: A route-shape hypothesis whose typed payload is a real, transported mutation.
_VARIANT_ID = "e2e-endpoint-shape-1"
_VARIANT_MUTATION = {
    "variant_id": _VARIANT_ID,
    "family": "endpoint-shape",
    "description": "trailing-slash route shape, one canonical resource",
    "identity_mutation": False,
    "payload": {"kind": "path", "mutation_id": "e2e-path-1", "suffix": "/"},
}

_SIGNAL_VOCABULARY = frozenset({"waf_protected", "waf_detection", "rate_limited"})


def _rate_envelope(messages: list[dict], brief: str) -> tuple[str, dict]:
    if RATE_STAGE_ERROR_TARGET in brief:
        # The conversation aims the run at the failing alias: the model
        # boundary is unavailable for this target, deterministically.
        raise ServiceUnavailable(
            "the deterministic provider is unavailable for this target",
            {"reason": "rate_stage_error_target"},
        )
    calls = _calls(messages)
    if not _has(calls, "load_skill", name=RATE_PROCEDURE):
        return "load_skill", {"name": RATE_PROCEDURE}
    if _count(calls, "map_rate_limit") == 0:
        return "map_rate_limit", {}
    mapped = _paired_results(messages, "map_rate_limit")[-1]
    if not isinstance(mapped, dict):
        raise UnknownState(
            "the mapping tool result is not a structured control object",
            {"reason": "unstructured_map_result"},
        )
    probes = _paired_results(messages, "test_rate_limit_variant")
    if mapped.get("outcome") == "mapped" and not probes:
        return "test_rate_limit_variant", {"mutation": dict(_VARIANT_MUTATION)}

    outcome = mapped.get("outcome")
    experiment_ids = [e for e in (mapped.get("experiment_ids") or [])
                      if isinstance(e, str)]
    signals = [s for s in (mapped.get("signals") or []) if s in _SIGNAL_VOCABULARY]
    confirmed: list[str] = []
    bypass_outcome = "inconclusive"
    if probes and isinstance(probes[-1], dict):
        finding = probes[-1]
        experiment_ids.extend(
            e for e in (finding.get("variant_experiment_ids") or [])
            if isinstance(e, str))
        canonical = finding.get("canonical_experiment_id")
        if isinstance(canonical, str) and canonical not in experiment_ids:
            experiment_ids.append(canonical)
        bypass_outcome = finding.get("outcome") or "inconclusive"
        variant_id = finding.get("variant_id")
        if bypass_outcome == "confirmed" and isinstance(variant_id, str):
            confirmed.append(variant_id)
    elif outcome in ("no_limiter", "failed", None):
        bypass_outcome = "inconclusive"
    return "RateLoopVerdict", {
        "outcome": outcome or "inconclusive",
        "bypass_outcome": bypass_outcome,
        "confirmed_variant_ids": confirmed,
        "evidence_experiment_ids": experiment_ids,
        "signals": signals,
        "interpretation": _RATE_INTERPRETATION,
        "rationale": (
            "The deterministic controller owns every measurement. The verdict "
            "restates the mapping outcome and names only the experiment ids and "
            "variant ids the probes actually returned; no finding was applied "
            "to the run's traffic."
        ),
    }


# --- the triager turn -----------------------------------------------------------


def _triager_envelope(messages: list[dict]) -> tuple[str, dict]:
    """The honest empty batch: the deterministic fixture flags nothing, so the
    pod's curation path is exercised without inventing discoveries."""
    return TRIAGER_SCHEMA_TOOL, {"observations": []}


# --- the completion -------------------------------------------------------------


def _next_envelope(request: dict) -> tuple[str, str, dict]:
    """`(turn, tool_name, arguments)` - the pure state machine."""
    turn = classify_turn(request)
    messages = request.get("messages") or []
    if turn == TURN_GATEWAY:
        name, args = _gateway_envelope(messages, _last_user_brief(messages))
    elif turn == TURN_RATE:
        name, args = _rate_envelope(messages, _last_user_brief(messages))
    else:
        name, args = _triager_envelope(messages)
    return turn, name, args


_COUNTER_LOCK = threading.Lock()


def _message_for(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }],
    }


def completion(request: dict, *, sequence: int = 0) -> tuple[int, dict]:
    """The pure completion: `(status_code, body)`.

    `sequence` only feeds the generated identifiers (the completion id and the
    tool-call id), which every client treats as opaque - identical inputs yield
    identical semantics.
    """
    model = request.get("model")
    if model != REGISTERED_MODEL:
        return 422, {"error": {
            "type": "unknown_state",
            "message": (
                f"the fixture serves exactly the registered model "
                f"{REGISTERED_MODEL!r}"
            ),
            "diagnostic": _diagnostic(request, session=None, turn=None,
                                      reason="unknown_model"),
        }}
    if request.get("stream"):
        # Honoured by the transport, which streams this body through
        # `stream_frames`; the body itself is the same as the buffered one.
        pass
    try:
        _turn, name, arguments = _next_envelope(request)
    except UnknownState as exc:
        diagnostic = dict(exc.diagnostic)
        diagnostic.setdefault("model", model)
        diagnostic.setdefault("roles",
                              [_role(m) for m in (request.get("messages") or [])])
        diagnostic.setdefault("tools", _tool_names(request))
        diagnostic.setdefault("observed_tools",
                              [n for n, _ in _calls(request.get("messages") or [])])
        return 422, {"error": {
            "type": "unknown_state",
            "message": exc.message,
            "diagnostic": diagnostic,
        }}
    except ServiceUnavailable as exc:
        diagnostic = dict(exc.diagnostic)
        diagnostic.setdefault("model", model)
        diagnostic.setdefault("roles",
                              [_role(m) for m in (request.get("messages") or [])])
        diagnostic.setdefault("tools", _tool_names(request))
        diagnostic.setdefault("observed_tools",
                              [n for n, _ in _calls(request.get("messages") or [])])
        return 503, {"error": {
            "type": "service_unavailable",
            "message": exc.message,
            "diagnostic": diagnostic,
        }}
    completion_id = f"chatcmpl-e2e-{sequence:08d}"
    body = {
        "id": completion_id,
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [{
            "index": 0,
            "message": _message_for(f"call_e2e_{sequence:08d}_0", name, arguments),
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    return 200, body


def stream_frames(body: dict, *, chunk_size: int = 8) -> Iterator[str]:
    """The SSE frames for a completion body: JSON strings, then `[DONE]`.

    The session seam streams (`agent.astream`), so the fixture must emit the
    OpenAI chunk protocol: one chunk opening the tool call, then the arguments
    in fragments, then the finish chunk.
    """
    base = {"id": body["id"], "object": "chat.completion.chunk", "created": 0,
            "model": body["model"]}
    message = body["choices"][0]["message"]
    call = message["tool_calls"][0]
    opening = {"role": "assistant", "content": ""}
    if message.get("content"):
        opening["content"] = message["content"]
    opening["tool_calls"] = [{
        "index": 0, "id": call["id"], "type": "function",
        "function": {"name": call["function"]["name"], "arguments": ""},
    }]
    yield json.dumps({**base, "choices": [
        {"index": 0, "delta": opening, "finish_reason": None}]})
    arguments = call["function"]["arguments"]
    for start in range(0, len(arguments), chunk_size):
        delta = {"tool_calls": [{
            "index": 0,
            "function": {"arguments": arguments[start:start + chunk_size]},
        }]}
        yield json.dumps({**base, "choices": [
            {"index": 0, "delta": delta, "finish_reason": None}]})
    yield json.dumps({
        **base,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        "usage": body["usage"],
    })
    yield "[DONE]"


# --- the HTTP surface -----------------------------------------------------------


class _State:
    """The served request counters (`GET /health`): proof that the REAL actor
    loop reached this fixture, per turn."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests = 0
        self.by_turn: dict[str, int] = {}
        self.by_model: dict[str, int] = {}
        self.errors: dict[str, int] = {}

    def observe(self, request: dict, status: int) -> None:
        with self.lock:
            self.requests += 1
            model = str(request.get("model"))
            self.by_model[model] = self.by_model.get(model, 0) + 1
            if status != 200:
                error_type = str(status)
                self.errors[error_type] = self.errors.get(error_type, 0) + 1
                return
            try:
                turn = classify_turn(request)
            except UnknownState:
                turn = "unknown"
            self.by_turn[turn] = self.by_turn.get(turn, 0) + 1

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "status": "ok",
                "models": [REGISTERED_MODEL],
                "requests": self.requests,
                "by_turn": dict(sorted(self.by_turn.items())),
                "by_model": dict(sorted(self.by_model.items())),
                "errors": dict(sorted(self.errors.items())),
            }


def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _sse_response(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    for frame in stream_frames(body):
        handler.wfile.write(f"data: {frame}\n\n".encode())
        handler.wfile.flush()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "polymerhus-deterministic-llm/1"

    def log_message(self, *args) -> None:  # noqa: D102 - quiet by design
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw) if raw else {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            _json_response(self, 200, self.server.state.snapshot())
            return
        _json_response(self, 404, {"error": {
            "type": "unknown_path",
            "message": f"the deterministic fixture serves /health and "
                       f"/v1/chat/completions only, not {self.path!r}",
        }})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            _json_response(self, 404, {"error": {
                "type": "unknown_path",
                "message": f"the deterministic fixture serves "
                           f"/v1/chat/completions only, not {self.path!r}",
            }})
            return
        try:
            request = self._read_json()
        except (json.JSONDecodeError, ValueError):
            _json_response(self, 400, {"error": {
                "type": "invalid_request",
                "message": "the request body is not a JSON object",
            }})
            return
        state = self.server.state
        with state.lock:
            sequence = state.requests
        status, body = completion(request, sequence=sequence)
        state.observe(request, status)
        if status != 200:
            _json_response(self, status, body)
            return
        if request.get("stream"):
            _sse_response(self, status, body)
            return
        _json_response(self, status, body)


def create_server(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    """A ready-to-serve fixture. `port=0` binds an ephemeral port (tests).

    Each server carries its OWN counters, so a test's health snapshot starts at
    zero and never inherits another test's traffic.
    """
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.state = _State()
    return httpd


def main() -> None:
    host = os.environ.get("RATE_LLM_HOST", "0.0.0.0")
    port = int(os.environ.get("RATE_LLM_PORT", "8080"))
    httpd = create_server(host, port)
    print(f"deterministic-llm listening on {host}:{httpd.server_address[1]} "
          f"serving {REGISTERED_MODEL}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
