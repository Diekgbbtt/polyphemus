"""The native JS outcome reaches Analysis as one explicit feed input."""

from __future__ import annotations

import asyncio

import pytest

from polymerhus.analysis import feed as analysis_feed
from polymerhus.app.js_context.records import context_id_for
from polymerhus.app.js_context.store import JsContextStore
from polymerhus.app.llm import checkpoints
from polymerhus.recon.control import pipeline
from polymerhus.recon.control.authn_loop import GatewayVerdict
from polymerhus.recon.control.job_agent import run_job as actual_run_job
from polymerhus.recon.control.js_analysis_job import (
    prepare_js_inventory,
    run_js_analysis_job,
)
from polymerhus.recon.domain.types import AssetDelta, PodExport
from tests.recon.test_js_context_writer import (
    FakeAccess,
    FakeNotes,
    FakeRetention,
    _event,
    _link,
    _receipt,
    _snapshot,
)
from tests.recon.test_js_native_context_publication import (
    _confirmed_graph,
    _writer,
)
from tests.recon.test_js_native_job import inventory


class Registry:
    def __init__(self):
        self.jobs = []

    def create_run(self, *args, **kwargs):
        return None

    def set_run_status(self, *args, **kwargs):
        return None

    def upsert_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))
        return None


class Feed:
    mode = "queued"

    def __init__(self):
        self.events = []

    async def push(self, chunk):
        self.events.append(("push", chunk))

    async def signal_end(self):
        self.events.append(("terminal", None))


class Orchestrator:
    async def run_gateway(self, **kwargs):
        return GatewayVerdict(
            outcome="anonymous",
            rationale="deterministic feed fixture",
        )

    async def stop(self):
        return None


def _orchestrator(run_id):
    return Orchestrator()


def _published(**overrides):
    value = {
        "status": "published",
        "context_id": "jsctx_" + "a" * 40,
        "document_id": "document-1",
        "document_sha256": "b" * 64,
        "auth_ref": "alice",
        "origin": {"status": "known", "value": "https://app.example"},
        "gaps": ["bounded_selection"],
    }
    value.update(overrides)
    return value


async def _noop_flush(*args, **kwargs):
    return None


async def _noop_heartbeat(run_id):
    return None


async def _inline_to_thread(fn, /, *args, **kwargs):
    return fn(*args, **kwargs)


def _run_with_feed(feed, *, exporter, monkeypatch, registry=None):
    monkeypatch.setattr(checkpoints, "flush_run_scoped", _noop_flush)
    monkeypatch.setattr(pipeline, "_heartbeat_loop", _noop_heartbeat)
    monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

    async def run_job(job, inputs, **kwargs):
        if job.tool != "js_analysis":
            return [PodExport(input_asset={}, verdict="success")]
        return exporter()

    asyncio.run(
        pipeline.run_pipeline(
            "project-a",
            run_id="run-1",
            job_subset=["httpx", "katana", "js_analysis"],
            run_job=run_job,
            load_settings=lambda project_id: {
                "target_domain": "*.example",
                "streaming_analysis": True,
            },
            registry=registry or Registry(),
            read_assets=lambda *args, **kwargs: [],
            orchestrator_factory=_orchestrator,
            input_provider=lambda **kwargs: {
                "resource": "JSInventory",
                "reference": "reference",
                "state": "empty",
                "coverage": {"status": "partial", "gaps": []},
            },
            feed_mode="inline",
            with_analysis=False,
        )
    )


def test_js_job_is_marked_selected_before_it_finishes(monkeypatch):
    feed = Feed()
    registry = Registry()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    _run_with_feed(
        feed,
        monkeypatch=monkeypatch,
        registry=registry,
        exporter=lambda: [
            PodExport(
                input_asset={},
                verdict="success",
                stats={"context_publication": _published()},
            )
        ],
    )

    in_progress = [
        kwargs["stats"]
        for args, kwargs in registry.jobs
        if args[2] == "js_analysis" and args[3] == "in_progress"
    ]
    assert in_progress == [{"js_selected": True}]


def test_js_context_only_job_pushes_nonterminal_chunk_once(monkeypatch):
    feed = Feed()
    registry = Registry()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    _run_with_feed(
        feed,
        monkeypatch=monkeypatch,
        registry=registry,
        exporter=lambda: [
            PodExport(
                input_asset={},
                verdict="success",
                assets=[],
                observations=[],
                stats={"context_publication": _published()},
            )
        ],
    )

    assert [kind for kind, _ in feed.events] == ["push", "terminal"]
    chunk = feed.events[0][1]
    assert chunk.terminal is False
    assert chunk.assets == []
    assert chunk.observations == []
    assert chunk.js_context_input.project_id == "project-a"
    assert chunk.js_context_input.producing_run_id == "run-1"
    assert chunk.js_context_input.document_id == "document-1"
    persisted = registry.jobs[-1][1]["stats"]["js_context_input"]
    assert persisted == chunk.js_context_input.as_dict()


def test_pipeline_origin_envelope_reaches_writer_and_publishes_context(
    tmp_path,
    monkeypatch,
):
    inventory(
        tmp_path,
        count=1,
        project_id="project-a",
        run_id="run-1",
    )
    unit = prepare_js_inventory(project_id="project-a", run_id="run-1", root=tmp_path)
    notes = FakeNotes([_event(context_ref="")])
    access = FakeAccess(
        {
            "read-a": _receipt(
                "read-a",
                project_id="project-a",
                run_id="run-1",
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
        calls.append("specialist")
        return {"coverage": "partial", "gaps": ["bounded_selection"]}

    graph_prepare, graph_submit = _confirmed_graph(calls=calls)

    async def js_executor(**kwargs):
        return await run_js_analysis_job(
            **kwargs,
            root=tmp_path,
            specialist_fn=specialist,
            prepare_fn=graph_prepare,
            submit_fn=graph_submit,
            context_writer=writer,
        )

    seen_origins = []

    async def pipeline_run_job(job, inputs, **kwargs):
        if job.tool != "js_analysis":
            return [PodExport(input_asset={}, verdict="success")]
        seen_origins.append(kwargs["extra"].get("application_origin"))
        return await actual_run_job(
            job,
            inputs,
            specialist_executor=js_executor,
            **kwargs,
        )

    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    monkeypatch.setattr(checkpoints, "flush_run_scoped", _noop_flush)
    monkeypatch.setattr(pipeline, "_heartbeat_loop", _noop_heartbeat)
    monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)
    monkeypatch.setattr(
        pipeline,
        "curate",
        lambda assets, observations, project_id: (0, 0, [], []),
    )

    asyncio.run(
        pipeline.run_pipeline(
            "project-a",
            run_id="run-1",
            job_subset=["httpx", "katana", "js_analysis"],
            run_job=pipeline_run_job,
            load_settings=lambda project_id: {
                "target_domain": "https://app.example",
                "streaming_analysis": True,
            },
            registry=Registry(),
            read_assets=lambda *args, **kwargs: [],
            orchestrator_factory=_orchestrator,
            input_provider=lambda **kwargs: unit,
            feed_mode="inline",
            with_analysis=False,
        )
    )

    assert seen_origins == [
        {"status": "known", "value": "https://app.example"}
    ]
    context = feed.events[0][1].js_context_input
    assert context.status == "published", context.as_dict()
    assert context.document_id
    context_id = context_id_for(
        project_id="project-a",
        origin={"status": "known", "value": "https://app.example"},
        auth_ref="",
    )
    stored = JsContextStore(root_dir=tmp_path).read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
        section="metadata",
    )
    assert stored["status"] == "ok"
    assert stored["publication"]["context_id"] == context_id
    published = tmp_path / "project-a/js-client-side" / context_id
    assert (published / "run-1.yml").is_file()
    assert (published / "current.json").is_file()
    assert list(
        (
            tmp_path
            / "project-a/recon/js_analysis/run-1/context-publications"
        ).glob("*.json")
    )


def test_js_assets_and_context_share_one_feed_input(monkeypatch):
    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    asset = AssetDelta(
        type="Endpoint",
        identity={"url": "https://app.example/client.js"},
    )
    _run_with_feed(
        feed,
        monkeypatch=monkeypatch,
        exporter=lambda: [
            PodExport(
                input_asset={},
                verdict="success",
                assets_merged=1,
                assets=[asset],
                stats={"context_publication": _published()},
            )
        ],
    )

    pushed = [chunk for kind, chunk in feed.events if kind == "push"]
    assert len(pushed) == 1
    assert pushed[0].assets == [asset]
    assert pushed[0].js_context_input.document_id == "document-1"


def test_failed_js_dispatch_pushes_a_scoped_gap(monkeypatch):
    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    monkeypatch.setattr(checkpoints, "flush_run_scoped", _noop_flush)
    monkeypatch.setattr(pipeline, "_heartbeat_loop", _noop_heartbeat)
    monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

    async def raising_job(job, inputs, **kwargs):
        if job.tool != "js_analysis":
            return [PodExport(input_asset={}, verdict="success")]
        raise RuntimeError("dispatch failed")

    asyncio.run(
        pipeline.run_pipeline(
            "project-a",
            run_id="run-1",
            job_subset=["httpx", "katana", "js_analysis"],
            run_job=raising_job,
            load_settings=lambda project_id: {
                "target_domain": "*.example",
                "streaming_analysis": True,
            },
            registry=Registry(),
            read_assets=lambda *args, **kwargs: [],
            orchestrator_factory=_orchestrator,
            input_provider=lambda **kwargs: {
                "resource": "JSInventory",
                "reference": "reference",
                "state": "empty",
                "coverage": {"status": "partial", "gaps": []},
            },
            feed_mode="inline",
            with_analysis=False,
        )
    )

    assert [kind for kind, _ in feed.events] == ["push", "terminal"]
    context = feed.events[0][1].js_context_input
    assert context.status == "unavailable"
    assert context.context_id is None
    assert context.gaps == ("js_analysis_dispatch_failed",)


def test_pending_timeout_freezes_old_gap_instead_of_later_current(monkeypatch):
    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    publication = _published(
        status="pending",
        error="context_publication_timeout",
    )
    _run_with_feed(
        feed,
        monkeypatch=monkeypatch,
        exporter=lambda: [
            PodExport(
                input_asset={},
                verdict="success",
                stats={"context_publication": publication},
            )
        ],
    )

    context = feed.events[0][1].js_context_input
    assert context.status == "pending"
    assert context.document_id is None
    assert "context_publication_timeout" in context.gaps


@pytest.mark.parametrize(
    "exports,status,gap",
    [
        (
            [
                PodExport(
                    input_asset={},
                    verdict="failed",
                    error="js_analysis_failed",
                    stats={"gap": "js_analysis_failed"},
                )
            ],
            "failed",
            "js_analysis_failed",
        ),
        ([], "unavailable", "js_analysis_not_dispatched"),
        (
            [PodExport(input_asset={}, verdict="success")],
            "unavailable",
            "context_publication_missing",
        ),
        (
            [
                PodExport(
                    input_asset={},
                    verdict="success",
                    stats={"context_publication": _published(status="skipped")},
                )
            ],
            "skipped",
            "bounded_selection",
        ),
    ],
)
def test_nonpublished_js_outcomes_are_explicit_scoped_chunks(
    monkeypatch, exports, status, gap
):
    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    _run_with_feed(
        feed,
        monkeypatch=monkeypatch,
        exporter=lambda: exports,
    )

    assert [kind for kind, _ in feed.events] == ["push", "terminal"]
    value = feed.events[0][1].js_context_input
    assert value.project_id == "project-a"
    assert value.producing_run_id == "run-1"
    assert value.status == status
    assert gap in value.gaps


def test_selected_js_inventory_setup_failure_is_not_silent(monkeypatch):
    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    monkeypatch.setattr(checkpoints, "flush_run_scoped", _noop_flush)
    monkeypatch.setattr(pipeline, "_heartbeat_loop", _noop_heartbeat)
    monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

    async def run_job(job, inputs, **kwargs):
        return [PodExport(input_asset={}, verdict="success")]

    def unavailable(**kwargs):
        raise RuntimeError("inventory unavailable")

    asyncio.run(
        pipeline.run_pipeline(
            "project-a",
            run_id="run-1",
            job_subset=["httpx", "katana", "js_analysis"],
            run_job=run_job,
            load_settings=lambda project_id: {
                "target_domain": "*.example",
                "streaming_analysis": True,
            },
            registry=Registry(),
            read_assets=lambda *args, **kwargs: [],
            orchestrator_factory=_orchestrator,
            input_provider=unavailable,
            feed_mode="inline",
            with_analysis=False,
        )
    )

    assert [kind for kind, _ in feed.events] == ["push", "terminal"]
    value = feed.events[0][1].js_context_input
    assert value.status == "unavailable"
    assert value.gaps == ("js_analysis_setup_failed",)


def test_non_js_empty_job_remains_a_noop(monkeypatch):
    feed = Feed()
    monkeypatch.setattr(analysis_feed, "InlineAnalysisFeed", lambda *a, **k: feed)
    monkeypatch.setattr(checkpoints, "flush_run_scoped", _noop_flush)
    monkeypatch.setattr(pipeline, "_heartbeat_loop", _noop_heartbeat)
    monkeypatch.setattr(asyncio, "to_thread", _inline_to_thread)

    async def run_job(job, inputs, **kwargs):
        return [PodExport(input_asset={}, verdict="success")]

    asyncio.run(
        pipeline.run_pipeline(
            "project-a",
            run_id="run-1",
            job_subset=["subfinder"],
            run_job=run_job,
            load_settings=lambda project_id: {
                "target_domain": "*.example",
                "streaming_analysis": True,
            },
            registry=Registry(),
            read_assets=lambda *args, **kwargs: [],
            orchestrator_factory=_orchestrator,
            feed_mode="inline",
            with_analysis=False,
        )
    )

    assert feed.events == [("terminal", None)]
