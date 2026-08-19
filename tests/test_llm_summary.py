"""Unit tier: the running-summary engine (#95 slice C, ADR D5/D6).

The summarisation half: ONE atomic call per compact pass, quality-gated (D5),
running under the #73 single escalating retry layer with the D6 failure
taxonomy - a window-cap 4xx is TERMINAL for the pass (never retried with
identical input), transient failures retry, exhaustion is a failed pass. The
consecutive-pass cap (3) is slice D's concern; this module only exposes the
three-way status. A fake summariser is injected throughout - no live model, no
live gateway, no database (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import dataclasses
import datetime as dt

import httpx
from langchain_core.messages import AIMessage, HumanMessage
from openai import BadRequestError

from polymerhus.app.llm import summary as S

GOOD_TEXT = ("The Next.js webapp exposes a login flow; enumeration found "
             "three auth endpoints and two are already patched.")
SHORT_TEXT = "tiny"
FLOOR = S.SUMMARY_MIN_FLOOR_CHARS


def _good_update(summary_text=GOOD_TEXT, decisions=None, evidence_refs=None, open_threads=None):
    return S.SummaryUpdate(
        summary_text=summary_text,
        decisions=list(decisions or []),
        evidence_refs=list(evidence_refs or []),
        open_threads=list(open_threads or []),
    )


def _openai_window_error() -> BadRequestError:
    """A real `openai.BadRequestError` in the exact shape the provider returns
    for a request that exceeds the model's window (D6) - code, message, body."""
    req = httpx.Request("POST", "http://x")
    resp = httpx.Response(400, request=req)
    body = {
        "error": {
            "code": "context_length_exceeded",
            "message": "This model's maximum context length is 128000 tokens.",
            "type": "invalid_request_error",
            "param": None,
        }
    }
    return BadRequestError(message=str(body), response=resp, body=body)


# --- the running summary shape -----------------------------------------------

def test_running_summary_is_frozen_with_tuple_list_fields():
    """The running summary carries the narrative plus the three list fields as
    immutable tuples, defaulting to empty when not supplied."""
    rs = S.RunningSummary(summary_text=GOOD_TEXT)
    assert rs.summary_text == GOOD_TEXT
    assert rs.decisions == ()
    assert rs.evidence_refs == ()
    assert rs.open_threads == ()

    rs2 = S.RunningSummary(
        summary_text=GOOD_TEXT,
        decisions=("d1",),
        evidence_refs=("ref-1",),
        open_threads=("t1",),
    )
    assert rs2.decisions == ("d1",)


def test_running_summary_to_text_renders_compact_narrative():
    """to_text renders a single compact narrative string carrying the narrative
    and the preserved decisions/evidence/open-threads (the synthetic exchange
    slice D persists)."""
    rs = S.RunningSummary(
        summary_text=GOOD_TEXT,
        decisions=("d1",),
        evidence_refs=("ref-1",),
        open_threads=("t1",),
    )
    text = rs.to_text()
    assert isinstance(text, str)
    assert GOOD_TEXT in text
    assert "d1" in text and "ref-1" in text and "t1" in text


def test_summary_update_is_the_structured_schema():
    """SummaryUpdate is the pydantic structured-output schema carrying the same
    four fields."""
    u = S.SummaryUpdate(
        summary_text=GOOD_TEXT,
        decisions=["d1"],
        evidence_refs=["ref-1"],
        open_threads=["t1"],
    )
    assert u.decisions == ["d1"]
    assert u.summary_text == GOOD_TEXT


# --- message composition -----------------------------------------------------

def test_build_messages_system_prompts_the_four_field_template():
    """The SYSTEM prompt states the job and presents the output template - the
    exact four fields, nothing invented."""
    msgs = S.build_summary_messages(None, [HumanMessage(content="span")])
    assert msgs[0].type == "system"
    for field in ("summary_text", "decisions", "evidence_refs", "open_threads"):
        assert field in msgs[0].content


def test_build_messages_user_carries_prior_summary_and_spans():
    """The USER message carries the prior running summary plus the spans being
    condensed - the atomic call's whole input."""
    prior = S.RunningSummary(
        summary_text="PRIOR-NARRATIVE told the decisions so far.",
        decisions=("d0",),
        evidence_refs=("r0",),
        open_threads=("t0",),
    )
    spans = [HumanMessage(content="span one"), AIMessage(content="span two")]
    msgs = S.build_summary_messages(prior, spans)
    assert msgs[1].type == "human"
    assert "PRIOR-NARRATIVE" in msgs[1].content
    assert "span one" in msgs[1].content and "span two" in msgs[1].content


def test_build_messages_without_prior_says_none_yet():
    """No prior summary is stated honestly, never fabricated."""
    msgs = S.build_summary_messages(None, ["raw span text"])
    assert msgs[1].type == "human"
    assert "none yet" in msgs[1].content
    assert "raw span text" in msgs[1].content


# --- the output-quality gate (D5) --------------------------------------------

def test_quality_gate_accepts_a_good_summary():
    assert S.is_quality_summary(_good_update(GOOD_TEXT)) is True


def test_quality_gate_accepts_empty_lists():
    """The list fields may be empty (they are LISTS, not None) - the narrative is
    the mandatory content."""
    assert S.is_quality_summary(S.SummaryUpdate(summary_text=GOOD_TEXT)) is True
    assert S.is_quality_summary(_good_update(GOOD_TEXT, decisions=[], evidence_refs=[], open_threads=[])) is True


def test_quality_gate_rejects_empty_and_degenerate_summaries():
    assert S.is_quality_summary(_good_update("")) is False
    assert S.is_quality_summary(_good_update("   ")) is False
    assert S.is_quality_summary(_good_update("x" * (FLOOR - 1))) is False
    assert S.is_quality_summary(_good_update("x" * FLOOR)) is True


def test_quality_gate_rejects_unparseable_inputs():
    """A list field that is None (or not a list at all), or a non-Update object,
    is a FAILED generation - never a silent pass, never a raise (fail-open)."""
    none_field = S.SummaryUpdate.model_construct(
        summary_text=GOOD_TEXT, decisions=None, evidence_refs=[], open_threads=[])
    assert S.is_quality_summary(none_field) is False
    str_field = S.SummaryUpdate.model_construct(
        summary_text=GOOD_TEXT, decisions="not-a-list", evidence_refs=[], open_threads=[])
    assert S.is_quality_summary(str_field) is False
    assert S.is_quality_summary(None) is False
    assert S.is_quality_summary({"summary_text": GOOD_TEXT}) is False


# --- the atomic call + failure taxonomy (D5/D6) ------------------------------

def test_summarise_ok_returns_a_running_summary():
    """A good fake result yields status ok and a RunningSummary whose list fields
    are tuples - the summary is convertible back into a RunningSummary."""
    seen = {}
    def fake(messages, budget):
        seen["messages"] = messages
        return _good_update(GOOD_TEXT, decisions=["d1"], evidence_refs=["ref-1"])
    outcome = S.summarise(fake, existing=None, spans=[HumanMessage(content="span")])
    assert outcome.status == "ok"
    assert isinstance(outcome.summary, S.RunningSummary)
    assert outcome.summary.summary_text == GOOD_TEXT
    assert outcome.summary.decisions == ("d1",)
    assert outcome.summary.evidence_refs == ("ref-1",)
    assert "summary_text" in seen["messages"][0].content
    assert "none yet" in seen["messages"][1].content


def test_summarise_passes_existing_and_spans_into_the_call():
    """The fake receives the composed messages: the prior summary and the spans
    both arrive in the USER message (atomic call input)."""
    prior = S.RunningSummary(
        summary_text="PRIOR-NARRATIVE told the decisions so far.",
        decisions=("d0",), evidence_refs=("r0",), open_threads=("t0",))
    seen = {}
    def fake(messages, budget):
        seen["user"] = messages[-1].content
        return _good_update(GOOD_TEXT)
    outcome = S.summarise(fake, existing=prior, spans=["NEW-SPAN", HumanMessage(content="MSG-SPAN")])
    assert outcome.status == "ok"
    assert "PRIOR-NARRATIVE" in seen["user"]
    assert "NEW-SPAN" in seen["user"] and "MSG-SPAN" in seen["user"]


def test_summarise_exhaustion_returns_failed(monkeypatch):
    """Always-None (the fail-closed transient signal) retries under the schedule
    and exhausts to status failed with no summary - the caller's fail-closed."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        return None
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "failed"
    assert outcome.summary is None
    assert len(calls) == 3


def test_summarise_transient_raise_exhausts_to_failed(monkeypatch):
    """A raised attempt (transport/timeout) is retried per the schedule and
    exhausts to status failed."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        raise TimeoutError("read timed out")
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "failed"
    assert outcome.summary is None
    assert len(calls) == 3


def test_summarise_weak_result_is_retried(monkeypatch):
    """A degenerate short summary (D5 quality gate) is a FAILED generation and is
    retried under the single retry layer - a later good attempt recovers to ok."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        return _good_update(GOOD_TEXT) if len(calls) > 1 else _good_update(SHORT_TEXT)
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "ok"
    assert len(calls) == 2


def test_summarise_weak_result_exhausts_to_failed(monkeypatch):
    """Only weak results -> every attempt is None, the schedule exhausts, failed."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        return _good_update(SHORT_TEXT)
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "failed"
    assert outcome.summary is None
    assert len(calls) == 3


def test_summarise_terminal_window_error_never_retries(monkeypatch):
    """A window-cap error is TERMINAL for the pass: the summariser is invoked
    EXACTLY ONCE - an identical retry would always fail identically (D6)."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        raise _openai_window_error()
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "terminal"
    assert outcome.summary is None
    assert len(calls) == 1


# --- terminal classification (D6) --------------------------------------------

def test_classify_terminal_recognises_context_length_code():
    """The openai BadRequestError shape's `code` (context_length_exceeded) is the
    canonical window-cap signal."""
    assert S.classify_terminal(_openai_window_error()) is True


def test_classify_terminal_recognises_message_markers():
    assert S.classify_terminal(Exception("maximum context length exceeded")) is True
    assert S.classify_terminal(Exception("request too large: context length 150000")) is True
    assert S.classify_terminal(Exception("MaxImUm CoNtExT LeNgTh")) is True


def test_classify_terminal_rejects_unrecognised_errors_fail_open():
    """Anything unrecognised is NOT terminal - and classification never raises
    on garbage input (fail-open)."""
    assert S.classify_terminal(RuntimeError("connection reset")) is False
    assert S.classify_terminal(TimeoutError("read timed out")) is False
    assert S.classify_terminal(Exception("429 too many requests")) is False
    assert S.classify_terminal(None) is False
    assert S.classify_terminal("not an exception") is False


# --- the per-thread summary ledger (D5/D6, driven by slice D) ----------------

def test_ledger_entry_exposes_exactly_the_contract_fields():
    """The entry's shape is exactly the ADR D5 field set - the object slice D drives."""
    names = {f.name for f in dataclasses.fields(S.SummaryLedgerEntry)}
    assert names == {
        "updated_at", "turn_count", "reclaimed_tokens",
        "last_compacted_at", "spans", "over_budget",
    }


def test_ledger_records_and_reads_required_fields():
    ledger = S.SummaryLedger()
    at = dt.datetime(2026, 8, 18, tzinfo=dt.timezone.utc)
    compacted = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.timezone.utc)
    entry = ledger.record(
        "thr1",
        updated_at=at,
        turn_count=4,
        reclaimed_tokens=12500,
        last_compacted_at=compacted,
        spans=23,
        over_budget=False,
    )
    assert entry.updated_at == at
    assert entry.turn_count == 4
    assert entry.reclaimed_tokens == 12500
    assert entry.last_compacted_at == compacted
    assert entry.spans == 23
    assert entry.over_budget is False
    assert ledger.entry("thr1") is entry
    assert ledger.entry("unknown") is None


def test_ledger_record_defaults_when_fields_omitted():
    """record stamps a now() updated_at and safe default field values."""
    ledger = S.SummaryLedger()
    entry = ledger.record("thr2", turn_count=1)
    assert isinstance(entry.updated_at, dt.datetime)
    assert entry.reclaimed_tokens == 0
    assert entry.last_compacted_at is None
    assert entry.spans == 0
    assert entry.over_budget is False