"""Unit tier: the hunting config endpoints (`hunting_pipeline_sync`, ADR
2026-10-22).

`GET /projects/{id}/hunting/config` reads the project's `settings.hunting` blob
(defaulted); `PUT` deep-merges a partial update into it. No live PG: the pg
accessors are faked, exactly like the hunting run endpoints' test tier.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

import polymerhus.app.clients.pg as pg
from polymerhus.app.main import app

client = TestClient(app)


class FakeHuntingSettings:
    def __init__(self, *, projects=("p1",), stored=None):
        self.projects = set(projects)
        self.stored = dict(stored or {})
        self.saves: list[tuple[str, dict]] = []

    def project_exists(self, project_id):
        return project_id in self.projects

    def get_hunting_settings(self, project_id):
        return dict(self.stored.get(project_id, {}))

    def save_hunting_settings(self, project_id, body):
        self.saves.append((project_id, dict(body)))
        self.stored.setdefault(project_id, {}).update(body)


def _install(monkeypatch, fake):
    monkeypatch.setattr(pg, "project_exists", fake.project_exists)
    monkeypatch.setattr(pg, "get_hunting_settings", fake.get_hunting_settings)
    monkeypatch.setattr(pg, "save_hunting_settings", fake.save_hunting_settings)


def test_get_reads_the_default_batched_mode(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.get("/projects/p1/hunting/config")
    assert response.status_code == 200
    assert response.json() == {
        "pipeline_sync": "batched",
        "risk_threshold": None,
        "pod_batch_size": 1,
        "promotion_risk_threshold": None,
        "threat_model_scope": "",
    }


def test_get_reads_the_stored_config(monkeypatch):
    fake = FakeHuntingSettings(stored={
        "p1": {
            "pipeline_sync": "serial",
            "risk_threshold": 250,
            "pod_batch_size": 3,
            "promotion_risk_threshold": 5,
        }})
    _install(monkeypatch, fake)
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "serial",
        "risk_threshold": 250,
        "pod_batch_size": 3,
        "promotion_risk_threshold": 5,
        "threat_model_scope": "",
    }


def test_get_reads_the_stored_project_scope_verbatim(monkeypatch):
    """#438: the project model exposes the free-text posture statement; the
    read returns it exactly as stored."""
    scope = ("The target is assumed to have a request-rate limiter and a WAF "
             "in blocking mode. The internal build network is out of scope.")
    fake = FakeHuntingSettings(stored={
        "p1": {"pipeline_sync": "serial", "risk_threshold": 250,
               "threat_model_scope": scope}})
    _install(monkeypatch, fake)
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "serial",
        "risk_threshold": 250,
        "pod_batch_size": 1,
        "promotion_risk_threshold": None,
        "threat_model_scope": scope,
    }


def test_put_merges_a_pipeline_sync_update(monkeypatch):
    fake = FakeHuntingSettings(stored={"p1": {"risk_threshold": 250}})
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"pipeline_sync": "serial"})
    assert response.status_code == 200
    assert fake.saves == [("p1", {"pipeline_sync": "serial"})]
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "serial",
        "risk_threshold": 250,
        "pod_batch_size": 1,
        "promotion_risk_threshold": None,
        "threat_model_scope": "",
    }


def test_put_accepts_the_pod_batch_size_and_promotion_threshold(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config",
        json={"pod_batch_size": 3, "promotion_risk_threshold": 5},
    )
    assert response.status_code == 200
    assert fake.saves == [
        ("p1", {"pod_batch_size": 3, "promotion_risk_threshold": 5})]


def test_put_rejects_a_zero_pod_batch_size(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"pod_batch_size": 0})
    assert response.status_code == 422
    assert fake.saves == []


def test_put_rejects_a_negative_promotion_threshold(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"promotion_risk_threshold": -1})
    assert response.status_code == 422
    assert fake.saves == []


def test_put_clears_both_settings_with_an_explicit_null(monkeypatch):
    fake = FakeHuntingSettings(stored={
        "p1": {"pod_batch_size": 3, "promotion_risk_threshold": 5}})
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config",
        json={"pod_batch_size": None, "promotion_risk_threshold": None},
    )
    assert response.status_code == 200
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "batched",
        "risk_threshold": None,
        "pod_batch_size": 1,
        "promotion_risk_threshold": None,
        "threat_model_scope": "",
    }


def test_put_accepts_the_risk_threshold(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"risk_threshold": 156.25})
    assert response.status_code == 200
    assert fake.saves == [("p1", {"risk_threshold": 156.25})]


def test_put_round_trips_the_float_thresholds(monkeypatch):
    """ADR 8 / spec 12: both thresholds are floats on the CVSS 4.0 scale (the
    iteration D values 112.5 and 2.5), so the settings round-trip without
    truncation."""
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config",
        json={"risk_threshold": 112.5, "promotion_risk_threshold": 2.5},
    )
    assert response.status_code == 200
    assert fake.saves == [
        ("p1", {"risk_threshold": 112.5, "promotion_risk_threshold": 2.5})]
    read = client.get("/projects/p1/hunting/config").json()
    assert read["risk_threshold"] == 112.5
    assert read["promotion_risk_threshold"] == 2.5


def test_put_rejects_a_negative_risk_threshold(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"risk_threshold": -0.5})
    assert response.status_code == 422
    assert fake.saves == []


def test_put_rejects_a_non_numeric_threshold_naming_the_field(monkeypatch):
    """A malformed threshold fails fast at the schema layer, naming the field,
    so the run never boots on a typo."""
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    for body, field in (
        ({"risk_threshold": "high"}, "risk_threshold"),
        ({"promotion_risk_threshold": "high"}, "promotion_risk_threshold"),
    ):
        response = client.put("/projects/p1/hunting/config", json=body)
        assert response.status_code == 422, body
        assert field in response.text, body
    assert fake.saves == []


def test_the_repository_rejects_a_malformed_threshold_naming_the_field(monkeypatch):
    """The use-case layer owns the same rule as the schema: a direct caller (an
    eval setup, a script) gets a ValueError naming the field, and nothing
    lands."""
    from polymerhus.project_management.repository import save_hunting_config

    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    for body, field in (
        ({"risk_threshold": -1.0}, "risk_threshold"),
        ({"risk_threshold": "high"}, "risk_threshold"),
        ({"promotion_risk_threshold": -1.0}, "promotion_risk_threshold"),
        ({"promotion_risk_threshold": "high"}, "promotion_risk_threshold"),
    ):
        with pytest.raises(ValueError) as excinfo:
            save_hunting_config("p1", body)
        assert field in str(excinfo.value), body
    assert fake.saves == []


def test_the_repository_reads_the_stored_thresholds_as_floats(monkeypatch):
    """A stored integer from a v4-era row reads back as a float: the surface has
    ONE numeric type for the thresholds."""
    from polymerhus.project_management.repository import read_hunting_config

    fake = FakeHuntingSettings(stored={
        "p1": {"risk_threshold": 250, "promotion_risk_threshold": 4}})
    _install(monkeypatch, fake)
    config = read_hunting_config("p1")
    assert config["risk_threshold"] == 250.0
    assert isinstance(config["risk_threshold"], float)
    assert config["promotion_risk_threshold"] == 4.0
    assert isinstance(config["promotion_risk_threshold"], float)


def test_put_sets_only_the_scope_and_preserves_the_sibling_settings(monkeypatch):
    """#438: the PUT is a partial deep merge - a scope-only body lands the
    string and never drops `pipeline_sync` or `risk_threshold`."""
    scope = ("The target is assumed to have a request-rate limiter and a WAF "
             "in blocking mode.")
    fake = FakeHuntingSettings(stored={
        "p1": {"pipeline_sync": "serial", "risk_threshold": 250}})
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"threat_model_scope": scope})
    assert response.status_code == 200
    assert fake.saves == [("p1", {"threat_model_scope": scope})]
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "serial",
        "risk_threshold": 250,
        "pod_batch_size": 1,
        "promotion_risk_threshold": None,
        "threat_model_scope": scope,
    }


def test_put_an_empty_scope_round_trips_and_preserves_the_siblings(monkeypatch):
    """#438: the empty string is a real value - it round-trips as `""` and wipes
    nothing, distinct from the unset default."""
    fake = FakeHuntingSettings(stored={"p1": {"pipeline_sync": "parallel"}})
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"threat_model_scope": ""})
    assert response.status_code == 200
    assert fake.saves == [("p1", {"threat_model_scope": ""})]
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "parallel",
        "risk_threshold": None,
        "pod_batch_size": 1,
        "promotion_risk_threshold": None,
        "threat_model_scope": "",
    }


def test_put_rejects_an_unknown_mode(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"pipeline_sync": "fast"})
    assert response.status_code == 422
    assert fake.saves == []


def test_put_rejects_an_unknown_field(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"burst": "high"})
    assert response.status_code == 422
    assert fake.saves == []


def test_put_on_an_unknown_project_is_404(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/nope/hunting/config", json={"pipeline_sync": "serial"})
    assert response.status_code == 404
    assert fake.saves == []


def test_get_on_an_unknown_project_is_404(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    assert client.get("/projects/nope/hunting/config").status_code == 404

def test_put_rejects_a_boolean_pod_batch_size(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"pod_batch_size": True})
    assert response.status_code == 422
    assert fake.saves == []


def test_put_rejects_a_boolean_promotion_threshold(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"promotion_risk_threshold": True})
    assert response.status_code == 422
    assert fake.saves == []


def test_get_warns_on_a_malformed_stored_value(monkeypatch, caplog):
    fake = FakeHuntingSettings(stored={
        "p1": {"pod_batch_size": "three", "promotion_risk_threshold": -1}})
    _install(monkeypatch, fake)

    with caplog.at_level(logging.WARNING, logger="polymerhus.project_management"):
        response = client.get("/projects/p1/hunting/config")

    assert response.status_code == 200
    assert response.json()["pod_batch_size"] == 1
    assert response.json()["promotion_risk_threshold"] is None
    assert "pod_batch_size" in caplog.text
    assert "promotion_risk_threshold" in caplog.text
