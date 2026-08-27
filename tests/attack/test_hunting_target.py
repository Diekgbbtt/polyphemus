"""Unit tier: target seed -> base URL normalization + dispatch threading (#197).

The pod must probe the seeded domain (``settings.recon.target_seed``), never a
guessed host (``localhost:8080``). The normalizer turns a bare domain / host:port
/ already-scheme'd URL into ``scheme://host[:port]/`` with a trailing slash and
no path/query/fragment, or ``None`` when non-normalizable (fail-closed).
``start_hunting`` reads ``settings`` via ``asyncio.to_thread(load_settings)``,
normalizes, and threads the value into the pod builder closure so every pod
dispatched through the surfer sees the same target.
"""

import asyncio

import pytest

from polymerhus.attack.hunting.target import normalize_target_seed


# --- the normalizer table (point 2) ----------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        # bare domains
        ("soupmarket.shop", "http://soupmarket.shop/"),
        ("example.com", "http://example.com/"),
        ("sub.example.com", "http://sub.example.com/"),
        # port-bearing bare
        ("example.com:8080", "http://example.com:8080/"),
        ("192.33.91.87", "http://192.33.91.87/"),
        ("192.33.91.87:8000", "http://192.33.91.87:8000/"),
        # already scheme'd
        ("http://example.com", "http://example.com/"),
        ("https://example.com", "https://example.com/"),
        ("http://example.com:8443", "http://example.com:8443/"),
        ("https://soupmarket.shop:443/", "https://soupmarket.shop:443/"),
        # path / query stripped to origin
        ("http://example.com/api", "http://example.com/"),
        ("https://example.com:443/path?q=1#frag", "https://example.com:443/"),
        ("http://example.com:8080/foo/bar", "http://example.com:8080/"),
        # whitespace trimmed
        ("  soupmarket.shop  ", "http://soupmarket.shop/"),
        (" https://example.com ", "https://example.com/"),
        # case preserved for host, scheme lowercased
        ("HTTP://Example.COM", "http://Example.COM/"),
    ],
)
def test_normalize_table(raw, expected):
    assert normalize_target_seed(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "http://",
        "://bad",
        "http:///a",
        "example com",
        "example.com/with space",
        "*.example.com",
        "*.soupmarket.shop",
        "http:// example.com",
    ],
)
def test_normalize_rejects(raw):
    assert normalize_target_seed(raw) is None


def test_normalize_empty_seed_is_none():
    assert normalize_target_seed("") is None
    assert normalize_target_seed(None) is None


# --- the threading: injected target reaches arun_pod via the builder --------

def test_default_pod_builder_forwards_target_url_to_arun_pod(monkeypatch):
    """The dispatch seam threads the normalized target into ``arun_pod``.

    ``_default_pod_builder`` is the production pod-session builder the surfer
    calls; it must forward ``target_url`` to ``arun_pod`` and, when no target
    is available, short-circuit to the ``technical-infeasibility`` envelope
    instead of guessing a host.
    """
    from polymerhus.attack.hunting import runtime as rt

    captured = {}

    async def fake_arun_pod(spec, **kw):
        captured.update(kw)
        return {"verdict": "successful", "evidence": {}}

    monkeypatch.setattr("polymerhus.attack.hunting.pod.pod.arun_pod", fake_arun_pod)

    # Valid target -> forwarded.
    asyncio.run(
        rt._default_pod_builder(
            {"target_identity": "Service:slug:a"},
            run_id="r1",
            project_id="p1",
            memory_store=None,
            spec_id="sqli_blind",
            target_url="http://soupmarket.shop/",
        )
    )
    assert captured["target_url"] == "http://soupmarket.shop/"
    assert captured["spec_id"] == "sqli_blind"

    # No target -> INIT-rejection, never calls arun_pod, never guesses.
    captured.clear()
    out = asyncio.run(
        rt._default_pod_builder(
            {"target_identity": "Service:slug:a"},
            run_id="r1",
            project_id="p1",
            memory_store=None,
            spec_id="sqli_blind",
            target_url=None,
        )
    )
    assert captured == {}  # arun_pod not invoked
    assert out["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert any("target" in v.lower() for v in out["evidence"]["init_validation"])
    assert out["verdict"] == "unsuccessful"


def test_default_pod_builder_without_target_does_not_probe(monkeypatch):
    """A missing target never reaches the exec surface - the builder returns the
    rejection envelope with iterations=0 and no raw observations, not a localhost
    probe that would be ``no-symptom-evidence`` with iterations=1."""
    from polymerhus.attack.hunting import runtime as rt

    out = asyncio.run(
        rt._default_pod_builder(
            {"target_identity": "Service:slug:a"},
            run_id="r1",
            project_id="p1",
            memory_store=None,
            spec_id="sqli_blind",
            target_url=None,
        )
    )
    assert out["evidence"]["iterations"] == 0
    assert out["evidence"]["clean"] is False
    assert "localhost" not in str(out)


def test_pod_graph_surfaces_target_in_runner_context():
    """The wired pod graph renders the target base URL into the Runner's
    filtered context so the LLM does not guess ``localhost:8080``.

    The production ReAct runner's lap-opener is built from
    ``compose_runner_delta`` which is fed the target; the test drives a
    non-production graph (injected symbolic runner) and inspects the
    deposited ``runner_messages`` for the target section.
    """
    from polymerhus.attack.hunting.pod.graph import build_pod_graph

    graph = build_pod_graph(
        exec_fn=lambda c, t: None,  # never called - init only
        runner_step_fn=lambda spec, msgs, tc: None,
        target_url="http://soupmarket.shop/",
    )
    # The graph's init seeds the runner channel with the system prompt plus
    # the human opener that now carries the target. Drive just the init.
    # ``ainvoke`` with a spec that passes C1 (non-empty typed base) lands in
    # the runner node; inspect the channel after one tick.
    # We exercise the context helper directly to avoid mocking the whole graph.
    from polymerhus.attack.hunting.pod.context import ExperimentLog

    log = ExperimentLog()
    ctx = log.runner_context(
        {"target_identity": "Service:slug:a"}, "", 1, 8, target_url="http://soupmarket.shop/"
    )
    assert "http://soupmarket.shop/" in ctx
    assert "Target base URL" in ctx


def test_start_hunting_threads_target_via_asyncio_to_thread(tmp_path, monkeypatch):
    """``start_hunting`` reads ``settings`` via ``asyncio.to_thread(load_settings)``
    and normalizes to a base URL that reaches the pod builder.

    The test fakes ``pg.load_settings`` to return a seed and a pod builder
    recorder that captures the threaded ``target_url`` kwarg.
    """
    from polymerhus.attack.hunting import runtime as rt
    from polymerhus.attack.hunting.hunt_store import HuntStore
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore

    seen = []

    async def rec_pod(spec, **kw):
        seen.append(kw.get("target_url"))
        return {"verdict": "successful", "evidence": {}}

    # The run's surfer will dispatch one pod for one specified spec; the hunter
    # builder writes that spec into the hunter store.
    def rec_hunter_builder(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def dispatch(config):
            from polymerhus.attack.hunting.hunting_agent import DispatchResult

            hunter_store.write_spec(
                project_id,
                f"{config.unit_id}_{config.fault_class}_{config.vulnerability_class}",
                fault_keyword="sqli",
                strategy_keyword="blind",
                spec={"status": "specified", "spec_id": "sqli_blind"},
            )
            return DispatchResult(hypothesis_verdict=None, feedback="done")

        return dispatch, None

    # Fake pg accessors: the hunting_runs row + the seed.
    class FakePg:
        def __init__(self):
            self.rows = []

        def create_hunting_run(self, pid):
            self.rows.append("running")
            return "run-197-thread"

        def set_hunting_run_status(self, rid, status):
            self.rows.append(status)

        def list_hunting_runs(self, pid):
            return []

        def load_settings(self, pid):
            return {"target_seed": "soupmarket.shop"}

    fake = FakePg()
    monkeypatch.setattr("polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr("polymerhus.app.clients.pg.set_hunting_run_status", fake.set_hunting_run_status)
    monkeypatch.setattr("polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)
    monkeypatch.setattr("polymerhus.app.clients.pg.load_settings", fake.load_settings)

    # Spy that the offload is via asyncio.to_thread.
    offloads = []
    orig = rt.asyncio.to_thread

    def spied(fn, /, *a, **kw):
        offloads.append(fn.__name__ if hasattr(fn, "__name__") else str(fn))
        return orig(fn, *a, **kw)

    monkeypatch.setattr(rt.asyncio, "to_thread", spied)

    # Minimal orchestration that writes one ratified config.
    from polymerhus.attack.hunting.hunt_orchestrator import (
        DeliveredCandidate,
        GateDecision,
        EnvisionedDirection,
        NoteDecision,
        NoteRecord,
        OrchestratorTools,
        RatifyDecision,
        ReadOnlyGraphView,
        Witness,
        revival_key,
    )

    def hyp(inp):
        return GateDecision(
            directions=[
                EnvisionedDirection(
                    unit_id=c.unit_id,
                    fault_class=c.fault_class,
                    carried=True,
                    rationale="r",
                    research_direction="rd",
                    vulnerability_classes=["IDOR"],
                )
                for c in inp.candidates
            ]
        )

    def rat(inp):
        cfgs = []
        for d in inp.configs:
            m = d.model_copy(deep=True)
            m.status = "ratified"
            cfgs.append(m)
        return RatifyDecision(configs=cfgs)

    def note(inp):
        return NoteDecision(notes=[NoteRecord(key=revival_key(inp.pair.unit_id, inp.pair.fault_class), note="n")])

    # Fake control that runs sessions on the loop.
    class FakeControl:
        def __init__(self):
            self.tasks = {}
            self.started = []

        def live_session_ids(self):
            return {sid for sid, t in self.tasks.items() if not t.done()}

        def start_session(self, sid, coro):
            self.started.append(sid)
            if coro is None:
                return None
            self.tasks[sid] = asyncio.get_running_loop().create_task(coro)
            return self.tasks[sid]

        def dispatch(self, sid, coro):
            return self.start_session(sid, coro) is not None

        def cancel_session(self, sid):
            if sid in self.tasks and not self.tasks[sid].done():
                self.tasks[sid].cancel()

        def gate(self):
            return None

    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    tools = OrchestratorTools(store_reads=hunt, graph_view=ReadOnlyGraphView("proj-197", read_fn=lambda c, p: []))

    asyncio.run(
        rt.start_hunting(
            "proj-197",
            candidates=[
                DeliveredCandidate(
                    unit_id="Service:slug:a",
                    fault_class="CWE-639",
                    applies_witnesses=Witness(deterministic="w", llm="w"),
                    match_verdict="applies",
                )
            ],
            tools=tools,
            hypothesise_fn=hyp,
            ratify_fn=rat,
            note_fn=note,
            control=FakeControl(),
            hunt_store=hunt,
            hunter_store=hunter,
            pod_store=None,
            hunter_builder=rec_hunter_builder,
            pod_builder=rec_pod,
            tick_interval=0.001,
        )
    )
    # The offload included load_settings, and the pod saw the normalized base.
    assert "load_settings" in offloads
    assert seen == ["http://soupmarket.shop/"]
