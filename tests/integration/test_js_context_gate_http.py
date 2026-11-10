"""Real ASGI/HTTP hunting gate over task-owned isolated PostgreSQL."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest

from polymerhus.app import config as config_module
from polymerhus.app.clients import pg
from polymerhus.app.js_context.selection import publication_input


def _dsn() -> str:
    value = os.environ.get("JS_CONTEXT_GATE_TEST_DSN", "").strip()
    if not value:
        pytest.skip("JS_CONTEXT_GATE_TEST_DSN is not configured")
    return value


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _seed_settled(dsn: str, project_id: str, run_id: str, *, pending=False):
    selection = publication_input(
        project_id=project_id,
        producing_run_id=run_id,
        publication={
            "status": "published",
            "context_id": "jsctx_" + "a" * 40,
            "document_id": "document-1",
            "document_sha256": "b" * 64,
            "auth_ref": "alice",
            "origin": {"status": "known", "value": "https://app.example"},
        },
    )
    pg.create_run(run_id, project_id)
    pg.upsert_job(
        run_id,
        6,
        "js_analysis",
        "success",
        stats={"js_selected": True, "js_context_input": selection.as_dict()},
    )
    pg.set_run_status(run_id, "complete")
    pg.set_run_stats(
        run_id,
        {
            "js_context_application": {
                "input_id": selection.input_id,
                "project_id": project_id,
                "producing_run_id": run_id,
                "status": "pending" if pending else "settled_success",
                "gaps": [],
                "selection": selection.as_dict(),
            }
        },
    )
    return selection


def test_real_asgi_http_gate_uses_isolated_database(monkeypatch):
    dsn = _dsn()
    monkeypatch.setattr(config_module.config, "POSTGRES_DSN", dsn)
    pg.ensure_recon_schema()
    pg.ensure_hunting_schema()

    suffix = uuid.uuid4().hex
    project_pending = f"http-pending-{suffix}"
    project_ready = f"http-ready-{suffix}"
    project_refuse = f"http-refuse-{suffix}"
    run_pending = f"run-pending-{suffix}"
    run_ready = f"run-ready-{suffix}"
    run_refuse = f"run-refuse-{suffix}"
    project_ids = [project_pending, project_ready, project_refuse]
    run_ids = [run_pending, run_ready, run_refuse]

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for project_id in project_ids:
            cur.execute(
                "INSERT INTO projects (project_id, name) VALUES (%s, %s)",
                (project_id, project_id),
            )
    selection_pending = _seed_settled(
        dsn,
        project_pending,
        run_pending,
        pending=True,
    )
    selection_ready = _seed_settled(dsn, project_ready, run_ready)
    selection_refuse = _seed_settled(dsn, project_refuse, run_refuse)

    port = _free_port()
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["POSTGRES_DSN"] = dsn
    env["PYTHONPATH"] = (
        str(root / "src")
        + os.pathsep
        + str(root / "tests" / "integration")
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "js_context_gate_asgi_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=1)
                raise AssertionError(
                    f"ASGI process exited early: {stdout}\n{stderr}"
                )
            try:
                if httpx.get(base + "/docs", timeout=0.5).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("ASGI process did not become ready")

        pending = httpx.post(
            f"{base}/projects/{project_pending}/hunting",
            json={"producing_run_id": run_pending},
            timeout=5,
        )
        assert pending.status_code == 409
        assert pending.json()["detail"]["code"] == "js_context_not_ready"
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM hunting_runs WHERE project_id = %s",
                (project_pending,),
            )
            assert cur.fetchone()[0] == 0

        ready = httpx.post(
            f"{base}/projects/{project_ready}/hunting",
            json={"producing_run_id": run_ready},
            timeout=5,
        )
        assert ready.status_code == 201, ready.text
        recorded = httpx.get(base + "/recorded", timeout=5).json()["calls"]
        assert recorded[0]["producing_run_id"] == run_ready
        assert type(selection_ready).from_dict(
            recorded[0]["js_context_selection"]
        ) == selection_ready

        refused = httpx.post(
            f"{base}/projects/{project_refuse}/hunting",
            json={"producing_run_id": run_refuse},
            timeout=5,
        )
        assert refused.status_code == 503
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM hunting_runs WHERE project_id = %s",
                (project_refuse,),
            )
            assert cur.fetchone()[0] == "failed"
        assert selection_pending.input_id != selection_refuse.input_id
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM hunting_runs WHERE project_id = ANY(%s)",
                (project_ids,),
            )
            cur.execute(
                "DELETE FROM recon_jobs WHERE run_id = ANY(%s)",
                (run_ids,),
            )
            cur.execute(
                "DELETE FROM recon_runs WHERE run_id = ANY(%s)",
                (run_ids,),
            )
            cur.execute(
                "DELETE FROM projects WHERE project_id = ANY(%s)",
                (project_ids,),
            )
