"""E7: the reasoning-replay round trip through the LIVE gateway (#100, #109 T6).

D11 items 3-4, walked end-to-end with REAL traffic: two stateful session
turns of the triager role through the co-located litellm proxy
(LLM_GATEWAY_URL=http://127.0.0.1:4000), on the real checkpointer seam
(`module_context` + `get_session_checkpointer`).

The path under assertion:

1. Turn 1: `stateful_turn` -> `ReasoningPreservingChatOpenAI._create_chat_result`
   captures the wire reasoning (the deepseek-family `reasoning_content` per
   the synced profile) onto the assistant message; `extract_reasoning` parses
   it; `_replay_reasoning` re-persists the message with the reasoning attached
   (byte-identical) via `agent.update_state`.
2. The checkpoint read-back carries the replayed reasoning, byte-identical to
   what the turn's own message carried.
3. The restored prefix re-emits it: `_get_request_payload` over the restored
   messages serializes the reasoning at MESSAGE level (`reasoning_content`) -
   exactly the shape the gateway forwards (the T1-verified transport).
4. `reasoning_readability` metadata: before turn 2, the persisted thread
   classifies as "replayed"; the observability line
   (`llm-response: ... reasoning_readability=parsed ... cached_tokens=...`)
   fires for the turn.
5. Turn 2 (a continuation on the same thread) completes with a non-empty
   answer over the replayed prefix.

Cost note: two real reasoning turns through the live gateway (sanctioned by
the operator - the E7 full-path walkthrough).

Model caveat: the walkthrough overrides `LLM_MODEL_TRIAGER` to
`opencode-go:deepseek/deepseek-v4-pro` because the production flash model
returns EMPTY `reasoning_content` on the go endpoint (verified live
2026-08-18), so there is nothing to capture/replay. The reasoning-replay path
needs a model that emits reasoning; pro does. Production role config is left
on flash - this override lives in the walkthrough only.
"""

import json

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")

GATEWAY_ENV = {"LLM_GATEWAY_URL": gs.GATEWAY_URL}

# E7 is a reasoning-replay walkthrough: it must run on a model that ACTUALLY
# emits reasoning content. The production role config points at
# opencode-go:deepseek/deepseek-v4-flash, whose go endpoint returns
# reasoning_content as an EMPTY string (verified live 2026-08-18 - flash
# strips/server-side-suppresses it), so the replay has nothing to capture.
# opencode-go:deepseek/deepseek-v4-pro returns full reasoning_content on the
# same endpoint. Per operator direction (option 1), override ONLY this
# walkthrough's model to pro - production role config is left on flash.
REPLAY_MODEL_ENV = {"LLM_MODEL_TRIAGER": "opencode-go:deepseek/deepseek-v4-pro"}
REPLAY_ENV = {**GATEWAY_ENV, **REPLAY_MODEL_ENV}

# The whole walkthrough runs in ONE in-container process: the checkpointer
# hold (resolve-and-hold, D7) and the thread state are process-lifetime, so a
# fresh exec per assertion would destroy the state under test.
PROBE = r"""
import json
import logging
import time

logging.basicConfig(level=logging.INFO)

from langchain_core.messages import HumanMessage

from polymerhus.app.llm import session as S
from polymerhus.app.llm.checkpoints import (
    get_session_checkpointer, module_context, flush_module_index,
)
from polymerhus.app.llm.reasoning import (
    extract_reasoning, replayed_request_fields, cached_tokens,
    reasoning_readability_metadata,
)
from polymerhus.app.llm.providers import resolve_role, build_chat_model
from polymerhus.app.llm.capability import resolve_capability

report = {}

provider, model = resolve_role("triager")
profile = resolve_capability(provider, model)
report["profile_reasoning_in_response"] = profile.reasoning_in_response
report["profile_reasoning_field"] = profile.reasoning_field

thread = "e2e-replay-%d" % int(time.time())
with module_context("recon"):
    ckpt = get_session_checkpointer()

    turn1 = S.run_session_turn("triager", thread,
                               [HumanMessage("Say only: TURN-ONE")],
                               checkpointer=ckpt)
    report["turn1_content"] = bool(turn1.content and str(turn1.content).strip())
    pristine = turn1.messages[-1]
    parsed = extract_reasoning(pristine, profile)
    report["wire_parsed"] = parsed is not None
    report["wire_surface"] = parsed.surface if parsed else None
    wire_value = parsed.reasoning if parsed else None

    memory = S.read_session_memory(ckpt, thread)
    restored = memory.messages[-1] if memory and memory.messages else None
    replay_fields = replayed_request_fields(restored) if restored else {}
    report["replayed_nonempty"] = bool(replay_fields)
    report["replayed_byte_identical"] = (
        replay_fields.get(parsed.surface) == wire_value
        if parsed and replay_fields else False)
    report["readability_metadata"] = (
        reasoning_readability_metadata(memory.messages)
        if memory and memory.messages else {})

    # The restored prefix re-emits at MESSAGE level (the outbound seam the
    # gateway forwards verbatim).
    if restored is not None:
        m = build_chat_model(provider, model, max_retries=0)
        payload = m._get_request_payload([restored])
        emitted = {}
        for message_dict in payload.get("messages", []):
            if message_dict.get("reasoning_content") is not None:
                emitted["reasoning_content"] = message_dict["reasoning_content"]
        report["outbound_reemitted"] = emitted.get("reasoning_content") == wire_value
    else:
        report["outbound_reemitted"] = False

    report["cached_tokens_turn1"] = cached_tokens(turn1.messages[-1])

    turn2 = S.run_session_turn("triager", thread,
                               [HumanMessage("Say only: TURN-TWO")],
                               checkpointer=ckpt)
    report["turn2_content"] = bool(turn2.content and str(turn2.content).strip())
    report["cached_tokens_turn2"] = cached_tokens(turn2.messages[-1])

    memory2 = S.read_session_memory(ckpt, thread)
    restored2 = memory2.messages[-1] if memory2 and memory2.messages else None
    report["replayed_after_turn2"] = bool(
        replayed_request_fields(restored2) if restored2 else {})
    flush_module_index("recon")

print(json.dumps(report))
"""


def test_e7_reasoning_replay_round_trip_through_gateway():
    result = gs.agent_python(PROBE, env=REPLAY_ENV, timeout=600)
    assert result.returncode == 0, (
        "the E7 walkthrough process failed:\n%s\n%s"
        % (result.stdout[-2000:], result.stderr[-2000:]))
    report = json.loads(result.stdout.strip().splitlines()[-1])

    # The synced profile says this model returns reasoning (the D11 matrix).
    assert report["profile_reasoning_in_response"] is True, (
        "the live profile must assert reasoning_in_response for the triager "
        "model; the replay pipeline is gated on it")
    assert report["profile_reasoning_field"] == "reasoning_content"

    # 1. Turn 1 ran and the wire reasoning was captured + parsed.
    assert report["turn1_content"], "turn 1 returned empty content"
    assert report["wire_parsed"], (
        "the wire reasoning must be captured and parsed by the "
        "ReasoningPreservingChatOpenAI seam")
    assert report["wire_surface"] == "reasoning_content"

    # 2. The re-persisted checkpoint carries it byte-identical.
    assert report["replayed_nonempty"], (
        "the checkpoint read-back must carry the replayed reasoning")
    assert report["replayed_byte_identical"], (
        "the replayed reasoning must be byte-identical to the wire value")

    # 3. The restored prefix re-emits it at message level.
    assert report["outbound_reemitted"], (
        "the restored prefix must re-emit reasoning_content at message level")

    # 4. Readability metadata: the persisted thread classifies as replayed.
    assert report["readability_metadata"].get("reasoning_readability") == "replayed", (
        "the D11 item-4 langfuse field must classify the persisted thread as "
        "replayed")

    # 5. The cache track is observability-only (int or None - never gated).
    for key in ("cached_tokens_turn1", "cached_tokens_turn2"):
        value = report[key]
        assert value is None or isinstance(value, int), (
            "%s must be an int or None, got %r" % (key, value))

    # 6. Turn 2 completed over the replayed prefix and re-persisted it.
    assert report["turn2_content"], "turn 2 returned empty content"
    assert report["replayed_after_turn2"], (
        "turn 2 must re-persist the reasoning on the continued thread")

    # The per-turn observability line (cache track + readability) fired. The
    # whole walkthrough runs in ONE in-container probe process (the
    # checkpointer hold and thread state are process-lifetime), so the
    # `llm-response` logger line lands in THAT process's own output - not the
    # agent container's `docker compose logs` managed stdout. Python's logging
    # default handler writes to STDERR, so it is captured on `result.stderr`,
    # alongside the scripted report JSON on `result.stdout`.
    probe_err = result.stderr
    assert "llm-response: role=triager" in probe_err, (
        "the llm-response observability line must be logged for the turn")
    assert "cached_tokens=" in probe_err
