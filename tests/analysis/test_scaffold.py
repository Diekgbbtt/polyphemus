"""The deterministic L1 scaffold (platform module `analysis.scaffold`).

Pure parse + shell build (no LLM, no driver), and `scaffold_project` through an
injected sole-writer seam. Asserts external shapes only: the parsed skeleton and
the deltas handed to the writer.
"""
from __future__ import annotations

import pytest

from polymerhus.analysis import scaffold


KB = """\
# Example (1.0)

## Overview
An example application.

## Services
### account-sign-in
- contract: Authenticates a user and mints their session.
- exposure: public
### content-management
- contract: Owns the articles and their publication state.
- exposure: authenticated

## Systems
### session - cookie
- description: Cookie-based identification.
### made-up - thing
- description: A mechanism the vocabulary does not speak.

## Roles
- admin
- editor
"""


def test_parse_kb_reads_the_three_sections():
    services, systems, roles = scaffold.parse_kb(KB)

    assert [s["slug"] for s in services] == ["account-sign-in", "content-management"]
    assert services[0]["contract"] == "Authenticates a user and mints their session."
    assert services[0]["exposure"] == "public"
    assert systems[0]["kind"] == "session"
    assert systems[0]["name"] == "cookie"
    assert roles == ["admin", "editor"]


def test_build_shells_maps_kinds_and_drops_out_of_vocabulary():
    service_shells, system_shells, dispositions = scaffold.build_shells(KB)

    assert [s.business_function_slug for s in service_shells] == [
        "account-sign-in", "content-management"]
    assert [s.kind for s in system_shells] == ["IdentificationSystem"]
    assert any(d[2] == "kind-dropped" for d in dispositions)
    # the KB Roles land on the AuthorizationSystem only; none exists here, so
    # they simply do not attach.
    assert system_shells[0].roles == []


def test_scaffold_project_runs_the_sole_writer_seam():
    recorded = {}

    def fake_curate(services, systems, project_id):
        recorded["services"] = [d.business_function_slug for d in services]
        recorded["systems"] = [d.kind for d in systems]
        recorded["project_id"] = project_id
        return len(services), len(systems)

    services_written, systems_written = scaffold.scaffold_project(
        "p1", KB, curate_fn=fake_curate)

    assert recorded["project_id"] == "p1"
    # the two KB services plus the hard-forced pre-auth account linchpin
    assert set(recorded["services"]) >= {"account-sign-in", "content-management"}
    assert {"IdentificationSystem", "AuthenticationMechanism",
            "AuthorizationSystem"} <= set(recorded["systems"])
    assert services_written == len(recorded["services"])
    assert systems_written == len(recorded["systems"])


def test_scaffold_project_zero_services_is_a_blocked_scaffold():
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.scaffold_project("p1", "## Overview\nnothing\n", curate_fn=lambda *a: (0, 0))


def test_eval_scaffold_is_a_thin_wrapper_over_the_platform_module(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "eval_scaffold", Path(__file__).resolve().parents[2] / "eval" / "scaffold.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    kb_path = tmp_path / "operator_kb.md"
    kb_path.write_text(KB)

    service_shells, system_shells, _ = module.build_shells(kb_path)

    assert [s.business_function_slug for s in service_shells] == [
        "account-sign-in", "content-management"]
    assert module.parse_kb(KB)[0][0]["slug"] == "account-sign-in"
    assert "IdentificationSystem" in module.SYSTEM_KINDS
