"""Real isolated-PostgreSQL behavior for JS producer discovery and admission."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from polymerhus.app import config as config_module
from polymerhus.app.clients import pg
from polymerhus.app.js_context.selection import publication_input
from polymerhus.attack.hunting.js_context_admission import (
    JsContextAdmissionError,
    resolve_js_context_admission,
)


def _dsn() -> str:
    value = os.environ.get("JS_CONTEXT_GATE_TEST_DSN", "").strip()
    if not value:
        pytest.skip("JS_CONTEXT_GATE_TEST_DSN is not configured")
    return value


def _cleanup(dsn: str, run_ids: list[str], hunting_ids: list[str]) -> None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM analysis_runs WHERE run_id = ANY(%s)",
            (run_ids,),
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
            "DELETE FROM hunting_runs WHERE hunting_run_id = ANY(%s)",
            (hunting_ids,),
        )


def _selection(project_id: str, run_id: str):
    return publication_input(
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


def test_real_postgres_js_gate_pending_settled_scope_and_hunting_metadata(
    monkeypatch,
):
    dsn = _dsn()
    monkeypatch.setattr(config_module.config, "POSTGRES_DSN", dsn)
    pg.ensure_recon_schema()
    pg.ensure_hunting_schema()

    suffix = uuid.uuid4().hex
    project_a = f"jsgate-a-{suffix}"
    project_b = f"jsgate-b-{suffix}"
    run_a = f"run-a-{suffix}"
    run_b = f"run-b-{suffix}"
    run_stopped = f"run-stopped-{suffix}"
    hunting_id = f"hunt-{suffix}"
    run_ids = [run_a, run_b, run_stopped]

    try:
        for project_id, run_id, run_status in (
            (project_a, run_a, "running"),
            (project_b, run_b, "running"),
            (project_b, run_stopped, "stopped"),
        ):
            pg.create_run(run_id, project_id)
            pg.upsert_job(
                run_id,
                6,
                "js_analysis",
                "in_progress",
                stats={"js_selected": True},
            )
            pg.create_analysis_run(
                f"analysis-{run_id}",
                run_id,
                project_id,
            )
            if run_status != "running":
                pg.set_run_status(run_id, run_status)

        assert pg.run_has_js_analysis(run_a) is True
        assert pg.list_active_js_context_producers(project_a) == [run_a]

        with pytest.raises(JsContextAdmissionError) as missing:
            resolve_js_context_admission(
                project_a,
                run_a,
                pg_module=pg,
            )
        assert missing.value.code == "js_context_analysis_missing"

        selection = _selection(project_a, run_a)
        pending = {
            "input_id": selection.input_id,
            "project_id": project_a,
            "producing_run_id": run_a,
            "status": "pending",
            "gaps": [],
            "selection": selection.as_dict(),
        }
        pg.set_run_stats(
            run_a,
            {
                "unrelated": {"preserved": True},
                "js_context_application": pending,
            },
        )
        pg.set_run_stats(
            run_a,
            {"second_write": True},
        )
        reopened = pg.get_run(run_a)
        assert reopened["stats"]["unrelated"] == {"preserved": True}
        assert reopened["stats"]["second_write"] is True
        with pytest.raises(JsContextAdmissionError) as not_ready:
            resolve_js_context_admission(
                project_a,
                run_a,
                pg_module=pg,
            )
        assert not_ready.value.code == "js_context_not_ready"

        settled = {
            **pending,
            "status": "settled_gap",
            "gaps": ["bounded_selection"],
        }
        pg.set_run_stats(
            run_a,
            {"js_context_application": settled},
        )
        admitted = resolve_js_context_admission(
            project_a,
            run_a,
            pg_module=pg,
        )
        assert admitted.selection == selection
        assert admitted.summary["status"] == "settled_gap"

        assert pg.list_active_js_context_producers(project_a) == [run_a]
        assert pg.list_active_js_context_producers(project_b) == [run_b]
        assert run_stopped not in pg.list_active_js_context_producers(
            project_b
        )

        with psycopg.connect(dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO hunting_runs "
                "(hunting_run_id, project_id, status) "
                "VALUES (%s, %s, 'running')",
                (hunting_id, project_a),
            )
        pg.set_hunting_run_status(
            hunting_id,
            "running",
            stats={"js_context": selection.as_dict()},
        )
        persisted = pg.get_hunting_run(hunting_id)
        assert persisted["stats"]["js_context"] == selection.as_dict()
    finally:
        _cleanup(dsn, run_ids, [hunting_id])
