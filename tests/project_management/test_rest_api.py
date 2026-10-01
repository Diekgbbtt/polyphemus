from fastapi.testclient import TestClient

from polymerhus.project_management import api as routes
from polymerhus.project_management import repository
from polymerhus.app.clients import pg
from polymerhus.app.main import app

client = TestClient(app)


def test_create_project_returns_project_id(monkeypatch):
    calls = []
    scaffolds = []
    monkeypatch.setattr(pg, "create_project", lambda pid, name: calls.append((pid, name)))
    monkeypatch.setattr(
        repository.data_root, "ensure_project", lambda pid, root=None: scaffolds.append(pid)
    )

    resp = client.post("/projects", json={"name": "acme"})

    assert resp.status_code == 200
    body = resp.json()
    assert "project_id" in body and body["project_id"]
    assert calls == [(body["project_id"], "acme")]
    assert scaffolds == [body["project_id"]]


def test_create_project_scaffolds_into_the_given_root(tmp_path, monkeypatch):
    from polymerhus.project_management import repository

    created = []
    monkeypatch.setattr(pg, "create_project", lambda pid, name: created.append(pid))

    project_id = repository.create_project("acme", root=tmp_path / "data")

    assert created == [project_id]
    assert (tmp_path / "data" / project_id / "skills").is_dir()
    assert (tmp_path / "data" / project_id / "hunting" / "orchestration").is_dir()


def test_put_settings_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    resp = client.put("/projects/nope/settings", json={"recon": {"target_domain": "x.com"}})

    assert resp.status_code == 404


def test_put_settings_partial_dict_persisted_verbatim_200(monkeypatch):
    """#243: the settings blob carries no auth - a partial PUT persists its
    recon dict verbatim (no value-object validation); auth lives in the
    shared store, seeded through PUT /projects/{id}/auth."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append((pid, recon)))

    recon = {
        "max_pods": 3,
        "target_domain": "example.com",
        "scope": {"mode": "wildcard"},
    }
    resp = client.put("/projects/p1/settings", json={"recon": recon})

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert saved == [("p1", recon)]


def test_put_settings_nested_partial_dict_persisted_verbatim_200(monkeypatch):
    """Nested settings (arbitrary operator keys, header-like or otherwise)
    persist verbatim - the settings face validates nothing beyond the
    project guard."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append(recon))

    recon = {"target_domain": "example.com", "scope": {"mode": "exact"},
             "notes": "operator free text: X-Api-Key k-123"}
    resp = client.put("/projects/p1/settings", json={"recon": recon})
    assert resp.status_code == 200
    assert saved and saved[0]["scope"] == {"mode": "exact"}


def test_put_settings_rejects_the_retired_auth_context_key_400(monkeypatch):
    """#243 retired the settings-blob auth footprint; this disarms the last
    receptacle. A PUT carrying `auth_context` is refused (nothing lands) with a
    pointer to the live seed face `PUT /projects/{id}/auth`."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append((pid, recon)))

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"cookies": [{"name": "s", "value": "v"}]}}},
    )

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "auth_context" in detail
    assert "/auth" in detail
    assert saved == []


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

    # arjun consumes "Endpoint", which is not produced by any earlier job in
    # this subset and is not covered by the seed-host injection (that only
    # satisfies "Subdomain"-consuming jobs like httpx).
    resp = client.post("/projects/p1/recon", json={"jobs": ["arjun"]})

    assert resp.status_code == 400


def test_post_recon_no_target_domain_400(monkeypatch):
    # A targetless run must be refused, not silently fall back to example.com.
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {})
    launched = []
    monkeypatch.setattr(routes, "_schedule_pipeline",
                        lambda project_id, run_id, jobs, **kw: launched.append(run_id))

    resp = client.post("/projects/p1/recon", json={"jobs": ["subfinder", "dnsx"]})

    assert resp.status_code == 400
    assert "target_seed" in resp.json()["detail"]
    assert launched == []  # never launched


def test_post_recon_valid_launches_pipeline_and_returns_run_id(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    events = []
    monkeypatch.setattr(pg, "create_run", lambda run_id, pid: events.append(("create_run", pid, run_id)))
    monkeypatch.setattr(
        routes, "_schedule_pipeline", lambda project_id, run_id, jobs, **kw: events.append(("launch", project_id, run_id, jobs))
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
        routes, "_schedule_pipeline", lambda project_id, run_id, jobs, **kw: launched.append((project_id, run_id, jobs))
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
    monkeypatch.setattr(routes, "_schedule_pipeline", lambda project_id, run_id, jobs, **kw: None)
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
            # #34: the analysis feed's report rides the run row, so the operator
            # asking "did this run finish its analysis?" can see the answer.
            "stats": {"mode": "queued", "analysis_drained": True,
                      "advance_blocked_s_max": 0.001},
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
    assert body["stats"]["analysis_drained"] is True
    assert body["stats"]["advance_blocked_s_max"] == 0.001


def test_post_recon_with_removed_gau_job_returns_error(monkeypatch):
    """gau is withdrawn from the pipeline (D-gau): the agent app must reject a
    run that lists it, and must never launch. Mirrors the operator's manual
    check (POST a run whose jobs include gau -> the app errors)."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    launched = []
    monkeypatch.setattr(routes, "_schedule_pipeline",
                        lambda project_id, run_id, jobs, **kw: launched.append(run_id))

    resp = client.post("/projects/p1/recon", json={"jobs": ["httpx", "gau"]})

    assert resp.status_code == 400
    assert "gau" in resp.json()["detail"]
    assert launched == []


def test_post_recon_baseline_pipeline_still_launches_without_gau(monkeypatch):
    """The baseline (default, no explicit jobs) pipeline still launches after
    gau's removal - the full phase plan no longer contains it."""
    from polymerhus.recon.control.jobs import PHASES
    assert not any("gau" in phase for phase in PHASES)

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_domain": "example.com"})
    monkeypatch.setattr(pg, "create_run", lambda run_id, pid: None)
    launched = []
    monkeypatch.setattr(routes, "_schedule_pipeline",
                        lambda project_id, run_id, jobs, **kw: launched.append(run_id))

    resp = client.post("/projects/p1/recon", json={})

    assert resp.status_code == 200
    assert launched  # baseline run accepted


# --- POST /projects/{id}/bootstrap (#29): the pre-analysis delivery seam --------
# The Bootstrapper is a pre-analysis PHASE, not a supervised analyser proposer, so
# the API is its delivery seam: a frontend component ingests the operator's
# knowledge here and triggers the projection.

def _stub_bootstrap(monkeypatch, result=None, exc=None):
    """Patch the use-case's collaborator, not the use-case: the route's error
    mapping is what is under test, and the real one runs two LLM calls."""
    from polymerhus.analysis import bootstrap as bootstrap_mod

    def fake(project_id, **kwargs):
        if exc is not None:
            raise exc
        return result

    monkeypatch.setattr(bootstrap_mod, "run_bootstrap", fake)


def test_bootstrap_ingests_the_kb_and_returns_the_skeleton_counts(monkeypatch):
    from polymerhus.analysis.bootstrap import BootstrapExport

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, s: saved.append((pid, s)))
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"operator_kb": "a juice marketplace"})
    _stub_bootstrap(monkeypatch, BootstrapExport(services_written=22, systems_written=3))

    resp = client.post("/projects/p1/bootstrap", json={"operator_kb": "a juice marketplace"})

    assert resp.status_code == 200
    assert resp.json() == {"services_written": 22, "systems_written": 3}
    # the operator's knowledge is INGESTED (persisted) before the projection runs,
    # so a re-bootstrap and the later analysis read the same durable text
    assert saved == [("p1", {"operator_kb": "a juice marketplace"})]


def test_bootstrap_without_a_body_kb_uses_the_stored_one(monkeypatch):
    from polymerhus.analysis.bootstrap import BootstrapExport

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, s: saved.append((pid, s)))
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"operator_kb": "stored kb"})
    _stub_bootstrap(monkeypatch, BootstrapExport(services_written=5, systems_written=3))

    resp = client.post("/projects/p1/bootstrap", json={})

    assert resp.status_code == 200
    assert saved == []  # nothing supplied -> nothing overwritten


def test_bootstrap_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    resp = client.post("/projects/nope/bootstrap", json={"operator_kb": "x"})
    assert resp.status_code == 404


def test_bootstrap_without_any_kb_is_400(monkeypatch):
    """A KB-less project is a caller error, not a blocked bootstrap: there is
    nothing to project, and the operator has to supply the knowledge first."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"target_seed": "x.com"})

    resp = client.post("/projects/p1/bootstrap", json={})

    assert resp.status_code == 400
    assert "operator_kb" in resp.json()["detail"]


def test_bootstrap_blank_kb_in_the_body_is_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, s: saved.append(s))

    resp = client.post("/projects/p1/bootstrap", json={"operator_kb": "   "})

    assert resp.status_code == 400
    assert saved == []  # a blank KB never overwrites a stored one


def test_bootstrap_fail_closed_is_503_not_a_zero_count_200(monkeypatch):
    """THE fail-closed contract (#26 Q6). A block must not reach the caller as a
    successful empty skeleton - that is exactly the misreading that would let the
    whole analysis run against an empty L1."""
    from polymerhus.analysis.bootstrap import BootstrapExport

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, s: None)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"operator_kb": "kb"})
    _stub_bootstrap(monkeypatch, BootstrapExport(blocked=True, error="reason: exhausted after retries"))

    resp = client.post("/projects/p1/bootstrap", json={"operator_kb": "kb"})

    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "must not proceed" in detail and "exhausted" in detail


def test_bootstrap_does_not_open_a_recon_run(monkeypatch):
    """A bootstrap is NOT a recon run: minting a run row here would leave a run the
    bootstrap never advances or heartbeats sitting in /runs?status=running forever."""
    from polymerhus.analysis.bootstrap import BootstrapExport

    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, s: None)
    monkeypatch.setattr(pg, "load_settings", lambda pid: {"operator_kb": "kb"})
    opened = []
    monkeypatch.setattr(pg, "create_run", lambda rid, pid: opened.append(rid))
    _stub_bootstrap(monkeypatch, BootstrapExport(services_written=1, systems_written=3))

    assert client.post("/projects/p1/bootstrap", json={"operator_kb": "kb"}).status_code == 200
    assert opened == []


# --- #75: the analysis-only dispatch validates the run exists ------------------

def test_post_analysis_unknown_run_is_404_not_a_zombie(monkeypatch):
    """Starting a consumer for an unknown run_id would create a `draining` analysis
    run whose queue no recon will ever end - a zombie. The dispatch must 404 first,
    and must NOT start a consumer."""
    started = []
    monkeypatch.setattr(pg, "get_run", lambda run_id: None)         # run does not exist
    import polymerhus.analysis.lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "start_analysis",
                        lambda pid, rid, **k: started.append(rid) or "should-not-happen")

    resp = client.post("/projects/p1/analysis", json={"run_id": "ghost"})
    assert resp.status_code == 404
    assert started == []                                            # no consumer started


def test_post_analysis_known_run_starts_the_consumer(monkeypatch):
    monkeypatch.setattr(pg, "get_run", lambda run_id: {"run_id": run_id, "status": "complete"})
    import polymerhus.analysis.lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "start_analysis", lambda pid, rid, **k: f"{rid}:aid")

    resp = client.post("/projects/p1/analysis", json={"run_id": "real"})
    assert resp.status_code == 200
    assert resp.json() == {"run_id": "real", "analysis_run_id": "real:aid"}


# --- GET /app-state: the read-only running-state surface ----------------------
# Consumers read this as the "is any effective project execution in flight?"
# signal, with a direct-postgres query as the documented fallback (see the
# route docstring). In-flight is a persisted-row predicate over the three run
# classes the store can express: recon `running`, analysis `draining` (its
# only live state), hunting `running` (its only live state).

def _stub_app_state(monkeypatch, projects, recon=(), analysis=(), hunting=()):
    monkeypatch.setattr(pg, "list_projects", lambda: list(projects))
    monkeypatch.setattr(pg, "list_running_runs", lambda: list(recon))
    monkeypatch.setattr(pg, "list_running_analysis_runs", lambda: list(analysis))
    monkeypatch.setattr(pg, "list_running_hunting_runs", lambda: list(hunting))


def _project(pid, name=None):
    return {"project_id": pid, "name": name or pid, "created_at": None}


def _recon_row(rid, pid):
    return {"run_id": rid, "project_id": pid, "project_name": pid,
            "status": "running", "current_phase": 0,
            "started_at": None, "last_heartbeat_at": None, "jobs": {}}


def test_app_state_idle_with_projects_present_but_nothing_running(monkeypatch):
    """Idle is not "a project exists": projects with no in-flight run read idle."""
    _stub_app_state(monkeypatch, [_project("p1"), _project("p2")])

    resp = client.get("/app-state")

    assert resp.status_code == 200
    body = resp.json()
    assert body["idle"] is True
    assert [p["project_id"] for p in body["projects"]] == ["p1", "p2"]
    for entry in body["projects"]:
        assert entry["in_flight"] is False
        assert entry["recon"] == [] and entry["analysis"] == [] and entry["hunting"] == []


def test_app_state_running_recon_is_in_flight(monkeypatch):
    _stub_app_state(monkeypatch, [_project("p1")], recon=[_recon_row("r1", "p1")])

    body = client.get("/app-state").json()

    assert body["idle"] is False
    (entry,) = body["projects"]
    assert entry["in_flight"] is True
    assert [r["run_id"] for r in entry["recon"]] == ["r1"]
    assert entry["analysis"] == [] and entry["hunting"] == []


def test_app_state_draining_analysis_is_in_flight(monkeypatch):
    """Analysis `draining` is its only live state; every other analysis status
    is terminal and must not count."""
    _stub_app_state(
        monkeypatch, [_project("p1")],
        analysis=[{"analysis_run_id": "a1", "run_id": "r1", "project_id": "p1",
                   "status": "draining", "started_at": None}],
    )

    body = client.get("/app-state").json()

    assert body["idle"] is False
    (entry,) = body["projects"]
    assert entry["in_flight"] is True
    assert [a["analysis_run_id"] for a in entry["analysis"]] == ["a1"]


def test_app_state_running_hunting_is_in_flight(monkeypatch):
    _stub_app_state(
        monkeypatch, [_project("p1")],
        hunting=[{"hunting_run_id": "h1", "project_id": "p1",
                  "status": "running", "started_at": None, "finished_at": None}],
    )

    body = client.get("/app-state").json()

    assert body["idle"] is False
    (entry,) = body["projects"]
    assert entry["in_flight"] is True
    assert [h["hunting_run_id"] for h in entry["hunting"]] == ["h1"]


def test_app_state_per_project_breakdown(monkeypatch):
    """Two projects, one busy: the breakdown names the busy one and leaves the
    other idle."""
    _stub_app_state(
        monkeypatch, [_project("p1"), _project("p2")],
        recon=[_recon_row("r1", "p2")],
        hunting=[{"hunting_run_id": "h1", "project_id": "p2",
                  "status": "running", "started_at": None, "finished_at": None}],
    )

    body = client.get("/app-state").json()

    assert body["idle"] is False
    by_id = {p["project_id"]: p for p in body["projects"]}
    assert by_id["p1"]["in_flight"] is False
    assert by_id["p2"]["in_flight"] is True
    assert [r["run_id"] for r in by_id["p2"]["recon"]] == ["r1"]
    assert [h["hunting_run_id"] for h in by_id["p2"]["hunting"]] == ["h1"]


def test_app_state_scoped_to_one_project(monkeypatch):
    """?project_id narrows the scope; the top-level idle reflects the scope."""
    _stub_app_state(
        monkeypatch, [_project("p1"), _project("p2")],
        recon=[_recon_row("r1", "p2")],
    )
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)

    idle_scope = client.get("/app-state", params={"project_id": "p1"}).json()
    assert [p["project_id"] for p in idle_scope["projects"]] == ["p1"]
    assert idle_scope["idle"] is True

    busy_scope = client.get("/app-state", params={"project_id": "p2"}).json()
    assert busy_scope["idle"] is False
    assert busy_scope["projects"][0]["in_flight"] is True


def test_app_state_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)

    assert client.get("/app-state", params={"project_id": "nope"}).status_code == 404
    assert client.get("/app-state", params={"project_id": "nope"}).json()["detail"] == "unknown project"
    assert client.get("/app-state", params={"project_id": ""}).status_code == 404


def test_app_state_writes_nothing(monkeypatch):
    """The surface is read-only: every pg write verb raises, the GET still
    succeeds, so no state change could have passed through the gateway seam."""
    _stub_app_state(monkeypatch, [_project("p1")])

    def _boom(*args, **kwargs):
        raise AssertionError("app-state must not write")

    for fn in ("create_project", "save_settings", "create_run", "set_run_status",
               "create_analysis_run", "set_analysis_run_status",
               "create_hunting_run", "set_hunting_run_status"):
        monkeypatch.setattr(pg, fn, _boom)

    resp = client.get("/app-state")

    assert resp.status_code == 200
    assert resp.json()["idle"] is True
