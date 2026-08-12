"""Unit tier: the client-side reasoning-replay pipeline (#109, ADR D11 items 3-4).

The pipeline lives in `app/llm` (the session seam `app/llm/session.py` and the
new helper module `app/llm/reasoning.py`): (1) PARSE reasoning from each
response per the T3 capability profile (`reasoning_in_response` +
`reasoning_field`; profile unknown -> no parse, gap logged), (2) REPLAY the
parsed reasoning into the next turn's message history so provider-native KV
caching can hit (byte-identical prefix; encrypted reasoning is replayed as well
- readability is tracked, never skipped), (3) CACHE-TRACK `cached_tokens` as
OBSERVABILITY ONLY (never gating; heuristic proxies recorded as heuristic),
and (4) record reasoning readability via the langfuse llm-response metadata
field the seam's `_observe_config` feeds the Langfuse CallbackHandler.

The unit tier exercises the seam with a FAKE tool-calling model (T3 reader
mocked, LLM mocked) and an `InMemorySaver` - no live model, no live gateway,
no litellm (CODING_STANDARD sections 6, 10). Parse tests cover the two
ratified surfaces from ADR D11 item 5's amendment: `reasoning_content` at
message / `additional_kwargs` level, and `reasoning_details` via
`provider_specific_fields` (the surface litellm 1.96.0 relocates non-schema
message keys to - see `tests/test_gateway_reasoning_passthrough.py`).
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm import reasoning as R
from polymerhus.app.llm import session as S
from polymerhus.app.llm.capability import CapabilityProfile

# Sentinel values proving BYTE-IDENTICAL passthrough: any trim, rewrap or
# reordering breaks the exact-string equality (mirrors the gateway passthrough
# tests' sentinel discipline).
REASONING_CONTENT_SENTINEL = "chain-of-thought-sentinel-7f3a9c1d"
REASONING_DETAILS_SENTINEL = "details-sentinel-2b8e4f60"
ENCRYPTED_PAYLOAD = {"type": "encrypted_content", "encrypted_content": "encrypted-blob-sentinel-0a1b2c"}

# The T3 profile as the T2 sync authors it for a deepseek-family model
# (D11 item 1: interleaved: {"field": ...} -> reasoning_in_response + field).
PROFILE_CONTENT = CapabilityProfile(
    context_limit=150_000,
    output_limit=16_000,
    source="models.dev/deepseek",
    synced_at=None,
    reasoning_in_response=True,
    reasoning_field="reasoning_content",
)
PROFILE_DETAILS = CapabilityProfile(
    reasoning_in_response=True,
    reasoning_field="reasoning_details",
)
PROFILE_INTERLEAVED = CapabilityProfile(
    reasoning_in_response=True,
    reasoning_field=None,
)


# --- PARSE: profile gating -------------------------------------------------

def test_extract_no_parse_when_profile_unknown(caplog):
    """Profile unknown (None per D5 Rule 1) -> NO parse, gap logged. The
    absence of an authored capability is never asserted."""
    assert R.extract_reasoning(
        {"role": "assistant", "content": "a", "reasoning_content": "r"}, None
    ) is None
    assert "unknown" in caplog.text


def test_extract_no_parse_when_profile_disables_reasoning():
    """`reasoning_in_response` falsy/None -> no parse (the profile says
    reasoning never comes back in the response)."""
    msg = {"role": "assistant", "content": "a", "reasoning_content": "r"}
    for profile in (
        CapabilityProfile(reasoning_in_response=False, reasoning_field="reasoning_content"),
        CapabilityProfile(),  # unknown fields -> treated as no reasoning
    ):
        assert R.extract_reasoning(msg, profile) is None


# --- PARSE: reasoning_content at message / additional_kwargs level ---------

def test_extract_reasoning_content_at_message_level_dict():
    """`reasoning_content` reads at MESSAGE level on the wire-shaped dict -
    the `_client_side_reasoning` surface the D11 item-5 amendment ratified."""
    parsed = R.extract_reasoning(
        {"role": "assistant", "content": "answer", "reasoning_content": REASONING_CONTENT_SENTINEL},
        PROFILE_CONTENT,
    )
    assert parsed is not None
    assert parsed.reasoning == REASONING_CONTENT_SENTINEL
    assert parsed.surface == "reasoning_content"
    assert parsed.encrypted is False


def test_extract_reasoning_content_from_ai_message_additional_kwargs():
    """A langchain AIMessage carries `reasoning_content` in
    `additional_kwargs` (the surface langchain_core's own
    `_extract_reasoning_from_additional_kwargs` reads)."""
    msg = AIMessage(content="answer", additional_kwargs={"reasoning_content": REASONING_CONTENT_SENTINEL})
    parsed = R.extract_reasoning(msg, PROFILE_CONTENT)
    assert parsed is not None
    assert parsed.reasoning == REASONING_CONTENT_SENTINEL
    assert parsed.surface == "reasoning_content"


def test_extract_reasoning_content_from_ai_message_response_metadata():
    """Tolerant SDK-shape variance: `response_metadata` is the second surface
    a provider subclass may use to land the field on the AIMessage."""
    msg = AIMessage(content="answer", response_metadata={"reasoning_content": REASONING_CONTENT_SENTINEL})
    parsed = R.extract_reasoning(msg, PROFILE_CONTENT)
    assert parsed is not None
    assert parsed.reasoning == REASONING_CONTENT_SENTINEL


def test_extract_reasoning_content_from_content_block():
    """The langchain-core blessed block form (`{"type": "reasoning",
    "reasoning": ...}` - what `to_content_blocks` emits from additional_kwargs)
    parses too, so a message that was already materialised as blocks replays."""
    msg = AIMessage(content=[
        {"type": "reasoning", "reasoning": REASONING_CONTENT_SENTINEL},
        {"type": "text", "text": "answer"},
    ])
    parsed = R.extract_reasoning(msg, PROFILE_CONTENT)
    assert parsed is not None
    assert parsed.reasoning == REASONING_CONTENT_SENTINEL


# --- PARSE: reasoning_details via provider_specific_fields -----------------

def test_extract_reasoning_details_via_provider_specific_fields_dict():
    """`reasoning_details` reads via `message.provider_specific_fields.
    reasoning_details` (D11 item-5 amendment: litellm 1.96.0 relocates
    non-schema message keys there, byte-identical)."""
    msg = {
        "role": "assistant",
        "content": "answer",
        "provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL},
    }
    parsed = R.extract_reasoning(msg, PROFILE_DETAILS)
    assert parsed is not None
    assert parsed.reasoning == REASONING_DETAILS_SENTINEL
    assert parsed.surface == "reasoning_details"


def test_extract_reasoning_details_from_ai_message():
    """The same relocation surface on an AIMessage: `additional_kwargs`
    provider_specific_fields, then `response_metadata` (tolerant)."""
    via_kwargs = AIMessage(
        content="answer",
        additional_kwargs={"provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL}},
    )
    parsed = R.extract_reasoning(via_kwargs, PROFILE_DETAILS)
    assert parsed is not None
    assert parsed.reasoning == REASONING_DETAILS_SENTINEL
    assert parsed.surface == "reasoning_details"

    via_metadata = AIMessage(
        content="answer",
        response_metadata={"provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL}},
    )
    parsed = R.extract_reasoning(via_metadata, PROFILE_DETAILS)
    assert parsed is not None
    assert parsed.reasoning == REASONING_DETAILS_SENTINEL


def test_extract_interleaved_profile_accepts_both_surfaces():
    """D11 item 1: `interleaved: true` authors `reasoning_in_response` with
    `reasoning_field` ABSENT - the tolerant extractor tries content first,
    then the provider_specific_fields relocation surface (the
    `_client_side_reasoning` fallback order)."""
    content = R.extract_reasoning(
        {"role": "assistant", "content": "a", "reasoning_content": REASONING_CONTENT_SENTINEL},
        PROFILE_INTERLEAVED,
    )
    assert content is not None and content.surface == "reasoning_content"
    details = R.extract_reasoning(
        {"role": "assistant", "content": "a",
         "provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL}},
        PROFILE_INTERLEAVED,
    )
    assert details is not None and details.surface == "reasoning_details"


def test_extract_prefers_reasoning_content_over_details_when_both_present():
    """The `_client_side_reasoning` precedence: `reasoning_content` wins when
    both surfaces carry a value (content is the first-class schema field)."""
    parsed = R.extract_reasoning(
        {"role": "assistant", "content": "a",
         "reasoning_content": REASONING_CONTENT_SENTINEL,
         "provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL}},
        PROFILE_INTERLEAVED,
    )
    assert parsed is not None
    assert parsed.reasoning == REASONING_CONTENT_SENTINEL
    assert parsed.surface == "reasoning_content"


def test_extract_gap_when_expected_field_absent(caplog):
    """The profile names ONE field; a response carrying the OTHER surface is a
    gap (extract None + gap logged), never a wrong-surface guess."""
    msg = {"role": "assistant", "content": "a",
           "provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL}}
    assert R.extract_reasoning(msg, PROFILE_CONTENT) is None
    assert "gap" in caplog.text

    assert R.extract_reasoning(
        {"role": "assistant", "content": "a", "reasoning_content": "r"}, PROFILE_DETAILS
    ) is None


def test_extract_empty_or_missing_reasoning_is_absent():
    """None (and empty string - nothing to replay byte-identically) parse as
    absent, not as a value."""
    assert R.extract_reasoning({"role": "assistant", "content": "a"}, PROFILE_CONTENT) is None
    assert R.extract_reasoning(
        {"role": "assistant", "content": "a", "reasoning_content": ""}, PROFILE_CONTENT
    ) is None


def test_extract_encrypted_reasoning_kept_byte_identical():
    """Encrypted reasoning (D11 item 4) parses: the opaque payload is kept
    VERBATIM - never decrypted, never skipped - and flagged for readability."""
    parsed = R.extract_reasoning(
        {"role": "assistant", "content": "a", "reasoning_content": ENCRYPTED_PAYLOAD},
        PROFILE_CONTENT,
    )
    assert parsed is not None
    assert parsed.reasoning == ENCRYPTED_PAYLOAD
    assert parsed.encrypted is True


# --- REPLAY: attach + pure pipeline ---------------------------------------

def test_attach_reasoning_content_byte_identical():
    msg = AIMessage(content="answer")
    replayed = R.attach_reasoning(msg, R.ParsedReasoning(
        reasoning=REASONING_CONTENT_SENTINEL, surface="reasoning_content", encrypted=False))
    assert replayed.additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL
    assert replayed.content == "answer"


def test_attach_reasoning_details_byte_identical():
    msg = AIMessage(content="answer")
    replayed = R.attach_reasoning(msg, R.ParsedReasoning(
        reasoning=REASONING_DETAILS_SENTINEL, surface="reasoning_details", encrypted=False))
    assert replayed.additional_kwargs["provider_specific_fields"]["reasoning_details"] == (
        REASONING_DETAILS_SENTINEL
    )
    assert replayed.content == "answer"


def test_attach_encrypted_reasoning_byte_identical():
    """Encrypted reasoning attaches UNCHANGED (replay is not skipped on
    unreadable content); readability is tracked via the report, not by
    dropping the payload."""
    msg = AIMessage(content="answer")
    replayed = R.attach_reasoning(msg, R.ParsedReasoning(
        reasoning=ENCRYPTED_PAYLOAD, surface="reasoning_content", encrypted=True))
    assert replayed.additional_kwargs["reasoning_content"] == ENCRYPTED_PAYLOAD


def test_attach_merges_existing_additional_kwargs():
    msg = AIMessage(content="a", additional_kwargs={"tool_calls": [{"id": "t1"}]})
    replayed = R.attach_reasoning(msg, R.ParsedReasoning(
        reasoning="r", surface="reasoning_content", encrypted=False))
    assert replayed.additional_kwargs["tool_calls"] == [{"id": "t1"}]
    assert replayed.additional_kwargs["reasoning_content"] == "r"


def test_replay_pipeline_returns_replacement_only_when_parsed():
    """Unknown profile / not-expected / gap -> (None, report): nothing is
    re-persisted. Parsed -> the replacement trail with the assistant message
    carrying the reasoning, every OTHER message untouched."""
    messages = [HumanMessage(content="hi"), AIMessage(content="a1")]
    replacement, report = R.replay_assistant_reasoning(messages, PROFILE_CONTENT)
    assert replacement is None
    assert report["readability"] == "gap"

    replacement, report = R.replay_assistant_reasoning(messages, None)
    assert replacement is None
    assert report["readability"] == "unknown_profile"

    replacement, report = R.replay_assistant_reasoning(messages, CapabilityProfile())
    assert replacement is None
    assert report["readability"] == "not_expected"

    parsed_message = AIMessage(content="a2", additional_kwargs={
        "reasoning_content": REASONING_CONTENT_SENTINEL})
    replacement, report = R.replay_assistant_reasoning(messages + [parsed_message], PROFILE_CONTENT)
    assert replacement is not None
    assert replacement[0] is messages[0]  # untouched messages keep identity
    assert replacement[1] is messages[1]
    assert replacement[2].additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL
    assert report["readability"] == "parsed"
    assert report["surface"] == "reasoning_content"
    assert report["encrypted"] is False


def test_replay_pipeline_preserves_byte_identical_prefix():
    """The re-persisted trail equals the ORIGINAL trail with ONLY the
    reasoning field guaranteed on the assistant message: every message's
    content (and the sentinel bytes) unchanged."""
    messages = [
        HumanMessage(content="first user"),
        AIMessage(content="prior answer"),
        HumanMessage(content="second user"),
        AIMessage(content="final answer", additional_kwargs={
            "reasoning_content": REASONING_CONTENT_SENTINEL}),
    ]
    replacement, _report = R.replay_assistant_reasoning(messages, PROFILE_CONTENT)
    assert [m.content for m in replacement] == [m.content for m in messages]
    assert replacement[-1].additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL
    for original, replayed in zip(messages[:-1], replacement[:-1]):
        assert replayed is original


def test_replay_pipeline_normalises_noncanonical_surfaces():
    """Reasoning parsed from a NON-canonical surface (e.g. `response_metadata`
    - how a future/compat SDK lands it) is re-persisted onto the canonical
    `additional_kwargs` replay surface, content untouched."""
    messages = [HumanMessage(content="hi"), AIMessage(
        content="a1", response_metadata={"reasoning_content": REASONING_CONTENT_SENTINEL})]
    replacement, report = R.replay_assistant_reasoning(messages, PROFILE_CONTENT)
    assert replacement is not None
    assert replacement[-1].content == "a1"
    assert replacement[-1].additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL
    assert report["readability"] == "parsed"


def test_replay_pipeline_encrypted_payload():
    messages = [HumanMessage(content="hi"), AIMessage(content="a1", additional_kwargs={
        "reasoning_content": ENCRYPTED_PAYLOAD})]
    replacement, report = R.replay_assistant_reasoning(messages, PROFILE_CONTENT)
    assert replacement is not None
    assert replacement[-1].additional_kwargs["reasoning_content"] == ENCRYPTED_PAYLOAD
    assert report["encrypted"] is True
    assert report["readability"] == "parsed"


# --- CACHE-TRACK: observability only, never gating -------------------------

def test_cached_tokens_reads_usage_metadata_cache_read():
    """`usage.cached_tokens` arrives as `usage_metadata.input_token_details.
    cache_read` (the mapping `_create_usage_metadata` applies to the provider's
    `prompt_tokens_details.cached_tokens`)."""
    msg = AIMessage(content="a", usage_metadata={
        "input_tokens": 700, "output_tokens": 30, "total_tokens": 730,
        "input_token_details": {"cache_read": 500},
    })
    assert R.cached_tokens(msg) == 500
    assert R.cached_tokens(AIMessage(content="a")) is None


def test_cache_track_observability_only_never_gating():
    """cached_tokens is recorded as a report field; a cache-hit value never
    changes retries, timeouts or the turn outcome (#73 axis - off)."""
    messages = [HumanMessage(content="hi"), AIMessage(content="a1", usage_metadata={
        "input_tokens": 700, "output_tokens": 30, "total_tokens": 730,
        "input_token_details": {"cache_read": 500},
    }, additional_kwargs={"reasoning_content": "r"})]
    replacement, report = R.replay_assistant_reasoning(messages, PROFILE_CONTENT)
    assert report["cached_tokens"] == 500
    # low-confidence heuristic (D11 grey point): recorded, never a gate
    assert report["heuristic"] == "interleaved+shape+cache-presence"
    assert replacement is not None  # replay still happens - cache presence never gates


# --- LANGFUSE readability field -------------------------------------------

def test_readability_values():
    assert R.readability(None, None) == "unknown_profile"
    assert R.readability(CapabilityProfile(), None) == "not_expected"
    assert R.readability(PROFILE_CONTENT, None) == "gap"
    parsed = R.ParsedReasoning(reasoning="r", surface="reasoning_content", encrypted=False)
    assert R.readability(PROFILE_CONTENT, parsed) == "parsed"


def test_readability_metadata_from_thread_messages():
    """The langfuse llm-response field: `reasoning_readability` derived from
    the PERSISTED thread's last assistant message - "replayed" when the
    re-persisted reasoning is attached, "absent" otherwise, omitted when the
    thread has no assistant message yet."""
    replayed = AIMessage(content="a", additional_kwargs={"reasoning_content": "r"})
    assert R.reasoning_readability_metadata([replayed]) == {
        "reasoning_readability": "replayed",
        "reasoning_surface": "reasoning_content",
        "reasoning_encrypted": False,
    }
    assert R.reasoning_readability_metadata([AIMessage(content="a")]) == {
        "reasoning_readability": "absent",
    }
    assert R.reasoning_readability_metadata([HumanMessage(content="hi")]) == {}


# --- SEAM: parse + replay + observability through run_session_turn ---------

_received: list = []


class _ScriptedModel(BaseChatModel):
    """Scripted tool-calling fake: returns the next reply per call; a reply
    can carry reasoning (additional_kwargs) and usage metadata. Every call's
    received messages are appended to the module-level `_received`, so a
    resumed turn's restored prefix can be asserted (mirrors the `_tool_inputs`
    recording convention in test_llm_session.py)."""

    replies: list = []
    idx: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        _received.append(list(messages))
        return ChatResult(generations=[ChatGeneration(
            message=self.replies[min(i, len(self.replies) - 1)])])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _scripted_factory(*replies):
    def make(role_id):
        return _ScriptedModel(replies=list(replies), idx={})
    return make


def _thread_messages(saver, thread_id):
    tup = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    return list(tup.checkpoint["channel_values"]["messages"])


def _pin_profile(monkeypatch, profile):
    monkeypatch.setattr(S, "_resolve_reasoning_profile", lambda role_id: profile)


def test_seam_repersists_reasoning_byte_identical(monkeypatch):
    """Turn 1 parses reasoning_content from the model reply and RE-PERSISTS it
    onto the checkpointed assistant message byte-identical; turn 2 restores
    that message with the reasoning attached (the replay-ready prefix)."""
    _pin_profile(monkeypatch, PROFILE_CONTENT)
    _received.clear()
    saver = InMemorySaver()
    reasoning_reply = AIMessage(content="a1", additional_kwargs={
        "reasoning_content": REASONING_CONTENT_SENTINEL})
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                       checkpointer=saver, model_factory=_scripted_factory(reasoning_reply),
                       observe=False)
    persisted = _thread_messages(saver, "run1:triager")
    assert persisted[-1].additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL

    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="again")],
                       checkpointer=saver, model_factory=_scripted_factory(
                           AIMessage(content="a2", additional_kwargs={
                               "reasoning_content": REASONING_CONTENT_SENTINEL})),
                       observe=False)
    seen = _received[-1]
    assert seen[1].additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL
    assert [m.content for m in seen] == ["hi", "a1", "again"]


def test_seam_repersists_reasoning_details_via_provider_specific_fields(monkeypatch):
    """The D11 item-5 ratified details surface flows through the seam too: the
    checkpoint carries `additional_kwargs["provider_specific_fields"]
    ["reasoning_details"]` byte-identical."""
    _pin_profile(monkeypatch, PROFILE_DETAILS)
    saver = InMemorySaver()
    reply = AIMessage(content="a1", additional_kwargs={
        "provider_specific_fields": {"reasoning_details": REASONING_DETAILS_SENTINEL}})
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                       checkpointer=saver, model_factory=_scripted_factory(reply), observe=False)
    persisted = _thread_messages(saver, "run1:triager")
    assert persisted[-1].additional_kwargs["provider_specific_fields"]["reasoning_details"] == (
        REASONING_DETAILS_SENTINEL
    )


def test_seam_repersists_encrypted_reasoning(monkeypatch):
    """Encrypted reasoning is replayed as well - the payload lands in the
    checkpoint verbatim (readability tracked, replay never skipped)."""
    _pin_profile(monkeypatch, PROFILE_CONTENT)
    saver = InMemorySaver()
    reply = AIMessage(content="a1", additional_kwargs={"reasoning_content": ENCRYPTED_PAYLOAD})
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                       checkpointer=saver, model_factory=_scripted_factory(reply), observe=False)
    persisted = _thread_messages(saver, "run1:triager")
    assert persisted[-1].additional_kwargs["reasoning_content"] == ENCRYPTED_PAYLOAD


def test_seam_gap_when_profile_unknown_leaves_thread_untouched(monkeypatch, caplog):
    """Unknown profile -> NO parse, gap logged, the re-persist NORMALISATION
    does not happen: the reasoning still sits on the surface the model
    emitted (response_metadata), never moved onto the canonical replay
    surface."""
    _pin_profile(monkeypatch, None)
    saver = InMemorySaver()
    reply = AIMessage(content="a1", response_metadata={"reasoning_content": "r"})
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                       checkpointer=saver, model_factory=_scripted_factory(reply), observe=False)
    persisted = _thread_messages(saver, "run1:triager")
    assert persisted[-1].additional_kwargs == {}
    assert persisted[-1].response_metadata["reasoning_content"] == "r"
    assert "unknown" in caplog.text


def test_seam_turn_succeeds_when_no_env_profile():
    """The production default path (no env vars, no gateway): the profile
    resolves unknown, replay no-ops, and the turn completes - fail-open, the
    session must always be able to start."""
    saver = InMemorySaver()
    turn = S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                              checkpointer=saver, model_factory=_scripted_factory(
                                  AIMessage(content="a1")),
                              observe=False)
    assert turn.content == "a1"


def test_seam_cache_track_observability_logged_not_gating(monkeypatch, caplog):
    """cached_tokens flows into the observability log line as a field; the
    turn still completes and replay still happens (no gating on the cache)."""
    caplog.set_level("INFO")
    _pin_profile(monkeypatch, PROFILE_CONTENT)
    saver = InMemorySaver()
    reply = AIMessage(content="a1",
                      additional_kwargs={"reasoning_content": "r"},
                      usage_metadata={"input_tokens": 700, "output_tokens": 30,
                                      "total_tokens": 730,
                                      "input_token_details": {"cache_read": 500}})
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                       checkpointer=saver, model_factory=_scripted_factory(reply), observe=False)
    assert "cached_tokens=500" in caplog.text
    assert "heuristic" in caplog.text
    assert _thread_messages(saver, "run1:triager")[-1].additional_kwargs["reasoning_content"] == "r"


def test_seam_langfuse_metadata_carries_reasoning_readability(monkeypatch):
    """The llm-response metadata the seam feeds the Langfuse CallbackHandler
    carries the dedicated `reasoning_readability` field - "replayed" on the
    turn after a parsed+re-persisted response (the same session trace, D11
    item 4's readability tracking)."""
    _pin_profile(monkeypatch, PROFILE_CONTENT)
    captured: list[dict] = []

    real_observe = S._observe_config

    def spy(config, role_id, thread_id, **kwargs):
        updated = real_observe(config, role_id, thread_id, **kwargs)
        captured.append(dict(updated["metadata"]))
        return updated

    monkeypatch.setattr(S, "_observe_config", spy)
    saver = InMemorySaver()
    reply = AIMessage(content="a1", additional_kwargs={"reasoning_content": "r"})
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="hi")],
                       checkpointer=saver, model_factory=_scripted_factory(reply), observe=True)
    S.run_session_turn("triager", "run1:triager", [HumanMessage(content="again")],
                       checkpointer=saver, model_factory=_scripted_factory(
                           AIMessage(content="a2")),
                       observe=True)
    assert "reasoning_readability" not in captured[0]  # first turn: no prior response
    assert captured[1]["reasoning_readability"] == "replayed"  # second: prior response re-persisted
    assert captured[1]["reasoning_surface"] == "reasoning_content"


def test_arun_session_turn_repersists_reasoning(monkeypatch):
    """The async entry point runs the same replay re-persist (aupdate_state)."""
    _pin_profile(monkeypatch, PROFILE_CONTENT)
    saver = InMemorySaver()
    reply = AIMessage(content="a1", additional_kwargs={"reasoning_content": REASONING_CONTENT_SENTINEL})

    async def _turn():
        return await S.arun_session_turn(
            "triager", "run1:triager", [HumanMessage(content="hi")],
            checkpointer=saver, model_factory=_scripted_factory(reply), observe=False)

    asyncio.run(_turn())
    persisted = _thread_messages(saver, "run1:triager")
    assert persisted[-1].additional_kwargs["reasoning_content"] == REASONING_CONTENT_SENTINEL


def test_stateful_turn_still_returns_content_with_replay_enabled(monkeypatch):
    """`stateful_turn` (the ubiquitous stateful-agent pattern) keeps its
    contract with the pipeline active: content is returned and the thread
    resumes with the replayed reasoning in place."""
    _pin_profile(monkeypatch, PROFILE_CONTENT)
    saver = InMemorySaver()
    first = S.stateful_turn("triager", "run1:triager", [HumanMessage(content="a")],
                            checkpointer=saver, model_factory=_scripted_factory(
                                AIMessage(content="1", additional_kwargs={
                                    "reasoning_content": "r"})),
                            observe=False)
    second = S.stateful_turn("triager", "run1:triager", [HumanMessage(content="b")],
                             checkpointer=saver, model_factory=_scripted_factory(
                                 AIMessage(content="3")),
                             observe=False)
    assert first == "1"
    assert second == "3"
    persisted = _thread_messages(saver, "run1:triager")
    assert persisted[1].additional_kwargs["reasoning_content"] == "r"