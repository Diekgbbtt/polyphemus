"""Safe Trial-resolution context for the resolved read API (unified workspace).

The resolved endpoints must map a full Trial identity to its storage context
without trusting a client path and without inferring an association from a
shared ``project_id``. These tests pin that small, typed seam.
"""
from __future__ import annotations

import pytest

from read_api.resolved import (
    ResolvedDataError,
    TrialContext,
    resolve_trial_context,
)

TARGET = "comfyui-1"
RUN = "run-a"
TRIAL = "t1"
PROJECT_ID = "c0641257-a1a9-4e13-acee-6effa28311f5"
INSTANCE = "eval-server-1"


def _snapshot(*trials: dict) -> dict:
    return {
        "dataset": {"id": "d", "name": "n"},
        "summary": {},
        "targets": [],
        "trials": list(trials),
    }


def _trial(
    *,
    target_id: str = TARGET,
    target_run_id: str = RUN,
    trial_id: str = TRIAL,
    project_id: object = PROJECT_ID,
    instance_id: object = INSTANCE,
) -> dict:
    return {
        "target_id": target_id,
        "target_run_id": target_run_id,
        "trial_id": trial_id,
        "project_id": project_id,
        "instance_id": instance_id,
    }


def test_exact_identity_lookup_returns_storage_context() -> None:
    snapshot = _snapshot(_trial(), _trial(trial_id="other"))
    context = resolve_trial_context(
        snapshot,
        TARGET,
        RUN,
        TRIAL,
        configured_instance_id=INSTANCE,
    )
    assert context == TrialContext(
        target_id=TARGET,
        target_run_id=RUN,
        trial_id=TRIAL,
        project_id=PROJECT_ID,
        instance_id=INSTANCE,
        fallback_eligible=True,
    )


def test_lookup_never_infers_association_from_project_id() -> None:
    # Same project id, different Trial identity: still not a match.
    snapshot = _snapshot(_trial(trial_id="other"))
    with pytest.raises(ResolvedDataError) as excinfo:
        resolve_trial_context(
            snapshot, TARGET, RUN, TRIAL, configured_instance_id=INSTANCE
        )
    assert excinfo.value.code == "trial_not_found"
    assert excinfo.value.status_code == 404


@pytest.mark.parametrize(
    "bad",
    ["../etc", "a/b", "", "..", ".", "a\\b", "a\x00b"],
)
def test_unsafe_identity_is_not_found(bad: str) -> None:
    snapshot = _snapshot(_trial(trial_id=bad))
    with pytest.raises(ResolvedDataError) as excinfo:
        resolve_trial_context(
            snapshot, TARGET, RUN, bad, configured_instance_id=INSTANCE
        )
    assert excinfo.value.code == "trial_not_found"
    assert excinfo.value.status_code == 404


def test_unknown_trial_is_not_found() -> None:
    with pytest.raises(ResolvedDataError) as excinfo:
        resolve_trial_context(
            _snapshot(_trial()),
            TARGET,
            RUN,
            "missing",
            configured_instance_id=INSTANCE,
        )
    assert excinfo.value.code == "trial_not_found"
    assert excinfo.value.status_code == 404


def test_missing_project_id_is_unavailable_metadata() -> None:
    snapshot = _snapshot(_trial(project_id=None))
    context = resolve_trial_context(
        snapshot, TARGET, RUN, TRIAL, configured_instance_id=INSTANCE
    )
    assert context.project_id is None
    assert context.fallback_eligible is False


def test_missing_instance_id_is_unavailable_metadata() -> None:
    snapshot = _snapshot(_trial(instance_id=None))
    context = resolve_trial_context(
        snapshot, TARGET, RUN, TRIAL, configured_instance_id=INSTANCE
    )
    assert context.instance_id is None
    assert context.fallback_eligible is False


def test_unsafe_project_id_is_treated_as_missing() -> None:
    snapshot = _snapshot(_trial(project_id="../../etc/passwd"))
    context = resolve_trial_context(
        snapshot, TARGET, RUN, TRIAL, configured_instance_id=INSTANCE
    )
    assert context.project_id is None
    assert context.fallback_eligible is False


def test_fallback_requires_matching_instance() -> None:
    snapshot = _snapshot(_trial(instance_id="other-instance"))
    context = resolve_trial_context(
        snapshot, TARGET, RUN, TRIAL, configured_instance_id=INSTANCE
    )
    assert context.instance_id == "other-instance"
    assert context.fallback_eligible is False


def test_fallback_ineligible_when_instance_not_configured() -> None:
    snapshot = _snapshot(_trial())
    context = resolve_trial_context(
        snapshot, TARGET, RUN, TRIAL, configured_instance_id=None
    )
    assert context.fallback_eligible is False


def test_error_message_never_carries_a_path() -> None:
    with pytest.raises(ResolvedDataError) as excinfo:
        resolve_trial_context(
            _snapshot(), TARGET, RUN, TRIAL, configured_instance_id=INSTANCE
        )
    assert "/" not in str(excinfo.value)
    assert "\\" not in str(excinfo.value)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("c0641257-a1a9", True),
        ("a.b_c-d", True),
        ("", False),
        (".", False),
        ("..", False),
        ("a/b", False),
        ("a\\b", False),
        ("a\x00b", False),
        (None, False),
        (7, False),
    ],
)
def test_is_safe_identifier(value: object, expected: bool) -> None:
    from read_api.resolved import is_safe_identifier

    assert is_safe_identifier(value) is expected
