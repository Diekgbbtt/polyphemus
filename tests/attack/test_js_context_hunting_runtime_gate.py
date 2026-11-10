"""Direct hunting bootstrap cannot bypass the bound JS admission check."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.js_context_admission import JsContextAdmissionError


def test_runtime_refuses_pending_bound_js_and_closes_preopened_row(
    monkeypatch,
):
    async def inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", lambda _: None)

    def refuse(*args, **kwargs):
        raise JsContextAdmissionError(
            "js_context_not_ready",
            gaps=["pending"],
        )

    monkeypatch.setattr(
        "polymerhus.attack.hunting.js_context_admission.resolve_js_context_admission",
        refuse,
    )
    writes = []
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.set_hunting_run_status",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )

    result = asyncio.run(
        hunting_runtime.start_hunting(
            "project-a",
            run_id="hunt-1",
            producing_run_id="run-1",
        )
    )

    assert result is None
    assert writes[0][0][:2] == ("hunt-1", "failed")


def test_runtime_revalidates_the_selection_admitted_by_the_api(monkeypatch):
    async def inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)
    monkeypatch.setattr("polymerhus.app.clients.pg.get_hunting_run", lambda _: None)
    seen = {}

    def changed(project_id, producing_run_id, *, expected_input_id=None):
        seen.update(
            project_id=project_id,
            producing_run_id=producing_run_id,
            expected_input_id=expected_input_id,
        )
        raise JsContextAdmissionError(
            "js_context_application_changed",
            gaps=["stale_js_context_application"],
        )

    monkeypatch.setattr(
        "polymerhus.attack.hunting.js_context_admission.resolve_js_context_admission",
        changed,
    )
    writes = []
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.set_hunting_run_status",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    admission = SimpleNamespace(
        selection=SimpleNamespace(
            input_id="jsinput_frozen",
            producing_run_id="run-1",
        )
    )

    result = asyncio.run(
        hunting_runtime.start_hunting(
            "project-a",
            run_id="hunt-1",
            js_context_admission=admission,
        )
    )

    assert result is None
    assert seen == {
        "project_id": "project-a",
        "producing_run_id": "run-1",
        "expected_input_id": "jsinput_frozen",
    }
    assert writes[0][0][:2] == ("hunt-1", "failed")
