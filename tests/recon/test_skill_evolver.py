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
    _write_bundle(tmp_path / "data" / "target-specific-procedure" / project, skill, version)


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
    # D-W3-3: the resolved version whenever the skill resolved; `zero_skip`
    # carries the base version the pass read.
    assert outcome.version == "1.0"
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
    # D-W3-3: only `skill_unknown` carries None - no skill resolved, so no
    # version was ever read.
    assert outcome.version is None
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
        tmp_path / "data" / "target-specific-procedure" / PROJECT / SKILL / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "# Revised" in body
    # Consumption is durable and key-encoded.
    assert lesson_store.read(PROJECT, skill=SKILL, unconsumed_only=True) == []
    assert [r["key"] for r in lesson_store.read(PROJECT, skill=SKILL)] == [
        "skill:ssrf:1:consumed"
    ]
    # The turn held the role's bound surface, the armed project write tool, and
    # the read-only target-context surface (D-W3-5).
    call = turn.calls[0]
    assert [t.name for t in call["tools"]] == [
        "load_skill",
        "record_skill_lesson",
        "write_skill",
        "search_http_history",
        "get_http_artifact",
        "auth_store",
        "graph_view",
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


def test_the_outcome_version_is_the_resolved_version_per_decision(
    tmp_path: Path, monkeypatch
) -> None:
    """D-W3-3 pins the vocabulary: `published` carries the new version;
    `zero_skip`, `no_write`, and `degraded` carry the base version the pass
    read; only `skill_unknown` carries None."""
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)

    degraded = asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=_FakeTurn(exc=RuntimeError("transport down")),
        )
    )
    unknown = asyncio.run(
        arun_evolution_pass(
            PROJECT, "no-such-skill", skill_store=skill_store,
            lesson_store=lesson_store, turn_fn=_FakeTurn(),
        )
    )
    # The degraded pass consumed the first lesson; seed a fresh one for the
    # no-write pass (a separate pass over a fresh selection).
    _seed_lesson(lesson_store)
    no_write = asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=_FakeTurn(),
        )
    )

    assert degraded.decision == "degraded" and degraded.version == "1.0"
    assert unknown.decision == "skill_unknown" and unknown.version is None
    assert no_write.decision == "no_write" and no_write.version == "1.0"


# --- the read-only target-context surface (D-W3-5) ----------------------------


def test_the_read_surface_is_the_four_named_target_context_tools() -> None:
    from polymerhus.app.auth.tool import AUTH_STORE_CONTRACT
    from polymerhus.app.llm.evolver import build_evolver_read_tools
    from polymerhus.attack.hunting.graph_view_tool import GRAPH_VIEW_CONTRACT
    from polymerhus.attack.hunting.http_history_contract import (
        GET_HTTP_ARTIFACT_DESCRIPTION,
        SEARCH_HTTP_HISTORY_DESCRIPTION,
    )

    tools = build_evolver_read_tools(PROJECT)

    assert [t.name for t in tools] == [
        "search_http_history",
        "get_http_artifact",
        "auth_store",
        "graph_view",
    ]
    # Each tool carries its single-sourced contract verbatim: the evolver reads
    # the same contracts every other binding renders, never a re-spelling.
    assert tools[0].description == SEARCH_HTTP_HISTORY_DESCRIPTION
    assert tools[1].description == GET_HTTP_ARTIFACT_DESCRIPTION
    assert tools[2].description == AUTH_STORE_CONTRACT
    assert tools[3].description == GRAPH_VIEW_CONTRACT


def test_the_graph_view_in_the_read_surface_refuses_write_shaped_cypher() -> None:
    from polymerhus.app.llm.evolver import build_evolver_read_tools
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphViewError

    graph = build_evolver_read_tools(PROJECT)[3]

    with pytest.raises(ReadOnlyGraphViewError):
        graph.invoke({"cypher": "MATCH (n) DETACH DELETE n"})


def test_the_http_readers_are_bound_to_the_pass_project_and_the_recording_seam(
    monkeypatch,
) -> None:
    import json

    from polymerhus.app.clients import kali_http_history
    from polymerhus.app.llm.evolver import build_evolver_read_tools

    seen: list[tuple] = []
    monkeypatch.setattr(
        kali_http_history,
        "default_http_search_fn",
        lambda project_id, filters, cursor, limit, text: seen.append(
            ("search", project_id)
        ) or {"summaries": []},
    )
    monkeypatch.setattr(
        kali_http_history,
        "default_http_get_fn",
        lambda project_id, artifact_id, include_body=False: seen.append(
            ("get", project_id, artifact_id)
        ) or {"artifact_id": artifact_id},
    )

    tools = build_evolver_read_tools(PROJECT)
    assert json.loads(tools[0].invoke({"text": "login"})) == {"summaries": []}
    assert json.loads(tools[1].invoke({"artifact_id": "http_A"})) == {
        "artifact_id": "http_A"
    }
    assert seen == [("search", PROJECT), ("get", PROJECT, "http_A")]


def test_the_pass_carries_an_injectable_read_surface_seam(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    turn = _FakeTurn()

    class _FakeReadTool:
        """Any tool-shaped object stands in for the read surface."""

        name = "fake_read_tool"

    asyncio.run(
        arun_evolution_pass(
            PROJECT, SKILL, skill_store=skill_store, lesson_store=lesson_store,
            turn_fn=turn, read_tools=[_FakeReadTool()],
        )
    )

    assert [t.name for t in turn.calls[0]["tools"]] == [
        "load_skill",
        "record_skill_lesson",
        "write_skill",
        "fake_read_tool",
    ]


# --- the prompt's ratified discipline (D-W3-1/5/6/8) ---------------------------


def test_the_role_prompt_carries_the_w3_workflow_discipline() -> None:
    """Pin the ratified prompt surgery at the text level: the write-at-the-end
    order (D-W3-1), the read-only grounding over the NAMED read tools (D-W3-5),
    the falsification checklist (D-W3-6), the corrections semantic (D-W3-7),
    and the internal transform-or-reject (D-W3-8). The harness-side tree and
    its vocabulary are gone."""
    from polymerhus.app.llm.evolver import _load_evolver_prompt

    prompt = _load_evolver_prompt()

    for needle in (
        "The write is LAST",
        "search_http_history",
        "get_http_artifact",
        "auth_store",
        "graph_view",
        'command: "read"',
        "corrections can only be made to already target-specified details",
        "falsification cannot be proved",
        "the stored lesson is never rewritten",
    ):
        assert needle in prompt, needle
    for gone in (
        "ARMED",
        "SCAN",
        "COOLDOWN",
        "SETTLE",
        "harness tracks",
        "symbolic layer",
        "zero_skip",
    ):
        assert gone not in prompt, gone


# --- the durable pass record (D-W3-4) -----------------------------------------


def test_the_pass_id_is_the_launcher_schedule_name() -> None:
    from polymerhus.app.llm.evolver import evolution_pass_id

    assert evolution_pass_id(PROJECT, SKILL) == f"skills:evolve:{PROJECT}:{SKILL}"


def test_the_pass_record_round_trips_start_and_finish(tmp_path: Path) -> None:
    from polymerhus.app.llm.evolver import (
        EvolutionOutcome,
        EvolutionPassStore,
        evolution_pass_id,
    )

    store = EvolutionPassStore(root_dir=tmp_path / "data")
    pass_id = evolution_pass_id(PROJECT, SKILL)

    running = store.start(PROJECT, SKILL, pass_id)

    assert running["pass_id"] == pass_id
    assert running["project_id"] == PROJECT and running["skill"] == SKILL
    assert running["status"] == "running"
    assert running["launched_at"]
    assert running["finished_at"] is None and running["outcome"] is None
    assert store.get(PROJECT, pass_id) == running

    outcome = EvolutionOutcome(
        "published", SKILL, version="1.1",
        consumed_keys=("skill:ssrf:1",), thread_id="t-1",
    )
    finished = store.finish(PROJECT, pass_id, outcome)

    assert finished["status"] == "finished"
    assert finished["finished_at"]
    assert finished["launched_at"] == running["launched_at"]
    assert finished["outcome"] == outcome.to_dict()
    assert store.get(PROJECT, pass_id) == finished


def test_the_pass_record_is_durable_under_the_projects_skill_area(
    tmp_path: Path,
) -> None:
    from polymerhus.app.llm.evolver import (
        EvolutionPassStore,
        evolution_pass_id,
    )

    store = EvolutionPassStore(root_dir=tmp_path / "data")
    store.start(PROJECT, SKILL, evolution_pass_id(PROJECT, SKILL))

    files = sorted(
        (
            tmp_path / "data" / "target-specific-procedure" / PROJECT / "evolution"
        ).glob("*.yaml")
    )
    assert [f.name for f in files] == ["skills_evolve_proj-1_ssrf.yaml"]
    # A FRESH store instance reads the same record: no in-memory state.
    assert EvolutionPassStore(root_dir=tmp_path / "data").get(
        PROJECT, evolution_pass_id(PROJECT, SKILL)
    )["status"] == "running"


def test_an_unknown_or_unsafe_pass_id_reads_as_none(tmp_path: Path) -> None:
    from polymerhus.app.llm.evolver import EvolutionPassStore

    store = EvolutionPassStore(root_dir=tmp_path / "data")

    assert store.get(PROJECT, "skills:evolve:proj-1:never") is None
    assert store.get(PROJECT, "../escape") is None
    assert store.get(PROJECT, "..") is None
    assert store.get(PROJECT, "") is None


def test_a_relaunch_replaces_the_slot_record(tmp_path: Path) -> None:
    from polymerhus.app.llm.evolver import (
        EvolutionOutcome,
        EvolutionPassStore,
        evolution_pass_id,
    )

    store = EvolutionPassStore(root_dir=tmp_path / "data")
    pass_id = evolution_pass_id(PROJECT, SKILL)
    store.start(PROJECT, SKILL, pass_id)
    store.finish(
        PROJECT, pass_id, EvolutionOutcome("no_write", SKILL, version="1.0")
    )
    assert store.get(PROJECT, pass_id)["outcome"]["decision"] == "no_write"

    second = store.start(PROJECT, SKILL, pass_id)

    # The identifier addresses the pass SLOT: the relaunch's running record
    # replaces the finished one, outcome and finish stamp included.
    assert store.get(PROJECT, pass_id) == second
    assert second["status"] == "running"
    assert second["outcome"] is None
    assert second["finished_at"] is None


def test_discard_drops_only_the_matching_running_record(tmp_path: Path) -> None:
    from polymerhus.app.llm.evolver import (
        EvolutionPassStore,
        evolution_pass_id,
    )

    store = EvolutionPassStore(root_dir=tmp_path / "data")
    pass_id = evolution_pass_id(PROJECT, SKILL)
    launched = store.start(PROJECT, SKILL, pass_id)

    store.discard(PROJECT, pass_id, launched_at="another-launch")
    assert store.get(PROJECT, pass_id) == launched

    store.discard(PROJECT, pass_id, launched_at=launched["launched_at"])
    assert store.get(PROJECT, pass_id) is None
    # Idempotent: discarding an absent record is a no-op, never a raise.
    store.discard(PROJECT, pass_id)


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


# --- the controller as a first-class hunting session ---------------------------


def test_the_controller_waits_on_the_shared_gate_at_each_tick(
    tmp_path: Path, monkeypatch
) -> None:
    """Each controller tick is a session UNIT: the loop awaits the injected
    `wait_ready` (the run's shared gate acquisition, which honours the module
    pause and the per-session hold) before every scan. A held controller fires
    no pass; the release lets the due pass through."""
    monkeypatch.setattr(skills, "_SKILLS_ROOT", _catalogue(tmp_path))
    _project_bundle(tmp_path)
    skill_store, lesson_store = _stores(tmp_path)
    _seed_lesson(lesson_store)
    passed: list[str] = []
    stop = asyncio.Event()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[int] = []

    async def fake_pass(project_id, skill, **kwargs):
        passed.append(skill)
        stop.set()

    async def wait_ready():
        calls.append(1)
        entered.set()
        await release.wait()

    async def scenario():
        task = asyncio.create_task(arun_evolver_controller(
            PROJECT,
            skill_store=skill_store,
            lesson_store=lesson_store,
            pass_fn=fake_pass,
            stop_event=stop,
            wait_ready=wait_ready,
            cap=1,
            period=300.0,
            tick=0.01,
        ))
        await asyncio.wait_for(entered.wait(), timeout=2)
        await asyncio.sleep(0.05)
        assert passed == [], "a held controller must not fire a pass"
        release.set()
        await asyncio.wait_for(task, timeout=2)

    asyncio.run(scenario())

    assert calls, "the controller must probe the gate every tick"
    assert passed == [SKILL]


def test_the_evolver_thread_is_a_first_class_run_session() -> None:
    """The controller session uses the SAME Q13 run-session typing as the
    orchestrator and surfer controllers, and the module REST thread endpoint's
    acceptance predicate (`is_run_session_id`) accepts it. So the REST `pause`,
    `resume`, and `stop` verbs address the controller by its thread id."""
    from polymerhus.app.llm.evolver import evolver_session_id
    from polymerhus.attack.hunting.surfer import is_run_session_id

    run_id = "r9"
    evolver_id = evolver_session_id(run_id)
    assert evolver_id == f"hunting:{run_id}:evolver"
    assert is_run_session_id(evolver_id, run_id)
    assert not is_run_session_id(evolver_id, "another-run")
