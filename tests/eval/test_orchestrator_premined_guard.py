"""The pre-mined-config guard (T10b #397).

The hunt-config family retired from the dispatch path in T4b (#387): a threat
file is the dispatch record. A pre-mined config therefore cannot be evidence
that the hunting prerequisite is satisfied. Two layers enforce it:

- the setup parser refuses the retired `configs` key (and the bare-string form)
  with a message naming the replacement;
- the hunting-entry gate counts only produced/consumed threat files and hunter
  test specs, and names a stale config tree as RETIRED instead of letting it
  read as an absent artifact.
"""
from __future__ import annotations

import pytest

from orchestrator import predicates, setup
from orchestrator.files import (
    FileStore,
    hunter_test_specs_family_dir,
    retired_hunt_configs_dir,
    threat_model_dir,
)

PROJECT = "pid"


def _targets(payload) -> dict:
    """The minimal parseable setup shape, with one target's preload overridden."""
    return {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "instances": [
            {
                "instance_id": "arm-a",
                "targets": [
                    {
                        "target_key": "webexploitbench/comfyui",
                        "target_id": "comfyui-1",
                        "preloaded_hunting_artifacts": payload,
                    }
                ],
            }
        ],
    }


def test_the_setup_parser_refuses_the_retired_configs_key() -> None:
    with pytest.raises(setup.SetupError, match="configs is RETIRED"):
        setup.parse_eval_setup(_targets({"configs": "/mnt/premined-configs"}))


def test_the_setup_parser_names_the_threat_replacement() -> None:
    try:
        setup.parse_eval_setup(_targets({"configs": "/mnt/premined-configs"}))
    except setup.SetupError as exc:
        text = str(exc)
        assert "models" in text
        assert "T10b" in text and "#397" in text
    else:  # pragma: no cover - the test above already proves the refusal
        raise AssertionError("the retired configs key was accepted")


def test_the_setup_parser_refuses_the_retired_bare_string_form() -> None:
    with pytest.raises(setup.SetupError, match="RETIRED"):
        setup.parse_eval_setup(_targets("/mnt/premined-configs"))


def test_a_stale_premined_config_does_not_satisfy_the_gate(tmp_path) -> None:
    files = FileStore()
    files.write_text(
        retired_hunt_configs_dir(tmp_path, PROJECT, "produced") / "cfg.yaml",
        "id: retired\n",
    )
    state = predicates.PhaseState(
        project_id=PROJECT,
        preloaded_configured=True,
        data_root=tmp_path,
    )

    result = predicates.hunting_entry(_gate_api(), files, state)

    assert not result.ok
    assert any("RETIRED" in block for block in result.blocks)
    assert "cannot satisfy" in result.reason


def test_a_produced_threat_file_satisfies_the_gate(tmp_path) -> None:
    files = FileStore()
    unit_dir = threat_model_dir(tmp_path, PROJECT, "produced") / "unit-web-x"
    files.write_text(unit_dir / "unit-web-x.yaml", "state: COMPLETED\n")
    files.write_text(unit_dir / "threat-1.yaml", "threat:\n  id: threat-1\n")
    state = predicates.PhaseState(
        project_id=PROJECT,
        preloaded_configured=True,
        data_root=tmp_path,
    )

    result = predicates.hunting_entry(_gate_api(), files, state)

    assert result.ok


def test_a_model_document_alone_does_not_satisfy_the_gate(tmp_path) -> None:
    # The dispatch grain is the THREAT FILE (S2 8.4); a COMPLETED model with no
    # dispatchable threat authors no work, so it is not a satisfied prerequisite.
    files = FileStore()
    unit_dir = threat_model_dir(tmp_path, PROJECT, "produced") / "unit-web-x"
    files.write_text(unit_dir / "unit-web-x.yaml", "state: COMPLETED\n")
    state = predicates.PhaseState(
        project_id=PROJECT,
        preloaded_configured=True,
        data_root=tmp_path,
    )

    result = predicates.hunting_entry(_gate_api(), files, state)

    assert not result.ok
    assert "pre-mined hunting artifacts configured but not present" in result.reason


def test_a_premined_test_spec_satisfies_the_gate(tmp_path) -> None:
    files = FileStore()
    spec_dir = hunter_test_specs_family_dir(
        tmp_path, PROJECT, "unit-web-x__threat-1", "produced"
    )
    files.write_text(spec_dir / "sqli.yaml", "status: ratified\n")
    state = predicates.PhaseState(
        project_id=PROJECT,
        preloaded_configured=True,
        data_root=tmp_path,
    )

    result = predicates.hunting_entry(_gate_api(), files, state)

    assert result.ok


def _gate_api():
    """The hunting gate reads the project listing and graph only."""

    class FakeApi:
        def __call__(self, call):
            key = f"{call.method} {call.path}"
            if key == "GET /projects":
                return {"projects": [{"project_id": PROJECT}]}
            if key == f"GET /projects/{PROJECT}/graph":
                return {"nodes": [{"type": "L1Service"}], "links": []}
            raise AssertionError(f"unexpected call {key}")

    return FakeApi()
