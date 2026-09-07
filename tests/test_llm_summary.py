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
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from openai import BadRequestError

from polymerhus.app.llm import summary as S
from polymerhus.app.llm.compaction import approx_tokens

GOOD_OBJECTIVE = "Enumerate and patch the auth endpoints of the target webapp."
GOOD_RESUME = "probe the third, still-unpatched auth endpoint"
SHORT_TEXT = "tiny"


def _good_update(objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME, **kwargs):
    fields = dict(objective=objective, resume_point=resume_point)
    fields.update(kwargs)
    return S.SummaryUpdate(**fields)


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
    """The running summary carries the eight concepts as immutable fields; the
    list concepts are tuples defaulting to empty, and task_status is nested."""
    rs = S.RunningSummary(objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME)
    assert rs.objective == GOOD_OBJECTIVE
    assert rs.resume_point == GOOD_RESUME
    assert rs.dead_branches == ()
    assert rs.decisions == ()
    assert rs.artifacts == ()
    assert rs.task_status.done == ()
    assert rs.task_status.in_progress == ()
    assert rs.task_status.remaining == ()

    rs2 = S.RunningSummary(
        objective=GOOD_OBJECTIVE,
        task_status=S.TaskStatus(done=("d1",), remaining=("r1",)),
        decisions=("dec1",),
        artifacts=("art-1",),
        resume_point=GOOD_RESUME,
    )
    assert rs2.decisions == ("dec1",)
    assert rs2.task_status.done == ("d1",)


def test_running_summary_to_text_renders_static_template():
    """to_text renders the static markdown template - every concept under its
    header with markdown structure elements - the synthetic exchange slice D persists."""
    rs = S.RunningSummary(
        objective=GOOD_OBJECTIVE,
        workflow="recon then patch",
        environment_state="two of three patched",
        task_status=S.TaskStatus(done=("a",), in_progress=("b",), remaining=("c",)),
        dead_branches=("dead-1",),
        decisions=("dec-1",),
        artifacts=("art-1",),
        resume_point=GOOD_RESUME,
    )
    text = rs.to_text()
    assert isinstance(text, str)
    assert text.startswith("[running summary]")
    # Markdown headers with sub-lists: the template uses headers and markdown
    # list elements, not flat colon labels. Lists under each paragraph are
    # generic and PREVIOUS DECISIONS / DISCOVERED ARTIFACTS are lists.
    for header in ("## Objective", "## Workflow", "## Environment State",
                   "## Task Status", "## Dead Branches Probed",
                   "## Previous Decisions with Rationale",
                   "## Discovered Crucial Artifacts", "## Resume Point"):
        assert header in text
    for sub in ("- Done:", "- In Progress:", "- Remaining:"):
        assert sub in text
    # Lists are rendered as markdown bullets, including the two explicitly
    # list-bearing concepts and the generic task-status sub-lists.
    for bullet in ("- dead-1", "- dec-1", "- art-1", "  - a", "  - b", "  - c"):
        assert bullet in text
    for value in (GOOD_OBJECTIVE, "recon then patch", GOOD_RESUME):
        assert value in text


def test_summary_update_is_the_structured_schema():
    """SummaryUpdate is the pydantic structured-output schema carrying the eight
    concepts; objective and resume_point are REQUIRED (no default)."""
    u = S.SummaryUpdate(objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME,
                        decisions=["d1"], artifacts=["art-1"])
    assert u.objective == GOOD_OBJECTIVE
    assert u.resume_point == GOOD_RESUME
    assert u.decisions == ["d1"]
    assert u.task_status.done == []


# --- message composition -----------------------------------------------------

def test_build_messages_system_prompts_the_concept_template():
    """The SYSTEM prompt states the job and presents the eight core concepts and
    the length target - nothing invented."""
    msgs = S.build_summary_messages(None, [HumanMessage(content="span")])
    assert msgs[0].type == "system"
    for concept in ("OBJECTIVE", "WORKFLOW", "ENVIRONMENT STATE", "TASK STATUS",
                    "DEAD BRANCHES", "DECISIONS", "ARTIFACTS", "RESUME POINT",
                    "200-500 tokens"):
        assert concept in msgs[0].content


def test_build_messages_user_carries_prior_summary_and_spans():
    """The USER message carries the prior running summary plus the spans being
    condensed - the atomic call's whole input."""
    prior = S.RunningSummary(
        objective="PRIOR-OBJECTIVE told the decisions so far.",
        decisions=("d0",),
        resume_point="prior resume point",
    )
    spans = [HumanMessage(content="span one"), AIMessage(content="span two")]
    msgs = S.build_summary_messages(prior, spans)
    assert msgs[1].type == "human"
    assert "PRIOR-OBJECTIVE" in msgs[1].content
    assert "span one" in msgs[1].content and "span two" in msgs[1].content


def test_build_messages_without_prior_says_none_yet():
    """No prior summary is stated honestly, never fabricated."""
    msgs = S.build_summary_messages(None, ["raw span text"])
    assert msgs[1].type == "human"
    assert "none yet" in msgs[1].content
    assert "raw span text" in msgs[1].content


# --- the output-quality gate (D5) --------------------------------------------

def test_quality_gate_accepts_a_good_summary():
    assert S.is_quality_summary(_good_update()) is True


def test_quality_gate_accepts_empty_lists():
    """The list fields may be empty (they are LISTS, not None) - objective and
    resume_point are the mandatory content."""
    assert S.is_quality_summary(S.SummaryUpdate(objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME)) is True
    assert S.is_quality_summary(
        _good_update(decisions=[], dead_branches=[], artifacts=[])) is True


def test_quality_gate_rejects_missing_mandatory_fields():
    """A summary missing its objective or resume point is a FAILED generation."""
    assert S.is_quality_summary(_good_update(objective="")) is False
    assert S.is_quality_summary(_good_update(objective="   ")) is False
    assert S.is_quality_summary(_good_update(resume_point="")) is False
    assert S.is_quality_summary(_good_update(resume_point=SHORT_TEXT)) is True


def test_quality_gate_rejects_unparseable_inputs():
    """A list field that is None (or not a list at all), a malformed
    task_status, or a non-Update object, is a FAILED generation - never a silent
    pass, never a raise (fail-open)."""
    none_field = S.SummaryUpdate.model_construct(
        objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME,
        decisions=None, dead_branches=[], artifacts=[])
    assert S.is_quality_summary(none_field) is False
    str_field = S.SummaryUpdate.model_construct(
        objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME,
        decisions="not-a-list", dead_branches=[], artifacts=[])
    assert S.is_quality_summary(str_field) is False
    bad_task = S.SummaryUpdate.model_construct(
        objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME, task_status="not-a-task")
    assert S.is_quality_summary(bad_task) is False
    assert S.is_quality_summary(None) is False
    assert S.is_quality_summary({"objective": GOOD_OBJECTIVE}) is False


# --- the atomic call + failure taxonomy (D5/D6) ------------------------------

def test_summarise_ok_returns_a_running_summary():
    """A good fake result yields status ok and a RunningSummary whose list fields
    are tuples - the summary is convertible back into a RunningSummary."""
    seen = {}
    def fake(messages, budget):
        seen["messages"] = messages
        return _good_update(decisions=["d1"], artifacts=["art-1"])
    outcome = S.summarise(fake, existing=None, spans=[HumanMessage(content="span")])
    assert outcome.status == "ok"
    assert isinstance(outcome.summary, S.RunningSummary)
    assert outcome.summary.objective == GOOD_OBJECTIVE
    assert outcome.summary.resume_point == GOOD_RESUME
    assert outcome.summary.decisions == ("d1",)
    assert outcome.summary.artifacts == ("art-1",)
    assert "OBJECTIVE" in seen["messages"][0].content
    assert "none yet" in seen["messages"][1].content


def test_summarise_passes_existing_and_spans_into_the_call():
    """The fake receives the composed messages: the prior summary and the spans
    both arrive in the USER message (atomic call input)."""
    prior = S.RunningSummary(
        objective="PRIOR-OBJECTIVE told the decisions so far.",
        decisions=("d0",),
        resume_point="prior resume",
    )
    seen = {}
    def fake(messages, budget):
        seen["user"] = messages[-1].content
        return _good_update()
    outcome = S.summarise(fake, existing=prior, spans=["NEW-SPAN", HumanMessage(content="MSG-SPAN")])
    assert outcome.status == "ok"
    assert "PRIOR-OBJECTIVE" in seen["user"]
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
    """A summary missing its objective (D5 quality gate) is a FAILED generation
    and is retried under the single retry layer - a later good attempt recovers."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        return _good_update() if len(calls) > 1 else _good_update(objective="")
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "ok"
    assert len(calls) == 2


def test_summarise_weak_result_exhausts_to_failed(monkeypatch):
    """Only weak results -> every attempt is None, the schedule exhausts, failed."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        return _good_update(resume_point="")
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "failed"
    assert outcome.summary is None
    assert len(calls) == 3


def test_summarise_window_error_degrades_to_failed_never_retries(monkeypatch):
    """A window-cap error is NEVER retried (D6 - an identical retry always fails
    identically): the summariser is invoked EXACTLY ONCE. #210 Track B retires the
    'terminal' status - a window-cap now degrades to 'failed' (operator ruling)."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1,1,1")
    calls = []
    def fake(messages, budget):
        calls.append(budget)
        raise _openai_window_error()
    outcome = S.summarise(fake, existing=None, spans=[])
    assert outcome.status == "failed"
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


# --- window-splitting summarisation (#210 Track B, never terminal) -----------

def _span(size_chars=1500, content=None):
    return AIMessage(content=content if content is not None else "s" * size_chars)


def _sys_tokens():
    return approx_tokens([SystemMessage(content=S._SYSTEM_PROMPT)])


def test_largest_prefix_fitting_is_span_granular_and_budget_bounded():
    """C5/C3: the largest prefix fitting within the budget is WHOLE spans (never
    mid-span), and the existing-summary growth is accounted (the bound re-measures
    with a larger existing -> fewer spans fit)."""
    spans = [_span(), _span(), _span()]
    budget = _sys_tokens() + 700  # ~one span fits per chunk
    assert S._largest_prefix_fitting(None, spans, budget) == 1
    assert S._largest_prefix_fitting(None, spans, _sys_tokens() + 100_000) == 3
    # a larger existing shrinks what fits - the bound accounts for the fold growth
    small = [_span(300), _span(300), _span(300)]  # ~75 tokens each
    two_fit = _sys_tokens() + 200  # the None case holds two small spans
    assert S._largest_prefix_fitting(None, small, two_fit) == 2
    big_existing = S.RunningSummary(objective="O" * 3000, resume_point="R" * 3000)
    assert S._largest_prefix_fitting(big_existing, small, two_fit) == 1


def test_largest_prefix_fitting_never_returns_zero_on_an_irreducible_span():
    """Q4: even when the FIRST span alone overflows the budget, the prefix count
    is still at least ONE (the irreducible single-span case) - the fold loop must
    never stall on an empty chunk."""
    from langchain_core.messages import SystemMessage
    budget = _sys_tokens()  # the system prompt alone fills the budget
    spans = [_span(), _span()]
    assert S._largest_prefix_fitting(None, spans, budget) == 1
    # an even smaller budget still returns at least one span
    assert S._largest_prefix_fitting(None, spans, 10) == 1


def test_summarise_splits_and_folds_progressively_never_terminal():
    """C1/C2: when the composed input exceeds the window, the spans split into
    window-fitting chunks and fold progressively - chunk k's summary becomes chunk
    k+1's existing, and the final summary is the single chainable RunningSummary,
    never a terminal pass."""
    spans = [_span(), _span(), _span()]
    budget = _sys_tokens() + 700  # forces chunking into ~one span per chunk
    calls = []
    def fake(messages, budget):
        user = messages[-1].content
        calls.append(user)
        return S.SummaryUpdate(objective=f"obj-{len(calls)-1}", resume_point="r")
    outcome = S.summarise(fake, existing=None, spans=spans, chunk_budget=budget)
    assert outcome.status == "ok"
    assert isinstance(outcome.summary, S.RunningSummary)
    assert len(calls) >= 2  # chunking happened - more than one atomic call
    # progressive fold: chunk 1's summary is the prior of chunk 2
    assert "obj-0" in calls[1]
    assert "obj-1" in calls[2]


def test_summarise_keeps_the_single_atomic_call_when_it_fits():
    """The common case is unchanged: when the composed input fits within the
    budget there is exactly ONE atomic call - no chunking overhead."""
    spans = [_span(50)]
    budget = _sys_tokens() + 100_000
    calls = []
    def fake(messages, budget):
        calls.append(1)
        return S.SummaryUpdate(objective="obj", resume_point="r")
    outcome = S.summarise(fake, existing=None, spans=spans, chunk_budget=budget)
    assert outcome.status == "ok"
    assert len(calls) == 1


def test_summarise_chunk_failure_after_success_returns_partial_ok(monkeypatch):
    """C4 + grey point 5: a weak chunk is retried under the #73 schedule; when a
    later chunk exhausts retries the pass ABORTS but still returns the chainable
    partial summary from the succeeded prefix as 'ok' - never terminal, and a
    partial summary is applied (strictly better than the over-budget original)."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "0.05,0.05,0.05")
    spans = [_span(), _span(), _span()]
    budget = _sys_tokens() + 700
    calls = []
    def fake(messages, budget):
        calls.append(1)
        if len(calls) == 1:
            return S.SummaryUpdate(objective="obj-first", resume_point="r")
        return None  # every later chunk is weak -> exhausts retries
    outcome = S.summarise(fake, existing=None, spans=spans, chunk_budget=budget)
    assert outcome.status == "ok"
    assert outcome.summary is not None
    assert outcome.summary.objective == "obj-first"
    assert len(calls) == 1 + 3  # 1 success + 3 retries of the failing 2nd chunk


def test_summarise_first_chunk_failure_returns_failed(monkeypatch):
    """C4: when NO chunk yields a summary (the first chunk fails), the pass is
    'failed' with no summary - the whole-pass-failed case."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "0.05,0.05,0.05")
    spans = [_span(), _span(), _span()]
    budget = _sys_tokens() + 700
    calls = []
    def fake(messages, budget):
        calls.append(1)
        return None
    outcome = S.summarise(fake, existing=None, spans=spans, chunk_budget=budget)
    assert outcome.status == "failed"
    assert outcome.summary is None
    assert len(calls) == 3  # only the first chunk's retries


def test_summarise_irreducible_single_span_overflow_degrades_to_failed(monkeypatch):
    """Q4: a single span that still overflows is the only irreducible exit - it
    escapes the retry (invoked once) but degrades to 'failed', never 'terminal'."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "0.05,0.05,0.05")
    calls = []
    def terminal(messages, budget):
        calls.append(1)
        raise Exception("maximum context length exceeded")
    outcome = S.summarise(terminal, existing=None, spans=[_span()], chunk_budget=10)
    assert outcome.status == "failed"
    assert outcome.summary is None
    assert len(calls) == 1  # a window-cap never burns the escalating retry


def test_summarise_spans_are_never_split_reasoning_passes_through():
    """C3: a chunk is a prefix of the ordered span list - a span is never split.
    A projected-reasoning span (the #206 fix, landing later) passes through
    unmodified because the chunker never inspects message content."""
    reasoning = AIMessage(content="REASONING-CORE-CONCLUSION")
    spans = [_span(), reasoning, _span()]
    budget = _sys_tokens() + 700
    seen_spans: list = []
    def fake(messages, budget):
        user = messages[-1].content
        seen_spans.append(user)
        return S.SummaryUpdate(objective="obj", resume_point="r")
    S.summarise(fake, existing=None, spans=spans, chunk_budget=budget)
    # the reasoning span's content reaches the summariser verbatim somewhere
    assert any("REASONING-CORE-CONCLUSION" in u for u in seen_spans)


# --- the summariser construction: negotiated method (ADR A1, #210) -----------

class _StructuredFake:
    """A fake `with_structured_output(...).invoke` wrapper recording the method."""

    def __init__(self, method, result):
        self.method = method
        self.result = result

    def invoke(self, messages):
        return self.result


def _summariser_harness(monkeypatch, profile, result):
    """Wire `build_summariser`'s lazy collaborators: role resolution, the model
    factory, the capability profile, and the construction seam. Returns
    (summariser, record) where record captures the negotiated method used."""
    import polymerhus.app.llm.capability as cap
    import polymerhus.app.llm.providers as providers
    import polymerhus.app.llm.roles as roles

    record = {}
    monkeypatch.setattr(providers, "resolve_role", lambda role: ("opencode", "deepseek-v4-flash"))
    monkeypatch.setattr(providers, "thinking_for", lambda role: "high")
    monkeypatch.setattr(providers, "build_chat_model",
                        lambda *a, **k: object())
    monkeypatch.setattr(cap, "resolve_capability", lambda p, m: profile)

    def structured_output_for(llm, schema, method):
        record["method"] = method
        return _StructuredFake(method, result)

    monkeypatch.setattr(roles, "structured_output_for", structured_output_for)
    summariser = S.build_summariser("triager")
    return summariser, record


def test_build_summariser_negotiates_json_schema_on_a_structured_profile(monkeypatch):
    """#210 Track A: the summariser routes through the shared negotiation -
    a structured-output profile yields the json_schema rung (not the hardcoded
    function_calling), consistent with invoke_role (ADR A1)."""
    profile = cap_prof(supports_structured_output=True)
    summariser, record = _summariser_harness(
        monkeypatch, profile,
        {"objective": GOOD_OBJECTIVE, "resume_point": GOOD_RESUME},
    )
    result = summariser([HumanMessage(content="m")], 30.0)
    assert record["method"] == "json_schema"
    assert isinstance(result, S.SummaryUpdate)
    assert result.objective == GOOD_OBJECTIVE


def test_build_summariser_degrades_to_function_calling_on_tool_only_profile(monkeypatch):
    """#210 AC: on a tool-calling-only profile the negotiated method degrades to
    function_calling - the existing degrade chain keeps the tool-only profiles
    on their proven rung (existing unit tests stay green)."""
    profile = cap_prof(supports_tool_calling=True, supports_structured_output=False)
    summariser, record = _summariser_harness(
        monkeypatch, profile, S.SummaryUpdate(objective=GOOD_OBJECTIVE, resume_point=GOOD_RESUME),
    )
    result = summariser([HumanMessage(content="m")], 30.0)
    assert record["method"] == "function_calling"
    assert isinstance(result, S.SummaryUpdate)


def test_build_summariser_fails_open_to_json_schema_on_resolution_error(monkeypatch):
    """#210 D7 fail-open: a capability resolution failure lands the semantic
    default json_schema and the call still proceeds - never a raise."""
    import polymerhus.app.llm.capability as cap
    import polymerhus.app.llm.roles as roles

    def resolve_capability(provider, model):
        raise ConnectionError("gateway down")

    monkeypatch.setattr(cap, "resolve_capability", resolve_capability)
    summariser, record = _summariser_harness(
        monkeypatch, cap_prof(supports_structured_output=True),
        {"objective": GOOD_OBJECTIVE, "resume_point": GOOD_RESUME},
    )
    # override the harness's working resolve_capability with the failing one
    monkeypatch.setattr(cap, "resolve_capability", resolve_capability)
    result = summariser([HumanMessage(content="m")], 30.0)
    assert record["method"] == "json_schema"  # the semantic default
    assert isinstance(result, S.SummaryUpdate)


def cap_prof(**kwargs):
    from polymerhus.app.llm.capability import CapabilityProfile
    return CapabilityProfile(**kwargs)


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