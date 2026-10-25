"""The malformed-spec fail-safe: render what parses, consume, export.

A body the symbolic layer cannot parse must never halt the queue. The mover
emits a malformed item, the gate admits it, the pod tries what it can, and the
PodExport is the completion fact. Only a missing probe URL is a hard INIT stop.
"""
from __future__ import annotations

import pytest
import yaml

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    TestSpecItem,
    pod_session_id,
    read_produced_inbox,
)
from polymerhus.attack.hunting.pipeline_sync import (
    RunSyncGate,
    SyncMode,
    hunting_artifacts_terminal,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.pod.verification import init_route
from polymerhus.attack.hunting.spec_contract import TargetIdentity

PROJECT = "proj-malformed"
RUN = "run-malformed"
HUNT = "Service-u1__threat-1"
STEM = "idor__report-id__signed-url"


@pytest.fixture
def hunter(tmp_path):
    return HunterMemoryStore(root_dir=tmp_path / "hunter")


@pytest.fixture
def pod(tmp_path):
    return PodMemoryStore(tmp_path / "pod")


def _write_ratified(hunter: HunterMemoryStore) -> None:
    spec = {
        "status": "hypothesised",
        "discriminators": [
            {"axis": "object", "value": "report-id"},
            {"axis": "delivery-route", "value": "signed-url"},
        ],
        "target_identity": {"url": "http://target/", "unit_id": "Service:u1"},
        "verification_symptoms": ["another tenant's report body is returned"],
        "rationale": "the item lookup trusts the request id",
        "provenance": {
            "run_id": RUN,
            "web_vulnerability_class": "idor",
        },
    }
    hunter.write_specs(PROJECT, HUNT, [spec])
    hunter.write_specs(PROJECT, HUNT, [{**spec, "status": "ratified"}])
    hunter.finalize_specs(PROJECT, HUNT, run_id=RUN)


def _corrupt(hunter: HunterMemoryStore, side: str = "produced") -> None:
    path = hunter._spec_file(PROJECT, HUNT, STEM, side)
    path.write_text(": : not yaml [", encoding="utf-8")


def test_read_spec_lenient_returns_the_parse_error(hunter):
    _write_ratified(hunter)
    body, error = hunter.read_spec_lenient(PROJECT, HUNT, STEM)
    assert body is not None and error == ""
    _corrupt(hunter)
    body, error = hunter.read_spec_lenient(PROJECT, HUNT, STEM)
    assert body is None
    assert error


def test_a_corrupt_produced_body_is_a_malformed_item(hunter):
    _write_ratified(hunter)
    _corrupt(hunter)
    inbox = read_produced_inbox(PROJECT, RUN, hunter_store=hunter)
    items = [i for i in inbox.items if isinstance(i, TestSpecItem)]
    assert len(items) == 1
    assert items[0].malformed is True
    assert items[0].spec is None
    assert items[0].parse_error


def test_the_serial_gate_admits_a_malformed_produced_spec(hunter, pod):
    _write_ratified(hunter)
    _corrupt(hunter)
    item = TestSpecItem(
        message_id=f"{HUNT}/{STEM}",
        session_id=pod_session_id(RUN, HUNT, STEM),
        hunt_key=HUNT,
        spec_file=STEM,
        malformed=True,
        parse_error="corrupt",
    )
    gate = RunSyncGate(
        mode=SyncMode.SERIAL, project_id=PROJECT, run_id=RUN,
        hunter_store=hunter, pod_store=pod,
    )
    assert gate.filter([item]) == (item,)


def test_a_consumed_malformed_spec_with_an_export_is_terminal(hunter, pod):
    _write_ratified(hunter)
    _corrupt(hunter)
    assert hunter.consume_spec(PROJECT, HUNT, STEM) is True
    pod.write_pod_export(
        STEM, RUN,
        {"verdict": "unsuccessful",
         "evidence": {"terminal_reason": "no-symptom-evidence"}},
    )
    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod)
    assert complete is True, reasons


def test_a_consumed_malformed_spec_without_an_export_blocks(hunter, pod):
    _write_ratified(hunter)
    _corrupt(hunter)
    assert hunter.consume_spec(PROJECT, HUNT, STEM) is True
    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod)
    assert complete is False
    assert any("malformed" in reason for reason in reasons)


def test_init_route_rejects_only_a_missing_probe_url():
    assert init_route([]) == "runner"
    assert init_route(["verification_symptoms is empty"]) == "runner"
    assert init_route([
        "target_identity.url is empty (the base URL the pod probes; "
        "author it as {'url': <base url>, 'unit_id': <L1 identity>})",
    ]) == "reject"


def test_the_bound_target_identity_is_available_to_a_degraded_pod():
    identity = TargetIdentity(url="http://target/", unit_id="Service:u1")
    assert identity.url == "http://target/"
    assert identity.unit_id == "Service:u1"
