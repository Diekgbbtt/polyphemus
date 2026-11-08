#!/usr/bin/env python3
"""Extract the source-level duplication and coverage ledger.

The script is deliberately lexical where text is compared, and schema-based where
a model or enum exists. It does not claim semantic equivalence from a high
similarity score. It produces evidence for the human review in the report.

Usage:

    python3 audit_context_duplication.py \
      --source-root /path/to/utm-context-auth-followup \
      --occupancy /tmp/audit_context_occupancy.json \
      --out /tmp/context_duplication_metrics.json
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
from pathlib import Path
from typing import Any


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def literal(tree: ast.AST, name: str) -> Any:
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        try:
            return ast.literal_eval(node.value)
        except (TypeError, ValueError):
            return None
    return None


def _assigned_value(tree: ast.AST, name: str) -> ast.expr | None:
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return node.value
    return None


def _module_strings(tree: ast.AST) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                continue
            if isinstance(value, str):
                values[target.id] = value
    return values


def literal_values(tree: ast.AST, name: str) -> Any:
    """Extract a Literal, tuple, set, or dict, including named tuple members."""
    value = _assigned_value(tree, name)
    if value is None:
        return None
    if isinstance(value, ast.Subscript):
        value = value.slice
    if isinstance(value, ast.Call) and value.args:
        value = value.args[0]
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, (set, frozenset)):
            return sorted(parsed)
        return parsed
    except (TypeError, ValueError):
        pass
    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        names = _module_strings(tree)
        resolved: list[Any] = []
        for element in value.elts:
            if isinstance(element, ast.Name) and element.id in names:
                resolved.append(names[element.id])
            else:
                try:
                    resolved.append(ast.literal_eval(element))
                except (TypeError, ValueError):
                    return None
        return resolved
    return None



def gate_mapping(tree: ast.AST) -> dict[str, list[str]] | None:
    """Extract GATE_SECTIONS when its keys are StrEnum attributes."""
    value = _assigned_value(tree, "GATE_SECTIONS")
    if not isinstance(value, ast.Dict):
        return None
    result: dict[str, list[str]] = {}
    for key, item in zip(value.keys, value.values):
        if isinstance(key, ast.Attribute):
            name = key.attr
        elif isinstance(key, ast.Name):
            name = key.id
        else:
            try:
                name = str(ast.literal_eval(key))
            except (TypeError, ValueError):
                name = ""
        try:
            sections = ast.literal_eval(item)
        except (TypeError, ValueError):
            sections = []
        result[name] = list(sections) if isinstance(sections, (tuple, list)) else []
    return result

def class_fields(tree: ast.AST, name: str) -> list[str]:
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != name:
            continue
        fields: list[str] = []
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                fields.append(statement.target.id)
        return fields
    return []


def section(text: str, heading: str) -> str:
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if line.strip() == heading]
    if not starts:
        return ""
    start = starts[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,4} ", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def prompt_mentions(text: str, name: str) -> bool:
    return name in text or f"`{name}`" in text


def matching_blocks(left: str, right: str, minimum: int = 80) -> list[dict[str, Any]]:
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    blocks = [
        {"chars": block.size, "left": left[block.a:block.a + 120]}
        for block in matcher.get_matching_blocks()
        if block.size >= minimum
    ]
    return sorted(blocks, key=lambda block: -block["chars"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--occupancy", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.source_root)
    occupancy = json.loads(Path(args.occupancy).read_text())
    first_calls = {row["role"]: row for row in occupancy["first_calls"]}

    prompt_dir = root / "src/polymerhus/attack/hunting/prompts"
    analysis_prompt_dir = root / "src/polymerhus/analysis/prompts"
    prompts = {
        "hunter": read(prompt_dir / "hunting-agent.md"),
        "examples": read(prompt_dir / "examples.md"),
        "cortex": read(prompt_dir / "COGNITIVE_ARCHITECTURE_MAP.md"),
        "modeller": read(prompt_dir / "threat-modeller.md"),
        "pod_runner": read(prompt_dir / "pod-runner.md"),
        "pod_triager": read(prompt_dir / "pod-triager.md"),
        "assigner": read(analysis_prompt_dir / "assigner.md"),
        "typist": read(analysis_prompt_dir / "technical-system.md"),
        "bootstrapper": read(analysis_prompt_dir / "bootstrapper.md"),
        "curation": read(analysis_prompt_dir / "curation.md"),
        "evolver": read(root / "src/polymerhus/app/llm/prompts/skill_evolver.md"),
        "gateway": read(root / "src/polymerhus/recon/control/prompts/auth-gateway.md"),
        "recon_triager": read(root / "src/polymerhus/recon/domain/prompts/writing-observations.md"),
    }

    conciseness = literal(
        ast.parse(read(root / "src/polymerhus/attack/hunting/conciseness.py")),
        "HUNTING_CONCISENESS_DIRECTIVE",
    )
    assigner_role = literal(
        ast.parse(read(root / "src/polymerhus/analysis/assigner.py")),
        "_ROLE_VERBATIM",
    )
    assigner_examples = literal(
        ast.parse(read(root / "src/polymerhus/analysis/assigner.py")),
        "_FEW_SHOTS",
    )
    reflection_steps = literal(
        ast.parse(read(root / "src/polymerhus/analysis/mechanism_typist.py")),
        "_REFLECTION_STEPS",
    )
    skill_load_contract = literal(
        ast.parse(read(root / "src/polymerhus/app/llm/skills.py")),
        "SKILL_LOAD_CONTRACT",
    )
    write_skill_contract = literal(
        ast.parse(read(root / "src/polymerhus/app/llm/skills.py")),
        "WRITE_SKILL_CONTRACT",
    )

    spec_tree = ast.parse(read(root / "src/polymerhus/attack/hunting/pod/types.py"))
    provenance_tree = ast.parse(read(root / "src/polymerhus/attack/hunting/spec_contract.py"))
    writer_tree = ast.parse(read(root / "src/polymerhus/attack/hunting/hunter_tools.py"))
    state_tree = ast.parse(read(root / "src/polymerhus/attack/hunting/hunter_state.py"))
    variant_tree = ast.parse(read(root / "src/polymerhus/attack/hunting/pod/variant_basis.py"))
    model_tree = ast.parse(read(root / "src/polymerhus/attack/hunting/threat_model.py"))
    anchor_tree = ast.parse(read(root / "src/polymerhus/recon/domain/curator.py"))

    spec_fields = class_fields(spec_tree, "TestImplementationSpec")
    provenance_fields = class_fields(provenance_tree, "SpecProvenance")
    writer_fields = class_fields(writer_tree, "SpecWrite")
    skill_fields = class_fields(provenance_tree, "SkillProcedure")
    spec_status = literal_values(state_tree, "SpecStatus")
    pass_sequence = literal_values(state_tree, "PASS_SEQUENCE")
    variant_bases = literal_values(variant_tree, "VARIANT_BASES")
    gate_sections = gate_mapping(model_tree)
    anchor_allowlist = literal_values(anchor_tree, "ANCHOR_ALLOWLIST")

    spec_section = section(prompts["hunter"], "## The spec body")
    spec_missing = [field for field in spec_fields if not prompt_mentions(spec_section, field)]
    provenance_missing = [
        field for field in provenance_fields if not prompt_mentions(spec_section, field)
    ]

    tool_sections = {
        "hunting_hunter": section(prompts["hunter"], "## The tools"),
        "hunting_threat_modeller": section(prompts["modeller"], "## Tools"),
        "pod_runner": section(prompts["pod_runner"], "# Tools"),
        "pod_triager": section(prompts["pod_triager"], "# Tools"),
        "assigner": prompts["assigner"],
        "mechanism_typist": prompts["typist"],
        "skill_evolver": prompts["evolver"],
        "job_orchestrator": prompts["gateway"],
        "triager": prompts["recon_triager"],
    }
    tool_coverage: dict[str, Any] = {}
    for role, first in first_calls.items():
        if role not in tool_sections:
            continue
        actual = [tool["name"] for tool in first["tool_descriptions"]]
        text = tool_sections[role]
        missing = [name for name in actual if not prompt_mentions(text, name)]
        tool_coverage[role] = {
            "actual": actual,
            "missing_from_prompt": missing,
            "actual_count": len(actual),
            "missing_count": len(missing),
        }

    shared_tools = {
        "load_skill": {"roles": 0, "chars": 0, "sizes": {}},
        "record_skill_lesson": {"roles": 0, "chars": 0, "sizes": {}},
        "auth_store": {"roles": 0, "chars": 0, "sizes": {}},
        "graph_view": {"roles": 0, "chars": 0, "sizes": {}},
        "search_http_history": {"roles": 0, "chars": 0, "sizes": {}},
        "get_http_artifact": {"roles": 0, "chars": 0, "sizes": {}},
        "exec": {"roles": 0, "chars": 0, "sizes": {}},
        "query_lightrag": {"roles": 0, "chars": 0, "sizes": {}},
        "write_skill": {"roles": 0, "chars": 0, "sizes": {}},
    }
    for role, first in first_calls.items():
        for tool in first["tool_descriptions"]:
            name = tool["name"]
            if name not in shared_tools:
                continue
            shared_tools[name]["roles"] += 1
            shared_tools[name]["chars"] += tool["schema"]
            shared_tools[name]["sizes"][role] = tool["schema"]

    first_total_chars = sum(first["raw_chars"] for first in first_calls.values())
    first_total_system = sum(
        first["components"].get("system", 0) for first in first_calls.values()
    )
    first_total_tool = sum(
        sum(tool["schema"] for tool in first["tool_descriptions"])
        for first in first_calls.values()
    )
    shared_total = sum(value["chars"] for value in shared_tools.values())

    pair_blocks = {
        "pod_runner_vs_pod_triager": matching_blocks(
            prompts["pod_runner"], prompts["pod_triager"]
        ),
        "hunter_vs_modeller": matching_blocks(
            prompts["hunter"], prompts["modeller"]
        ),
        "assigner_examples_vs_assigner": matching_blocks(
            assigner_examples or "", prompts["assigner"]
        ),
        "reflection_steps_vs_typist": matching_blocks(
            "\n".join(reflection_steps or []), prompts["typist"]
        ),
    }

    report = {
        "source_root": str(root),
        "prompt_chars": {name: len(text) for name, text in prompts.items()},
        "cortex_chars": len(prompts["cortex"]),
        "conciseness_chars": len(conciseness or ""),
        "skill_load_contract_chars": len(skill_load_contract or ""),
        "write_skill_contract_chars": len(write_skill_contract or ""),
        "assigner_role_verbatim_chars": len(assigner_role or ""),
        "assigner_examples_chars": len(assigner_examples or ""),
        "reflection_steps": len(reflection_steps or []),
        "spec_fields": spec_fields,
        "spec_writer_fields": writer_fields,
        "provenance_fields": provenance_fields,
        "skill_procedure_fields": skill_fields,
        "spec_fields_missing_from_prompt": spec_missing,
        "provenance_fields_missing_from_prompt": provenance_missing,
        "statuses": {
            "spec_status": list(spec_status) if isinstance(spec_status, (tuple, list)) else spec_status,
            "pass_sequence": list(pass_sequence or ()),
            "variant_bases": list(variant_bases or ()),
            "gate_sections": sorted(gate_sections) if isinstance(gate_sections, dict) else gate_sections,
            "anchor_allowlist": sorted(anchor_allowlist) if anchor_allowlist else anchor_allowlist,
        },
        "tool_coverage": tool_coverage,
        "shared_tools": shared_tools,
        "first_call_totals": {
            "raw_chars": first_total_chars,
            "system_chars": first_total_system,
            "tool_chars": first_total_tool,
            "shared_tool_chars": shared_total,
            "shared_tool_share_of_tool_text": round(shared_total / first_total_tool, 4),
            "shared_tool_share_of_all_first_calls": round(shared_total / first_total_chars, 4),
            "tool_share_of_all_first_calls": round(first_total_tool / first_total_chars, 4),
            "system_share_of_all_first_calls": round(first_total_system / first_total_chars, 4),
        },
        "exact_blocks": pair_blocks,
        "direct_vs_suite_skill_names": {
            "catalog_loader": "load_skill",
            "suite_pair": ["skill_list", "skill_load"],
            "write": "write_skill",
        },
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
