"""The hunter tool-description budget and the critical usage clauses.

The request schemas are the machine contract. The top-level descriptions carry
only the usage, the operation, the hard constraints, and the error envelope, so
the repeated fixed text stays small without losing the contract.
"""
from __future__ import annotations

from polymerhus.app.auth.tool import build_auth_store_tool
from polymerhus.app.llm.skills import build_skill_tools
from polymerhus.attack.hunting.hunter_tools import build_hunter_tools
from polymerhus.attack.hunting.pod.agents import runner_react_tools, triager_react_tools
from polymerhus.attack.hunting.threat_modeller_tools import (
    ModellerTools,
    build_modeller_tool_surface,
)


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
    # 8700 (was 8500): the shared auth contract now teaches the retired full
    # view and the 12000-character read bound, the two changes that remove the
    # run's 1.5M-character auth occupancy.
    assert total <= 8700, total


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
    for name in ("status", "discriminators", "target_identity",
                 "verification_symptoms", "assumptions", "rationale",
                 "parent_spec_ref", "provenance", "skills",
                 "skill_concretised_procedure", "merged_from"):
        assert spec[name].get("description"), name
    provenance = schema["$defs"]["SpecProvenance"]["properties"]
    assert provenance["run_id"].get("description")
    concretised = schema["$defs"]["SkillConcretisedProcedure"]["properties"]
    for name in (
            "recon_action", "bypass_technique", "advanced_technique",
            "preliminary_chaining", "payload_vector",
            "technology_misconfiguration", "technology_grounding",
            "pro_tips", "interpretation_pitfalls"):
        assert concretised[name].get("description"), name


def _role_surfaces():
    auth = [build_auth_store_tool(project_id="p", read_only=True)]
    skills = list(build_skill_tools("p"))
    modeller = list(build_modeller_tool_surface(
        "p", "u", ModellerTools(project_id="p", run_id="r")).values())
    runner = runner_react_tools(None, None, "s", None, "v", project_id="p")
    triager = triager_react_tools(None, "s")
    return {
        "hunter": {tool.name: tool for tool in _surface()},
        "modeller": {tool.name: tool for tool in modeller + auth + skills},
        "runner": {tool.name: tool for tool in runner + auth + skills},
        "triager": {tool.name: tool for tool in triager + auth + skills},
    }


def test_shared_tool_descriptions_are_byte_identical_across_bindings():
    """The shared constants are the sharing mechanism: the same tool text is

    bound by every role that carries the tool, so a role subset cannot drift.
    """
    roles = _role_surfaces()
    for name in ("graph_view", "load_skill", "record_skill_lesson", "auth_store"):
        texts = {
            role: tools[name].description
            for role, tools in roles.items()
            if name in tools
        }
        assert len(set(texts.values())) == 1, name

    for name in ("search_http_history", "get_http_artifact", "exec",
                 "skill_list", "skill_load"):
        assert (roles["hunter"][name].description
                == roles["modeller"][name].description), name

    kb_texts = {
        roles["hunter"]["kb_query"].description,
        roles["runner"]["query_lightrag"].description,
        roles["triager"]["query_lightrag"].description,
    }
    assert len(kb_texts) == 1
