"""Regression: the streamed per-chunk assigner keeps its slice-based data contract.

The L1-unit-first rewrite (ADR `batched-l1unit-first-adr.md`, T1) is scoped to
`service_sourced`. It was applied UNCONDITIONALLY to the shared `assign` body, so the
streamed per-chunk path (`make_assigner_body`) fed a job-keyed chunk to a
Service-anchored discipline: the unit resolved to a phantom Service
(`service_contract: (none)` for `katana`/`httpx`), `harvest_surface` derived no
candidate strings from an absent contract, `_halt_without_surface` stopped the chain,
and every streamed pod wrote ZERO `AGGREGATES` - no `L1Service -> L0` edges.

This test locks the mode guard. It drives the REAL streamed seam
(`make_assigner_body`, the supervisor's `ProposerBody`) and asserts the L0 `surface`
reaches the assigner, which is the contract that was lost.
"""
from types import SimpleNamespace

from polymerhus.analysis import assigner
from polymerhus.analysis.assigner import assign
from polymerhus.analysis.chunking import Chunk
from polymerhus.recon.domain.types import AssetDelta

BU = "https://a"
INVENTORY = {
    "services": ["workflow-submission"],
    "service_contracts": {"workflow-submission": "Submits a node-graph prompt for execution."},
}


def _ep(path):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU})


def _streamed_chunk():
    # A recon-job-keyed chunk: the shape `chunks_for_job` produces in `streamed` mode.
    return Chunk(chunk_id="katana:0", source_job="katana", assets=(_ep("/prompt"),))


def _service_chunk():
    # A Service-keyed chunk: the shape `build_service_slices` produces in service_sourced.
    return Chunk(
        chunk_id="workflow-submission",
        source_job="service:workflow-submission",
        assets=(_ep("/prompt"),),
    )


def _capture(monkeypatch):
    """Stub `run_workflow` to record the workflow ids, the base artifacts and the
    system prompt, then stop (fail-open to an empty outcome)."""
    import polymerhus.analysis.reasoning_workflow as rw

    captured = {}

    def fake(workflow, *, invoke_fn, system_prompt, base_artifacts, **kw):
        captured["sub_problems"] = [sp.id for sp in workflow.sub_problems]
        captured["base_artifacts"] = dict(base_artifacts)
        captured["system_prompt"] = system_prompt
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(rw, "run_workflow", fake)
    return captured


def test_streamed_seam_feeds_the_l0_surface(monkeypatch):
    """The streamed production seam (make_assigner_body) must feed the chunk's L0
    surface - the contract that was dropped when the L1-unit-first discipline leaked
    into `streamed`."""
    cap = _capture(monkeypatch)
    body = assigner.make_assigner_body(
        invoke_fn=lambda *a, **k: None, inventory_fn=lambda pid: INVENTORY
    )
    body(SimpleNamespace(chunk=_streamed_chunk(), role="assigner"),
         {"project_id": "p", "run_id": "run-1"})

    assert "surface" in cap["base_artifacts"]
    assert "/prompt" in cap["base_artifacts"]["surface"]
    assert cap["base_artifacts"]["service"].startswith("SERVICE UNIT: katana")
    assert "service_contract:" in cap["base_artifacts"]["service"]
    # The legacy workflow, not the L1-unit-first one.
    assert cap["sub_problems"][0] == "surface_scan"
    assert "harvest_surface" not in cap["sub_problems"]


def test_service_sourced_feeds_unit_and_runs_l1unit_first(monkeypatch):
    cap = _capture(monkeypatch)
    assign(_service_chunk(), invoke_fn=lambda *a, **k: None, inventory=INVENTORY, unit_first=True)

    # No pre-fed surface: the model discovers it through the tools (L1-unit-first).
    assert "surface" not in cap["base_artifacts"]
    assert cap["base_artifacts"]["service"].startswith("SERVICE UNIT: workflow-submission")
    assert "contract: Submits a node-graph prompt" in cap["base_artifacts"]["service"]
    # The L1-unit-first workflow.
    assert cap["sub_problems"][0] == "harvest_surface"
    assert "falsify_harvest" in cap["sub_problems"]
    assert "surface_scan" not in cap["sub_problems"]


def test_the_two_flavours_load_different_prompt_files(monkeypatch):
    """The prompt variant travels WITH the workflow: streamed loads the legacy
    `assigner.md`, service_sourced the batched L1-unit-first file."""
    cap = _capture(monkeypatch)
    assign(_streamed_chunk(), invoke_fn=lambda *a, **k: None, inventory=INVENTORY, unit_first=False)
    streamed_prompt = cap["system_prompt"]

    cap = _capture(monkeypatch)
    assign(_service_chunk(), invoke_fn=lambda *a, **k: None, inventory=INVENTORY, unit_first=True)
    service_prompt = cap["system_prompt"]

    legacy = assigner.prompt_path("assigner", assigner.LEGACY).read_text(encoding="utf-8")
    batched = assigner.prompt_path("assigner", assigner.BATCHED_L1UNIT_FIRST).read_text(encoding="utf-8")
    assert streamed_prompt.endswith(legacy)
    assert service_prompt.endswith(batched)
