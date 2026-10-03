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

from collections import Counter
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

MANIFEST_FILENAME = "run-manifest.yaml"
VERDICTS_FILENAME = "verdicts.yaml"
DIAGNOSES_FILENAME = "diagnoses.yaml"
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

_INVALID = object()


def build_snapshot(
    store: str | Path,
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    dataset_name: str = DEFAULT_DATASET_NAME,
) -> dict[str, Any]:
    """A complete, deterministic, JSON-serializable report of the store."""
    root = Path(store)
    trials: list[dict[str, Any]] = []
    successes: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    trial_counts: Counter[str] = Counter()
    identified_counts: Counter[str] = Counter()
    partial_counts: Counter[str] = Counter()
    missed_counts: Counter[str] = Counter()

    for target_dir in _child_dirs(root):
        for run_dir in _child_dirs(target_dir):
            for trial_dir in _child_dirs(run_dir):
                record = _read_trial(
                    trial_dir,
                    default_target_id=target_dir.name,
                    default_target_run_id=run_dir.name,
                )
                trials.append(record)
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

    trials.sort(key=lambda t: (t["target_id"], t["target_run_id"], t["trial_id"]))
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
) -> dict[str, Any]:
    """Read one trial tree into an allowlisted record (never raises)."""
    manifest_path = trial_dir / MANIFEST_FILENAME
    manifest = _load_mapping(manifest_path)
    if manifest is None:
        reason = "manifest_missing" if not manifest_path.exists() else "manifest_invalid"
        return _record(
            default_target_id, default_target_run_id, trial_dir.name, reason=reason
        )

    target_id = _safe_id(manifest.get("target_id")) or default_target_id
    target_run_id = _safe_id(manifest.get("target_run_id")) or default_target_run_id
    trial_id = _safe_id(manifest.get("trial_id")) or trial_dir.name
    eval_sha = _safe_id(manifest.get("eval_sha"))
    stack_fingerprint = _safe_id(manifest.get("stack_fingerprint"))
    meta = _metadata(manifest)
    if not eval_sha or not stack_fingerprint:
        return _record(target_id, target_run_id, trial_id, reason="identity_missing", meta=meta)

    identity = {
        "eval_sha": eval_sha,
        "stack_fingerprint": stack_fingerprint,
        "meta": meta,
    }
    verdicts_path = trial_dir / VERDICTS_FILENAME
    if not verdicts_path.exists():
        return _record(
            target_id, target_run_id, trial_id, reason="verdicts_missing", **identity
        )
    payload = _load_payload(verdicts_path)
    if payload is _INVALID or not isinstance(payload, list):
        return _record(
            target_id, target_run_id, trial_id, reason="verdicts_invalid", **identity
        )

    verdicts: list[dict[str, Any]] = []
    for raw in payload:
        status, row = _parse_verdict(raw)
        if status == "invalid":
            return _record(
                target_id, target_run_id, trial_id, reason="verdict_invalid", **identity
            )
        if status == "ok":
            verdicts.append(row)
    verdicts.sort(key=lambda row: row["vuln_id"])

    diagnoses, defect = _read_diagnoses(trial_dir, verdicts)
    if defect is not None:
        return _record(target_id, target_run_id, trial_id, reason=defect, **identity)

    return _record(
        target_id,
        target_run_id,
        trial_id,
        availability="complete",
        verdicts=verdicts,
        diagnoses=diagnoses,
        **identity,
    )


def _read_diagnoses(
    trial_dir: Path, verdicts: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    """The paired diagnoses, or the safe reason code that degrades the trial."""
    required = {row["vuln_id"] for row in verdicts if row["identified"] in DIAGNOSABLE}
    path = trial_dir / DIAGNOSES_FILENAME
    if not path.exists():
        return [], "diagnoses_missing" if required else None
    payload = _load_payload(path)
    if payload is _INVALID or not isinstance(payload, list):
        return [], "diagnoses_invalid"
    rows, defect = _parse_diagnoses(payload, required)
    return (rows, None) if defect is None else ([], defect)


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
        unit = _safe_id(matched.get("unit"))
        fault_class = _safe_id(matched.get("fault_class"))
        symptom = _safe_id(matched.get("symptom"))
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
    rows: list, required: set[str]
) -> tuple[list[dict[str, Any]], str | None]:
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            return [], "diagnoses_invalid"
        vuln = _safe_id(raw.get("vuln"))
        if not vuln or vuln not in required or vuln in seen:
            return [], "diagnoses_invalid"
        seen.add(vuln)

        failure_mode = _safe_id(raw.get("failure_mode"))
        root = raw.get("root_cause")
        if not failure_mode or not isinstance(root, Mapping):
            return [], "diagnoses_invalid"
        cause_type = _safe_id(root.get("type"))
        overview = _safe_text(raw.get("diagnosis_overview"))
        if not cause_type or not overview:
            return [], "diagnoses_invalid"
        combination = root.get("combination_of") or []
        if not isinstance(combination, list):
            return [], "diagnoses_invalid"
        combined = [_safe_id(item) for item in combination]
        if any(item is None for item in combined):
            return [], "diagnoses_invalid"

        closest = _closest_issue(raw.get("closest_issue"))
        proposed = _proposed_issue(raw.get("proposed_issue"))
        if closest is _INVALID or proposed is _INVALID:
            return [], "diagnoses_invalid"
        if (closest is None) == (proposed is None):
            # Exactly one of the two must be present.
            return [], "diagnoses_invalid"

        parsed.append(
            {
                "vuln": vuln,
                "failure_mode": failure_mode,
                "root_cause": {
                    "type": cause_type,
                    "combination_of": [item for item in combined if item],
                    "extended_description": _safe_text(root.get("extended_description")),
                },
                "diagnosis_overview": overview,
                "closest_issue": closest,
                "proposed_issue": proposed,
            }
        )
    if required - seen:
        # A partial/missed verdict with no diagnosis entry is a defect.
        return [], "diagnoses_invalid"
    parsed.sort(key=lambda row: row["vuln"])
    return parsed, None


def _closest_issue(raw: object) -> dict[str, Any] | object | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _INVALID
    repo = _safe_text(raw.get("repo"))
    title = _safe_text(raw.get("title"))
    rationale = _safe_text(raw.get("rationale"))
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
    title = _safe_text(raw.get("title"))
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
) -> dict[str, Any]:
    meta = meta or {}
    return {
        "target_id": target_id,
        "target_run_id": target_run_id,
        "trial_id": trial_id,
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
        "availability": availability,
        "reason": reason,
    }


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


def _safe_ref(value: object) -> str | None:
    """A valid, relative, path-safe reference - or `None` when it is not one."""
    text = _safe_text(value, limit=MAX_REF)
    if text is None or "://" in text:
        return None
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return text
