"""#232 increment E - the SkillEvolver: one bounded pass per (project, skill)
(D232-7/8/9), the due logic, the controller loop, and posted-lesson injection.

External behaviour only: the `EvolutionOutcome`, the consumed keys on disk, the
version the store reports, the payload the model sees, and the due selection.
The model turn is an injected seam, so no test touches an LLM; the published
case drives the REAL `write_skill` tool the binding arms, so the store's
validation and version bump stay inside the loop.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path
from typing import cast

import pytest
from langchain_core.messages import HumanMessage

from polymerhus.app.llm import skills
from polymerhus.app.llm.evolver import (
    EVOLVER_ROLE_ID,
    append_posted_lessons,
    arun_evolution_pass,
    arun_evolver_controller,
    due_skills,
    evolver_session_id,
)
from polymerhus.app.llm.session_address import ModuleScopedSession
from polymerhus.app.llm.skills import LessonStore, SkillStore

PROJECT = "proj-1"
SKILL = "ssrf"


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    skills.clear_cache()
    yield
    skills.clear_cache()


def _write_bundle(base: Path, skill: str, version: str, body: str = "# Seed\n") -> None:
    bundle = base / skill
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "SKILL.md").write_text(
        "---\n"
        f"name: {skill}\n"
        f"description: The {skill} procedure.\n"
        "metadata:\n"
        f"  version: '{version}'\n"
        "---\n\n" + body,
        encoding="utf-8",
    )


def _catalogue(tmp_path: Path, skill: str = SKILL, version: str = "1.0") -> Path:
    catalogue = tmp_path / "catalogue"
    _write_bundle(catalogue, skill, version)
    return catalogue


def _project_bundle(
    tmp_path: Path, project: str = PROJECT, skill: str = SKILL, version: str = "1.0"
) -> None:
    _write_bundle(tmp_path / "data" / project / "skills", skill, version)


def _stores(tmp_path: Path) -> tuple[SkillStore, LessonStore]:
    root = tmp_path / "data"
    skill_store = SkillStore(root_dir=root)
    return skill_store, LessonStore(root_dir=root, skill_store=skill_store)


def _seed_lesson(lesson_store: LessonStore, **overrides) -> str:
    payload = {
        "skill": SKILL,
        "type": "defect",
        "lesson": "step 2 never settles",
        "expected": "the procedure expects the page to settle",
        "evidence": ["http-artifact/abc123"],
        "agent": {"role_id": "pod_runner", "session_id": "hunting:r1:pod:s1"},
    }
    payload.update(overrides)
    return lesson_store.append(PROJECT, **payload)


class _FakeTurn:
    """The injected turn seam: records each call, optionally publishes through
    the REAL `write_skill` tool the pass armed, and can observe the store state
    at the moment the turn runs (the load-for-pasting ordering pin)."""

    def __init__(
        self,
        *,
        body: str | None = None,
        source_note_ids: list[str] | None = None,
        exc: Exception | None = None,
        observe=None,
    ):
        self.calls: list[dict] = []
        self._body = body
        self._source_note_ids = source_note_ids
        self._exc = exc
        self._observe = observe

    async def __call__(
        self, thread_id, prompt, *, tools, middleware, system_prompt, context,
        model_factory,
    ):
        self.calls.append(
            {
                "thread_id": thread_id,
                "prompt": prompt,
                "tools": tools,
                "middleware": middleware,
                "system_prompt": system_prompt,
                "context": context,
                "model_factory": model_factory,
            }
        )
        if self._observe is not None:
            self._observe()
        if self._exc is not None:
            raise self._exc
        if self._body is not None:
            write = next(t for t in tools if t.name == "write_skill")
            payload: dict = {"skill": SKILL, "target": "procedure", "content": self._body}
            if self._source_note_ids is not None:
                payload["source_note_ids"] = list(self._source_note_ids)
            out = write.invoke(payload)
            assert out["ok"] is True, out
        return None


# --- the pass -----------------------------------------------------------------


def test_a_pass_without_lessons_zero_skips_and_never_calls_the_model(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    turn = _FakeTurn(body="# Should never run\n")

    outcome = asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=turn,
        )
    )

    assert outcome.decision == "zero_skip"
    assert outcome.consumed_keys == ()
    assert outcome.version is None
    assert turn.calls == []
    assert (
        skill_store.meta(SKILL, project_id=PROJECT)["metadata"]["version"] == "1.0"
    )


def test_a_pass_on_an_unresolvable_skill_is_skill_unknown_without_a_model_call(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", tmp_path / "empty-catalogue")
    skill_store, lesson_store = _stores(tmp_path)
    turn = _FakeTurn(body="# x\n")

    outcome = asyncio.run(
        arun_evolution_pass(
            PROJECT, "no-such-skill", skill_store=skill_store,
            lesson_store=lesson_store, turn_fn=turn,
        )
    )

    assert outcome.decision == "skill_unknown"
    assert outcome.consumed_keys == ()
    assert turn.calls == []


def test_a_grounded_pass_publishes_and_marks_the_lessons_consumed(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    seen_at_turn: list[list[dict]] = []
    turn = _FakeTurn(
        body="# Revised\n",
        source_note_ids=["skill:ssrf:1"],
        observe=lambda: seen_at_turn.append(
            lesson_store.read(PROJECT, skill=SKILL, unconsumed_only=True)
        ),
    )

    outcome = asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=turn,
        )
    )

    assert outcome.decision == "published"
    assert outcome.skill == SKILL
    assert outcome.consumed_keys == ("skill:ssrf:1",)
    assert outcome.version == "1.1"
    # The boundary-safe composition escapes the separator inside the synthetic
    # run segment, so the id is stable and collision-free.
    assert outcome.thread_id == "hunting:skill-evolution_proj-1:ssrf:skill_evolver"
    assert outcome.thread_id == ModuleScopedSession(
        module="hunting",
        run_id=f"skill-evolution:{PROJECT}",
        tool=SKILL,
        role_id=EVOLVER_ROLE_ID,
    ).thread_id
    # Load-for-pasting: the turn ran with the selection already consumed.
    assert seen_at_turn == [[]]
    # The revision landed in the PROJECT bundle, version bumped one minor.
    body = (
        tmp_path / "data" / PROJECT / "skills" / SKILL / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "# Revised" in body
    # Consumption is durable and key-encoded.
    assert lesson_store.read(PROJECT, skill=SKILL, unconsumed_only=True) == []
    assert [r["key"] for r in lesson_store.read(PROJECT, skill=SKILL)] == [
        "skill:ssrf:1:consumed"
    ]
    # The turn held the role's bound surface plus the armed project write tool.
    call = turn.calls[0]
    assert [t.name for t in call["tools"]] == [
        "load_skill",
        "record_skill_lesson",
        "write_skill",
    ]
    assert call["context"]["skills"] == ["meta/meta-write-skill"]
    assert call["context"]["project_id"] == PROJECT
    assert call["system_prompt"] and "skill" in call["system_prompt"].lower()


def test_a_pass_whose_turn_writes_nothing_is_no_write(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    turn = _FakeTurn()

    outcome = asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=turn,
        )
    )

    assert outcome.decision == "no_write"
    assert outcome.version == "1.0"
    assert outcome.consumed_keys == ("skill:ssrf:1",)
    assert lesson_store.read(PROJECT, skill=SKILL, unconsumed_only=True) == []


def test_a_pass_whose_turn_raises_degrades_fail_open(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    turn = _FakeTurn(exc=RuntimeError("transport down"))

    outcome = asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=turn,
        )
    )

    assert outcome.decision == "degraded"
    assert "transport down" in outcome.detail
    # The accepted trade (D232-2): selection consumed its input even though the
    # pass failed; the operator can re-post lessons through the evolve endpoint.
    assert outcome.consumed_keys == ("skill:ssrf:1",)
    assert outcome.version == "1.0"


def test_the_payload_carries_every_selected_record_in_full(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(
        lesson_store,
        type="specification",
        lesson="metadata endpoint is reachable on this target",
        expected="the procedure expects cloud metadata to be blocked",
        evidence=["http-artifact/abc123", "run-41"],
    )
    _seed_lesson(
        lesson_store,
        type="extension",
        lesson="wait on the selector instead",
        expected="the procedure expects the page to settle",
        evidence=["session:r1:s2"],
    )
    turn = _FakeTurn()

    asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=turn,
        )
    )

    prompt = turn.calls[0]["prompt"]
    assert isinstance(prompt, HumanMessage)
    content = prompt.content
    for needle in (
        f"Skill: {SKILL}",
        "Current version: 1.0",
        "skill:ssrf:1",
        "skill:ssrf:2",
        "specification",
        "extension",
        "metadata endpoint is reachable on this target",
        "wait on the selector instead",
        "the procedure expects cloud metadata to be blocked",
        "http-artifact/abc123",
        "run-41",
        "session:r1:s2",
        "base_version",
        "1.0",
        "pod_runner",
        "hunting:r1:pod:s1",
        "written_at",
    ):
        assert needle in content


# --- posted lessons (the endpoint's injection surface, D232-10) ----------------


def test_posted_lessons_append_store_stamped_with_the_operator_agent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _, lesson_store = _stores(tmp_path)

    keys = append_posted_lessons(
        PROJECT,
        SKILL,
        [
            {
                "type": "specification",
                "lesson": "the endpoint injects this",
                "expected": "a base procedure",
                "evidence": ["manual-1"],
            }
        ],
        lesson_store=lesson_store,
    )

    assert keys == ["skill:ssrf:1"]
    record = lesson_store.read(PROJECT, skill=SKILL)[0]
    assert record["agent"] == {"role_id": "operator", "session_id": ""}
    assert record["base_version"] == "1.0"
    assert record["written_at"]


# --- due logic ------------------------------------------------------------------


def test_due_skills_fires_on_the_cap_regardless_of_the_period() -> None:
    due = due_skills(
        {"ssrf": 5, "xss": 2}, last_pass={}, now=1000.0, cap=5, period=300.0
    )

    assert due == ["ssrf"]


def test_due_skills_batches_first_sight_and_fires_when_the_period_elapsed() -> None:
    # A skill seen for the first time is NOT due: the controller initialises its
    # last-pass time at first sight, so the period batches rather than firing
    # immediately (only the cap fast-path can fire on first sight).
    assert due_skills({"ssrf": 1}, last_pass={}, now=1000.0, cap=5, period=300.0) == []
    assert due_skills(
        {"ssrf": 1}, last_pass={"ssrf": 1000.0}, now=1299.0, cap=5, period=300.0
    ) == []
    assert due_skills(
        {"ssrf": 1}, last_pass={"ssrf": 1000.0}, now=1300.0, cap=5, period=300.0
    ) == ["ssrf"]


def test_due_skills_is_deterministic_and_ignores_skills_without_lessons() -> None:
    due = due_skills({"b": 5, "a": 5}, last_pass={}, now=0.0, cap=5, period=300.0)

    assert due == ["a", "b"]


# --- the controller loop --------------------------------------------------------


def test_the_controller_passes_due_skills_and_honours_the_stop_event(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    passed: list[str] = []
    stop = asyncio.Event()

    async def fake_pass(project_id, skill, **kwargs):
        passed.append(skill)
        stop.set()
        return None

    async def scenario():
        await arun_evolver_controller(
            PROJECT,
            skill_store=skill_store,
            lesson_store=lesson_store,
            pass_fn=fake_pass,
            stop_event=stop,
            cap=1,
            period=300.0,
            tick=0.01,
        )

    asyncio.run(scenario())

    assert passed == [SKILL]


def test_the_controller_does_not_pass_a_first_sight_skill_below_the_cap(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    passed: list[str] = []

    async def fake_pass(project_id, skill, **kwargs):
        passed.append(skill)
        return None

    async def scenario():
        try:
            await asyncio.wait_for(
                arun_evolver_controller(
                    PROJECT,
                    skill_store=skill_store,
                    lesson_store=lesson_store,
                    pass_fn=fake_pass,
                    stop_event=asyncio.Event(),
                    cap=5,
                    period=300.0,
                    tick=0.01,
                ),
                timeout=0.05,
            )
        except (asyncio.TimeoutError, TimeoutError):
            pass

    asyncio.run(scenario())

    assert passed == []


def test_the_controller_survives_a_failing_tick(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    passed: list[str] = []
    stop = asyncio.Event()

    class _FlakyStore:
        """Reads raise once (a store hiccup), then behave; the loop must
        survive the bad tick (fail-open) and pass on the next one."""

        def __init__(self, real):
            self._real = real
            self._failed = False

        def skills_with_lessons(self, project_id):
            if not self._failed:
                self._failed = True
                raise OSError("shard read hiccup")
            return self._real.skills_with_lessons(project_id)

        def read(self, project_id, **kwargs):
            return self._real.read(project_id, **kwargs)

    async def fake_pass(project_id, skill, **kwargs):
        passed.append(skill)
        stop.set()
        return None

    async def scenario():
        await arun_evolver_controller(
            PROJECT,
            skill_store=skill_store,
            lesson_store=cast(LessonStore, _FlakyStore(lesson_store)),
            pass_fn=fake_pass,
            stop_event=stop,
            cap=1,
            period=300.0,
            tick=0.01,
        )

    asyncio.run(scenario())

    assert passed == [SKILL]


def test_the_evolver_session_id_is_the_run_scoped_q13_shape() -> None:
    assert evolver_session_id("rt-1") == "hunting:rt-1:evolver"
