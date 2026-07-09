from fastapi.testclient import TestClient

from agent.app import routes
from agent.app.clients import pg
from agent.app.main import app

client = TestClient(app)


def test_create_project_returns_project_id(monkeypatch):
    calls = []
    monkeypatch.setattr(pg, "create_project", lambda pid, name: calls.append((pid, name)))

    resp = client.post("/projects", json={"name": "acme"})

    assert resp.status_code == 200
    body = resp.json()
    assert "project_id" in body and body["project_id"]
    assert calls == [(body["project_id"], "acme")]


def test_put_settings_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    resp = client.put("/projects/nope/settings", json={"recon": {"target_domain": "x.com"}})

    assert resp.status_code == 404


def test_put_settings_malformed_auth_context_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append((pid, recon)))

    # cookies must be a list of {name, value}; here it's a bare string
    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"cookies": "not-a-list"}}},
    )

    assert resp.status_code == 400
    assert saved == []


def test_put_settings_malformed_auth_context_missing_cookies_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"scope": "/app"}}},
    )

    assert resp.status_code == 400


def test_put_settings_valid_auth_context_200(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append((pid, recon)))

    recon = {
        "max_pods": 3,
        "target_domain": "example.com",
        "auth_context": {
            "cookies": [{"name": "session", "value": "abc123"}],
            "scope": "/app",
        },
    }
    resp = client.put("/projects/p1/settings", json={"recon": recon})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert saved == [("p1", recon)]


def test_post_recon_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    resp = client.post("/projects/nope/recon", json={})

    assert resp.status_code == 404


def test_post_recon_unknown_job_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)

    resp = client.post("/projects/p1/recon", json={"jobs": ["not_a_real_job"]})

    assert resp.status_code == 400


def test_post_recon_subset_breaking_consumes_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)

    # httpx consumes "Subdomain", which is not produced without subfinder/amass/dnsx
    resp = client.post("/projects/p1/recon", json={"jobs": ["httpx"]})

    assert resp.status_code == 400


def test_post_recon_no_target_domain_400(monkeypatch):
    # A targetless run must be refused, not silently fall back to example.com.
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {})
    launched = []
    monkeypatch.setattr(routes, "_launch_pipeline",
                        lambda project_id, run_id, jobs: launched.append(run_id))

    resp = client.post("/projects/p1/recon", json={"jobs": ["subfinder", "dnsx"]})

    assert resp.status_code == 400
    assert "target_domain" in resp.json()["detail"]
    assert launched == []  # never launched


def test_post_recon_valid_launches_pipeline_and_returns_run_id(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    events = []
    monkeypatch.setattr(pg, "create_run", lambda run_id, pid: events.append(("create_run", pid, run_id)))
    monkeypatch.setattr(
        routes, "_launch_pipeline", lambda project_id, run_id, jobs: events.append(("launch", project_id, run_id, jobs))
    )

    resp = client.post("/projects/p1/recon", json={"jobs": ["subfinder", "dnsx"]})

    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body and body["run_id"]
    # create_run runs SYNCHRONOUSLY and BEFORE the pipeline launch, so the run
    # row exists the instant POST returns (no GET 404 race).
    assert events == [
        ("create_run", "p1", body["run_id"]),
        ("launch", "p1", body["run_id"], ["subfinder", "dnsx"]),
    ]


def test_post_recon_valid_no_jobs_launches_full_pipeline(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    monkeypatch.setattr(pg, "create_run", lambda run_id, pid: None)
    launched = []
    monkeypatch.setattr(
        routes, "_launch_pipeline", lambda project_id, run_id, jobs: launched.append((project_id, run_id, jobs))
    )

    resp = client.post("/projects/p1/recon", json={})

    assert resp.status_code == 200
    assert launched[0][2] is None


def test_post_recon_then_get_status_no_404_race(monkeypatch):
    """The run row exists synchronously after POST, so a GET immediately
    afterwards returns 200, not 404."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    store: dict[str, dict] = {}
    monkeypatch.setattr(
        pg, "create_run", lambda run_id, pid: store.__setitem__(
            run_id, {"run_id": run_id, "project_id": pid, "status": "running",
                     "current_phase": None, "started_at": None, "finished_at": None}
        ),
    )
    monkeypatch.setattr(routes, "_launch_pipeline", lambda project_id, run_id, jobs: None)
    monkeypatch.setattr(pg, "get_run", lambda run_id: store.get(run_id))
    monkeypatch.setattr(pg, "get_run_jobs", lambda run_id: [])

    run_id = client.post("/projects/p1/recon", json={}).json()["run_id"]
    resp = client.get(f"/projects/p1/recon/{run_id}")

    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_get_recon_status_unknown_run_404(monkeypatch):
    monkeypatch.setattr(pg, "get_run", lambda run_id: None)

    resp = client.get("/projects/p1/recon/nope")

    assert resp.status_code == 404


def test_get_recon_status_returns_registry_shape(monkeypatch):
    monkeypatch.setattr(
        pg,
        "get_run",
        lambda run_id: {
            "run_id": run_id,
            "project_id": "p1",
            "status": "running",
            "current_phase": 2,
            "started_at": None,
            "finished_at": None,
        },
    )
    monkeypatch.setattr(
        pg,
        "get_run_jobs",
        lambda run_id: [
            {"id": 1, "run_id": run_id, "phase": 0, "job": "subfinder", "status": "success",
             "started_at": None, "finished_at": None, "stats": {}, "error": None}
        ],
    )

    resp = client.get("/projects/p1/recon/run-1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["current_phase"] == 2
    assert len(body["per_job"]) == 1
    assert body["per_job"][0]["job"] == "subfinder"


def test_post_recon_with_removed_gau_job_returns_error(monkeypatch):
    """gau is withdrawn from the pipeline (D-gau): the agent app must reject a
    run that lists it, and must never launch. Mirrors the operator's manual
    check (POST a run whose jobs include gau -> the app errors)."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    launched = []
    monkeypatch.setattr(routes, "_launch_pipeline",
                        lambda project_id, run_id, jobs: launched.append(run_id))

    resp = client.post("/projects/p1/recon", json={"jobs": ["httpx", "gau"]})

    assert resp.status_code == 400
    assert "gau" in resp.json()["detail"]
    assert launched == []


def test_post_recon_baseline_pipeline_still_launches_without_gau(monkeypatch):
    """The baseline (default, no explicit jobs) pipeline still launches after
    gau's removal - the full phase plan no longer contains it."""
    from agent.recon.jobs import PHASES
    assert not any("gau" in phase for phase in PHASES)

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    monkeypatch.setattr(pg, "create_run", lambda run_id, pid: None)
    launched = []
    monkeypatch.setattr(routes, "_launch_pipeline",
                        lambda project_id, run_id, jobs: launched.append(run_id))

    resp = client.post("/projects/p1/recon", json={})

    assert resp.status_code == 200
    assert launched  # baseline run accepted
