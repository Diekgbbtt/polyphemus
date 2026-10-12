"""The eval recovery state: hold markers and applied action keys.

This module holds the eval-wide atomic state file the surfer loop and the
`up`/`trial` verbs share: the `Hold` markers an escalation writes (which block a
bring-up or a trial until an operator resolves them), the surfer's handled-trigger
keys, and the applied-action keys a replay reads for idempotency.

The version jump itself is no longer performed or decided here. The eval
instance is owned by the external operator, so the fast-forward and its
alignment decision live outside this codebase; only the durable state every
bring-up, trial, and surfer cycle must see stays.

Every effect is injected - the clock, the `FileStore` - so the unit tier needs
no Docker and no agent. Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

import yaml

from orchestrator import subagents
from orchestrator.files import FileStore
from orchestrator.ids import short_id

# The eval state file (holds + applied keys). Overridable by CLI/env.
DEFAULT_STATE_PATH = Path("eval/state/alignment.yaml")


class AlignmentError(RuntimeError):
    """The eval recovery state could not be read or written."""


class AlignmentHoldError(AlignmentError):
    """An unresolved hold refuses a trial/bring-up."""

    def __init__(self, hold: "Hold") -> None:
        super().__init__(f"alignment hold {hold.hold_id}: {hold.rationale}")
        self.hold_id = hold.hold_id
        self.rationale = hold.rationale


# The state namespace for the surfer's handled-trigger keys. Reusing the
# `applied` map keeps one atomic state file; this constant pair isolates the
# surfer's handled keys from the applied-action keys, so neither can clear the
# other. Defined here (surfer aliases them) so `resolve_hold` can clear the
# markers a surfer hold recorded, re-arming its triggers (I7).
SURFER_HANDLED_SHA = "surfer"
SURFER_HANDLED_FINGERPRINT = ""


@dataclass(frozen=True)
class Hold:
    """An unresolved escalation; blocks trials until resolved."""

    hold_id: str
    rationale: str
    target_sha: str
    target_fingerprint: str
    created_at: str
    resolved: bool = False
    decision: str | None = None
    resolved_at: str | None = None
    # I7: the surfer trigger identities this hold disarmed, so resolving it can
    # re-arm them; `history` records the operator resolutions of prior re-opens.
    trigger_keys: tuple[str, ...] = ()
    history: tuple[Mapping, ...] = ()


def _hold_from(entry: Mapping) -> Hold:
    history = entry.get("history") or []
    trigger_keys = entry.get("trigger_keys") or []
    return Hold(
        hold_id=str(entry.get("hold_id") or ""),
        rationale=str(entry.get("rationale") or ""),
        target_sha=str(entry.get("target_sha") or ""),
        target_fingerprint=str(entry.get("target_fingerprint") or ""),
        created_at=str(entry.get("created_at") or ""),
        resolved=bool(entry.get("resolved")),
        decision=(str(entry["decision"]) if entry.get("decision") is not None else None),
        resolved_at=(
            str(entry["resolved_at"]) if entry.get("resolved_at") is not None else None
        ),
        trigger_keys=tuple(str(key) for key in trigger_keys if key is not None),
        history=tuple(
            item for item in history if isinstance(item, Mapping)
        ),
    )


def _pair_key(target_sha: str, target_fingerprint: str) -> str:
    return f"{target_sha}@{target_fingerprint}"


class AlignmentState:
    """The eval-wide recovery state: atomic hold markers and applied keys."""

    def __init__(self, path: str | Path, *, files: FileStore | None = None) -> None:
        self.path = Path(path)
        self._files = files or FileStore()

    # -- holds -------------------------------------------------------------

    def holds(self) -> tuple[Hold, ...]:
        return tuple(_hold_from(entry) for entry in self._load()["holds"])

    def unresolved_holds(self) -> tuple[Hold, ...]:
        return tuple(hold for hold in self.holds() if not hold.resolved)

    def require_no_holds(self) -> None:
        """Raise `AlignmentHoldError` naming the first unresolved hold."""
        holds = self.unresolved_holds()
        if holds:
            raise AlignmentHoldError(holds[0])

    def add_hold(
        self,
        *,
        target_sha: str,
        target_fingerprint: str,
        rationale: str,
        now: str,
        trigger_keys: Sequence[str] = (),
    ) -> Hold:
        """Write a hold marker atomically; re-adding the same one is idempotent.

        I7: if the same hold was resolved, re-adding re-opens it (unresolved
        again) and appends the prior resolution to its `history`, so a condition
        that persists after an operator resolution re-escalates with that
        context recorded.
        """
        payload = self._load()
        hold_id = short_id(f"{target_sha}:{target_fingerprint}:{rationale}")
        keys = tuple(str(key) for key in trigger_keys if key is not None)
        for entry in payload["holds"]:
            if entry.get("hold_id") != hold_id:
                continue
            if entry.get("resolved"):
                history = list(entry.get("history") or [])
                history.append(
                    {
                        "decision": entry.get("decision"),
                        "resolved_at": entry.get("resolved_at"),
                    }
                )
                entry["history"] = history
                entry["resolved"] = False
                entry["decision"] = None
                entry["resolved_at"] = None
                if keys:
                    entry["trigger_keys"] = sorted(set(entry.get("trigger_keys") or []) | set(keys))
                self._write(payload)
            return _hold_from(entry)
        hold = Hold(
            hold_id=hold_id,
            rationale=rationale,
            target_sha=target_sha,
            target_fingerprint=target_fingerprint,
            created_at=now,
            trigger_keys=keys,
        )
        payload["holds"].append(asdict(hold))
        self._write(payload)
        return hold

    def resolve_hold(self, hold_id: str, decision: str, *, now: str | None = None) -> Hold:
        """Record the operator's decision and clear the hold.

        I7: the surfer handled markers recorded under this hold's triggers are
        cleared, so the next surfer cycle re-asserts; a condition that persists
        re-escalates (and re-opens the hold with this decision in its history).
        """
        payload = self._load()
        for entry in payload["holds"]:
            if entry.get("hold_id") != hold_id:
                continue
            if entry.get("resolved"):
                raise AlignmentError(f"alignment hold {hold_id!r} is already resolved")
            entry["resolved"] = True
            entry["decision"] = decision
            entry["resolved_at"] = (now or subagents.utcnow)()
            self._clear_surfer_markers(payload, entry.get("trigger_keys") or [])
            self._write(payload)
            return _hold_from(entry)
        raise AlignmentError(f"no alignment hold {hold_id!r}")

    def _clear_surfer_markers(self, payload: dict, trigger_keys: Sequence) -> None:
        """Clear the surfer handled markers for `trigger_keys` (I7)."""
        keys = {str(key) for key in trigger_keys if key is not None}
        if not keys:
            return
        pair = _pair_key(SURFER_HANDLED_SHA, SURFER_HANDLED_FINGERPRINT)
        current = [str(key) for key in payload["applied"].get(pair, [])]
        remaining = [key for key in current if key not in keys]
        if remaining:
            payload["applied"][pair] = remaining
        else:
            payload["applied"].pop(pair, None)

    # -- applied actions (idempotency) -------------------------------------

    def applied_for(self, target_sha: str, target_fingerprint: str) -> frozenset[str]:
        applied = self._load()["applied"].get(_pair_key(target_sha, target_fingerprint), [])
        return frozenset(str(key) for key in applied)

    def record_applied(
        self,
        target_sha: str,
        target_fingerprint: str,
        keys: Sequence[str],
    ) -> None:
        payload = self._load()
        pair = _pair_key(target_sha, target_fingerprint)
        current = [str(key) for key in payload["applied"].get(pair, [])]
        for key in keys:
            if key not in current:
                current.append(key)
        payload["applied"][pair] = current
        self._write(payload)

    # -- storage -----------------------------------------------------------

    def _load(self) -> dict:
        if not self._files.is_file(self.path):
            return {"holds": [], "applied": {}}
        try:
            payload = yaml.safe_load(self._files.read_text(self.path))
        except yaml.YAMLError as exc:
            raise AlignmentError(f"alignment state {self.path}: invalid YAML: {exc}") from exc
        if payload is None:
            return {"holds": [], "applied": {}}
        if not isinstance(payload, Mapping):
            raise AlignmentError(f"alignment state {self.path}: expected a mapping")
        holds = payload.get("holds") or []
        applied = payload.get("applied") or {}
        if not isinstance(holds, list) or not isinstance(applied, Mapping):
            raise AlignmentError(f"alignment state {self.path}: malformed holds/applied")
        return {"holds": list(holds), "applied": dict(applied)}

    def _write(self, payload: Mapping) -> None:
        self._files.write_text_atomic(self.path, yaml.safe_dump(dict(payload), sort_keys=False))
