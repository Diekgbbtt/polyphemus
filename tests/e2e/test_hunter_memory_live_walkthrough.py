"""E1: the hunter memory live walkthrough - the full happy path at runtime state
(docs/design/hunting-164-assertion-catalogue.md).

The walkthrough runs the stack at RUNTIME STATE through the hunter's proper
interface: the real turn-by-turn ReAct host (`build_sync_hunting_agent` ->
`dispatch_fn(HuntConfig)`, the seam the inbox surfer feeds) with the REAL model
resolved through the co-located gateway (`LLM_MODEL_HUNTING_HUNTER`), the real
per-project `HunterMemoryStore` on the filesystem, the real five-tool surface,
and the real compiled state graph. The LLM drives the full happy path -
grounding -> hypothesise -> verify -> commit-specification -> conclude - with
the phase-transition hints riding the tool responses and the graph tracking the
loop. Every terminal quantity is read back from the real YAML files.

Qualitative by design (like the tier's other live walkthroughs): the model is
the live edge, so the assertions hold on the memory-system invariants - the
produced spec files and their lifecycle statuses, the fault/note identifier
equality, the no-verdict idle - not on exact step counts or terminal wording.
The dispatch concludes when the model concludes or the step budget is spent;
both land the same no-verdict idle. The procedure is agent-orchestrated: the
operator/agent runs the in-container probe below and reads the report, it is
not a fixed script.

The probe runs INSIDE the agent container (the gateway binds its loopback, ADR
D1 - the host cannot reach port 4000). It writes to a per-run store root under
`/tmp` and prints ONE JSON report line the host-side assertion reads.
"""
from __future__ import annotations

import json

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(
    skip is not None, reason=skip or "agent stack not up for the gateway live tier")

PROBE = r"""
import json
import time
from pathlib import Path

from polymerhus.attack.hunting.hunt_orchestrator import (
    HuntConfig, HuntPromptTemplate,
)
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunting_agent import build_sync_hunting_agent

root = Path("/tmp/hunter-memory-live") / ("e1-%d" % int(time.time()))
store = HunterMemoryStore(root_dir=root)
project_id = "proj-live-e1"
unit_id = "Service:slug:a"

config = HuntConfig(
    hunt_id="hunt-live-e1",
    unit_id=unit_id,
    fault_class="fault-x",
    prompt_template=HuntPromptTemplate(
        rationale=("fault-x applies to slug-a because it exposes an unvalidated "
                   "parameter surface over the public REST api"),
        extension_points=["csrf-probe", "parameter-tampering"],
        assumptions=["public exposure", "no auth on /api/a"],
        supposed_payload_vectors=["q=value"],
        l0_evidence=["GET /api/a answers 200"],
    ),
    surface_context={"cards": [{
        "kind": "Service",
        "key": {"business_function_slug": "a"},
        "label": "a",
        "spine": {"exposure": "public", "api_paradigm": "REST"},
        "edge_degree": {"EXPOSED_VIA": 1},
        "nl_handles": {},
    }]},
    target_caveats=["perimeter WAF on /api/*"],
    prior_hunt_insights=[],
    tool_registry=[{"technique": "csrf-probe"}, {"technique": "parameter-tampering"}],
)

agent = build_sync_hunting_agent(
    run_id="run-live-e1",
    project_id=project_id,
    memory_store=store,
    observe=True,
)
result = agent(config)

# the model chooses the config identifier (fault_key) itself - walk the REAL
# topology the store persisted, whatever key it used
project_root = root / project_id
specs_dir = project_root / "test-specs"
fault_keys = sorted(p.name for p in specs_dir.glob("*")) if specs_dir.exists() else []
produced_files = sorted(
    p for p in project_root.rglob("produced/*.yaml"))
produced_statuses = [
    {"file": p.relative_to(project_root).as_posix(),
     "status": store.read_spec(project_id, p.parent.parent.name,
                               p.stem.rsplit("_", 1)[0], p.stem.rsplit("_", 1)[1],
                               side="produced").get("status")}
    for p in produced_files
]
notes = store.read_notes(project_id)

report = {
    "verdict": result.hypothesis_verdict,
    "fault_keys": fault_keys,
    "produced": produced_statuses,
    "note_keys": [n.get("key") for n in notes],
    "project_id": project_id,
}
print(json.dumps(report, default=str))
"""


def test_E1_memory_full_happy_path_live():
    """The full happy path completes at runtime state: the real model walks the
    lifecycle through the real store, and the memory invariants hold."""
    result = gs.agent_python(PROBE, timeout=900)
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    lines = [ln for ln in result.stdout.strip().splitlines() if ln]
    report = json.loads(lines[-1])

    # the no-verdict idle: the harness derives no hypothesis verdict
    assert report["verdict"] is None
    # the model authored the memory through hunts_store - produced spec files
    # under a real test-specs/<fault_key>/produced/ topology
    assert report["fault_keys"], "no test-specs/<fault_key> folder - nothing written"
    assert report["produced"], "no produced spec files - the happy path did not run"
    # the lifecycle completed: at least one fault reached a terminal status
    terminals = {p["status"] for p in report["produced"]}
    assert terminals, "produced files carry no lifecycle status"
    assert any(st in ("specified", "dropped") for st in terminals), (
        f"the lifecycle never terminated (statuses: {terminals})")
    # the persisted statuses are all from the ratified lifecycle
    assert terminals <= {"hypothesised", "verified", "dropped", "specified"}
    # if the model took notes, their keys embed one of the USED config
    # identifiers (fault/note identifier equality over the real pipeline)
    for key in report["note_keys"]:
        assert any(fk in key for fk in report["fault_keys"]), (
            f"note key {key!r} embeds none of the used fault_keys {report['fault_keys']}")