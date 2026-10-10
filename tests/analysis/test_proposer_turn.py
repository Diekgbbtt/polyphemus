"""Unit tier: the ONE converged analysis-proposer turn seam (proposer_turn).

The three analysis proposers (`assigner`, `mechanism_typist`, `data_modeller`) are
structurally identical in their turn construction - a per-run session thread, the
role's compaction middleware, the role prompt. They therefore share ONE seam
(#187's convergent precedent, already applied to the hunting gate actor): the role
prompt is bound ONCE as the agent's ephemeral leading block and never enters the
checkpointed trail, and the one-shot legacy leg prepends the same prompt into its
message list. These tests pin that, plus the per-role thread identity the
`AnalysisSession` addressing guarantees.
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from polymerhus.analysis.proposer_turn import (
    prepend_prompt,
    session_invoke_fn,
)


class _CapturingSeam:
    """A stand-in for `stateful_turn` that records what the seam received, so a test
    asserts the CONSTRUCTION (prompt binding, message shape) without a live model."""

    def __init__(self):
        self.seen: list[dict] = []

    def __call__(self, role_id, thread, messages, **kw):
        self.seen.append({
            "role_id": role_id,
            "thread_id": getattr(thread, "thread_id", thread),
            "messages": list(messages),
            "system_prompt": kw.get("system_prompt"),
            "schema": kw.get("schema"),
            "extra_tags": kw.get("extra_tags"),
            "usage_scope": kw.get("usage_scope"),
            "middleware": kw.get("middleware"),
        })
        return None


def _patch_stateful_turn(monkeypatch, seam):
    """Replace `session.stateful_turn` with the capturing seam. The factory must
    reach the patched function through the module the seam imports from, so patch
    at the source (`polymerhus.app.llm.session`), which `proposer_turn` imports
    lazily inside the call - the same lazy seam the real code uses."""
    import polymerhus.app.llm.session as S

    monkeypatch.setattr(S, "stateful_turn", seam)


# --- the stateful leg: the role prompt is bound ONCE, ephemerally -------------

def test_the_stateful_leg_binds_the_role_prompt_not_the_messages(monkeypatch):
    """The ONE structural guarantee of the converged seam: the role prompt rides
    the `system_prompt=` binding (so `create_agent` prepends it ephemerally per
    model call and never persists it into the checkpoint), and the caller's
    messages are forwarded VERBATIM - a `system_prompt` is never smuggled back
    into the trail as a `SystemMessage`."""
    seam = _CapturingSeam()
    _patch_stateful_turn(monkeypatch, seam)

    invoke = session_invoke_fn("mechanism_typist", "runX", object(), project_id="proj-1")
    task = HumanMessage(content="the per-chunk task")
    invoke([task], schema=None)

    prompt = seam.seen[0]["system_prompt"]
    assert isinstance(prompt, str) and prompt.strip()
    assert seam.seen[0]["messages"] == [task]
    # No role prompt in the forwarded messages - the trail stays prompt-free.
    assert not any(isinstance(m, SystemMessage) for m in seam.seen[0]["messages"])


def test_the_stateful_leg_honours_an_explicit_prompt_over_the_role_default(monkeypatch):
    """The caller owns its prompt (the pod-agent pattern), so a role whose prompt
    varies by mode still gets the right one; absent one the role's OWN default
    applies, so no proposer can be built with another's prompt by accident."""
    seam = _CapturingSeam()
    _patch_stateful_turn(monkeypatch, seam)
    invoke = session_invoke_fn("assigner", "runX", object())

    invoke([HumanMessage(content="reflect")], schema=None, system_prompt="THE-MODE-PROMPT")
    assert seam.seen[-1]["system_prompt"] == "THE-MODE-PROMPT"

    invoke([HumanMessage(content="create")])
    assert seam.seen[-1]["system_prompt"] != "THE-MODE-PROMPT", "the role default applies"


def test_the_stateful_leg_keys_a_distinct_thread_per_role(monkeypatch):
    """No cross-agent collision: each role id addresses its own per-run session,
    so one proposer never resumes another's memory."""
    seam = _CapturingSeam()
    _patch_stateful_turn(monkeypatch, seam)
    cp = object()

    threads = set()
    for role in ("assigner", "mechanism_typist", "data_modeller"):
        session_invoke_fn(role, "runX", cp)([HumanMessage(content="m")], schema=None)
        threads.add(seam.seen[-1]["thread_id"])

    assert threads == {"runX:assigner", "runX:mechanism_typist", "runX:data_modeller"}


def test_the_stateful_leg_threads_the_run_tags_project_and_schema(monkeypatch):
    """The three seams every stateful proposer needs, preserved exactly: the run
    correlation tag, the project usage scope, and the per-call schema (None for a
    prose turn, a schema for a structured one)."""
    seam = _CapturingSeam()
    _patch_stateful_turn(monkeypatch, seam)

    invoke = session_invoke_fn("assigner", "runX", object(), project_id="proj-1")
    invoke([HumanMessage(content="reflect")], schema=None)
    assert seam.seen[-1]["schema"] is None
    assert seam.seen[-1]["extra_tags"] == ["runX"]
    assert seam.seen[-1]["usage_scope"] == "proj-1"

    invoke([HumanMessage(content="extract")], schema="THE-SCHEMA")
    assert seam.seen[-1]["schema"] == "THE-SCHEMA"


def test_the_stateful_leg_carries_each_roles_own_prompt(monkeypatch):
    """The ONE seam still gives each role ITS prompt - the convergence is in the
    construction, not in flattening the roles into one shared prompt."""
    seam = _CapturingSeam()
    _patch_stateful_turn(monkeypatch, seam)

    prompts = {}
    for role in ("assigner", "mechanism_typist", "data_modeller"):
        session_invoke_fn(role, "runX", object())([HumanMessage(content="m")])
        prompts[role] = seam.seen[-1]["system_prompt"]

    assert prompts["assigner"] != prompts["mechanism_typist"]
    assert prompts["mechanism_typist"] != prompts["data_modeller"]
    for role, prompt in prompts.items():
        assert isinstance(prompt, str) and prompt.strip()


def test_the_stateful_leg_carries_no_skill_surface(monkeypatch):
    """Operator ruling (2026-09-17), preserved: the analysis proposers interact
    with LOCAL context only, so they bind no skill tool, no skill context, and no
    L1 skill-index middleware - their turns carry structure, not skills."""
    from polymerhus.analysis import proposer_turn
    from polymerhus.app.llm import compaction as C
    import polymerhus.app.llm.session as S

    roles: list[str] = []
    bound: dict = {}
    real_builder = C.build_role_compaction_middleware

    def spy_builder(role_id):
        roles.append(role_id)
        return real_builder(role_id)

    def spy_turn(role_id, thread, messages, **kw):
        bound.update(kw)
        return None

    monkeypatch.setattr(C, "build_role_compaction_middleware", spy_builder)
    monkeypatch.setattr(S, "stateful_turn", spy_turn)

    proposer_turn.session_invoke_fn("mechanism_typist", "runX", object())(
        [HumanMessage(content="m")], schema=None)

    assert "tools" not in bound, "no tool binding at all (the default empty set applies)"
    assert "context" not in bound or bound.get("context") is None
    assert "_skill_index" not in {type(m).__name__ for m in bound["middleware"] or ()}
    assert roles == ["mechanism_typist"], "one middleware per turn, for its OWN role"


# --- the one-shot legacy leg: the same prompt, headed -------------------------

def test_the_one_shot_leg_prepends_the_prompt_once():
    """The legacy stateless seam (`_default_invoke_fn`, used by the unit/contract
    tiers) keeps working: the role prompt is prepended ONCE at the head of the
    request list, exactly where `create_agent` puts it in the stateful leg."""
    out = prepend_prompt([HumanMessage(content="the task")], "THE-ROLE-PROMPT")
    assert isinstance(out[0], SystemMessage)
    assert out[0].content == "THE-ROLE-PROMPT"
    assert isinstance(out[1], HumanMessage)


def test_the_one_shot_leg_without_a_prompt_leaves_the_list_untouched():
    """No prompt -> no synthetic `SystemMessage` (a `schema=None` one-shot caller
    that supplied its own head keeps it)."""
    original = [HumanMessage(content="only this")]
    assert prepend_prompt(original, None) == original
    assert prepend_prompt(original, "") == original


def test_the_one_shot_leg_prepends_over_an_existing_head():
    """With a prompt AND a caller-provided head, the prompt still leads - the
    stable fundamental instruction is the first thing the model reads."""
    head = HumanMessage(content="caller head")
    out = prepend_prompt([head], "THE-ROLE-PROMPT")
    assert [type(m).__name__ for m in out] == ["SystemMessage", "HumanMessage"]
    assert out[1].content == "caller head"


# --- THE end-to-end re-verification: the two legs are byte-identical ----------
#
# Everything above pins the CONSTRUCTION. This last tier runs the REAL production
# seam (`run_session_turn` -> `create_agent(system_prompt=...)` -> the model) with a
# recording model, so what is asserted is the request the model actually receives,
# not what a seam was handed. That is the property the whole change rests on: the
# one-shot leg and the stateful leg must put the role prompt in the SAME place,
# byte-for-byte, or a provider's cached prefix cannot survive a call site moving
# between them.

class _RecordingModel(BaseChatModel):
    """A model that records the messages it is handed on every invocation, so the
    test can assert against the real wire request rather than a capture point."""

    def __init__(self):
        super().__init__()
        self._seen: list[list[BaseMessage]] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append(list(messages))
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))

    @property
    def _llm_type(self) -> str:
        return "proposer-recording"

    def bind_tools(self, tools, **kwargs):
        return self


def _drive_real_seam(role_prompt: str, monkeypatch, *, calls: int = 1):
    """Drive the REAL proposer seam for this role and return the model, the
    checkpointer, and the recorded wire requests.

    Only two things are patched, and neither sits above the seam under test: the
    role's prompt (so a test knows the exact string) and the session seam's own
    default model factory (so a recording model answers instead of a live
    provider). Everything else - `system_prompt`, the messages, the middleware,
    the compaction - travels through the production code untouched."""
    from polymerhus.analysis.proposer_turn import session_invoke_fn

    model = _RecordingModel()
    monkeypatch.setattr(
        "polymerhus.analysis.proposer_turn._role_prompt", lambda role_id: role_prompt)
    monkeypatch.setattr(
        "polymerhus.app.llm.session._default_model_factory",
        lambda role_id: model)

    saver = InMemorySaver()
    invoke = session_invoke_fn("mechanism_typist", "runbyte", saver)
    for k in range(calls):
        invoke([HumanMessage(content=f"the per-chunk task {k}")], schema=None)
    return model, saver, model._seen


def test_the_two_legs_send_a_byte_identical_prompt_at_the_same_position(monkeypatch):
    """THE acceptance criterion (ADR §8 item 1), verified end to end.

    Two independent requests are compared:
    1. the STATEFUL leg's wire request, read off a recording model driven through
       the real `session_invoke_fn` -> `stateful_turn` -> `create_agent` path;
    2. the one-shot leg's request, built by `prepend_prompt` from the very same
       role prompt and the very same human task.

    The comparison is only meaningful if both legs hold the same prompt STRING, so
    the role's prompt is pinned to a known value. Both then place it at the head,
    byte for byte - which is what lets a provider's cached prefix survive a call
    site moving between the legs.

    SCOPE, stated so it is not over-read: the one-shot leg is stateless, so the
    comparison is on a single call. On a fresh thread the two legs are byte
    identical, and that is the whole claim - a call site that migrates between
    them does not change the request on its first call. What the OLD defect broke
    was every call AFTER the first, which is what the multi-call tests below
    cover; this one would pass on the old shape, and the tier is the real guard."""
    from polymerhus.analysis.proposer_turn import prepend_prompt

    PROMPT = "THE ONE ROLE PROMPT - byte-identical across every call"
    _model, _saver, requests = _drive_real_seam(PROMPT, monkeypatch, calls=1)
    one_shot = prepend_prompt([HumanMessage(content="the per-chunk task 0")], PROMPT)

    wire = requests[0]
    # Same length, same order, same content, byte for byte.
    assert [type(m).__name__ for m in wire] == [type(m).__name__ for m in one_shot]
    assert [m.content for m in wire] == [m.content for m in one_shot]
    # The prompt LEADS the stateful leg, not merely appears somewhere in it.
    assert wire[0].content == PROMPT
    assert wire[0].content == one_shot[0].content
    assert wire[0].content.encode("utf-8") == PROMPT.encode("utf-8")


def test_the_wire_prompt_sits_at_position_zero_on_every_call(monkeypatch):
    """The prompt is ephemeral and STILL leads on every call - the property that
    makes the provider's cached prefix reusable. A `SystemMessage` that only
    appears on call 1, or one that slides to a later offset, silently defeats the
    cache, so both are asserted here over a real multi-call run.

    The trail must be RESTORED for the defect to show, so the run shares one
    checkpointer: the old shape inserted a fresh prompt copy into the MIDDLE of
    the restored trail, which left the head correct and the request uncacheable."""
    PROMPT = "THE ONE ROLE PROMPT - fixed position, fixed content"
    model, _saver, requests = _drive_real_seam(PROMPT, monkeypatch, calls=4)

    assert len(requests) >= 4, "the model was invoked once per call"
    for index, request in enumerate(requests):
        # 1. The prompt LEADS, and leads byte-identically, every single call.
        assert request[0].content == PROMPT, (
            f"the prompt leads call {index}")
        # 2. It appears EXACTLY ONCE. A second copy later in the request is the
        #    old stacking defect, which the leading copy alone cannot expose.
        assert sum(1 for m in request if m.content == PROMPT) == 1, (
            f"exactly one prompt copy in call {index}")
        # 3. Nothing after position 0 carries the prompt: it is NOT trail content.
        assert all(
            not isinstance(m, SystemMessage) for m in request[1:]), (
            f"no role prompt in the trail of call {index}")


def test_the_prompt_leads_a_request_that_grows_only_by_the_task(monkeypatch):
    """The cache property in its strongest form: across a real multi-call run each
    request's TRAIL is the previous request's trail plus the turn's own two
    messages, with the leading block unchanged.

    This is what a provider's prefix cache actually reuses, so it is the direct
    end-to-end check of the ADR's goal. It is RED on the old shape, where each
    call inserted a fresh `SystemMessage` into the middle of the restored trail."""
    PROMPT = "THE ONE ROLE PROMPT - the stable head"
    _model, _saver, requests = _drive_real_seam(PROMPT, monkeypatch, calls=3)

    assert len(requests) >= 3
    for previous, current in zip(requests, requests[1:]):
        # The head is byte-identical.
        assert current[0].content == previous[0].content == PROMPT
        # The previous TRAIL is a strict PREFIX of the next one - append-only.
        # Nothing earlier is rewritten, inserted or removed, which is exactly
        # what a provider needs in order to extend its cached prefix.
        previous_trail = [m.content for m in previous[1:]]
        current_trail = [m.content for m in current[1:]]
        assert current_trail[:len(previous_trail)] == previous_trail
        assert len(current_trail) > len(previous_trail)
        # What the turn appended is ITS OWN task and answer, nothing the caller
        # did not send. A prompt copy in there is the stacking defect.
        assert PROMPT not in current_trail[len(previous_trail):], (
            "the appended block is the turn's own task and answer")


def test_the_checkpointed_trail_never_holds_the_role_prompt(monkeypatch):
    """The other half of the criterion: the prompt is NOT persisted into the
    checkpoint state, so it cannot accumulate as trail content.

    Read the thread back through the shared checkpointer exactly as the
    parent-to-child memory READ does, and assert the role prompt is absent - while
    the human task the caller sent IS there. This is what distinguishes the
    converged seam from the old per-call `SystemMessage` re-add."""
    from polymerhus.app.llm.session import read_session_memory

    PROMPT = "THE ONE ROLE PROMPT - never checkpointed"
    model, saver, _requests = _drive_real_seam(PROMPT, monkeypatch, calls=3)
    invoke = session_invoke_fn("mechanism_typist", "runbyte", saver)
    for k in range(3):
        invoke([HumanMessage(content=f"the task {k}")], schema=None)

    trail = read_session_memory(saver, "runbyte:mechanism_typist")
    assert trail is not None
    joined = [getattr(m, "content", "") for m in trail.messages]

    assert all(PROMPT not in text for text in joined), "no role prompt in the trail"
    assert any(text == "the per-chunk task 0" for text in joined), (
        "the caller's task is there")


def test_the_stateful_leg_is_read_through_the_real_seam(monkeypatch):
    """Guard against the byte-identity tests above silently regressing to a fake
    seam: drive `session_invoke_fn` with NO `stateful_turn` patch and no
    `model_factory` injection, and confirm the production seam really reached the
    model.

    If this fails, the tests above were asserting against a stub rather than
    against the production request, and the whole verification is void."""
    from polymerhus.analysis.proposer_turn import session_invoke_fn
    from polymerhus.app.llm import session as S

    model = _RecordingModel()
    monkeypatch.setattr(
        "polymerhus.app.llm.session._default_model_factory", lambda role_id: model)
    monkeypatch.setattr(
        "polymerhus.analysis.proposer_turn._role_prompt", lambda role_id: "P")

    # Patching the SEAM itself here would defeat the test's purpose, so assert
    # only that nothing above it was stubbed out.
    assert not hasattr(S, "_recording_stub")
    invoke = session_invoke_fn("mechanism_typist", "runbyte", InMemorySaver())
    invoke([HumanMessage(content="the task")], schema=None)
    assert model._seen, "the real seam reached the model"
    assert model._seen[0][0].content == "P"


