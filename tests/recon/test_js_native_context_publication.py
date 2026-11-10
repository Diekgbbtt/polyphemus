"""Native js_analysis finalization with frozen, recoverable context YAML."""

from __future__ import annotations

import asyncio
import json
import threading
import time

from polymerhus.app.js_context.store import JsContextStore
from polymerhus.recon.control.job_agent import run_job
from polymerhus.recon.control.jobs import JOBS
from polymerhus.recon.control.js_analysis_job import (
    prepare_js_inventory,
    run_js_analysis_job,
)
from polymerhus.recon.control.js_context_writer import JsContextWriter
from polymerhus.recon.domain.types import AssetDelta
from polymerhus.recon.js_specialist.agent import SpecialistLimits
from tests.recon.test_js_context_writer import (
    FakeAccess,
    FakeNotes,
    FakeRetention,
    _event,
    _link,
    _receipt,
    _snapshot,
)
from tests.recon.test_js_native_job import inventory


def _confirmed_graph(*, assets=None, calls=None):
    def prepare(**kwargs):
        if calls is not None:
            calls.append(("prepare", kwargs["closure"]))
        return {
            "proposal_id": "a" * 64,
            "coverage": {
                "status": kwargs["closure"]["status"],
                "gaps": list(kwargs["closure"]["gaps"]),
            },
        }

    def submit(**kwargs):
        if calls is not None:
            calls.append(("submit", kwargs["proposal_id"]))
        merged = [asset.model_dump() for asset in (assets or [])]
        return {
            "status": "confirmed",
            "assets_merged": len(merged),
            "observations_merged": 0,
            "merged_assets": merged,
            "merged_observations": [],
        }

    return prepare, submit


def _writer(tmp_path, *, notes, access, retention):
    return JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes,
        access=access,
        retention=retention,
    )


async def _native_run(
    tmp_path,
    *,
    unit,
    writer,
    specialist,
    graph_prepare,
    graph_submit,
    extra=None,
    limits=None,
):
    async def executor(**kwargs):
        return await run_js_analysis_job(
            **kwargs,
            root=tmp_path,
            specialist_fn=specialist,
            prepare_fn=graph_prepare,
            submit_fn=graph_submit,
            context_writer=writer,
            limits=limits,
        )

    return await run_job(
        JOBS["js_analysis"],
        [unit],
        run_id="r",
        phase=6,
        extra={
            "project_id": "p",
            "application_origin": "https://app.test",
            **(extra or {}),
        },
        specialist_executor=executor,
    )


def _current_context(tmp_path, *, auth_ref=""):
    from polymerhus.app.js_context.records import context_id_for

    context_id = context_id_for(
        project_id="p",
        origin={"status": "known", "value": "https://app.test"},
        auth_ref=auth_ref,
    )
    return context_id, JsContextStore(root_dir=tmp_path).read(
        project_id="p",
        context_id=context_id,
        selector="current",
        section="metadata",
    )


def test_run_job_partial_producer_coverage_publishes_yaml_with_zero_assets(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(
        project_id="p",
        run_id="r",
        root=tmp_path,
        producer_outcomes={"ffuf": {"status": "degraded", "pods": 1}},
    )
    notes = FakeNotes([])
    access = FakeAccess(
        {
            "read-a": _receipt(
                "read-a",
                project_id="p",
                run_id="r",
                auth_ref="",
            )
        }
    )
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(_link("read-a"))}
    )
    calls = []

    async def specialist(**kwargs):
        calls.append("specialist")
        notes.records.append(
            _event(context_ref="")
        )
        return {"coverage": "partial", "gaps": ["bounded_selection"]}

    prepare_graph, submit_graph = _confirmed_graph(calls=calls)
    result = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=_writer(
                tmp_path,
                notes=notes,
                access=access,
                retention=retention,
            ),
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )

    assert calls[0] == "specialist"
    assert result[0].verdict == "success"
    assert result[0].assets == []
    publication = result[0].stats["context_publication"]
    assert publication["status"] == "published"
    assert publication["coverage"] == "partial"
    assert "producer_incomplete" in publication["gaps"]
    assert "bounded_selection" in publication["gaps"]

    context_id, current = _current_context(tmp_path)
    assert current["status"] == "ok"
    assert current["publication"]["context_id"] == context_id
    assert current["context"]["coverage"]["status"] == "partial"
    behaviors = JsContextStore(root_dir=tmp_path).read(
        project_id="p",
        context_id=context_id,
        selector="current",
        section="behaviors",
    )
    assert behaviors["items"][0]["steps"][0]["read_ids"] == ["read-a"]


def test_complete_analysis_with_no_behaviour_publishes_empty_context(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)

    async def specialist(**kwargs):
        return {"coverage": "complete", "gaps": []}

    prepare_graph, submit_graph = _confirmed_graph()
    result = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=_writer(
                tmp_path,
                notes=FakeNotes([]),
                access=FakeAccess(),
                retention=FakeRetention(),
            ),
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )

    assert result[0].verdict == "success"
    publication = result[0].stats["context_publication"]
    assert publication["status"] == "published"
    assert publication["coverage"] == "empty"
    assert publication["gaps"] == ["no_saved_behaviors"]


def test_graph_confirmed_yaml_failure_retries_frozen_snapshot_without_model(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)
    notes = FakeNotes([_event(context_ref="")])
    access = FakeAccess(
        {
            "read-a": _receipt(
                "read-a",
                project_id="p",
                run_id="r",
                auth_ref="",
            )
        }
    )
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(_link("read-a"))}
    )
    real = _writer(
        tmp_path,
        notes=notes,
        access=access,
        retention=retention,
    )

    class FailOnceWriter:
        def __init__(self):
            self.prepare_calls = 0
            self.publish_calls = 0

        def prepare(self, **kwargs):
            self.prepare_calls += 1
            return real.prepare(**kwargs)

        def publish_prepared(self, prepared):
            self.publish_calls += 1
            if self.publish_calls == 1:
                raise OSError("simulated YAML write failure")
            return real.publish_prepared(prepared)

    writer = FailOnceWriter()
    calls = []

    async def specialist(**kwargs):
        calls.append("model")
        return {"coverage": "complete", "gaps": []}

    asset = AssetDelta(
        type="BaseURL",
        identity={"url": "https://app.test"},
    )
    prepare_graph, submit_graph = _confirmed_graph(
        assets=[asset],
        calls=calls,
    )
    first = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )
    assert first[0].verdict == "success"
    assert first[0].assets_merged == 1
    assert first[0].assets[0].identity == asset.identity
    assert first[0].stats["context_publication"]["status"] == "pending"
    frozen_id = first[0].stats["context_publication"]["document_id"]
    snapshot_path = (
        tmp_path
        / "p"
        / "recon"
        / "js_analysis"
        / "r"
        / first[0].stats["context_publication"]["snapshot_ref"]
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["document_id"] == frozen_id
    assert snapshot["scope"] == {
        "project_id": "p",
        "run_id": "r",
        "auth_ref": "",
    }

    retention.snapshots[("behavior-a", 2)] = _snapshot(
        _link("read-a", status="gap", failure_reason="retention_changed")
    )
    second = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
            extra={"js_resume_analysis": True},
        )
    )

    assert calls.count("model") == 1
    assert writer.prepare_calls == 1
    assert second[0].verdict == "success"
    assert second[0].assets_merged == 1
    assert second[0].stats["context_publication"]["status"] == "published"
    assert second[0].stats["context_publication"]["document_id"] == frozen_id
    context_id, current = _current_context(tmp_path)
    evidence = JsContextStore(root_dir=tmp_path).read(
        project_id="p",
        context_id=context_id,
        selector="current",
        section="evidence",
    )
    assert evidence["items"][0]["availability"] == "retained_unverified"


def test_lost_yaml_acknowledgement_reuses_current_without_rollback(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)
    real = _writer(
        tmp_path,
        notes=FakeNotes([_event(context_ref="")]),
        access=FakeAccess(
            {
                "read-a": _receipt(
                    "read-a",
                    project_id="p",
                    run_id="r",
                    auth_ref="",
                )
            }
        ),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    class LostAckWriter:
        def __init__(self):
            self.failed = False

        def prepare(self, **kwargs):
            return real.prepare(**kwargs)

        def publish_prepared(self, prepared):
            result = real.publish_prepared(prepared)
            if not self.failed:
                self.failed = True
                raise OSError("simulated lost acknowledgement")
            return result

    async def specialist(**kwargs):
        return {"coverage": "complete", "gaps": []}

    prepare_graph, submit_graph = _confirmed_graph()
    writer = LostAckWriter()
    first = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )
    context_id, before = _current_context(tmp_path)
    second = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )
    _, after = _current_context(tmp_path)

    assert first[0].stats["context_publication"]["status"] == "pending"
    assert second[0].stats["context_publication"]["status"] == "published"
    assert before["publication"]["run_id"] == after["publication"]["run_id"] == "r"
    assert second[0].stats["context_publication"]["context_id"] == context_id


def test_continuation_cannot_rewrite_published_same_run_context(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)
    notes = FakeNotes([_event(context_ref="")])
    access = FakeAccess(
        {
            "read-a": _receipt(
                "read-a",
                project_id="p",
                run_id="r",
                auth_ref="",
            )
        }
    )
    retention = FakeRetention(
        {("behavior-a", 2): _snapshot(_link("read-a"))}
    )
    writer = _writer(
        tmp_path,
        notes=notes,
        access=access,
        retention=retention,
    )
    calls = []

    async def specialist(**kwargs):
        calls.append("model")
        return {"coverage": "complete", "gaps": []}

    prepare_graph, submit_graph = _confirmed_graph()
    first = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )
    assert first[0].stats["context_publication"]["status"] == "published"
    notes.records.append(
        _event(
            revision=3,
            text="Changed same-run meaning.",
            context_ref="",
        )
    )
    retention.snapshots[("behavior-a", 3)] = _snapshot(_link("read-a"))
    assert [
        record["revision"]
        for record in notes.typed_records(event_types={"behavior_save"})
    ] == [2, 3]
    changed = writer.prepare(
        reference=unit["reference"],
        origin="https://app.test",
        analysis_coverage={"status": "complete", "gaps": []},
    )
    assert changed["document"]["behaviors"][0]["revision"] == 3
    assert changed["document_id"] != (
        first[0].stats["context_publication"]["document_id"]
    )

    second = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
            extra={"js_resume_analysis": True},
        )
    )
    context_id, current = _current_context(tmp_path)
    behaviors = JsContextStore(root_dir=tmp_path).read(
        project_id="p",
        context_id=context_id,
        selector="current",
        section="behaviors",
    )

    assert calls == ["model", "model"]
    assert second[0].stats["context_publication"]["status"] == "pending"
    assert second[0].stats["context_publication"]["error"] == (
        "context_same_run_conflict"
    )
    assert current["publication"]["run_id"] == "r"
    assert behaviors["items"][0]["revision"] == 2
    assert behaviors["items"][0]["steps"][0]["text"] == (
        "The stored semantic step."
    )


def test_corrupt_frozen_snapshot_is_explicit_and_not_rebuilt(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)
    real = _writer(
        tmp_path,
        notes=FakeNotes([_event(context_ref="")]),
        access=FakeAccess(
            {
                "read-a": _receipt(
                    "read-a",
                    project_id="p",
                    run_id="r",
                    auth_ref="",
                )
            }
        ),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    class FailPublisher:
        def __init__(self):
            self.prepare_calls = 0

        def prepare(self, **kwargs):
            self.prepare_calls += 1
            return real.prepare(**kwargs)

        def publish_prepared(self, prepared):
            raise OSError("simulated publish failure")

    writer = FailPublisher()
    calls = []

    async def specialist(**kwargs):
        calls.append("model")
        return {"coverage": "complete", "gaps": []}

    prepare_graph, submit_graph = _confirmed_graph()
    first = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )
    snapshot_ref = first[0].stats["context_publication"]["snapshot_ref"]
    snapshot_path = tmp_path / "p" / "recon" / "js_analysis" / "r" / snapshot_ref
    snapshot_path.write_text("{corrupt", encoding="utf-8")

    second = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=writer,
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )

    assert calls == ["model"]
    assert writer.prepare_calls == 1
    assert second[0].verdict == "success"
    assert second[0].stats["context_publication"]["status"] == "pending"
    assert second[0].stats["context_publication"]["error"] == (
        "context_snapshot_corrupt"
    )


def test_graph_preparation_failure_does_not_block_yaml(tmp_path) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)

    async def specialist(**kwargs):
        return {"coverage": "complete", "gaps": []}

    def prepare_graph(**kwargs):
        raise ValueError("graph_prepare_failed")

    def submit_graph(**kwargs):
        raise AssertionError("submit must not run without a proposal")

    result = asyncio.run(
        _native_run(
            tmp_path,
            unit=unit,
            writer=_writer(
                tmp_path,
                notes=FakeNotes([_event(context_ref="")]),
                access=FakeAccess(
                    {
                        "read-a": _receipt(
                            "read-a",
                            project_id="p",
                            run_id="r",
                            auth_ref="",
                        )
                    }
                ),
                retention=FakeRetention(
                    {("behavior-a", 2): _snapshot(_link("read-a"))}
                ),
            ),
            specialist=specialist,
            graph_prepare=prepare_graph,
            graph_submit=submit_graph,
        )
    )

    assert result[0].verdict == "failed"
    assert result[0].error == "js_graph_preparation_failed"
    assert result[0].stats["context_publication"]["status"] == "published"


def test_context_timeout_keeps_lock_until_late_completion_then_retries(
    tmp_path,
) -> None:
    inventory(tmp_path, count=1)
    unit = prepare_js_inventory(project_id="p", run_id="r", root=tmp_path)
    release = threading.Event()
    finished = threading.Event()
    real = _writer(
        tmp_path,
        notes=FakeNotes([_event(context_ref="")]),
        access=FakeAccess(
            {
                "read-a": _receipt(
                    "read-a",
                    project_id="p",
                    run_id="r",
                    auth_ref="",
                )
            }
        ),
        retention=FakeRetention(
            {("behavior-a", 2): _snapshot(_link("read-a"))}
        ),
    )

    class BlockingWriter:
        def __init__(self):
            self.prepare_calls = 0

        def prepare(self, **kwargs):
            self.prepare_calls += 1
            try:
                release.wait(timeout=3)
                kwargs["deadline"] = None
                return real.prepare(**kwargs)
            finally:
                finished.set()

        def publish_prepared(self, prepared):
            return real.publish_prepared(prepared)

    writer = BlockingWriter()
    calls = []

    async def specialist(**kwargs):
        calls.append("model")
        return {"coverage": "complete", "gaps": []}

    prepare_graph, submit_graph = _confirmed_graph()
    try:
        first = asyncio.run(
            _native_run(
                tmp_path,
                unit=unit,
                writer=writer,
                specialist=specialist,
                graph_prepare=prepare_graph,
                graph_submit=submit_graph,
                limits=SpecialistLimits(wall_time_s=0.3),
            )
        )
        second = asyncio.run(
            _native_run(
                tmp_path,
                unit=unit,
                writer=writer,
                specialist=specialist,
                graph_prepare=prepare_graph,
                graph_submit=submit_graph,
                limits=SpecialistLimits(wall_time_s=0.3),
            )
        )
        release.set()
        assert finished.wait(timeout=2)
        third = None
        until = time.monotonic() + 2
        while time.monotonic() < until:
            third = asyncio.run(
                _native_run(
                    tmp_path,
                    unit=unit,
                    writer=writer,
                    specialist=specialist,
                    graph_prepare=prepare_graph,
                    graph_submit=submit_graph,
                )
            )
            if third[0].error != "js_analysis_in_progress":
                break
            time.sleep(0.01)
    finally:
        release.set()

    assert first[0].stats["context_publication"]["status"] == "pending"
    assert first[0].stats["context_publication"]["error"] == (
        "context_prepare_timeout"
    )
    assert second[0].error == "js_analysis_in_progress"
    assert calls == ["model"]
    assert writer.prepare_calls == 1
    assert third[0].stats["context_publication"]["status"] == "published"


def test_two_auth_contexts_publish_independently(tmp_path) -> None:
    from polymerhus.recon.domain.types import ExecResult
    from polymerhus.recon.js_intake import JsIntakeStore

    store = JsIntakeStore(root=tmp_path)
    for auth_ref in ("alice", "bob"):
        store.record_exec_result(
            project_id="p",
            run_id="r",
            pod_id=f"pod-{auth_ref}",
            producer="katana",
            input_context_ref="ctx",
            auth_context_label="authenticated",
            auth_context_ref=auth_ref,
            exec_result=ExecResult(
                stdout=json.dumps(
                    {
                        "request": {
                            "endpoint": f"https://app.test/{auth_ref}.js"
                        }
                    }
                ),
                stderr="",
                returncode=0,
            ),
        )
    units = [
        prepare_js_inventory(
            project_id="p",
            run_id="r",
            context_ref=auth_ref,
            root=tmp_path,
        )
        for auth_ref in ("alice", "bob")
    ]
    assert all(unit["state"] == "ready" for unit in units), units
    notes = {
        "alice": FakeNotes([_event(context_ref="alice")]),
        "bob": FakeNotes(
            [
                _event(
                    behavior_id="behavior-bob",
                    context_ref="bob",
                    read_ids=("read-bob",),
                )
            ]
        ),
    }
    access = FakeAccess(
        {
            "read-a": _receipt(
                "read-a",
                project_id="p",
                run_id="r",
                auth_ref="alice",
            ),
            "read-bob": _receipt(
                "read-bob",
                project_id="p",
                run_id="r",
                auth_ref="bob",
            ),
        }
    )
    retention = FakeRetention(
        {
            ("behavior-a", 2): _snapshot(_link("read-a")),
            ("behavior-bob", 2): _snapshot(_link("read-bob")),
        }
    )
    writer = JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes[scope.context_ref],
        access=access,
        retention=retention,
    )

    async def specialist(**kwargs):
        return {"coverage": "complete", "gaps": []}

    prepare_graph, submit_graph = _confirmed_graph()
    results = [
        asyncio.run(
            _native_run(
                tmp_path,
                unit=unit,
                writer=writer,
                specialist=specialist,
                graph_prepare=prepare_graph,
                graph_submit=submit_graph,
            )
        )
        for unit in units
    ]

    assert all(result[0].verdict == "success" for result in results), [
        (result[0].verdict, result[0].error) for result in results
    ]
    assert results[0][0].stats["context_publication"]["context_id"] != (
        results[1][0].stats["context_publication"]["context_id"]
    )
    for auth_ref in ("alice", "bob"):
        _, current = _current_context(tmp_path, auth_ref=auth_ref)
        assert current["status"] == "ok"
        assert current["context"]["auth_ref"] == auth_ref
