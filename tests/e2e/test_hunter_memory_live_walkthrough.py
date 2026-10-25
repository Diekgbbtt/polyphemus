"""E1: the hunter memory live walkthrough - the full happy path at runtime state
(docs/design/hunting-164-assertion-catalogue.md).

The walkthrough runs the stack at RUNTIME STATE through the hunter's proper
interface: the real turn-by-turn ReAct host (`build_sync_hunting_agent` ->
`dispatch_fn(threat payload)`, the seam the inbox surfer feeds) with the REAL model
resolved through the co-located gateway (`LLM_HUNTING_HUNTER`), the real
per-project `HunterMemoryStore` on the filesystem, the real five-tool surface,
and the real compiled state graph. The LLM drives the full happy path -
grounding -> collect -> discriminate -> generate -> well-formedness ->
verify-claims -> complete - with
the phase-transition hints riding the tool responses and the graph tracking the
threat. Every terminal quantity is read back from the real YAML files.

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

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunting_agent import build_sync_hunting_agent

root = Path("/tmp/hunter-memory-live") / ("e1-%d" % int(time.time()))
store = HunterMemoryStore(root_dir=root)
project_id = "proj-live-e1"
unit_id = "Service:slug:a"
hunt_key = "Service-slug-a__threat-1"

payload = {
    "dispatch_id": hunt_key,
    "run_id": "run-live-e1",
    "threat_id": "threat-1",
    "unit_id": unit_id,
    "unit_kind": "service",
    "threat": {
        "id": "threat-1",
        "fault_ref": "fault-1",
        "vulnerability_ref": "v-1",
        "canonical_class": "CSRF",
        "web_vulnerability_class": "csrf",
        "likelihood": "high",
        "likelihood_rationale": "the public form accepts cross-site posts",
        "confidence": "INFERRED",
        "evidences": [{"kind": "request", "ref": "POST /api/a"}],
    },
    "technical_sharpening": {
        "interface_agreements": [{
            "id": "ia-1",
            "statement": "the form trusts the origin header",
        }],
        "control_flows": [{"id": "cf-1"}],
        "data_flows": [{"id": "df-1"}],
    },
    "trust_agreement": {"id": "ta-1",
                        "statement": "the endpoint trusts the ambient session"},
    "dynamic_state": None,
    "programming_fault": {
        "id": "fault-1",
        "label": "missing anti-CSRF token",
        "description": "the state-changing form carries no verified token",
    },
    "canonical_class": "CSRF",
    "web_vulnerability_class": "csrf",
    "evidence": [{"kind": "request", "ref": "POST /api/a"}],
    "likelihood": "high",
    "likelihood_rationale": "the public form accepts cross-site posts",
    "vulnerability_rationale": "a cross-site post changes the victim's state",
    "confidence": "INFERRED",
    "target_context": {"unit_id": unit_id, "unit_kind": "service",
                       "baseline_refs": ["POST /api/a"]},
}

agent = build_sync_hunting_agent(
    run_id="run-live-e1",
    project_id=project_id,
    memory_store=store,
    observe=True,
)
result = agent(payload)

# the harness BINDS the threat dispatch id at tool construction - walk the REAL
# topology the store persisted
project_root = root / project_id / "hunting" / "hunter"
specs_dir = project_root / "test-specs"
hunt_keys = sorted(p.name for p in specs_dir.glob("*")) if specs_dir.exists() else []
produced_files = sorted(
    p for p in project_root.rglob("produced/*.yaml"))
produced_statuses = [
    {"file": p.relative_to(project_root).as_posix(),
     "status": store.read_spec(project_id, p.parent.parent.name, p.stem,
                               side="produced").get("status")}
    for p in produced_files
]
notes = store.read_notes(project_id)

report = {
    "terminal_state": result.get("state"),
    "hunt_keys": hunt_keys,
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

    # the terminal state is reported (the harness derives no verdict)
    assert report["terminal_state"]
    # the model authored the memory through hunts_store - produced spec files
    # under a real test-specs/<hunt_key>/produced/ topology
    assert report["hunt_keys"], "no test-specs/<hunt_key> folder - nothing written"
    assert report["produced"], "no produced spec files - the happy path did not run"
    # the lifecycle completed: at least one spec reached a terminal status
    terminals = {p["status"] for p in report["produced"]}
    assert terminals, "produced files carry no lifecycle status"
    assert any(st in ("ratified", "dropped") for st in terminals), (
        f"the lifecycle never terminated (statuses: {terminals})")
    # the persisted statuses are all from the live vocabulary
    assert terminals <= {"hypothesised", "ratified", "dropped"}
    # if the model took notes, their keys embed one of the USED hunt keys
    for key in report["note_keys"]:
        assert any(hk in key for hk in report["hunt_keys"]), (
            f"note key {key!r} embeds none of the used hunt keys {report['hunt_keys']}")