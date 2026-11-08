"""The iteration E setup: the first work item is the Steel session alignment.

The leg evaluates the local Steel pool, so the setup must declare the
data-dependency alignment before any trial, keep `steel_crawl` in the recon
subset, and freeze the requested hunting policy.
"""
from __future__ import annotations

from pathlib import Path

from orchestrator.setup import load_eval_setup

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP = REPO_ROOT / "eval" / "setups" / "siyucms-iteration-e.yaml"


def test_the_first_work_item_is_the_steel_session_alignment() -> None:
    setup = load_eval_setup(SETUP)

    first = setup.work_items[0]
    assert first.name == "steel-browser-sessions"
    assert first.status == "complete"
    assert first.required is True


def test_the_setup_targets_siyucms_from_recon() -> None:
    setup = load_eval_setup(SETUP)

    instance = setup.instances[0]
    assert instance.instance_id == "eval-server-2"
    run = instance.targets[0]
    assert run.target_key == "webexploitbench/siyucms"
    assert run.target_id == "siyucms-web"
    assert run.start_phase == "recon"
    assert run.token_budget == 7_000_000
    assert "steel_crawl" in run.target_config.recon_jobs
    assert run.target_config.data_dir == "/root/eval-dd/data/siyucms"


def test_the_setup_freezes_the_requested_hunting_policy() -> None:
    setup = load_eval_setup(SETUP)

    hunting = setup.instances[0].targets[0].hunting
    assert hunting.pipeline_sync == "batched"
    assert hunting.pod_batch_size == 2
    assert hunting.promotion_risk_threshold == 2.5
    assert hunting.risk_threshold == 156.25
