"""The `verdicts.yaml` schema, its validation, and the atomic write (#271).

One row per ground-truth vuln, exactly the spec block: `vuln_id`,
`identified | partial | missed`, `confidence`, `matched{unit,fault_class,
symptom}`, `evidence_chain` (required for `identified`/`partial`), `eval_sha`,
and `stack_fingerprint`. The SHA and fingerprint are carried from the trial
record - never invented: a row whose identity does not match the record, or a
record with no identity at all, is refused.

A malformed verdict is rejected loudly on write; the write itself is temp +
rename so a crash never leaves a half-written file. PyYAML is the one
third-party dependency (the repo's existing dependency); import performs no I/O
(CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from orchestrator import evidence, subagents
from orchestrator.files import FileStore

VERDICTS_FILENAME = "verdicts.yaml"
VERDICT_VALUES = ("identified", "partial", "missed")
# A positive (`identified`) and an ambiguous (`partial`) verdict both need an
# auditable chain; only `missed` may stand without one.
EVIDENCE_REQUIRED = ("identified", "partial")
# D20: only a success (`identified`) is exempt from a diagnosis entry. The
# diagnosis pair and the artifact store share this verdict vocabulary.
DIAGNOSABLE = ("missed", "partial")

_ROW_FIELDS = (
    "vuln_id",
    "identified",
    "confidence",
    "matched",
    "evidence_chain",
    "eval_sha",
    "stack_fingerprint",
)
_MATCHED_FIELDS = ("unit", "fault_class", "symptom")
_CHAIN_FIELDS = ("hunt_config", "spec_dir", "experiment_logs", "pod_export", "reasoning")


class VerdictError(ValueError):
    """A verdict row is malformed or its evidence is unresolvable."""


@dataclass(frozen=True)
class Matched:
    """The unit/fault-class/symptom triple a verdict reconciles to."""

    unit: str
    fault_class: str
    symptom: str


@dataclass(frozen=True)
class Verdict:
    """One validated verdict row."""

    vuln_id: str
    identified: str
    confidence: float
    matched: Matched
    evidence_chain: evidence.EvidenceChain | None
    eval_sha: str
    stack_fingerprint: str


def parse_verdict(
    row: Mapping,
    *,
    data_root: str | Path,
    files: FileStore,
    eval_sha: str | None,
    stack_fingerprint: str | None,
) -> Verdict:
    """Validate one decoded row and build its `Verdict`."""
    if not isinstance(row, Mapping):
        raise VerdictError(f"verdict row must be a mapping, got {type(row).__name__}")
    unknown = sorted(set(row) - set(_ROW_FIELDS))
    if unknown:
        raise VerdictError(f"verdict row: unknown field(s): {', '.join(unknown)}")
    missing = [name for name in _ROW_FIELDS if name not in row or row[name] is None]
    # `evidence_chain` is required only for a positive verdict; a null chain is
    # re-checked below.
    if "evidence_chain" in missing:
        missing.remove("evidence_chain")
    if missing:
        raise VerdictError(f"verdict row: missing required field(s): {', '.join(missing)}")

    vuln_id = _non_empty(row["vuln_id"], "vuln_id")
    identified = row["identified"]
    if identified not in VERDICT_VALUES:
        raise VerdictError(
            f"verdict row {vuln_id}: identified must be one of "
            f"{', '.join(VERDICT_VALUES)}, got {identified!r}"
        )
    confidence = _confidence(row["confidence"], vuln_id)
    matched = _matched(row["matched"], vuln_id)
    _check_identity(row["eval_sha"], eval_sha, "eval_sha")
    _check_identity(row["stack_fingerprint"], stack_fingerprint, "stack_fingerprint")

    chain: evidence.EvidenceChain | None = None
    raw_chain = row.get("evidence_chain")
    if raw_chain is None and identified in EVIDENCE_REQUIRED:
        raise VerdictError(
            f"verdict row {vuln_id}: evidence_chain is required for a {identified} verdict"
        )
    if raw_chain is not None:
        chain = _parse_chain(raw_chain, vuln_id, data_root=data_root, files=files)

    if identified in EVIDENCE_REQUIRED and chain is None:  # pragma: no cover - guarded above
        raise VerdictError(f"verdict row {vuln_id}: evidence_chain is required")

    return Verdict(
        vuln_id=vuln_id,
        identified=identified,
        confidence=confidence,
        matched=matched,
        evidence_chain=chain,
        eval_sha=str(row["eval_sha"]),
        stack_fingerprint=str(row["stack_fingerprint"]),
    )


def validate_verdicts(
    rows: Sequence,
    *,
    data_root: str | Path,
    files: FileStore,
    eval_sha: str | None,
    stack_fingerprint: str | None,
) -> tuple[Verdict, ...]:
    """Validate a whole `verdicts.yaml` payload (a list of rows)."""
    if not isinstance(rows, list) or not rows:
        raise VerdictError("verdicts.yaml must be a non-empty list of rows")
    return tuple(
        parse_verdict(
            row,
            data_root=data_root,
            files=files,
            eval_sha=eval_sha,
            stack_fingerprint=stack_fingerprint,
        )
        for row in rows
    )


def write_verdicts(
    path: str | Path,
    rows: Sequence,
    *,
    files: FileStore,
    data_root: str | Path,
    eval_sha: str | None,
    stack_fingerprint: str | None,
) -> None:
    """Validate, then write the rows atomically (temp + rename)."""
    validate_verdicts(
        rows,
        data_root=data_root,
        files=files,
        eval_sha=eval_sha,
        stack_fingerprint=stack_fingerprint,
    )
    files.write_text_atomic(path, yaml.safe_dump(list(rows), sort_keys=False))


def load_verdicts(
    path: str | Path,
    *,
    files: FileStore,
    data_root: str | Path,
    eval_sha: str | None,
    stack_fingerprint: str | None,
) -> tuple[Verdict, ...]:
    """Read and validate `verdicts.yaml`; raise `VerdictError` on any defect."""
    if not files.exists(path):
        raise VerdictError(f"verdicts.yaml not found at {path}")
    text = files.read_text(path)
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise VerdictError(f"verdicts.yaml: invalid YAML: {exc}") from exc
    return validate_verdicts(
        payload,
        data_root=data_root,
        files=files,
        eval_sha=eval_sha,
        stack_fingerprint=stack_fingerprint,
    )


# --- internals ----------------------------------------------------------------


def _parse_chain(
    raw: Mapping, vuln_id: str, *, data_root: str | Path, files: FileStore
) -> evidence.EvidenceChain:
    if not isinstance(raw, Mapping):
        raise VerdictError(f"verdict row {vuln_id}: evidence_chain must be a mapping")
    unknown = sorted(set(raw) - set(_CHAIN_FIELDS))
    if unknown:
        raise VerdictError(
            f"verdict row {vuln_id}: evidence_chain unknown field(s): {', '.join(unknown)}"
        )
    missing = [name for name in _CHAIN_FIELDS if name not in raw and name != "reasoning"]
    if missing:
        raise VerdictError(
            f"verdict row {vuln_id}: evidence_chain missing field(s): {', '.join(missing)}"
        )
    logs = raw["experiment_logs"]
    if not isinstance(logs, list) or not logs or not all(
        isinstance(item, str) and item for item in logs
    ):
        raise VerdictError(
            f"verdict row {vuln_id}: evidence_chain.experiment_logs must be a "
            "non-empty list of paths"
        )
    try:
        chain = evidence.EvidenceChain(
            hunt_config=_non_empty(raw["hunt_config"], "hunt_config"),
            spec_dir=_non_empty(raw["spec_dir"], "spec_dir"),
            experiment_logs=tuple(logs),
            pod_export=_non_empty(raw["pod_export"], "pod_export"),
            reasoning=evidence.map_reasoning(raw.get("reasoning") or []),
        )
        evidence.validate_evidence(chain, data_root, files=files)
    except evidence.EvidenceError as exc:
        raise VerdictError(f"verdict row {vuln_id}: {exc}") from exc
    return chain


def _matched(raw: object, vuln_id: str) -> Matched:
    if not isinstance(raw, Mapping):
        raise VerdictError(f"verdict row {vuln_id}: matched must be a mapping")
    unknown = sorted(set(raw) - set(_MATCHED_FIELDS))
    if unknown:
        raise VerdictError(
            f"verdict row {vuln_id}: matched unknown field(s): {', '.join(unknown)}"
        )
    return Matched(
        unit=_non_empty(raw.get("unit"), "matched.unit"),
        fault_class=_non_empty(raw.get("fault_class"), "matched.fault_class"),
        symptom=_non_empty(raw.get("symptom"), "matched.symptom"),
    )


def _confidence(raw: object, vuln_id: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise VerdictError(f"verdict row {vuln_id}: confidence must be a number")
    value = float(raw)
    if not 0.0 <= value <= 1.0:
        raise VerdictError(f"verdict row {vuln_id}: confidence must be within 0.0-1.0")
    return value


def _check_identity(actual: object, expected: str | None, label: str) -> None:
    if not expected:
        raise VerdictError(
            f"{label}: the trial record carries no {label}; a verdict must never "
            "invent it"
        )
    if not actual:
        raise VerdictError(f"{label}: is required on every verdict row")
    if str(actual) != expected:
        raise VerdictError(
            f"{label}: {actual!r} does not match the trial record's {expected!r}"
        )


def _non_empty(raw: object, label: str) -> str:
    return subagents.non_empty(raw, label, error=VerdictError)
