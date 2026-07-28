from fastapi.testclient import TestClient

from polymerhus.project_management import api as routes
from polymerhus.app.clients import pg
from polymerhus.app.main import app

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


def test_put_settings_auth_context_without_cookies_200(monkeypatch):
    """cookies is optional: it drives request-based crawling and is independent
    of credentials (agentic login, D23-2). An auth_context that omits cookies
    entirely (e.g. only scope, or only credentials) must be accepted so a
    partial PUT can set one item without supplying the other."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append((pid, recon)))

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"scope": "/app"}}},
    )

    assert resp.status_code == 200
    assert saved == [("p1", {"auth_context": {"scope": "/app"}})]


def test_put_settings_credentials_without_cookies_200(monkeypatch):
    """Regression: a PUT carrying only credentials (no cookies key at all) must
    succeed - cookies must not be a required sibling of credentials."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append(recon))

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"credentials": {
            "username": "u@e.com", "password": "pw",
            "login_url": "https://login.example.com/"}}}},
    )

    assert resp.status_code == 200
    assert saved and "cookies" not in saved[0]["auth_context"]
    assert saved[0]["auth_context"]["credentials"]["username"] == "u@e.com"


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


def test_put_settings_valid_credentials_200(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append(recon))
    recon = {"target_domain": "example.com", "auth_context": {
        "cookies": [],
        "credentials": {"username": "u@e.com", "password": "pw",
                        "login_url": "https://login.example.com/", "domain": "example.com"}}}
    resp = client.put("/projects/p1/settings", json={"recon": recon})
    assert resp.status_code == 200
    assert saved and saved[0]["auth_context"]["credentials"]["username"] == "u@e.com"


def test_put_settings_malformed_credentials_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)
    # missing password
    resp = client.put("/projects/p1/settings", json={"recon": {"auth_context": {
        "cookies": [], "credentials": {"username": "u", "login_url": "https://x"}}}})
    assert resp.status_code == 400


def test_put_settings_arbitrary_headers_200(monkeypatch):
    """auth_context is header-agnostic: any non-reserved key is an HTTP header
    (Authorization, X-Api-Key, ...) that must be accepted and stored verbatim,
    alongside the structured cookies list."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    saved = []
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: saved.append(recon))

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {
            "cookies": [{"name": "session", "value": "abc"}],
            "Authorization": "Bearer eyJx.y.z",
            "X-Api-Key": "k-123",
        }}},
    )

    assert resp.status_code == 200
    ac = saved[0]["auth_context"]
    assert ac["Authorization"] == "Bearer eyJx.y.z"
    assert ac["X-Api-Key"] == "k-123"


def test_put_settings_literal_cookie_header_400(monkeypatch):
    """A literal `Cookie` header is refused: the cookies list is the one source
    of the Cookie header (no two sources of truth)."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"Cookie": "session=abc"}}},
    )

    assert resp.status_code == 400


def test_put_settings_invalid_header_name_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"X Api Key": "k-123"}}},  # space is not a token char
    )

    assert resp.status_code == 400


def test_put_settings_header_non_string_value_400(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"X-Api-Key": 123}}},
    )

    assert resp.status_code == 400


def test_put_settings_header_crlf_injection_400(monkeypatch):
    """A CR/LF in a header value is header-injection and must be rejected."""
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)
    monkeypatch.setattr(pg, "save_settings", lambda pid, recon: None)

    resp = client.put(
        "/projects/p1/settings",
        json={"recon": {"auth_context": {"Authorization": "Bearer x\r\nX-Evil: 1"}}},
    )

    assert resp.status_code == 400


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
    monkeypatch.setattr(routes, "_launch_pipeline",
                        lambda project_id, run_id, jobs: launched.append(run_id))

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
    monkeypatch.setattr(routes, "_launch_pipeline",
                        lambda project_id, run_id, jobs: launched.append(run_id))

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
    monkeypatch.setattr(routes, "_launch_pipeline",
                        lambda project_id, run_id, jobs: launched.append(run_id))

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
