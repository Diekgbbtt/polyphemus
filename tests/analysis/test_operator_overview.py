"""W-d: the operator_kb `## Overview` as a skeleton attribute.

The Overview is parsed by the deterministic scaffold, persisted to settings as
`application_overview`, surfaced by `read_l1_inventory`, and prepended to each
Service's reasoning (the assigner's unit context).
"""
from __future__ import annotations

from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_inventory import read_l1_inventory
from polymerhus.analysis.scaffold import parse_overview, scaffold_project

KB = """# ComfyUI with ComfyUI-Manager

## Overview

The deployed application is a single web service that hosts the ComfyUI node-graph
editor, extended with the ComfyUI-Manager custom node.

## Services

### workflow-submission
- contract: Submits a node-graph prompt for execution.
- exposure: public
"""


def test_parse_overview_extracts_the_section():
    overview = parse_overview(KB)
    assert "single web service" in overview
    assert "ComfyUI-Manager" in overview
    assert "## Services" not in overview
    assert "workflow-submission" not in overview


def test_parse_overview_is_empty_when_absent():
    assert parse_overview("## Services\n\n### a\n- contract: x\n") == ""


def test_scaffold_project_persists_the_overview_as_a_skeleton_attribute():
    saved: dict = {}

    def save_settings(project_id, values):
        saved[project_id] = values

    scaffold_project(
        "p1", KB,
        curate_fn=lambda services, systems, project_id: (len(services), len(systems)),
        save_settings_fn=save_settings,
    )
    assert "single web service" in saved["p1"]["application_overview"]


def test_read_l1_inventory_surfaces_the_overview():
    inv = read_l1_inventory(
        "p1",
        read_fn=lambda cypher, params=None: [],
        settings_fn=lambda pid: {"application_overview": "The macro framing."},
    )
    assert inv["application_overview"] == "The macro framing."


def test_read_l1_inventory_defaults_the_overview_to_empty():
    inv = read_l1_inventory("p1", read_fn=lambda cypher, params=None: [],
                            settings_fn=lambda pid: {})
    assert inv["application_overview"] == ""


def test_overview_block_prepends_the_application_overview():
    from polymerhus.analysis.pod import overview_block

    inv = {"application_overview": "A single web service for node-graph editing."}
    assert overview_block(inv).startswith("APPLICATION OVERVIEW: A single web service")
    assert overview_block(inv).endswith("\n\n")


def test_overview_block_omits_the_framing_when_absent():
    from polymerhus.analysis.pod import overview_block

    assert overview_block({}) == ""
    assert overview_block(None) == ""


def test_assigner_user_prompt_is_framed_by_the_overview():
    from polymerhus.analysis.assigner import _user_prompt

    inventory = {
        "service_contracts": {"checkout": "Take a basket to a paid order."},
        "application_overview": "A single web service for node-graph editing.",
    }
    prompt = _user_prompt({"nodes": [], "edges": []}, inventory)
    assert prompt.startswith("APPLICATION OVERVIEW: A single web service")


def test_typist_reflection_prompt_is_framed_by_the_overview():
    from polymerhus.analysis.mechanism_typist import _reflection_prompt

    chunk = Chunk(chunk_id="katana_0", source_job="katana", assets=())
    inventory = {"application_overview": "A single web service for node-graph editing."}
    assert _reflection_prompt(chunk, inventory).startswith(
        "APPLICATION OVERVIEW: A single web service"
    )


def test_data_modeller_reflection_prompt_is_framed_by_the_overview():
    from polymerhus.analysis.data_modeller import _reflection_prompt

    chunk = Chunk(chunk_id="katana_0", source_job="katana", assets=())
    inventory = {"application_overview": "A single web service for node-graph editing."}
    assert _reflection_prompt(chunk, inventory, {}).startswith(
        "APPLICATION OVERVIEW: A single web service"
    )
