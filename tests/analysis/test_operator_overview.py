"""W-d: the operator_kb `## Overview` as the structured skeleton attribute.

The Overview is parsed by the deterministic scaffold into the structured entity
`{domain, description, journeys}`, persisted to settings as
`application_overview`, surfaced by `read_l1_inventory`, and delivered to the
four item-consuming agents as a dedicated message (the Q4 model, see
`docs/design/overview-entity-impact-map.md`).
"""
from __future__ import annotations

from polymerhus.analysis.scaffold import parse_overview

EMPTY = {"domain": "", "description": "", "journeys": []}

STRUCTURED_KB = """# ComfyUI with ComfyUI-Manager

## Overview

```yaml
domain: comfyui
description: A single web service hosting the ComfyUI node-graph editor.
journeys:
  - name: Register and submit a workflow
    steps:
      - Open / and click the queue button (workflow-submission, WebPresentation).
      - Fill the prompt form and submit it (RESTApi).
      - Watch the queue page update (WebPresentation).
  - name: Install a custom node
    steps:
      - Open the Manager menu entry (RESTApi).
      - Submit the install form (workflow-submission).
      - Restart the server from the Manager page (IdentificationSystem).
```

## Services

### workflow-submission
- contract: Submits a node-graph prompt for execution.
- exposure: public
"""

LEGACY_KB = """# ComfyUI

## Overview

The deployed application is a single web service that hosts the ComfyUI
node-graph editor.

## Services

### workflow-submission
- contract: Submits a node-graph prompt for execution.
- exposure: public
"""


def test_parse_overview_structured_block():
    overview = parse_overview(STRUCTURED_KB)
    assert set(overview) == {"domain", "description", "journeys"}
    assert overview["domain"] == "comfyui"
    assert "node-graph editor" in overview["description"]
    assert len(overview["journeys"]) == 2
    first = overview["journeys"][0]
    assert set(first) == {"name", "steps"}
    assert first["name"] == "Register and submit a workflow"
    assert len(first["steps"]) == 3
    assert all(isinstance(step, str) for step in first["steps"])


def test_parse_overview_structured_block_excludes_other_sections():
    overview = parse_overview(STRUCTURED_KB)
    assert "contract" not in overview["description"]
    assert "exposure" not in overview["description"]


def test_parse_overview_legacy_prose_maps_to_description():
    overview = parse_overview(LEGACY_KB)
    assert overview["domain"] == ""
    assert overview["journeys"] == []
    assert "single web service" in overview["description"]
    assert "## Services" not in overview["description"]
    assert "contract" not in overview["description"]


def test_parse_overview_absent_is_empty():
    assert parse_overview("## Services\n\n### a\n- contract: x\n") == EMPTY


def test_parse_overview_malformed_yaml_fails_open():
    kb = "## Overview\n\n```yaml\ndomain: [unclosed\n```\n"
    assert parse_overview(kb) == EMPTY


def test_parse_overview_drops_malformed_journey_entries():
    kb = (
        "## Overview\n\n```yaml\n"
        "domain: shop\n"
        "description: A web storefront.\n"
        "journeys:\n"
        "  - not-a-mapping\n"
        "  - name: only-a-name\n"
        "    steps: [open /, submit the form]\n"
        "  - name: bad-steps\n"
        "    steps: not-a-list\n"
        "```\n"
    )
    overview = parse_overview(kb)
    assert [j["name"] for j in overview["journeys"]] == ["only-a-name", "bad-steps"]
    assert overview["journeys"][0]["steps"] == ["open /", "submit the form"]
    assert overview["journeys"][1]["steps"] == []


def _recording_settings(saved: dict):
    def save_settings(project_id, values):
        saved[project_id] = values

    return save_settings


def _curate_len(services, systems, project_id):
    return len(services), len(systems)


def test_scaffold_project_persists_the_structured_overview():
    from polymerhus.analysis.scaffold import scaffold_project

    saved: dict = {}
    scaffold_project(
        "p1", STRUCTURED_KB,
        curate_fn=_curate_len, save_settings_fn=_recording_settings(saved),
    )
    persisted = saved["p1"]["application_overview"]
    assert set(persisted) == {"domain", "description", "journeys"}
    assert persisted["domain"] == "comfyui"
    assert len(persisted["journeys"]) == 2


def test_scaffold_project_persists_all_keys_for_legacy_prose():
    # JSONB deep merge: every key must ride every write so an older value can
    # never survive under a missing key (impact map, section 6).
    from polymerhus.analysis.scaffold import scaffold_project

    saved: dict = {}
    scaffold_project(
        "p1", LEGACY_KB,
        curate_fn=_curate_len, save_settings_fn=_recording_settings(saved),
    )
    persisted = saved["p1"]["application_overview"]
    assert set(persisted) == {"domain", "description", "journeys"}
    assert persisted["domain"] == ""
    assert "single web service" in persisted["description"]


def test_scaffold_project_skips_the_overview_write_when_absent():
    from polymerhus.analysis.scaffold import scaffold_project

    calls: list = []
    scaffold_project(
        "p1", "## Services\n\n### a\n- contract: x\n- exposure: public\n",
        curate_fn=_curate_len,
        save_settings_fn=lambda project_id, values: calls.append(values),
    )
    assert calls == []


def test_scaffold_project_overview_persistence_fails_open():
    from polymerhus.analysis.scaffold import scaffold_project

    def save_settings(project_id, values):
        raise RuntimeError("settings store down")

    services, systems = scaffold_project(
        "p1", STRUCTURED_KB, curate_fn=_curate_len, save_settings_fn=save_settings,
    )
    assert services >= 1


def _no_graph_read(cypher, params=None):
    return []


def test_read_l1_inventory_normalizes_the_structured_overview():
    from polymerhus.analysis.l1_inventory import read_l1_inventory

    inv = read_l1_inventory(
        "p1",
        read_fn=_no_graph_read,
        settings_fn=lambda pid: {
            "application_overview": {
                "domain": "shop",
                "description": "A web storefront.",
                "journeys": [{"name": "Buy an item", "steps": ["open /", "pay"]}],
            }
        },
    )
    overview = inv["application_overview"]
    assert set(overview) == {"domain", "description", "journeys"}
    assert overview["domain"] == "shop"
    assert overview["journeys"][0]["steps"] == ["open /", "pay"]


def test_read_l1_inventory_normalizes_legacy_prose():
    from polymerhus.analysis.l1_inventory import read_l1_inventory

    inv = read_l1_inventory(
        "p1", read_fn=_no_graph_read,
        settings_fn=lambda pid: {"application_overview": "The old macro framing."},
    )
    assert inv["application_overview"] == {
        "domain": "", "description": "The old macro framing.", "journeys": [],
    }


def test_read_l1_inventory_defaults_the_overview_to_the_empty_shape():
    from polymerhus.analysis.l1_inventory import read_l1_inventory

    inv = read_l1_inventory("p1", read_fn=_no_graph_read, settings_fn=lambda pid: {})
    assert inv["application_overview"] == EMPTY


def test_read_application_overview_is_settings_only():
    from polymerhus.analysis.l1_inventory import read_application_overview

    overview = read_application_overview(
        "p1", settings_fn=lambda pid: {"application_overview": "Legacy prose."},
    )
    assert overview == {"domain": "", "description": "Legacy prose.", "journeys": []}


def test_read_application_overview_fails_open_on_settings_error():
    from polymerhus.analysis.l1_inventory import read_application_overview

    def settings_fn(project_id):
        raise RuntimeError("settings store down")

    assert read_application_overview("p1", settings_fn=settings_fn) == EMPTY


STRUCTURED_OVERVIEW = {
    "domain": "comfyui",
    "description": "A single web service hosting the ComfyUI node-graph editor.",
    "journeys": [
        {
            "name": "Register and submit a workflow",
            "steps": [
                "Open / and click the queue button (workflow-submission, WebPresentation).",
                "Fill the prompt form and submit it (RESTApi).",
                "Watch the queue page update (WebPresentation).",
            ],
        },
        {
            "name": "Install a custom node",
            "steps": [
                "Open the Manager menu entry (RESTApi).",
                "Submit the install form (workflow-submission).",
                "Restart the server from the Manager page (IdentificationSystem).",
            ],
        },
    ],
}


def test_overview_message_renders_the_structured_overview_cleanly():
    from polymerhus.analysis.overview import overview_message

    message = overview_message(STRUCTURED_OVERVIEW)
    lines = message.splitlines()
    assert lines[0] == (
        "APPLICATION OVERVIEW (the deployed application the following items "
        "belong to):"
    )
    assert "Domain: comfyui" in lines
    assert (
        "Offered features: A single web service hosting the ComfyUI node-graph editor."
        in lines
    )
    assert "Canonical journeys:" in lines
    assert "1. Register and submit a workflow" in lines
    assert "2. Install a custom node" in lines
    assert (
        "   - Open / and click the queue button (workflow-submission, WebPresentation)."
        in lines
    )
    # no formatting noise: no YAML/markdown artifacts, no blank-line runs,
    # no leading/trailing whitespace
    assert "{" not in message
    assert "```" not in message
    assert "\n\n" not in message
    assert message == message.strip()


def test_overview_message_legacy_prose_keeps_the_one_line_render():
    from polymerhus.analysis.overview import overview_message

    assert overview_message("The macro framing.") == (
        "APPLICATION OVERVIEW: The macro framing."
    )
    assert overview_message({"description": "Only prose."}) == (
        "APPLICATION OVERVIEW: Only prose."
    )


def test_overview_message_is_empty_when_absent():
    from polymerhus.analysis.overview import overview_message

    assert overview_message(None) == ""
    assert overview_message("") == ""
    assert overview_message({}) == ""


def test_overview_message_skips_empty_fields():
    from polymerhus.analysis.overview import overview_message

    message = overview_message({"domain": "shop", "description": "", "journeys": []})
    assert message.splitlines() == [
        "APPLICATION OVERVIEW (the deployed application the following items "
        "belong to):",
        "Domain: shop",
    ]
