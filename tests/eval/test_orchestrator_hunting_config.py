"""The eval setup hunting block and its project-side application.

Iteration C needs three frozen hunting settings the eval setup could not
express: the pod batch width, the per-threat promotion floor, and the
cumulative risk threshold. They live on the project, so the trial must apply
them through `PUT /projects/{id}/hunting/config` before the hunting run opens.

The parser refuses an unknown key and an out-of-range value loudly, mirroring
the REST body's own validation, so a bad setup cannot half-apply.
"""
from __future__ import annotations

import copy

import pytest

from orchestrator import setup as setup_mod
from tests.eval.conftest import sample_setup_dict
from tests.eval.test_orchestrator_trial import (
    FakeApi,
    FileStore,
    _full_routes,
    _trial,
)


# --- the setup block ----------------------------------------------------------


def _setup_with_hunting(hunting) -> dict:
    payload = copy.deepcopy(sample_setup_dict())
    payload["instances"][0]["targets"][0]["hunting"] = hunting
    return payload


def test_hunting_block_is_optional_and_defaults_empty(sample_setup) -> None:
    parsed = setup_mod.parse_eval_setup(sample_setup)

    (run,) = parsed.instances[0].targets
    assert run.hunting == setup_mod.HuntingSettings()
    assert run.hunting.payload() == {}


def test_hunting_block_is_parsed() -> None:
    parsed = setup_mod.parse_eval_setup(
        _setup_with_hunting(
            {
                "pipeline_sync": "batched",
                "pod_batch_size": 3,
                "promotion_risk_threshold": 0,
                "risk_threshold": 180,
            }
        )
    )

    (run,) = parsed.instances[0].targets
    assert run.hunting.pipeline_sync == "batched"
    assert run.hunting.pod_batch_size == 3
    assert run.hunting.promotion_risk_threshold == 0
    assert run.hunting.risk_threshold == 180
    assert run.hunting.payload() == {
        "pipeline_sync": "batched",
        "pod_batch_size": 3,
        "promotion_risk_threshold": 0,
        "risk_threshold": 180,
    }


def test_partial_hunting_block_payload_carries_only_set_keys() -> None:
    parsed = setup_mod.parse_eval_setup(
        _setup_with_hunting({"pod_batch_size": 3})
    )

    (run,) = parsed.instances[0].targets
    assert run.hunting.payload() == {"pod_batch_size": 3}


def test_unknown_hunting_key_is_named() -> None:
    with pytest.raises(setup_mod.SetupError) as excinfo:
        setup_mod.parse_eval_setup(
            _setup_with_hunting({"pod_batch_sizes": 3})
        )

    assert "pod_batch_sizes" in str(excinfo.value)


def test_bad_pipeline_sync_is_named() -> None:
    with pytest.raises(setup_mod.SetupError) as excinfo:
        setup_mod.parse_eval_setup(
            _setup_with_hunting({"pipeline_sync": "concurrent"})
        )

    assert "pipeline_sync" in str(excinfo.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pod_batch_size", 0),
        ("pod_batch_size", True),
        ("promotion_risk_threshold", -1),
        ("risk_threshold", -1),
    ],
)
def test_out_of_range_hunting_value_is_named(field, value) -> None:
    with pytest.raises(setup_mod.SetupError) as excinfo:
        setup_mod.parse_eval_setup(_setup_with_hunting({field: value}))

    assert field in str(excinfo.value)


# --- the project-side application --------------------------------------------


def _routes() -> dict:
    routes = _full_routes()
    routes["PUT /projects/pid/hunting/config"] = {"ok": True}
    return routes


def _run_with_hunting(tmp_path, api_runner, hunting):
    return _trial(tmp_path, api_runner, hunting=hunting).run()


def test_trial_applies_hunting_config_before_recon(tmp_path) -> None:
    api_runner = FakeApi(_routes())

    _run_with_hunting(
        tmp_path,
        api_runner,
        {"pipeline_sync": "batched", "pod_batch_size": 3, "risk_threshold": 180},
    )

    call = next(
        c for c in api_runner.calls
        if c.path == "/projects/pid/hunting/config"
    )
    assert call.method == "PUT"
    assert call.body == {
        "pipeline_sync": "batched",
        "pod_batch_size": 3,
        "risk_threshold": 180,
    }
    paths = [c.path for c in api_runner.calls]
    assert paths.index("/projects/pid/hunting/config") < next(
        i for i, path in enumerate(paths) if path.endswith("/recon")
    )


def test_trial_without_hunting_issues_no_hunting_config_call(tmp_path) -> None:
    api_runner = FakeApi(_routes())

    _trial(tmp_path, api_runner).run()

    assert not [
        c for c in api_runner.calls
        if c.path == "/projects/pid/hunting/config"
    ]


def test_plan_lists_the_hunting_config_step(tmp_path) -> None:
    api_runner = FakeApi(_routes())

    plan = _trial(
        tmp_path,
        api_runner,
        hunting={"pod_batch_size": 3},
    ).plan()

    steps = {step.label: step for step in plan.steps}
    assert "hunting config" in steps
    (call,) = steps["hunting config"].calls
    assert call.path.endswith("/hunting/config")
    assert call.body == {"pod_batch_size": 3}
    assert api_runner.calls == []
