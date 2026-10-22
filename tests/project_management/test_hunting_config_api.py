"""Unit tier: the hunting config endpoints (`hunting_pipeline_sync`, ADR
2026-10-22).

`GET /projects/{id}/hunting/config` reads the project's `settings.hunting` blob
(defaulted); `PUT` deep-merges a partial update into it. No live PG: the pg
accessors are faked, exactly like the hunting run endpoints' test tier.
"""
from __future__ import annotations

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
        "pipeline_sync": "batched", "risk_threshold": None}


def test_get_reads_the_stored_config(monkeypatch):
    fake = FakeHuntingSettings(stored={
        "p1": {"pipeline_sync": "serial", "risk_threshold": 250}})
    _install(monkeypatch, fake)
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "serial", "risk_threshold": 250}


def test_put_merges_a_pipeline_sync_update(monkeypatch):
    fake = FakeHuntingSettings(stored={"p1": {"risk_threshold": 250}})
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"pipeline_sync": "serial"})
    assert response.status_code == 200
    assert fake.saves == [("p1", {"pipeline_sync": "serial"})]
    assert client.get("/projects/p1/hunting/config").json() == {
        "pipeline_sync": "serial", "risk_threshold": 250}


def test_put_accepts_the_risk_threshold(monkeypatch):
    fake = FakeHuntingSettings()
    _install(monkeypatch, fake)
    response = client.put(
        "/projects/p1/hunting/config", json={"risk_threshold": 250})
    assert response.status_code == 200
    assert fake.saves == [("p1", {"risk_threshold": 250})]


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
