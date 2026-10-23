"""The hunter tool-description budget and the critical usage clauses.

The request schemas are the machine contract. The top-level descriptions carry
only the usage, the operation, the hard constraints, and the error envelope, so
the repeated fixed text stays small without losing the contract.
"""
from __future__ import annotations

from polymerhus.app.auth.tool import build_auth_store_tool
from polymerhus.app.llm.skills import build_skill_tools
from polymerhus.attack.hunting.hunter_tools import build_hunter_tools


def _surface():
    tools = build_hunter_tools(
        store=None, project_id="p", hunt_key="u__loop-1", run_id="r",
        suite_classes=("idor",),
    )
    tools.append(build_auth_store_tool(project_id="p", read_only=True))
    tools.extend(build_skill_tools("p"))
    return tools


def test_the_hunter_tool_descriptions_stay_within_the_budget():
    """The 12 request descriptions are a fixed tax on every hunter call. The
    dense contract is bounded; the schemas remain the full machine surface."""
    total = sum(len(tool.description or "") for tool in _surface())
    assert total <= 8500, total


def test_every_hunter_tool_has_a_description():
    for tool in _surface():
        assert tool.description and tool.description.strip(), tool.name


def test_the_critical_contract_clauses_survive_the_slimming():
    """Each tool keeps the one or two clauses a model must not lose."""
    by_name = {tool.name: (tool.description or "") for tool in _surface()}
    clauses = {
        "hunts_store": ("exactly ONE spec", "finalize", "derived"),
        "notes": ("phase_summary", "append", "update"),
        "graph_view": ("read-only", "MATCH", "LIMIT"),
        "kb_query": ("QuerySpecV1", "degraded", "not evidence of absence"),
        "exec": ("target front", "5xx", "baseline_ref"),
        "skill_list": ("suite_gap", "web_vulnerability_class"),
        "skill_load": ("suite_gap",),
        "search_http_history": ("invalid_filter", "next_cursor", "artifact_id"),
        "get_http_artifact": ("capture_state", "baseline_ref", "not_found"),
        "auth_store": ("READ-ONLY", "<redacted>", "auth_readonly"),
        "load_skill": ("listing", "meta-usage-skill"),
        "record_skill_lesson": ("specification", "extension", "defect"),
    }
    for name, expected in clauses.items():
        text = by_name[name]
        for clause in expected:
            assert clause in text, f"{name} lost {clause!r}"


def test_the_typed_spec_schema_still_describes_every_field():
    """The schema carries the field-level contract; slimming the top-level text
    never strips a field description."""
    from polymerhus.attack.hunting.hunter_tools import HuntsStoreArgs  # noqa: PLC0415

    schema = HuntsStoreArgs.model_json_schema()
    spec = schema["$defs"]["SpecWrite"]["properties"]
    for name in ("status", "fault_keyword", "strategy_keyword",
                 "target_identity", "verification_symptoms", "assumptions",
                 "rationale", "parent_spec_ref", "provenance", "skills"):
        assert spec[name].get("description"), name
    provenance = schema["$defs"]["SpecProvenance"]["properties"]
    assert provenance["run_id"].get("description")
    assert provenance["skill_procedure"].get("description")
