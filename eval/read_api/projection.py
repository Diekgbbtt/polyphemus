"""Project the materialized artifact store into the eval snapshot (#278).

The store's authoritative trees are `<store>/<target_id>/<target_run_id>/<trial_id>/`
(see `orchestrator.store`). This module reads *only* those trees: each trial's
`run-manifest.yaml` (identity + phases), `verdicts.yaml` (every verdict), and
`diagnoses.yaml` (the paired partial/missed diagnoses). Everything outside the
authoritative trees - the `_sync/` deploy dir, the `live/` mirror, any loose
file - is ignored.

The projection is total: a missing or malformed artifact degrades that one trial
(a safe, path-free record) instead of failing the whole report, and a defect in
the diagnoses/evidence degrades only the trial it belongs to. Nothing host-only
ever reaches the output: only allowlisted fields are emitted, evidence is kept
only when it is a valid relative, path-safe reference, and free text carrying an
absolute-path-looking token is dropped. PyYAML is the one third-party
dependency; import performs no I/O.
"""
from __future__ import annotations

import os
import stat
from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

MANIFEST_FILENAME = "run-manifest.yaml"
VERDICTS_FILENAME = "verdicts.yaml"
DIAGNOSES_FILENAME = "diagnoses.yaml"

# The lightweight project-snapshot statuses the dashboard consumes.
ARTIFACTS_AVAILABLE = "available"
GRAPH_AVAILABLE = "available"
ARTIFACTS_UNAVAILABLE = "project_artifacts_unavailable"
GRAPH_UNAVAILABLE = "project_graph_unavailable"
SNAPSHOT_UNAVAILABLE = "project_snapshot_unavailable"
STORE_SCHEMA_V2 = 2
# Where a projected Trial's data came from: the materialized store tree, or the
# authoritative record the harness wrote under a runs root (not yet copied).
STORAGE_MATERIALIZED = "materialized"
STORAGE_RUN_RECORD = "run_record"
# The independent results availability of each results file.
RESULTS_AVAILABLE = "available"
RESULTS_UNAVAILABLE = "unavailable"
_ARTIFACT_CATEGORIES = ("hunting", "skill")
# The non-authoritative siblings the store also contains (D7/D12, project
# artifacts): the rendered deploy dir, the raw one-way live mirror, and the
# materializer's `_staging/` scratch trees. Never an input to the report.
SKIP_DIRNAMES = frozenset({"_sync", "live", "_staging"})

DEFAULT_DATASET_ID = "webexploitbench"
DEFAULT_DATASET_NAME = "WebExploitBench"

# The full verdict vocabulary; only `identified` is a success, but every value
# is preserved on the trial so the UI can show partial/missed work honestly.
VERDICT_VALUES = ("identified", "partial", "missed")
# D20: a partial/missed verdict must be paired with a diagnosis entry.
DIAGNOSABLE = ("partial", "missed")
# The deduplicated coverage precedence: a vuln's best verdict across the trials
# of one Target wins (identified > partial > missed).
_PRECEDENCE = {"identified": 3, "partial": 2, "missed": 1}

MAX_TEXT = 2000
MAX_REF = 512
# Matched labels ("unit", "fault_class", "symptom") are short display values.
MAX_LABEL = 512

# Display fields are human-readable prose or labels, never filesystem
# references. They legitimately name HTTP routes (`/view`, `/userdata`,
# `/api/v1/items`), so a leading slash is not by itself a leak - it is one only
# when the token is a filesystem location: a `..` traversal, an UNC path, a
# known system/home root, or a path with a file extension.
HOST_PATH_ROOTS = frozenset(
    {
        "Applications",
        "Library",
        "System",
        "Users",
        "Volumes",
        "bin",
        "boot",
        "dev",
        "etc",
        "home",
        "lib",
        "lib64",
        "media",
        "mnt",
        "opt",
        "proc",
        "root",
        "run",
        "sbin",
        "srv",
        "sys",
        "tmp",
        "usr",
        "var",
    }
)
FILE_SUFFIXES = frozenset(
    {
        "bin",
        "cfg",
        "conf",
        "csv",
        "env",
        "gz",
        "ini",
        "jpeg",
        "jpg",
        "json",
        "log",
        "md",
        "md5",
        "parquet",
        "pem",
        "png",
        "py",
        "pyc",
        "sh",
        "so",
        "sqlite",
        "tar",
        "toml",
        "ts",
        "tsx",
        "txt",
        "whl",
        "xml",
        "xz",
        "yaml",
        "yml",
        "zip",
    }
)

_INVALID = object()


def build_snapshot(
    store: str | Path,
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    dataset_name: str = DEFAULT_DATASET_NAME,
) -> dict[str, Any]:
    """A complete, deterministic, JSON-serializable report of the store."""
    return assemble_snapshot(
        project_store_trials(store),
        dataset_id=dataset_id,
        dataset_name=dataset_name,
    )


def project_store_trials(store: str | Path) -> list[dict[str, Any]]:
    """Every materialized Trial tree under `store`, projected (never raises)."""
    root = Path(store)
    trials: list[dict[str, Any]] = []
    for target_dir in _child_dirs(root):
        for run_dir in _child_dirs(target_dir):
            for trial_dir in _child_dirs(run_dir):
                trials.append(
                    _read_trial(
                        trial_dir,
                        default_target_id=target_dir.name,
                        default_target_run_id=run_dir.name,
                    )
                )
    return trials


def assemble_snapshot(
    trials: list[dict[str, Any]],
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    dataset_name: str = DEFAULT_DATASET_NAME,
) -> dict[str, Any]:
    """Aggregate already-projected Trial records into the full report.

    The catalogue's union (store + runs roots) is aggregated here, so every
    derived section - targets, summary, versions, coverage, successes and the
    degraded list - is recomputed coherently after the merge.
    """
    trials = sorted(
        trials, key=lambda t: (t["target_id"], t["target_run_id"], t["trial_id"])
    )
    successes: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    trial_counts: Counter[str] = Counter()
    identified_counts: Counter[str] = Counter()
    partial_counts: Counter[str] = Counter()
    missed_counts: Counter[str] = Counter()

    for record in trials:
        target_id = record["target_id"]
        trial_counts[target_id] += 1
        counts = Counter(row["identified"] for row in record["verdicts"])
        identified_counts[target_id] += counts["identified"]
        partial_counts[target_id] += counts["partial"]
        missed_counts[target_id] += counts["missed"]
        if record["availability"] == "degraded":
            degraded.append(
                {
                    key: record[key]
                    for key in ("target_id", "target_run_id", "trial_id", "reason")
                }
            )
            continue
        for row in record["verdicts"]:
            if row["identified"] == "identified":
                successes.append(_success_row(record, row))

    successes.sort(
        key=lambda r: (r["target_id"], r["target_run_id"], r["trial_id"], r["vuln_id"])
    )
    degraded.sort(
        key=lambda d: (d["target_id"], d["target_run_id"], d["trial_id"], d["reason"] or "")
    )

    targets = [
        {
            "target_id": target_id,
            "trial_count": trial_counts[target_id],
            "identified_count": identified_counts[target_id],
            "partial_count": partial_counts[target_id],
            "missed_count": missed_counts[target_id],
        }
        for target_id in sorted(trial_counts)
    ]
    return {
        "dataset": {"id": dataset_id, "name": dataset_name},
        "summary": {
            "targets": len(targets),
            "trials": len(trials),
            "identified": len(successes),
            "partial": sum(partial_counts.values()),
            "missed": sum(missed_counts.values()),
            "degraded": len(degraded),
        },
        "targets": targets,
        "trials": trials,
        "versions": _versions(trials),
        "coverage": _coverage(trials),
        "successes": successes,
        "degraded_trials": degraded,
    }


# --- one trial -----------------------------------------------------------------


def _read_trial(
    trial_dir: Path,
    *,
    default_target_id: str,
    default_target_run_id: str,
    storage_source: str = STORAGE_MATERIALIZED,
) -> dict[str, Any]:
    """Read one trial tree into an allowlisted record (never raises)."""
    manifest_path = trial_dir / MANIFEST_FILENAME
    manifest = _load_mapping(manifest_path)
    if manifest is None:
        reason = "manifest_missing" if not manifest_path.exists() else "manifest_invalid"
        return _record(
            default_target_id,
            default_target_run_id,
            trial_dir.name,
            reason=reason,
            storage_source=storage_source,
            results_availability=_unavailable_results(reason),
        )

    target_id = _safe_id(manifest.get("target_id")) or default_target_id
    target_run_id = _safe_id(manifest.get("target_run_id")) or default_target_run_id
    trial_id = _safe_id(manifest.get("trial_id")) or trial_dir.name
    eval_sha = _safe_id(manifest.get("eval_sha"))
    stack_fingerprint = _safe_id(manifest.get("stack_fingerprint"))
    meta = _metadata(manifest)
    artifact_summary, project_graph_summary = _project_summaries(manifest)
    if not eval_sha or not stack_fingerprint:
        return _record(
            target_id,
            target_run_id,
            trial_id,
            reason="identity_missing",
            meta=meta,
            artifact_summary=artifact_summary,
            project_graph_summary=project_graph_summary,
            storage_source=storage_source,
            results_availability=_unavailable_results("identity_missing"),
        )

    identity = {
        "eval_sha": eval_sha,
        "stack_fingerprint": stack_fingerprint,
        "meta": meta,
        "artifact_summary": artifact_summary,
        "project_graph_summary": project_graph_summary,
    }
    verdicts, verdicts_availability, verdict_defect = _read_verdicts(trial_dir)
    diagnoses, diagnoses_availability, diagnosis_defect = _read_diagnoses(
        trial_dir,
        verdicts,
        verdicts_available=verdicts_availability["status"] == RESULTS_AVAILABLE,
    )
    defect = verdict_defect or diagnosis_defect

    return _record(
        target_id,
        target_run_id,
        trial_id,
        availability="degraded" if defect else "complete",
        reason=defect,
        verdicts=verdicts,
        diagnoses=diagnoses,
        **identity,
        storage_source=storage_source,
        results_availability=_results_block(
            verdicts_availability, diagnoses_availability
        ),
    )


def _read_verdicts(
    trial_dir: Path, *, strict: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """Every valid verdict row, plus its availability and any defect code.

    A missing file is `unavailable`; a present file is `available` even when it
    is empty or carries an unusable row (in which case the valid siblings are
    kept and the Trial reports the stable defect). With `strict`, only a regular
    non-symlink file counts, so an unmaterialized Trial never follows a link out
    of its own record directory.
    """
    path = trial_dir / VERDICTS_FILENAME
    if not _present(path, strict=strict):
        return [], _availability(RESULTS_UNAVAILABLE, "verdicts_missing"), "verdicts_missing"
    payload = _load_payload(path)
    if payload is _INVALID or not isinstance(payload, list):
        return [], _availability(RESULTS_UNAVAILABLE, "verdicts_invalid"), "verdicts_invalid"

    verdicts: list[dict[str, Any]] = []
    defect: str | None = None
    for raw in payload:
        status, row = _parse_verdict(raw)
        if status == "invalid":
            # One unusable row never erases its valid siblings: they are kept
            # and the Trial reports this stable reason.
            defect = "verdict_invalid"
            continue
        if status == "ok":
            verdicts.append(row)
    verdicts.sort(key=lambda row: row["vuln_id"])
    return verdicts, _availability(RESULTS_AVAILABLE, None), defect


def _read_diagnoses(
    trial_dir: Path,
    verdicts: list[dict[str, Any]],
    *,
    verdicts_available: bool = True,
    strict: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """The valid diagnoses, plus its availability and any defect code.

    Availability is independent of the verdicts: a present diagnoses file is
    `available` even when every verdicts file is missing. When the verdicts are
    available, a partial/missed verdict still demands a paired entry; when they
    are not, the rows are read structurally without inventing a pairing.
    """
    required = (
        {row["vuln_id"] for row in verdicts if row["identified"] in DIAGNOSABLE}
        if verdicts_available
        else set()
    )
    path = trial_dir / DIAGNOSES_FILENAME
    if not _present(path, strict=strict):
        defect = "diagnoses_missing" if required else None
        return [], _availability(RESULTS_UNAVAILABLE, "diagnoses_missing"), defect
    payload = _load_payload(path)
    if payload is _INVALID or not isinstance(payload, list):
        return [], _availability(RESULTS_UNAVAILABLE, "diagnoses_invalid"), "diagnoses_invalid"
    parsed, defect = _parse_diagnoses(
        payload, required, gate_on_required=verdicts_available
    )
    return parsed, _availability(RESULTS_AVAILABLE, None), defect


def _parse_verdict(raw: object) -> tuple[str, dict[str, Any] | None]:
    """`(status, row)` with status `ok`, `skip`, or `invalid` (degrade the trial)."""
    if not isinstance(raw, Mapping):
        return "skip", None
    identified = raw.get("identified")
    if identified not in VERDICT_VALUES:
        return "skip", None
    vuln_id = _safe_id(raw.get("vuln_id"))
    confidence = raw.get("confidence")
    if (
        not vuln_id
        or isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.0 <= float(confidence) <= 1.0
    ):
        return "invalid", None

    matched = raw.get("matched")
    unit = fault_class = symptom = None
    if matched is not None:
        if not isinstance(matched, Mapping):
            return "invalid", None
        unit = _safe_display_text(matched.get("unit"), limit=MAX_LABEL)
        fault_class = _safe_display_text(matched.get("fault_class"), limit=MAX_LABEL)
        symptom = _safe_display_text(matched.get("symptom"), limit=MAX_LABEL)
    # A positive verdict must name all three; a `missed` row describes no match.
    if identified != "missed" and not (unit and fault_class and symptom):
        return "invalid", None

    evidence, ok = _evidence_refs(raw.get("evidence_chain"))
    if not ok:
        return "invalid", None
    return (
        "ok",
        {
            "vuln_id": vuln_id,
            "identified": identified,
            "confidence": float(confidence),
            "matched": {"unit": unit, "fault_class": fault_class, "symptom": symptom},
            "evidence": evidence,
        },
    )


def _evidence_refs(chain: object) -> tuple[list[str], bool]:
    """The path-safe relative references of an evidence chain, `(refs, ok)`."""
    if chain is None:
        return [], True
    if not isinstance(chain, Mapping):
        return [], False
    refs: list[str] = []

    def add(value: object) -> None:
        ref = _safe_ref(value)
        if ref and ref not in refs:
            refs.append(ref)

    for key in ("hunt_config", "spec_dir"):
        if chain.get(key) is not None:
            add(chain[key])
    logs = chain.get("experiment_logs")
    if logs is not None:
        if not isinstance(logs, list):
            return [], False
        for item in logs:
            add(item)
    if chain.get("pod_export") is not None:
        add(chain["pod_export"])
    return refs, True


def _parse_diagnoses(
    rows: list, required: set[str], *, gate_on_required: bool = True
) -> tuple[list[dict[str, Any]], str | None]:
    """The valid diagnoses, plus the stable reason when a row was unusable.

    A malformed row is dropped without erasing its valid siblings; the caller
    degrades the Trial. A partial/missed verdict left without any diagnosis is
    itself a defect, so the pairing rule still holds. `gate_on_required` is
    false only when the verdicts are themselves unavailable, so the rows are
    read structurally without inventing a pairing that cannot be checked.
    """
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    defect: str | None = None
    for raw in rows:
        row = _parse_diagnosis(
            raw, required=required, seen=seen, gate_on_required=gate_on_required
        )
        if row is None:
            defect = "diagnoses_invalid"
            continue
        seen.add(row["vuln"])
        parsed.append(row)
    if gate_on_required and required - seen:
        # A partial/missed verdict with no diagnosis entry is a defect.
        defect = "diagnoses_invalid"
    parsed.sort(key=lambda row: row["vuln"])
    return parsed, defect


def _parse_diagnosis(
    raw: object, *, required: set[str], seen: set[str], gate_on_required: bool = True
) -> dict[str, Any] | None:
    """One diagnosis row, or `None` when it is not a usable paired entry."""
    if not isinstance(raw, Mapping):
        return None
    vuln = _safe_id(raw.get("vuln"))
    if not vuln or vuln in seen:
        return None
    if gate_on_required and vuln not in required:
        return None

    failure_mode = _safe_id(raw.get("failure_mode"))
    root = raw.get("root_cause")
    if not failure_mode or not isinstance(root, Mapping):
        return None
    cause_type = _safe_id(root.get("type"))
    overview = _safe_display_text(raw.get("diagnosis_overview"))
    if not cause_type or not overview:
        return None
    combination = root.get("combination_of") or []
    if not isinstance(combination, list):
        return None
    combined = [_safe_id(item) for item in combination]
    if any(item is None for item in combined):
        return None

    closest = _closest_issue(raw.get("closest_issue"))
    proposed = _proposed_issue(raw.get("proposed_issue"))
    if closest is _INVALID or proposed is _INVALID:
        return None
    if (closest is None) == (proposed is None):
        # Exactly one of the two must be present.
        return None

    return {
        "vuln": vuln,
        "failure_mode": failure_mode,
        "root_cause": {
            "type": cause_type,
            "combination_of": [item for item in combined if item],
            "extended_description": _safe_display_text(root.get("extended_description")),
        },
        "diagnosis_overview": overview,
        "closest_issue": closest,
        "proposed_issue": proposed,
    }


def _closest_issue(raw: object) -> dict[str, Any] | object | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _INVALID
    repo = _safe_text(raw.get("repo"))
    title = _safe_display_text(raw.get("title"))
    rationale = _safe_display_text(raw.get("rationale"))
    number = raw.get("number")
    if not repo or not title or not rationale:
        return _INVALID
    if isinstance(number, bool) or not isinstance(number, int):
        return _INVALID
    return {"repo": repo, "number": number, "title": title, "rationale": rationale}


def _proposed_issue(raw: object) -> dict[str, Any] | object | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _INVALID
    title = _safe_display_text(raw.get("title"))
    labels = raw.get("labels") or []
    if not title or not isinstance(labels, list):
        return _INVALID
    safe_labels = [_safe_id(label) for label in labels]
    if any(label is None for label in safe_labels):
        return _INVALID
    # The free-form body is intentionally not exposed.
    return {"title": title, "labels": [label for label in safe_labels if label]}


# --- versions ------------------------------------------------------------------


def _coverage(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Benchmark coverage, deduplicated by `(target_id, vuln_id)`.

    A vuln repeated across trials counts once, keeping its best verdict
    (identified > partial > missed). A degraded trial carries no verdicts, so it
    never contributes. `partial` is an informational subset of `not_found`, not
    a third outcome.
    """
    best: dict[tuple[str, str], str] = {}
    for trial in trials:
        for verdict in trial["verdicts"]:
            key = (trial["target_id"], verdict["vuln_id"])
            current = best.get(key)
            if current is None or _PRECEDENCE[verdict["identified"]] > _PRECEDENCE[current]:
                best[key] = verdict["identified"]

    found = sum(1 for kind in best.values() if kind == "identified")
    partial = sum(1 for kind in best.values() if kind == "partial")
    tested = len({trial["target_id"] for trial in trials})
    with_identified = len(
        {target_id for (target_id, _), kind in best.items() if kind == "identified"}
    )
    return {
        "targets": {
            "tested": tested,
            "with_identified": with_identified,
            "without_identified": tested - with_identified,
        },
        "vulnerabilities": {
            "total": len(best),
            "found": found,
            "not_found": len(best) - found,
            "partial": partial,
        },
    }


def _versions(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregation keyed by the `eval_sha + stack_fingerprint` pair (D23)."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for trial in trials:
        sha, fingerprint = trial["eval_sha"], trial["stack_fingerprint"]
        if not sha or not fingerprint:
            continue
        group = groups.setdefault((sha, fingerprint), {"targets": set(), "trials": []})
        group["targets"].add(trial["target_id"])
        counts = Counter(row["identified"] for row in trial["verdicts"])
        group["trials"].append(
            {
                "target_id": trial["target_id"],
                "target_run_id": trial["target_run_id"],
                "trial_id": trial["trial_id"],
                "availability": trial["availability"],
                "identified": counts["identified"],
                "partial": counts["partial"],
                "missed": counts["missed"],
            }
        )

    versions: list[dict[str, Any]] = []
    for sha, fingerprint in sorted(groups):
        group = groups[(sha, fingerprint)]
        contrib = sorted(
            group["trials"],
            key=lambda r: (r["target_id"], r["target_run_id"], r["trial_id"]),
        )
        versions.append(
            {
                "eval_sha": sha,
                "stack_fingerprint": fingerprint,
                "targets": sorted(group["targets"]),
                "trial_count": len(contrib),
                "identified": sum(r["identified"] for r in contrib),
                "partial": sum(r["partial"] for r in contrib),
                "missed": sum(r["missed"] for r in contrib),
                "trials": contrib,
            }
        )
    return versions


# --- helpers -------------------------------------------------------------------


def _child_dirs(root: Path) -> Iterator[Path]:
    """Every non-skipped child directory, or nothing when `root` is not a dir."""
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return
    for entry in entries:
        if entry.is_dir() and entry.name not in SKIP_DIRNAMES:
            yield entry


def _load_payload(path: Path) -> object:
    """The decoded YAML, or the `_INVALID` sentinel when it cannot be read."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return _INVALID


def _load_mapping(path: Path) -> Mapping | None:
    if not path.is_file():
        return None
    payload = _load_payload(path)
    return payload if isinstance(payload, Mapping) else None


def _metadata(manifest: Mapping) -> dict[str, Any]:
    return {
        "instance_id": _safe_id(manifest.get("instance_id")),
        "project_id": _safe_id(manifest.get("project_id")),
        "start_phase": _safe_id(manifest.get("start_phase")),
        "terminal": _safe_id(manifest.get("terminal")),
        "copied_at": _safe_id(manifest.get("copied_at")),
        "phases": _phases(manifest.get("phases")),
    }


# --- lightweight project-snapshot summaries ------------------------------------


def _historical_artifact_summary() -> dict[str, Any]:
    return {"status": ARTIFACTS_UNAVAILABLE, "hunting": 0, "skills": 0}


def _historical_graph_summary() -> dict[str, Any]:
    return {"status": GRAPH_UNAVAILABLE, "nodes": 0, "links": 0, "captured_at": None}


def _snapshot_unavailable_artifact_summary() -> dict[str, Any]:
    return {"status": SNAPSHOT_UNAVAILABLE, "hunting": 0, "skills": 0}


def _snapshot_unavailable_graph_summary() -> dict[str, Any]:
    return {"status": SNAPSHOT_UNAVAILABLE, "nodes": 0, "links": 0, "captured_at": None}


def _project_summaries(manifest: Mapping) -> tuple[dict[str, Any], dict[str, Any]]:
    """The lightweight artifact/graph summaries for one manifest.

    A schema-v1 (or unversioned) manifest is a historical Trial and reports the
    two distinct unavailable statuses. A schema-v2 manifest yields `available`
    summaries only when the three sections are coherent and complete; a
    malformed or non-atomic snapshot reports `project_snapshot_unavailable` for
    both without touching the Trial's own availability or reason.
    """
    if manifest.get("schema_version") != STORE_SCHEMA_V2:
        return _historical_artifact_summary(), _historical_graph_summary()

    snapshot = manifest.get("project_snapshot")
    artifacts = manifest.get("project_artifacts")
    graph = manifest.get("project_graph")
    sections = (snapshot, artifacts, graph)
    if not all(
        isinstance(section, Mapping) and section.get("status") == "available"
        for section in sections
    ):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()

    project_id = _safe_id(manifest.get("project_id"))
    if project_id is None or any(
        section.get("project_id") != manifest.get("project_id") for section in sections
    ):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()

    captured_at = snapshot.get("captured_at")
    if not _is_text(captured_at) or any(
        section.get("captured_at") != captured_at for section in (artifacts, graph)
    ):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()

    snapshot_fingerprint = snapshot.get("snapshot_sha256")
    artifacts_fingerprint = artifacts.get("snapshot_sha256")
    if (
        not _is_text(snapshot_fingerprint)
        or snapshot_fingerprint != artifacts_fingerprint
    ):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()
    if not _is_text(graph.get("sha256")):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()

    entries = artifacts.get("entries")
    if not isinstance(entries, list) or not all(_valid_entry(entry) for entry in entries):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()
    node_count = graph.get("node_count")
    link_count = graph.get("link_count")
    if not _is_count(node_count) or not _is_count(link_count):
        return _snapshot_unavailable_artifact_summary(), _snapshot_unavailable_graph_summary()

    hunting = sum(1 for entry in entries if entry["category"] == "hunting")
    skills = sum(1 for entry in entries if entry["category"] == "skill")
    return (
        {"status": ARTIFACTS_AVAILABLE, "hunting": hunting, "skills": skills},
        {
            "status": GRAPH_AVAILABLE,
            "nodes": node_count,
            "links": link_count,
            "captured_at": captured_at,
        },
    )


def _valid_entry(entry: object) -> bool:
    if not isinstance(entry, Mapping):
        return False
    if entry.get("category") not in _ARTIFACT_CATEGORIES:
        return False
    relative = entry.get("relative_path")
    return isinstance(relative, str) and bool(relative.strip())


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _phases(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    phases: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        phases.append(
            {
                "phase": _safe_id(item.get("phase")),
                "status": _safe_id(item.get("status")),
                "run_id": _safe_id(item.get("run_id")),
            }
        )
    return phases


def _record(
    target_id: str,
    target_run_id: str,
    trial_id: str,
    *,
    availability: str = "degraded",
    reason: str | None = None,
    eval_sha: str | None = None,
    stack_fingerprint: str | None = None,
    meta: Mapping[str, Any] | None = None,
    verdicts: list[dict[str, Any]] | None = None,
    diagnoses: list[dict[str, Any]] | None = None,
    artifact_summary: Mapping[str, Any] | None = None,
    project_graph_summary: Mapping[str, Any] | None = None,
    storage_source: str = STORAGE_MATERIALIZED,
    results_availability: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    return {
        "target_id": target_id,
        "target_run_id": target_run_id,
        "trial_id": trial_id,
        "storage_source": storage_source,
        "instance_id": meta.get("instance_id"),
        "project_id": meta.get("project_id"),
        "start_phase": meta.get("start_phase"),
        "terminal": meta.get("terminal"),
        "copied_at": meta.get("copied_at"),
        "phases": meta.get("phases", []),
        "eval_sha": eval_sha,
        "stack_fingerprint": stack_fingerprint,
        "verdicts": verdicts or [],
        "diagnoses": diagnoses or [],
        "results_availability": (
            dict(results_availability)
            if results_availability is not None
            else _unavailable_results(None)
        ),
        "availability": availability,
        "reason": reason,
        "artifact_summary": artifact_summary or _historical_artifact_summary(),
        "project_graph_summary": project_graph_summary or _historical_graph_summary(),
    }


# --- results availability -------------------------------------------------------


def _availability(status: str, reason: str | None) -> dict[str, Any]:
    """One results file's availability: `available`, else a stable reason code."""
    return {"status": status, "reason": reason}


def _results_block(
    verdicts: Mapping[str, Any], diagnoses: Mapping[str, Any]
) -> dict[str, Any]:
    return {"verdicts": dict(verdicts), "diagnoses": dict(diagnoses)}


def _unavailable_results(reason: str | None) -> dict[str, Any]:
    """Both results blocks unavailable for the same reason (no file read)."""
    return _results_block(
        _availability(RESULTS_UNAVAILABLE, reason),
        _availability(RESULTS_UNAVAILABLE, reason),
    )


def _present(path: Path, *, strict: bool) -> bool:
    """Whether a results file is present; `strict` rejects a symlink/special.

    The materialized tree keeps its historical `exists()` behavior; a run
    record is read only from a real regular file, so a link planted there can
    never redirect the reader outside the Trial's own directory.
    """
    if not strict:
        return path.exists()
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


# --- one authoritative run record (not yet materialized) ------------------------


def project_run_record(record: Any) -> dict[str, Any]:
    """Project one validated run record into a Trial, reading its own results.

    The identity and phases come from the record; `copied_at` stays null because
    nothing was materialized. Verdicts and diagnoses are read from the record's
    directory with the strict, symlink-free reader, and each one's availability
    is independent of the other.
    """
    target_id, target_run_id, trial_id = record.identity
    meta = {
        "instance_id": record.instance_id,
        "project_id": record.project_id,
        "start_phase": record.start_phase,
        "terminal": record.terminal,
        "copied_at": None,
        "phases": _phases(list(record.phases)),
    }
    verdicts, verdicts_availability, verdict_defect = _read_verdicts(
        record.directory, strict=True
    )
    diagnoses, diagnoses_availability, diagnosis_defect = _read_diagnoses(
        record.directory,
        verdicts,
        verdicts_available=verdicts_availability["status"] == RESULTS_AVAILABLE,
        strict=True,
    )
    defect = verdict_defect or diagnosis_defect
    return _record(
        target_id,
        target_run_id,
        trial_id,
        availability="degraded" if defect else "complete",
        reason=defect,
        eval_sha=record.eval_sha,
        stack_fingerprint=record.stack_fingerprint,
        meta=meta,
        verdicts=verdicts,
        diagnoses=diagnoses,
        storage_source=STORAGE_RUN_RECORD,
        results_availability=_results_block(
            verdicts_availability, diagnoses_availability
        ),
    )
def _success_row(record: Mapping[str, Any], verdict: Mapping[str, Any]) -> dict[str, Any]:
    matched = verdict["matched"]
    return {
        "vuln_id": verdict["vuln_id"],
        "target_id": record["target_id"],
        "target_run_id": record["target_run_id"],
        "trial_id": record["trial_id"],
        "eval_sha": record["eval_sha"],
        "stack_fingerprint": record["stack_fingerprint"],
        "confidence": verdict["confidence"],
        "matched": {
            "unit": matched["unit"],
            "fault_class": matched["fault_class"],
            "symptom": matched["symptom"],
        },
    }


def _safe_id(value: object) -> str | None:
    """A non-empty, relative, single-segment identifier - never a host path."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        return None
    return text


def _safe_text(value: object, *, limit: int = MAX_TEXT) -> str | None:
    """Free text, unless it carries an absolute-path-looking token or an escape."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or "\\" in text:
        return None
    if any(token.startswith("/") for token in text.split()):
        return None
    return text


def _safe_display_text(value: object, *, limit: int = MAX_TEXT) -> str | None:
    """Human-readable display text, unless it carries a *host* path or an escape.

    Display fields (matched labels, diagnosis prose, issue titles) legitimately
    name HTTP routes such as `/view`, `/userdata` or `/api/v1/items`, so a
    leading slash is not by itself a leak. A token is rejected only when it is a
    filesystem location: a `..` traversal, a UNC path, a known system/home root,
    or a path that ends in a file extension. Identifiers and evidence
    references do not use this function - they stay strictly relative.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > limit or "\\" in text:
        return None
    if any(_looks_like_host_path(token) for token in text.split()):
        return None
    return text


def _looks_like_host_path(token: str) -> bool:
    """Whether one whitespace-delimited token names a filesystem location."""
    if token.startswith("//"):
        return True
    if not token.startswith("/"):
        return False
    segments = [segment for segment in token.split("/") if segment]
    if not segments:
        return False
    if any(segment == ".." for segment in segments):
        return True
    if segments[0] in HOST_PATH_ROOTS:
        return True
    last = segments[-1]
    suffix = last.rsplit(".", 1)[1].lower() if "." in last else ""
    return suffix in FILE_SUFFIXES


def _safe_ref(value: object) -> str | None:
    """A valid, relative, path-safe reference - or `None` when it is not one."""
    text = _safe_text(value, limit=MAX_REF)
    if text is None or "://" in text:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return text
