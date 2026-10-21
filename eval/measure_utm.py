#!/usr/bin/env python3
"""Deterministic unit-threat-model trial metrics.

Reads one trial record, its persisted hunting artifacts, the project graph, the
WebExploitBench ground truth, and the private ground-truth corpus, and writes a
`metrics.yaml` beside the official verdicts. This script makes no LLM calls and
never writes into the pipeline data root.

The quality rubrics that need semantic judgement are the measurement
subagent's job; this script produces the objective substrate it reads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

SCHEMA_VERSION = 1


def load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def load_mapping(path: Path) -> dict:
    value = load_yaml(path)
    return value if isinstance(value, dict) else {}


def load_list(path: Path) -> list:
    value = load_yaml(path)
    return value if isinstance(value, list) else []


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def text_of(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def api_get(base: str, path: str) -> Any:
    try:
        with urllib.request.urlopen(base.rstrip("/") + path, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


# --- ground truth -------------------------------------------------------------


def load_challenge(target_dir: Path) -> list[dict]:
    challenge = load_mapping(target_dir / "challenge.json")
    rows: list[dict] = []
    for entry in as_list(challenge.get("vulnerabilities")):
        vuln_id = entry.get("vuln_id")
        if not vuln_id:
            continue
        meta = load_mapping(target_dir / "vulnerability" / str(vuln_id) / "metadata.json")
        rows.append({
            "vuln_id": str(vuln_id),
            "type": meta.get("Vulnerability Type", ""),
            "location": meta.get("Location", ""),
            "scoring": entry.get("scoring", []),
        })
    return rows


def load_corpus_unit(corpus_target: Path, vuln_id: str) -> dict:
    unit = load_mapping(corpus_target / vuln_id / "unit-spec.yaml")
    if not unit:
        return {}
    return unit


def unit_identity(unit_spec: dict) -> dict:
    unit = as_dict(unit_spec.get("unit"))
    kind = str(unit.get("kind") or "")
    match = as_dict(unit.get("match"))
    slug = str(match.get("business_function_slug") or "")
    aliases = [str(a) for a in as_list(match.get("aliases")) if a]
    sys_kind = str(match.get("kind") or kind)
    disc = str(match.get("discriminator") or "")
    if kind == "Service":
        expected = f"Service:{slug}" if slug else ""
        names = {slug, *aliases}
    else:
        expected = f"{sys_kind}:{disc}" if disc else sys_kind
        names = {sys_kind, disc}
    return {
        "kind": kind,
        "slug": slug,
        "aliases": aliases,
        "sys_kind": sys_kind,
        "discriminator": disc,
        "expected_id": expected,
        "names": {n for n in names if n},
        "fault_class": str(unit_spec.get("fault_class") or ""),
        "location": str(unit_spec.get("location") or ""),
    }


def class_hints(vuln_type: str) -> set[str]:
    text = norm(vuln_type)
    hints: set[str] = set()
    if "xss" in text or "cross-site" in text:
        hints.update({"xss", "cross-site", "scripting"})
    if "sql" in text:
        hints.update({"sql", "sqli", "injection"})
    if "ssrf" in text or "server-side request" in text:
        hints.update({"ssrf", "server-side request"})
    if "file read" in text or "path traversal" in text or "directory traversal" in text:
        hints.update({"file read", "path traversal", "traversal", "lfi", "arbitrary file"})
    if "file deletion" in text:
        hints.update({"file deletion", "traversal", "delete"})
    if "idor" in text or "authorization" in text or "access control" in text:
        hints.update({"idor", "authorization", "access control", "bola", "bfla", "cwe-284", "cwe-639"})
    if "credential" in text:
        hints.update({"credential", "weak", "default", "cwe-521", "cwe-1392"})
    if "remote code" in text or "command injection" in text or "code injection" in text:
        hints.update({"rce", "remote code", "command injection", "code injection", "cwe-78", "cwe-94"})
    if "sensitive information" in text or "information read" in text:
        hints.update({"information", "sensitive", "cwe-200", "disclosure", "config"})
    if "xxe" in text or "external entity" in text:
        hints.update({"xxe", "external entity"})
    if "open redirect" in text:
        hints.update({"open redirect", "redirect"})
    if not hints:
        hints.update({w for w in text.replace("/", " ").split() if len(w) > 3})
    return hints


def class_matches(text: str, vuln_type: str, cwe: str) -> bool:
    haystack = norm(text)
    if cwe and norm(cwe) in haystack:
        return True
    return any(hint in haystack for hint in class_hints(vuln_type))


# --- graph --------------------------------------------------------------------


def graph_index(graph: dict) -> dict:
    nodes = [as_dict(n) for n in as_list(graph.get("nodes"))]
    links = [as_dict(l) for l in as_list(graph.get("links"))]
    by_id: dict[str, dict] = {}
    by_type: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        node_id = str(node.get("id") or "")
        if node_id:
            by_id[node_id] = node
        by_type[str(node.get("type") or "")].append(node)
    out_links: dict[str, list[dict]] = defaultdict(list)
    in_links: dict[str, list[dict]] = defaultdict(list)
    for link in links:
        source = str(link.get("source") or "")
        target = str(link.get("target") or "")
        if source:
            out_links[source].append(link)
        if target:
            in_links[target].append(link)
    services = by_type.get("L1Service", [])
    systems = by_type.get("L1System", [])
    endpoints = by_type.get("Endpoint", [])
    baseurls = by_type.get("BaseURL", [])
    parameters = by_type.get("Parameter", [])
    service_slugs: dict[str, dict] = {}
    for node in services:
        props = as_dict(node.get("properties"))
        slug = str(props.get("business_function_slug") or "")
        if slug:
            service_slugs[slug] = node
    system_keys: dict[tuple[str, str], dict] = {}
    for node in systems:
        props = as_dict(node.get("properties"))
        kind = str(props.get("kind") or "")
        disc = str(props.get("discriminator") or "")
        system_keys[(kind, disc)] = node
    endpoint_paths: dict[str, dict] = {}
    for node in endpoints:
        props = as_dict(node.get("properties"))
        path = str(props.get("path") or "")
        if path:
            endpoint_paths[path] = node
    return {
        "nodes": nodes,
        "links": links,
        "by_id": by_id,
        "by_type": by_type,
        "out_links": out_links,
        "in_links": in_links,
        "services": services,
        "systems": systems,
        "endpoints": endpoints,
        "baseurls": baseurls,
        "parameters": parameters,
        "service_slugs": service_slugs,
        "system_keys": system_keys,
        "endpoint_paths": endpoint_paths,
    }


def find_unit_nodes(index: dict, identity: dict) -> tuple[dict | None, list[dict], list[dict]]:
    if identity["kind"] == "Service":
        nodes = []
        for name in identity["names"]:
            node = index["service_slugs"].get(name)
            if node is not None:
                nodes.append(node)
        if not nodes:
            for node in index["services"]:
                props = as_dict(node.get("properties"))
                haystack = norm(props.get("business_function_slug"))
                if any(norm(name) in haystack or haystack in norm(name) for name in identity["names"]):
                    nodes.append(node)
        return (nodes[0] if nodes else None), nodes, []
    kind = identity["sys_kind"]
    disc = identity["discriminator"]
    nodes = []
    if kind and disc:
        node = index["system_keys"].get((kind, disc))
        if node is not None:
            nodes.append(node)
    if not nodes:
        for node in index["systems"]:
            props = as_dict(node.get("properties"))
            if kind and norm(props.get("kind")) != norm(kind):
                continue
            if disc and norm(disc) not in norm(props.get("discriminator")):
                continue
            nodes.append(node)
    return (nodes[0] if nodes else None), [], nodes


def unit_metrics(index: dict, unit_spec: dict) -> dict:
    identity = unit_identity(unit_spec)
    unit_node, service_nodes, system_nodes = find_unit_nodes(index, identity)
    present = unit_node is not None
    expected_endpoints = [
        as_dict(e) for e in as_list(as_dict(unit_spec.get("edges_to_l0")).get("endpoints"))
    ]
    expected_paths = [str(e.get("path") or "") for e in expected_endpoints if e.get("path")]
    linked_endpoints: list[dict] = []
    link_present = False
    for service in service_nodes:
        service_id = str(service.get("id") or "")
        for link in index["out_links"].get(service_id, []):
            target = index["by_id"].get(str(link.get("target") or ""))
            if target is not None and str(target.get("type")) in {"Endpoint", "BaseURL", "Parameter"}:
                linked_endpoints.append(target)
                if str(link.get("type")) in {"AGGREGATES", "SURFACES_AT", "EXPOSES", "HAS_ENDPOINT"}:
                    link_present = True
    if not link_present and system_nodes:
        for system in system_nodes:
            system_id = str(system.get("id") or "")
            for link in index["in_links"].get(system_id, []):
                source = index["by_id"].get(str(link.get("source") or ""))
                if source is not None and str(source.get("type")) == "L1Service":
                    for out in index["out_links"].get(str(source.get("id") or ""), []):
                        target = index["by_id"].get(str(out.get("target") or ""))
                        if target is not None and str(target.get("type")) in {"Endpoint", "BaseURL", "Parameter"}:
                            linked_endpoints.append(target)
                            if str(out.get("type")) in {"AGGREGATES", "SURFACES_AT"}:
                                link_present = True
    l0_present = False
    matched_paths: list[str] = []
    for path in expected_paths:
        for endpoint in index["endpoints"]:
            props = as_dict(endpoint.get("properties"))
            actual = str(props.get("path") or "")
            if actual == path or actual.startswith(path.rstrip("/") + "/") or path.rstrip("/") == actual:
                l0_present = True
                matched_paths.append(actual)
                break
    typed = as_dict(unit_spec.get("typed_backbone")).get("required")
    typed_rows = []
    for requirement in as_list(typed):
        req = as_dict(requirement)
        field = str(req.get("field") or "")
        props = as_dict(unit_node.get("properties")) if unit_node is not None else {}
        value = props.get(field)
        if "expected" in req:
            ok = value == req.get("expected")
        elif req.get("non_empty"):
            ok = bool(value)
        else:
            ok = value is not None
        typed_rows.append({"field": field, "ok": bool(ok), "value": value})
    typed_present = (
        sum(1 for row in typed_rows if row["ok"]) / len(typed_rows)
        if typed_rows else None
    )
    systems_required = [
        as_dict(e) for e in as_list(
            as_dict(unit_spec.get("service_to_system_edges")).get("required"))
    ]
    systems_rows = []
    for requirement in systems_required:
        rel = str(requirement.get("rel") or "")
        target_kind = str(requirement.get("target_kind") or "")
        found = False
        for service in service_nodes:
            for link in index["out_links"].get(str(service.get("id") or ""), []):
                if str(link.get("type")) != rel:
                    continue
                target = index["by_id"].get(str(link.get("target") or ""))
                if target is None:
                    continue
                props = as_dict(target.get("properties"))
                if target_kind and norm(props.get("kind")) != norm(target_kind):
                    continue
                found = True
        systems_rows.append({"rel": rel, "target_kind": target_kind, "ok": found})
    systems_present = (
        sum(1 for row in systems_rows if row["ok"]) / len(systems_rows)
        if systems_rows else None
    )
    core = [1.0 if present else 0.0, 1.0 if l0_present else 0.0, 1.0 if link_present else 0.0]
    enriched = core + [
        1.0 if typed_present is None else typed_present,
        1.0 if systems_present is None else systems_present,
    ]
    return {
        "unit_identity": identity["expected_id"],
        "unit_kind": identity["kind"],
        "unit_present": present,
        "l0_present": l0_present,
        "link_present": link_present,
        "typed_present": typed_present,
        "systems_present": systems_present,
        "core_score": round(sum(core) / len(core), 4),
        "enriched_score": round(sum(enriched) / len(enriched), 4),
        "expected_paths": expected_paths,
        "matched_paths": matched_paths,
        "typed_rows": typed_rows,
        "systems_rows": systems_rows,
        "linked_endpoint_count": len(linked_endpoints),
    }


# --- hunting artifacts --------------------------------------------------------


def load_models(store: Path) -> tuple[list[dict], list[dict]]:
    models: list[dict] = []
    loops: list[dict] = []
    for family in ("produced", "consumed", "abandoned"):
        family_dir = store / family
        if not family_dir.is_dir():
            continue
        for unit_dir in sorted(p for p in family_dir.iterdir() if p.is_dir()):
            model_path = unit_dir / f"{unit_dir.name}.yaml"
            model = load_mapping(model_path)
            if model:
                model["_path"] = str(model_path)
                model["_family"] = family
                model["_unit_name"] = unit_dir.name
                models.append(model)
            for loop_path in sorted(unit_dir.glob("loop-*.yaml")):
                record = load_mapping(loop_path)
                if record:
                    record["_path"] = str(loop_path)
                    record["_family"] = family
                    record["_unit_name"] = unit_dir.name
                    loops.append(record)
    return models, loops


def resolve_model_text(model: dict) -> str:
    parts = [
        model.get("unit_id"),
        model.get("technical_sharpening"),
        model.get("trust_model"),
        model.get("assumptions"),
        model.get("vulnerabilities"),
        model.get("failure_modes"),
    ]
    return text_of(parts)


def loop_text(loop_record: dict, model: dict) -> str:
    loop = as_dict(loop_record.get("loop"))
    return text_of([
        loop_record.get("unit_id"),
        loop_record.get("likelihood"),
        loop,
        resolve_model_text(model),
    ])


def model_for_loop(loop_record: dict, models: list[dict]) -> dict:
    unit_id = str(loop_record.get("unit_id") or "")
    family = str(loop_record.get("_family") or "")
    unit_name = str(loop_record.get("_unit_name") or "")
    for model in models:
        if str(model.get("unit_id") or "") != unit_id:
            continue
        if family and str(model.get("_family") or "") != family:
            continue
        if unit_name and str(model.get("_unit_name") or "") != unit_name:
            continue
        return model
    for model in models:
        if str(model.get("unit_id") or "") == unit_id:
            return model
    return {}


def unit_match_text(text: str, identity: dict) -> bool:
    haystack = norm(text)
    if identity["expected_id"] and norm(identity["expected_id"]) in haystack:
        return True
    return any(norm(name) in haystack for name in identity["names"])


def load_specs(hunter_dir: Path) -> list[dict]:
    specs: list[dict] = []
    if not hunter_dir.is_dir():
        return specs
    for dispatch_dir in sorted(p for p in hunter_dir.iterdir() if p.is_dir()):
        for family in ("produced", "consumed", "abandoned"):
            family_dir = dispatch_dir / family
            if not family_dir.is_dir():
                continue
            for path in sorted(family_dir.glob("*.yaml")):
                spec = load_mapping(path)
                if not spec:
                    continue
                spec["_path"] = str(path)
                spec["_family"] = family
                spec["_dispatch"] = dispatch_dir.name
                specs.append(spec)
    return specs


def spec_text(spec: dict) -> str:
    return text_of(spec)


def spec_metrics(spec: dict, vuln: dict, identity: dict) -> dict:
    target = as_dict(spec.get("target_identity"))
    provenance = as_dict(spec.get("provenance"))
    unit_id = str(target.get("unit_id") or provenance.get("unit_id") or "")
    class_text = text_of([
        provenance.get("canonical_class"),
        provenance.get("web_vulnerability_class"),
        provenance.get("fault"),
        provenance.get("loop_id"),
        spec.get("rationale"),
        spec.get("assumptions"),
        spec.get("verification_symptoms"),
        as_dict(spec.get("target_identity")).get("url"),
    ])
    unit_match = unit_match_text(unit_id, identity)
    class_match = class_matches(class_text, vuln.get("type", ""), identity.get("fault_class", ""))
    required = ("target_identity", "verification_symptoms", "assumptions", "rationale", "provenance")
    present = sum(1 for key in required if key in spec)
    retired = [key for key in ("testing_pattern", "payload_vector_space", "interpretation_guidance") if key in spec]
    procedures = as_dict(provenance.get("skill_procedure"))
    procedure_fields = (
        "recon_action", "bypass_technique", "technology_grounding", "pro_tips",
        "advanced_technique", "preliminary_chaining", "interpretation_pitfalls",
    )
    procedure_count = sum(1 for field in procedure_fields if procedures.get(field))
    symptoms = [str(s) for s in as_list(spec.get("verification_symptoms")) if str(s).strip()]
    generic_symptoms = all(
        norm(s).startswith(("http 200", "status 200", "non-empty", "not empty"))
        for s in symptoms
    ) if symptoms else False
    return {
        "path": spec.get("_path"),
        "spec_id": Path(str(spec.get("_path") or "")).stem,
        "dispatch": spec.get("_dispatch"),
        "family": spec.get("_family"),
        "status": spec.get("status"),
        "unit_id": unit_id,
        "unit_match": unit_match,
        "class_match": class_match,
        "candidate": bool(unit_match and class_match),
        "class_candidate": class_match,
        "required_present": present,
        "required_total": len(required),
        "retired_fields": retired,
        "procedure_fields": procedure_count,
        "procedure_total": len(procedure_fields),
        "symptom_count": len(symptoms),
        "generic_symptoms": generic_symptoms,
        "skills": as_list(spec.get("skills")),
    }


def load_pods(pod_dir: Path) -> list[dict]:
    pods: list[dict] = []
    if not pod_dir.is_dir():
        return pods
    for spec_dir in sorted(p for p in pod_dir.iterdir() if p.is_dir()):
        exports: list[dict] = []
        for path in sorted(spec_dir.glob("*.yaml")):
            data = load_mapping(path)
            if data and "verdict" in data:
                data["_path"] = str(path)
                data["_spec_dir"] = spec_dir.name
                exports.append(data)
        variants = []
        variant_dir = spec_dir / "variants"
        if variant_dir.is_dir():
            variants = [p.name for p in sorted(variant_dir.glob("*.yaml"))]
        experiments = []
        exp_dir = spec_dir / "experiment-log"
        if exp_dir.is_dir():
            experiments = [p.name for p in sorted(exp_dir.glob("*.yaml"))]
        if exports or variants or experiments:
            pods.append({
                "spec_dir": spec_dir.name,
                "exports": exports,
                "variant_count": len(variants),
                "experiment_count": len(experiments),
                "confirmed": sum(
                    1 for e in exports
                    if str(e.get("verdict")) == "successful"
                    and str(as_dict(e.get("evidence")).get("terminal_reason")) == "symptom-confirmed"
                ),
            })
    return pods


# --- official records ---------------------------------------------------------


def load_verdicts(path: Path) -> list[dict]:
    rows = load_list(path)
    return [as_dict(r) for r in rows if isinstance(r, dict)]


def token_summary(trial: dict) -> dict:
    spectrum = as_dict(trial.get("token_spectrum"))
    usage = as_dict(trial.get("usage"))
    by_agent_usage = as_dict(usage.get("by_agent"))
    agents: dict[str, dict] = {}
    for agent, row in {**by_agent_usage, **spectrum}.items():
        row = as_dict(row)
        agents[str(agent)] = {
            "visible": row.get("visible"),
            "reasoning": row.get("reasoning"),
            "cached_input": row.get("cached_input"),
            "uncached_input": row.get("uncached_input"),
            "generated": row.get("generated"),
            "total": row.get("total"),
            "capped": row.get("capped"),
            "calls": row.get("calls"),
            "cache_detail_omitted": row.get("cache_detail_omitted"),
        }
    total_capped = sum(
        int(row.get("capped") or 0) for row in agents.values()
    ) if agents else None
    total_generated = sum(
        int(row.get("generated") or 0) for row in agents.values()
    ) if agents else None
    total_uncached = sum(
        int(row.get("uncached_input") or 0) for row in agents.values()
    ) if agents else None
    total_cached = sum(
        int(row.get("cached_input") or 0) for row in agents.values()
    ) if agents else None
    return {
        "spent_tokens": trial.get("spent_tokens"),
        "spend_baseline": trial.get("spend_baseline"),
        "spend_overshoot": trial.get("spend_overshoot"),
        "token_budget": trial.get("token_budget"),
        "usage": usage,
        "agents": agents,
        "total_capped": total_capped,
        "total_generated": total_generated,
        "total_uncached_input": total_uncached,
        "total_cached_input": total_cached,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", required=True, help="trial directory holding trial.yaml")
    parser.add_argument("--data-root", required=True, help="the instance app data root")
    parser.add_argument("--corpus", required=True, help="the private ground-truth corpus root")
    parser.add_argument("--target", required=True, help="the WebExploitBench target")
    parser.add_argument("--ground-truth", required=True, help="the WebExploitBench target directory")
    parser.add_argument("--api", default=os.environ.get("PH_API", "http://localhost:8080"))
    parser.add_argument("--graph", help="optional graph JSON path; otherwise read the API")
    parser.add_argument("--out", help="output path; default <trial>/metrics.yaml")
    args = parser.parse_args()

    trial_dir = Path(args.trial)
    trial = load_mapping(trial_dir / "trial.yaml")
    if not trial:
        print(f"measure_utm: no trial.yaml in {trial_dir}", file=sys.stderr)
        return 2
    project_id = str(trial.get("project_id") or "")
    if not project_id:
        print("measure_utm: trial record has no project_id", file=sys.stderr)
        return 2

    ground_truth = load_challenge(Path(args.ground_truth))
    corpus_target = Path(args.corpus) / args.target
    verdicts = load_verdicts(trial_dir / "verdicts.yaml")
    diagnoses = load_verdicts(trial_dir / "diagnoses.yaml")

    graph = load_mapping(Path(args.graph)) if args.graph else api_get(args.api, f"/projects/{project_id}/graph")
    index = graph_index(as_dict(graph))

    project_root = Path(args.data_root) / project_id / "hunting"
    models, loops = load_models(project_root / "threat_modeller")
    specs = load_specs(project_root / "hunter" / "test-specs")
    pods = load_pods(project_root / "test-executor-pod")

    per_vuln: list[dict] = []
    for vuln in ground_truth:
        unit_spec = load_corpus_unit(corpus_target, vuln["vuln_id"])
        identity = unit_identity(unit_spec) if unit_spec else {
            "kind": "", "slug": "", "aliases": [], "sys_kind": "", "discriminator": "",
            "expected_id": "", "names": set(), "fault_class": "",
            "location": vuln.get("location", ""),
        }
        graph_metrics = unit_metrics(index, unit_spec) if unit_spec else {}
        loop_rows = []
        for loop_record in loops:
            model = model_for_loop(loop_record, models)
            candidate_text = loop_text(loop_record, model)
            unit_match = unit_match_text(text_of(loop_record.get("unit_id")), identity)
            class_match = class_matches(candidate_text, vuln.get("type", ""), identity.get("fault_class", ""))
            # Keep a class-level row even when the model bound a different L1
            # unit: the artifact exists and the class is the benchmark's, so
            # zeroing it hides real work behind a unit-identity miss.
            if unit_match or class_match:
                loop_rows.append({
                    "path": loop_record.get("_path"),
                    "unit_id": loop_record.get("unit_id"),
                    "dispatch_id": loop_record.get("dispatch_id"),
                    "likelihood": loop_record.get("likelihood"),
                    "unit_match": unit_match,
                    "class_match": class_match,
                    "candidate": bool(unit_match and class_match),
                    "class_candidate": class_match,
                    "web_vulnerability_class": as_dict(loop_record.get("loop")).get("web_vulnerability_class"),
                    "canonical_class": as_dict(loop_record.get("loop")).get("canonical_class"),
                })
        spec_rows = []
        for spec in specs:
            row = spec_metrics(spec, vuln, identity)
            if row["unit_match"] or row.get("class_match"):
                spec_rows.append(row)
        pod_rows = []
        for pod in pods:
            spec_dir = str(pod.get("spec_dir") or "")
            if any(
                spec_dir == str(row.get("spec_id") or "")
                or spec_dir == str(row.get("dispatch") or "")
                for row in spec_rows
                if row.get("candidate") or row.get("class_candidate")
            ):
                pod_rows.append(pod)
        verdict = next((v for v in verdicts if str(v.get("vuln_id")) == vuln["vuln_id"]), {})
        diagnosis = next((d for d in diagnoses if str(d.get("vuln")) == vuln["vuln_id"]), {})
        per_vuln.append({
            "vuln_id": vuln["vuln_id"],
            "type": vuln.get("type", ""),
            "location": vuln.get("location", ""),
            "scoring": vuln.get("scoring", []),
            "unit_spec_present": bool(unit_spec),
            "unit_expected": identity.get("expected_id"),
            "fault_class": identity.get("fault_class"),
            "graph": graph_metrics,
            "loops": loop_rows,
            "loop_candidate": any(row["candidate"] for row in loop_rows),
            "loop_unit_candidate": any(row["unit_match"] for row in loop_rows),
            "loop_class_candidate": any(row.get("class_candidate") for row in loop_rows),
            "specs": spec_rows,
            "spec_candidate": any(row["candidate"] for row in spec_rows),
            "spec_unit_candidate": any(row["unit_match"] for row in spec_rows),
            "spec_class_candidate": any(row.get("class_candidate") for row in spec_rows),
            "pods": pod_rows,
            "pod_run": bool(pod_rows),
            "pod_confirmed": any(int(p.get("confirmed") or 0) > 0 for p in pod_rows),
            "verdict": verdict,
            "diagnosis": diagnosis,
        })

    gt_total = len(per_vuln)
    identified = sum(1 for v in per_vuln if str(as_dict(v.get("verdict")).get("identified")) == "identified")
    partial = sum(1 for v in per_vuln if str(as_dict(v.get("verdict")).get("identified")) == "partial")
    missed = sum(1 for v in per_vuln if str(as_dict(v.get("verdict")).get("identified")) == "missed")
    core_floor = sum(
        1 for v in per_vuln
        if as_dict(v.get("graph")).get("core_score") is not None
        and float(as_dict(v.get("graph")).get("core_score")) >= 0.3
    )
    full_core = sum(
        1 for v in per_vuln
        if all(bool(as_dict(v.get("graph")).get(key)) for key in ("unit_present", "l0_present", "link_present"))
    )
    loops_all = [row for v in per_vuln for row in as_list(v.get("loops"))]
    specs_all = [row for v in per_vuln for row in as_list(v.get("specs"))]
    pods_all = [row for v in per_vuln for row in as_list(v.get("pods"))]
    mapped_spec_ids = {
        str(row.get("spec_id") or "")
        for v in per_vuln
        for row in as_list(v.get("specs"))
        if row.get("candidate")
    }
    confirmed_pods = [p for p in pods if int(p.get("confirmed") or 0) > 0]
    confirmed_non_gt = sum(
        1 for pod in confirmed_pods
        if str(pod.get("spec_dir") or "") not in mapped_spec_ids
    )
    metrics = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "trial": {
            "trial_id": trial.get("trial_id"),
            "target_id": trial.get("target_id"),
            "project_id": project_id,
            "terminal": trial.get("terminal"),
            "started_at": trial.get("started_at"),
            "finished_at": trial.get("finished_at"),
            "eval_sha": trial.get("eval_sha"),
            "stack_fingerprint": trial.get("stack_fingerprint"),
            "token_budget": trial.get("token_budget"),
        },
        "counts": {
            "gt_total": gt_total,
            "identified": identified,
            "partial": partial,
            "missed": missed,
            "loop_candidates": sum(1 for v in per_vuln if v.get("loop_candidate")),
            "loop_unit_candidates": sum(1 for v in per_vuln if v.get("loop_unit_candidate")),
            "loop_class_candidates": sum(1 for v in per_vuln if v.get("loop_class_candidate")),
            "spec_candidates": sum(1 for v in per_vuln if v.get("spec_candidate")),
            "spec_unit_candidates": sum(1 for v in per_vuln if v.get("spec_unit_candidate")),
            "spec_class_candidates": sum(1 for v in per_vuln if v.get("spec_class_candidate")),
            "pod_runs": sum(1 for v in per_vuln if v.get("pod_run")),
            "pod_confirmed": sum(1 for v in per_vuln if v.get("pod_confirmed")),
            "confirmed_non_gt": confirmed_non_gt,
            "core_floor": core_floor,
            "full_core": full_core,
            "loops_total": len(loops),
            "specs_total": len(specs),
            "pods_total": len(pods),
            "loop_rows_matched": len(loops_all),
            "spec_rows_matched": len(specs_all),
            "pod_rows_matched": len(pods_all),
        },
        "rates": {
            "identification_rate": round(identified / gt_total, 4) if gt_total else None,
            "partial_or_identified_rate": round((identified + partial) / gt_total, 4) if gt_total else None,
            "loop_candidate_recall": round(sum(1 for v in per_vuln if v.get("loop_candidate")) / gt_total, 4) if gt_total else None,
            "spec_candidate_recall": round(sum(1 for v in per_vuln if v.get("spec_candidate")) / gt_total, 4) if gt_total else None,
            "core_floor_rate": round(core_floor / gt_total, 4) if gt_total else None,
            "full_core_rate": round(full_core / gt_total, 4) if gt_total else None,
        },
        "tokens": token_summary(trial),
        "per_vuln": per_vuln,
        "artifact_inventory": {
            "models": [
                {
                    "unit_id": m.get("unit_id"),
                    "state": m.get("state"),
                    "family": m.get("_family"),
                    "path": m.get("_path"),
                    "loops": len(as_list(m.get("loops"))),
                    "validation": as_dict(m.get("validation")),
                }
                for m in models
            ],
            "loops": len(loops),
            "specs": len(specs),
            "pods": len(pods),
        },
        "sources": {
            "trial_record": str(trial_dir / "trial.yaml"),
            "verdicts": str(trial_dir / "verdicts.yaml"),
            "diagnoses": str(trial_dir / "diagnoses.yaml"),
            "corpus": str(corpus_target),
            "ground_truth": str(args.ground_truth),
            "graph": str(args.graph) if args.graph else f"{args.api}/projects/{project_id}/graph",
            "data_root": str(Path(args.data_root) / project_id),
        },
    }
    out = Path(args.out) if args.out else trial_dir / "metrics.yaml"
    out.write_text(yaml.safe_dump(metrics, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "counts": metrics["counts"],
        "rates": metrics["rates"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
