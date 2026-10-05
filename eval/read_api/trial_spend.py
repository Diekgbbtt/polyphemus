"""Recorded Trial spend, resolved from the authoritative harness record.

The live app endpoint `GET /projects/{id}/usage` is a process-wide, in-memory
accumulator: it carries no per-run attribution and dies with the app process.
The *recorded* spend of a finished Trial is written once by the harness into
its record under the runs root. That record is the single source of truth for
`spent_tokens`, `spend_overshoot`, and `spend_by_agent`.

The record filename is arbitrary, so this module resolves it by the Trial's
full identity - `(target_id, target_run_id, trial_id)` plus a verified
`project_id` and `instance_id` - within a caller-configured, read-only root. An
absent or ambiguous association is `unavailable` (never guessed); zero is a
value while a missing field stays `None`; the overshoot is never folded into
the spent total, and the per-agent breakdown is preserved verbatim. Nothing
here writes a record, and every failure is a stable, path-free code.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from orchestrator.files import FileStore

from .resolved import is_safe_identifier

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

# Stable, path-free reason codes. Every one names a data condition, never a
# host location, so the value is safe to surface in the API body and the UI.
SPEND_ROOT_UNCONFIGURED = "spend_root_unconfigured"
SPEND_IDENTITY_UNAVAILABLE = "spend_identity_unavailable"
SPEND_RECORD_NOT_FOUND = "spend_record_not_found"
SPEND_RECORD_AMBIGUOUS = "spend_record_ambiguous"
SPEND_RECORD_INVALID = "spend_record_invalid"

# Only a YAML record can carry the harness's spend fields; a stray JSON or a
# directory entry is never mistaken for the record.
_YAML_SUFFIXES = (".yaml", ".yml")
# The per-agent entry fields the live ledger records. The breakdown is kept
# verbatim apart from dropping anything that is not one of these integer
# counters, so no attribution is invented.
_AGENT_INT_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "calls")


@dataclass(frozen=True)
class TrialSpend:
    """One Trial's recorded spend, serialized as the `/snapshot` `spend` block."""

    status: str
    spent_tokens: int | None = None
    spend_overshoot: int | None = None
    spend_by_agent: dict[str, dict[str, int]] | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "spent_tokens": self.spent_tokens,
            "spend_overshoot": self.spend_overshoot,
            "spend_by_agent": self.spend_by_agent,
            "reason": self.reason,
        }


def _unavailable(reason: str) -> TrialSpend:
    return TrialSpend(status=STATUS_UNAVAILABLE, reason=reason)


def load_spend_records(
    runs_root: str | Path | None, *, files: FileStore | None = None
) -> list[Mapping]:
    """Every parseable YAML mapping under `runs_root` (missing root -> []).

    A symlinked or special file is never followed, and a corrupt record is
    skipped rather than raised, so one broken file cannot hide the rest.
    """
    if not runs_root:
        return []
    root = Path(runs_root)
    if not root.is_dir():
        return []
    store = files or FileStore()
    records: list[Mapping] = []
    for path in store.walk_regular_files(root):
        if path.suffix.lower() not in _YAML_SUFFIXES:
            continue
        try:
            payload = yaml.safe_load(store.read_text(path))
        except (yaml.YAMLError, OSError, UnicodeDecodeError):
            continue
        if isinstance(payload, Mapping):
            records.append(payload)
    return records


def match_spend(
    records: list[Mapping],
    *,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    project_id: str | None,
    instance_id: str | None,
) -> TrialSpend:
    """One Trial's spend from preloaded records, or an `unavailable` block."""
    if not all(
        is_safe_identifier(part) for part in (target_id, target_run_id, trial_id)
    ):
        return _unavailable(SPEND_RECORD_NOT_FOUND)
    if not is_safe_identifier(project_id) or not is_safe_identifier(instance_id):
        # Without a verified project and instance the association cannot be
        # proven, so the spend stays unavailable rather than guessed.
        return _unavailable(SPEND_IDENTITY_UNAVAILABLE)

    matches = [
        record
        for record in records
        if _matches(
            record,
            target_id=target_id,
            target_run_id=target_run_id,
            trial_id=trial_id,
            project_id=project_id,
            instance_id=instance_id,
        )
    ]
    if not matches:
        return _unavailable(SPEND_RECORD_NOT_FOUND)
    if len(matches) > 1:
        return _unavailable(SPEND_RECORD_AMBIGUOUS)
    return _parse_spend(matches[0])


def resolve_trial_spend(
    runs_root: str | Path | None,
    *,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    project_id: str | None,
    instance_id: str | None,
    files: FileStore | None = None,
) -> TrialSpend:
    """One Trial's recorded spend, resolved by full identity under `runs_root`."""
    if not runs_root:
        return _unavailable(SPEND_ROOT_UNCONFIGURED)
    records = load_spend_records(runs_root, files=files)
    return match_spend(
        records,
        target_id=target_id,
        target_run_id=target_run_id,
        trial_id=trial_id,
        project_id=project_id,
        instance_id=instance_id,
    )


def _matches(
    record: Mapping,
    *,
    target_id: str,
    target_run_id: str,
    trial_id: str,
    project_id: str,
    instance_id: str,
) -> bool:
    if record.get("target_id") != target_id:
        return False
    if record.get("trial_id") != trial_id:
        return False
    record_run = record.get("target_run_id") or record.get("instance_id")
    if record_run != target_run_id:
        return False
    if record.get("project_id") != project_id:
        return False
    return record.get("instance_id") == instance_id


def _parse_spend(record: Mapping) -> TrialSpend:
    spent = _optional_count(record, "spent_tokens")
    overshoot = _optional_count(record, "spend_overshoot")
    if spent is _INVALID or overshoot is _INVALID:
        return _unavailable(SPEND_RECORD_INVALID)
    breakdown = _breakdown(record.get("spend_by_agent"))
    if breakdown is _INVALID:
        return _unavailable(SPEND_RECORD_INVALID)
    return TrialSpend(
        status=STATUS_AVAILABLE,
        spent_tokens=spent,
        spend_overshoot=overshoot,
        spend_by_agent=breakdown,
    )


_INVALID = object()


def _optional_count(record: Mapping, key: str) -> int | None | object:
    """A validated non-negative counter, `None` when absent, `_INVALID` bad."""
    if key not in record:
        return None
    value = record.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return _INVALID
    return value


def _breakdown(raw: object) -> dict[str, dict[str, int]] | None | object:
    """The per-agent breakdown, sanitized to integer counters, or `_INVALID`."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        return _INVALID
    breakdown: dict[str, dict[str, int]] = {}
    for agent, entry in raw.items():
        if not isinstance(agent, str) or not agent:
            return _INVALID
        if not isinstance(entry, Mapping):
            return _INVALID
        counters: dict[str, int] = {}
        for field in _AGENT_INT_FIELDS:
            value = entry.get(field)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return _INVALID
            counters[field] = value
        breakdown[agent] = counters
    return breakdown


__all__ = [
    "SPEND_IDENTITY_UNAVAILABLE",
    "SPEND_RECORD_AMBIGUOUS",
    "SPEND_RECORD_INVALID",
    "SPEND_RECORD_NOT_FOUND",
    "SPEND_ROOT_UNCONFIGURED",
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "TrialSpend",
    "load_spend_records",
    "match_spend",
    "resolve_trial_spend",
]
