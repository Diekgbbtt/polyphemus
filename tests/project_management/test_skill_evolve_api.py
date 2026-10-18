"""#232 D232-10 / D-W3-4: the skill-evolution REST launch + status pair.

`POST /projects/{pid}/skills/{skill}/evolve` starts ONE pass and returns its
identifier (202); `GET /projects/{pid}/evolution-passes/{pass_id}` serves the
DURABLE pass record (200), 404 for an unknown identifier. No live runtime /
PG / LLM: the launcher seam, the project read, and the control-plane presence
are faked, mirroring the hunting launch-surface tests; the pass-record store is
a temp-rooted real store so the durability claim is exercised end to end.
"""
from __future__ import annotations

import concurrent.futures

import pytest
from fastapi.testclient import TestClient

from polymerhus.app.clients import pg
from polymerhus.app.llm import evolver
from polymerhus.app.llm.evolver import EvolutionOutcome
from polymerhus.app.main import app

client = TestClient(app)

PASS_ID = "skills:evolve:p1:ssrf"
STATUS_URL = f"/projects/p1/evolution-passes/{PASS_ID}"

# The real class, captured before any fixture patches the module attribute.
_REAL_PASS_STORE = evolver.EvolutionPassStore


@pytest.fixture
def records_root(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def records(records_root, monkeypatch) -> evolver.EvolutionPassStore:
    """The temp-rooted record store the endpoint resolves (the store's own
    explicit-root constructor - the #220/#234 precedent)."""
    store = _REAL_PASS_STORE(root_dir=records_root)
    monkeypatch.setattr(evolver, "EvolutionPassStore", lambda: store)
    return store


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


def test_launch_returns_the_identifier_and_starts_a_running_record(
    monkeypatch, records: evolver.EvolutionPassStore
) -> None:
    """#232 D232-10 / D-W3-4: the launch does not await the pass; it hands back
    the identifier and the durable record the status endpoint answers for."""
    hunting_runtime = _patch(monkeypatch)
    seen: dict = {}
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: seen.update(pid=pid, skill=skill, **kw)
        or _resolved(None),
    )

    resp = client.post("/projects/p1/skills/ssrf/evolve", json={})

    assert resp.status_code == 202
    body = resp.json()
    assert body["pass_id"] == PASS_ID
    assert body["project_id"] == "p1"
    assert body["skill"] == "ssrf"
    assert body["status"] == "running"
    assert body["finished_at"] is None and body["outcome"] is None
    assert body["launched_at"]
    # The launcher got the identifier's store, so it can finish the record.
    assert seen["pid"] == "p1" and seen["skill"] == "ssrf"
    assert seen["records"] is records
    assert records.get("p1", PASS_ID)["status"] == "running"


def test_status_serves_the_finished_record_with_the_outcome(
    monkeypatch, records: evolver.EvolutionPassStore
) -> None:
    """D-W3-4: given the identifier, the status endpoint returns the pass
    outcome; here the launcher's finish is driven through the same store."""
    hunting_runtime = _patch(monkeypatch)
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: _resolved(None),
    )
    client.post("/projects/p1/skills/ssrf/evolve", json={})
    records.finish(
        "p1",
        PASS_ID,
        EvolutionOutcome(
            "published",
            "ssrf",
            version="1.1",
            consumed_keys=("skill:ssrf:1",),
            thread_id="hunting:skill-evolution_p1:ssrf:skill_evolver",
        ),
    )

    resp = client.get(STATUS_URL)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "finished"
    assert body["finished_at"]
    assert body["launched_at"]  # the launch stamp survives the finish
    assert body["outcome"] == {
        "decision": "published",
        "skill": "ssrf",
        "version": "1.1",
        "consumed_keys": ["skill:ssrf:1"],
        "thread_id": "hunting:skill-evolution_p1:ssrf:skill_evolver",
        "detail": "",
    }


def test_status_survives_a_process_restart(monkeypatch, records, records_root) -> None:
    """The record is DURABLE: a fresh store instance (a later process, a
    different service) reads the same record with no in-memory state."""
    hunting_runtime = _patch(monkeypatch)
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: _resolved(None),
    )
    client.post("/projects/p1/skills/ssrf/evolve", json={})

    fresh = _REAL_PASS_STORE(root_dir=records_root)
    monkeypatch.setattr(evolver, "EvolutionPassStore", lambda: fresh)

    resp = client.get(STATUS_URL)

    assert resp.status_code == 200
    assert resp.json()["pass_id"] == PASS_ID


def test_status_unknown_identifier_404(monkeypatch) -> None:
    _patch(monkeypatch)

    resp = client.get("/projects/p1/evolution-passes/skills:evolve:p1:never")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "no evolution pass for that identifier"


def test_status_is_scoped_to_the_projects_records(monkeypatch, records) -> None:
    hunting_runtime = _patch(monkeypatch)
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: _resolved(None),
    )
    client.post("/projects/p1/skills/ssrf/evolve", json={})

    resp = client.get("/projects/p2/evolution-passes/" + PASS_ID)

    assert resp.status_code == 404


def test_status_refuses_an_unsafe_identifier_with_404(monkeypatch, records) -> None:
    _patch(monkeypatch)

    resp = client.get("/projects/p1/evolution-passes/%2e%2e")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "no evolution pass for that identifier"


def test_a_refused_launch_leaves_no_record_behind(monkeypatch, records) -> None:
    from polymerhus.app.runtime import ModuleAdmissionRefused

    hunting_runtime = _patch(monkeypatch)

    def refuse(pid, skill, **kw):
        raise ModuleAdmissionRefused("module 'hunting' is draining")

    monkeypatch.setattr(hunting_runtime, "launch_evolution_pass", refuse)

    resp = client.post("/projects/p1/skills/ssrf/evolve", json={})

    assert resp.status_code == 503
    assert records.get("p1", PASS_ID) is None


def test_launch_appends_posted_lessons_before_the_pass(monkeypatch, records) -> None:
    hunting_runtime = _patch(monkeypatch)
    order: list[tuple] = []

    def record_append(pid, skill, lessons, **kw):
        order.append(("append", pid, skill, lessons))
        return ["skill:ssrf:1"]

    monkeypatch.setattr(evolver, "append_posted_lessons", record_append)
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: order.append(("launch", pid, skill))
        or _resolved(None),
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

    assert resp.status_code == 202
    assert order[0] == ("append", "p1", "ssrf", body["lessons"])
    assert order[1] == ("launch", "p1", "ssrf")


def test_launch_unknown_project_404(monkeypatch, records) -> None:
    hunting_runtime = _patch(monkeypatch, project=False)
    called: list[str] = []
    monkeypatch.setattr(
        hunting_runtime,
        "launch_evolution_pass",
        lambda pid, skill, **kw: called.append(pid) or _resolved(None),
    )

    resp = client.post("/projects/nope/skills/ssrf/evolve", json={})

    assert resp.status_code == 404
    assert called == []
    assert records.get("nope", PASS_ID) is None


def test_launch_fails_closed_503_without_the_control_plane(monkeypatch, records) -> None:
    _patch(monkeypatch, plane=False)

    resp = client.post("/projects/p1/skills/ssrf/evolve", json={})

    assert resp.status_code == 503
    assert records.get("p1", PASS_ID) is None


def test_launch_invalid_posted_lesson_is_refused_400(monkeypatch, records) -> None:
    _patch(monkeypatch)
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
    assert records.get("p1", PASS_ID) is None


def test_an_unwritable_record_refuses_the_launch_503(monkeypatch) -> None:
    """The launch cannot honour the status contract without its record: an
    unwritable store is a refusal, never a silent in-memory pass."""
    _patch(monkeypatch)

    class _Collapsed(_REAL_PASS_STORE):
        def start(self, project_id, skill, pass_id):
            raise evolver.StoreUnavailableError("store_unavailable: disk gone")

    monkeypatch.setattr(evolver, "EvolutionPassStore", _Collapsed)

    resp = client.post("/projects/p1/skills/ssrf/evolve", json={})

    assert resp.status_code == 503
    assert "pass record unavailable" in resp.json()["detail"]
