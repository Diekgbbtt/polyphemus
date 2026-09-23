"""#232 D232-10: the skill-evolution REST trigger.

`POST /projects/{pid}/skills/{skill}/evolve` forces one pass through the
runtime, appends any posted lessons before the pass, and carries the
`EvolutionOutcome` back. No live runtime / PG / LLM: the launcher seam, the
project read, and the control-plane presence are faked, mirroring the hunting
launch-surface tests.
"""
from __future__ import annotations

import concurrent.futures

from fastapi.testclient import TestClient

from polymerhus.app.clients import pg
from polymerhus.app.llm.evolver import EvolutionOutcome
from polymerhus.app.main import app

client = TestClient(app)


def _resolved(outcome) -> concurrent.futures.Future:
    future: concurrent.futures.Future = concurrent.futures.Future()
    future.set_result(outcome)
    return future


def _patch(monkeypatch, *, project: bool = True, plane: bool = True):
    from polymerhus.attack.hunting import runtime as hunting_runtime

    monkeypatch.setattr(pg, "project_exists", lambda pid: project)
    monkeypatch.setattr(
        hunting_runtime, "hunting_control_plane_available", lambda: plane
    )
    return hunting_runtime


def test_evolve_returns_the_pass_outcome(monkeypatch):
    hunting_runtime = _patch(monkeypatch)
    outcome = EvolutionOutcome(
        "published",
        "ssrf",
        version="1.1",
        consumed_keys=("skill:ssrf:1",),
        thread_id="hunting:skill-evolution:p1:ssrf:skill_evolver",
    )
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: _resolved(outcome),
    )

    resp = client.post("/projects/p1/skills/ssrf/evolve", json={})

    assert resp.status_code == 200
    assert resp.json() == {
        "decision": "published",
        "skill": "ssrf",
        "version": "1.1",
        "consumed_keys": ["skill:ssrf:1"],
        "thread_id": "hunting:skill-evolution:p1:ssrf:skill_evolver",
        "detail": "",
    }


def test_evolve_appends_posted_lessons_before_the_pass(monkeypatch):
    hunting_runtime = _patch(monkeypatch)
    order: list[tuple] = []
    from polymerhus.app.llm import evolver

    def record_append(pid, skill, lessons, **kw):
        order.append(("append", pid, skill, lessons))
        return ["skill:ssrf:1"]

    monkeypatch.setattr(evolver, "append_posted_lessons", record_append)
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: order.append(("launch", pid, skill))
        or _resolved(EvolutionOutcome("published", skill)),
    )
    body = {
        "lessons": [
            {
                "type": "defect",
                "lesson": "step 2 never settles",
                "expected": "the procedure expects the page to settle",
                "evidence": ["manual-1"],
            }
        ]
    }

    resp = client.post("/projects/p1/skills/ssrf/evolve", json=body)

    assert resp.status_code == 200
    assert order[0] == ("append", "p1", "ssrf", body["lessons"])
    assert order[1] == ("launch", "p1", "ssrf")


def test_evolve_unknown_project_404(monkeypatch):
    hunting_runtime = _patch(monkeypatch, project=False)
    called: list[str] = []
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: called.append(pid)
        or _resolved(EvolutionOutcome("zero_skip", skill)),
    )

    resp = client.post("/projects/nope/skills/ssrf/evolve", json={})

    assert resp.status_code == 404
    assert called == []


def test_evolve_fails_closed_503_without_the_control_plane(monkeypatch):
    _patch(monkeypatch, plane=False)

    resp = client.post("/projects/p1/skills/ssrf/evolve", json={})

    assert resp.status_code == 503


def test_evolve_invalid_posted_lesson_is_refused_400(monkeypatch):
    _patch(monkeypatch)
    from polymerhus.app.llm import evolver
    from polymerhus.app.llm.skills import LessonInvalidError

    def boom(pid, skill, lessons, **kw):
        raise LessonInvalidError("lesson_invalid: type 'nope' is not a lesson type")

    monkeypatch.setattr(evolver, "append_posted_lessons", boom)

    resp = client.post(
        "/projects/p1/skills/ssrf/evolve",
        json={"lessons": [{"type": "nope", "lesson": "x"}]},
    )

    assert resp.status_code == 400
    assert "lesson_invalid" in resp.json()["detail"]
