#!/usr/bin/env python3
"""Poll one iteration C trial: usage, impact rows, promotion, batch width.

Read-only. Writes one JSON line per poll to MONITOR_OUT.
The checks are observational: a violation is recorded, never repaired.

Iteration C changes what the run produces, so the monitor tracks four things
iteration B did not:

- `impact_rows` and the CIA red/green split from every consumed or produced
  unit model;
- the promotion split: stored threats at or above the floor versus demoted
  ones still sitting in `produced/`;
- the live hunt count against `pod_batch_size`, because the batched pipeline now
  dispatches three hunts' pods together;
- the cumulative risk against the 180 halt.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import time
import urllib.request

import yaml

API = os.environ.get("PH_API", "http://localhost:8080").rstrip("/")
DATA = pathlib.Path(os.environ.get(
    "MONITOR_DATA_ROOT",
    "/opt/polymerhus-dev/eval/instances/data/eval-server-1",
))
OUT = pathlib.Path(os.environ.get(
    "MONITOR_OUT",
    "/opt/polymerhus-dev/eval/runs-iteration-c-20261026/monitor.jsonl",
))
SINCE = os.environ.get("MONITOR_SINCE") or dt.datetime.now(
    dt.timezone.utc).isoformat()
PROJECT_NAME = os.environ.get("MONITOR_PROJECT_NAME", "eval-white-jotter-1")
INTERVAL_S = int(os.environ.get("MONITOR_INTERVAL_S", "120"))
POD_BATCH_SIZE = int(os.environ.get("MONITOR_POD_BATCH_SIZE", "3"))
PROMOTION_FLOOR = int(os.environ.get("MONITOR_PROMOTION_FLOOR", "0"))

CIA_KEYS = ("confidentiality", "integrity", "availability")


def get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=10) as response:
        return json.load(response)


def load_yaml(path: pathlib.Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def find_project() -> tuple[str | None, str | None]:
    projects = get("/projects").get("projects", [])
    candidates = [
        item for item in projects
        if item.get("name") == PROJECT_NAME
        and (item.get("created_at") or "") >= SINCE
    ]
    if not candidates:
        return None, None
    chosen = max(candidates, key=lambda item: item.get("created_at") or "")
    return chosen.get("project_id"), chosen.get("created_at")


def unit_models(root: pathlib.Path) -> list[pathlib.Path]:
    """Every unit model, whether it is still produced or already consumed."""
    models: list[pathlib.Path] = []
    for stage in ("produced", "consumed", "abandoned"):
        for directory in sorted((root / "hunting/threat_modeller" / stage).glob("*")):
            if not directory.is_dir():
                continue
            for path in directory.glob("*.yaml"):
                if path.name.startswith("threat-"):
                    continue
                models.append(path)
    return models


def impact_summary(model: dict) -> dict:
    """The CIA red/green split over one model's impact-assessment rows."""
    # The join is the threat's `impact_ref`: several threats share one
    # vulnerability, so a vulnerability-keyed map would double-count.
    threats = {
        str(row.get("impact_ref") or ""): (row.get("impact") or {})
        for row in (model.get("threats") or [])
        if isinstance(row, dict) and row.get("impact_ref")
    }
    rows = [row for row in (model.get("impact_assessment") or [])
            if isinstance(row, dict)]
    distribution: dict[str, dict[str, int]] = {key: {} for key in CIA_KEYS}
    green = 0
    threat_rows = 0
    placeholders = 0
    for row in rows:
        disposition = str(row.get("disposition") or "")
        ref = str(row.get("vulnerability_ref") or "")
        impact = threats.get(str(row.get("id") or "")) or {}
        vector = {key: str(impact.get(key) or "none") for key in CIA_KEYS}
        for key in CIA_KEYS:
            level = vector[key]
            distribution[key][level] = distribution[key].get(level, 0) + 1
        damage_bearing = any(level != "none" for level in vector.values())
        if damage_bearing:
            green += 1
        if disposition == "threat":
            threat_rows += 1
        elif disposition == "placeholder":
            placeholders += 1
    return {
        "rows": len(rows),
        "green": green,
        "red": len(rows) - green,
        "threats": threat_rows,
        "placeholders": placeholders,
        "cia": distribution,
    }


def promotion_summary(root: pathlib.Path) -> dict:
    """Stored threats versus the ones a hunter can see.

    A threat is demoted when its risk is below the floor; with the control-arm
    floor of 0 nothing is demoted, so a non-zero demoted count would mean the
    filter or the risk scoring drifted.
    """
    stored: list[tuple[str, int]] = []
    model_dir = root / "hunting/threat_modeller"
    for stage in ("produced", "consumed"):
        for path in sorted((model_dir / stage).glob("*/threat-*.yaml")):
            data = load_yaml(path)
            body = data.get("threat") or {}
            stored.append((
                str(body.get("web_vulnerability_class") or ""),
                int(body.get("risk") or 0),
            ))
    if PROMOTION_FLOOR <= 0:
        demoted = 0
    else:
        demoted = sum(1 for _, risk in stored if risk < PROMOTION_FLOOR)
    return {
        "stored": len(stored),
        "promoted": len(stored) - demoted,
        "demoted": demoted,
        "promotion_floor": PROMOTION_FLOOR,
        "risk_total": sum(risk for _, risk in stored),
    }


def pod_terminals(root: pathlib.Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    pod_root = root / "hunting/test-executor-pod"
    if not pod_root.is_dir():
        return counts
    for path in pod_root.glob("*/*.yaml"):
        if path.name.endswith(".resume.yaml") or path.name == "notes.yaml":
            continue
        data = load_yaml(path)
        reason = str((data.get("evidence") or {}).get("terminal_reason") or "none")
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    last_poll = time.time()
    project_id = None
    while True:
        polled = time.time()
        row: dict = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "since": SINCE,
        }
        try:
            found, created = find_project()
            if found:
                project_id = found
                row["project_id"] = project_id
                row["project_created_at"] = created
            if project_id:
                pid = project_id
                usage = get(f"/projects/{pid}/usage")
                row["capped_tokens"] = usage.get("capped_tokens")
                row["total_tokens"] = usage.get("total_tokens")
                row["calls"] = usage.get("calls")
                row["by_agent_capped"] = {
                    key: value.get("capped_tokens")
                    for key, value in (usage.get("by_agent") or {}).items()
                }
                root = DATA / pid
                rows = []
                distribution: dict[str, dict[str, int]] = {key: {} for key in CIA_KEYS}
                model_paths = unit_models(root)
                in_flight = 0
                for path in model_paths:
                    model = load_yaml(path)
                    # The CIA vector lands with the threats at COMPLETED, so an
                    # earlier gate would read as a red row and understate the
                    # share. Only complete models score.
                    if str(model.get("state") or "") != "COMPLETED":
                        in_flight += 1
                        continue
                    summary = impact_summary(model)
                    rows.append(summary)
                    for key in CIA_KEYS:
                        for level, count in summary["cia"][key].items():
                            distribution[key][level] = (
                                distribution[key].get(level, 0) + count)
                total_rows = sum(item["rows"] for item in rows)
                total_green = sum(item["green"] for item in rows)
                row["units_modelled"] = len(rows)
                row["units_in_flight"] = in_flight
                row["impact_rows"] = total_rows
                row["impact_green"] = total_green
                row["impact_red"] = total_rows - total_green
                row["impact_threats"] = sum(item["threats"] for item in rows)
                row["impact_placeholders"] = sum(
                    item["placeholders"] for item in rows)
                row["green_share"] = (
                    total_green / total_rows if total_rows else None)
                row["cia"] = distribution

                promotion = promotion_summary(root)
                row.update({
                    "threat_files": promotion["stored"],
                    "threats_promoted": promotion["promoted"],
                    "threats_demoted": promotion["demoted"],
                    "promotion_floor": promotion["promotion_floor"],
                    "threat_risk_total": promotion["risk_total"],
                })

                specs = [
                    path for path in root.glob(
                        "hunting/hunter/test-specs/*/*/*.yaml")
                    if path.name != "terminal.yaml"
                ]
                hunts = [
                    path for path in root.glob(
                        "hunting/hunter/test-specs/*/terminal.yaml")
                ]
                row["spec_files"] = len(specs)
                row["hunt_terminals"] = len(hunts)
                pod_root = root / "hunting/test-executor-pod"
                pods = (
                    [item for item in pod_root.iterdir() if item.is_dir()]
                    if pod_root.is_dir() else []
                )
                row["pod_dirs"] = len(pods)
                row["pod_resumes"] = (
                    len(list(pod_root.glob("*/*.resume.yaml")))
                    if pod_root.is_dir() else 0)
                row["pod_exports"] = sum(pod_terminals(root).values())
                row["pod_terminals"] = pod_terminals(root)

                run_id = os.environ.get("MONITOR_HUNTING_RUN_ID")
                if not run_id:
                    # The unit model names its run as soon as the first gate
                    # lands, which is sooner than the first hunt terminal.
                    for path in model_paths:
                        run_id = str(load_yaml(path).get("run_id") or "") or None
                        if run_id:
                            break
                if not run_id:
                    for path in hunts[:1]:
                        run_id = str(load_yaml(path).get("run_id") or "") or None
                returncode = None
                if run_id:
                    row["hunting_run_id"] = run_id
                    try:
                        status = get(f"/projects/{pid}/hunting/{run_id}")
                    except Exception:
                        status = {}
                    stats = status.get("stats") or {}
                    row["hunting_status"] = status.get("status")
                    row["pipeline_sync"] = stats.get("pipeline_sync")
                    row["risk_total"] = stats.get("risk_total")
                    row["risk_threshold"] = stats.get("risk_threshold")
                    row["threshold_basis"] = stats.get("threshold_basis")
                    row["pod_batch_size"] = stats.get("pod_batch_size")
                    row["promotion_risk_threshold"] = stats.get(
                        "promotion_risk_threshold")
                    row["halt"] = stats.get("halt")
                    row["crossing_unit"] = stats.get("crossing_unit")
                    row["blocked_unit"] = stats.get("blocked_unit")
                    row["model_sums"] = [
                        (item.get("unit_id"), item.get("total"))
                        for item in (stats.get("model_sums") or [])
                    ]
                    live = stats.get("live_hunts") or []
                    row["live_hunts"] = live
                    row["live_hunt_count"] = len(live)
                    row["live_units"] = stats.get("live_units") or []
                    row["batch_within_width"] = len(live) <= POD_BATCH_SIZE
                    row["sync_one_unit"] = len(row["live_units"]) <= 1
        except Exception as exc:  # noqa: BLE001 - a poll must never kill the loop
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["elapsed_s"] = round(polled - last_poll, 1)
        last_poll = polled
        with OUT.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
