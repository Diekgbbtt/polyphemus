"""Run state: one atomically-written JSON document per run, and its transitions.

The state file is the run's handoff (the architecture doc, section 6): a crashed
or stopped orchestrator resumes from it, `status` reads it, and every phase,
gate, and lifecycle observation is recorded in it. It therefore has to be
crash-safe - a reader must never see a half-written file - which is why every
save goes through a temp file plus `os.replace` (atomic on POSIX).

Secrets rule: this document holds PATHS and session ids, never values. Nothing
here reads an artifact; it only records what the orchestrator did.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

STATE_FILE = "state.json"
# `ses_bt_<run_short>_<target>_creator`: deterministic, so any target's session
# can be found by id, and a resume adopts the same session instead of a second.
SESSION_PREFIX = "ses_bt"
CREATOR_SUFFIX = "creator"
RUN_SHORT_LEN = 8

# Per-phase statuses. `skipped` exists for the `--no-lifecycle` re-run of an
# already-authored target: the phase was not attempted, and it is not a failure.
PENDING = "pending"
ACTIVE = "active"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

RUN_ACTIVE = "active"
RUN_DONE = "done"
RUN_FAILED = "failed"


def utc_now() -> str:
    """An ISO-8601 UTC stamp, second precision, so states diff cleanly."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize(part: str) -> str:
    """The session-id-safe form of a name: `[a-z0-9_]`, never empty."""
    return re.sub(r"[^a-z0-9_]", "_", part.lower())


def run_short(run_id: str) -> str:
    """The short, path-safe run token the session ids carry."""
    token = sanitize(run_id)[:RUN_SHORT_LEN].strip("_")
    return token or "run"


def session_id(run_id: str, target: str, phase: str = "creator") -> str:
    """The deterministic session id for one target's creator session."""
    return f"{SESSION_PREFIX}_{run_short(run_id)}_{sanitize(target)}_{phase}"


@dataclass
class PhaseState:
    """One phase's outcome: the dispatch, the gate, and the evidence paths."""

    read: str = PENDING
    gate: str = PENDING
    gate_output: str = ""
    session: str = ""
    turns: int = 0
    repairs: int = 0
    timeouts: int = 0
    started: str = ""
    finished: str = ""
    logs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """A phase is complete only when BOTH the dispatch and the gate are done."""
        return self.read == DONE and self.gate in (DONE, SKIPPED)


@dataclass
class LifecycleState:
    """What the environment signals said, as recorded evidence."""

    up: dict[str, Any] = field(default_factory=dict)
    teardown: dict[str, Any] = field(default_factory=dict)
    reused: bool = False
    verified_teardown: bool | None = None
    leftovers: list[str] = field(default_factory=list)


@dataclass
class TargetState:
    """One target's whole record: session, phases, gates, lifecycle, status."""

    target: str
    session_creator: str = ""
    base_url: str | None = None
    phases: dict[str, PhaseState] = field(default_factory=dict)
    gates: dict[str, str] = field(default_factory=dict)
    lifecycle: LifecycleState = field(default_factory=LifecycleState)
    status: str = PENDING
    repair_attempts: int = 0
    notes: list[str] = field(default_factory=list)
    model: dict[str, Any] | None = None

    def phase(self, name: str) -> PhaseState:
        """The named phase's record, created on first use."""
        if name not in self.phases:
            self.phases[name] = PhaseState()
        return self.phases[name]

    def creator_session(self, run_id: str) -> str:
        """The target's deterministic creator session id (state wins when set)."""
        return self.session_creator or session_id(run_id, self.target)

    def status_row(self, run_id: str) -> dict[str, str]:
        """One `status` table row: what the operator needs at a glance."""
        def phase_cell(name: str) -> str:
            phase = self.phases.get(name)
            if phase is None:
                return "-"
            if phase.complete:
                return DONE
            if phase.read == FAILED or phase.gate == FAILED:
                return FAILED
            if phase.read == ACTIVE or phase.gate == ACTIVE:
                return ACTIVE
            if phase.read == SKIPPED:
                return SKIPPED
            return PENDING

        if self.lifecycle.leftovers:
            # Leftovers are the loud form of "not verified": the count names how
            # much is still on the host after `down`.
            teardown = f"leftovers({len(self.lifecycle.leftovers)})"
        elif self.lifecycle.verified_teardown is True:
            teardown = "verified"
        elif self.lifecycle.verified_teardown is False:
            teardown = "unverified"
        else:
            teardown = "-"

        return {
            "target": self.target,
            "status": self.status,
            "authn": phase_cell("authn"),
            "l1": phase_cell("l1"),
            "gates": ",".join(f"{k}={v}" for k, v in sorted(self.gates.items())) or "-",
            "teardown": teardown,
            "session": self.creator_session(run_id),
        }


@dataclass
class RunState:
    """The whole run: its identity, its config digest, and every target."""

    run_id: str
    created: str = field(default_factory=utc_now)
    updated: str = field(default_factory=utc_now)
    config_digest: str = ""
    status: str = RUN_ACTIVE
    targets: dict[str, TargetState] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    # --- target access ---

    def target(self, name: str) -> TargetState:
        """The named target's record, created on first use (session id pre-seeded)."""
        if name not in self.targets:
            record = TargetState(target=name)
            record.session_creator = record.creator_session(self.run_id)
            self.targets[name] = record
        return self.targets[name]

    def set_targets(self, names: Sequence[str]) -> None:
        """Register the planned targets in plan order (idempotent)."""
        for name in names:
            self.target(name)

    def first_incomplete_phase(self, name: str) -> str | None:
        """The first phase of a target that is not complete, or None.

        A phase with no record yet counts as incomplete, and the lookup never
        creates one: a target that was never worked on must not gain phase rows
        just because the orchestrator asked whether it had any.
        """
        record = self.target(name)
        for phase in ("authn", "l1"):
            state = record.phases.get(phase)
            if state is None or not state.complete:
                return phase
        return None

    def target_status(self, name: str) -> str:
        return self.target(name).status

    # --- persistence ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": {
                "id": self.run_id,
                "created": self.created,
                "updated": self.updated,
                "config_digest": self.config_digest,
                "status": self.status,
                "notes": list(self.notes),
            },
            "targets": {
                name: {
                    "target": record.target,
                    "session_creator": record.session_creator,
                    "base_url": record.base_url,
                    "status": record.status,
                    "repair_attempts": record.repair_attempts,
                    "model": record.model,
                    "gates": dict(record.gates),
                    "notes": list(record.notes),
                    "lifecycle": asdict(record.lifecycle),
                    "phases": {
                        phase: asdict(phase_state)
                        for phase, phase_state in record.phases.items()
                    },
                }
                for name, record in self.targets.items()
            },
        }

    def save(self, rundir: Path) -> Path:
        """Write the state atomically: temp file in the same dir, then `os.replace`."""
        self.updated = utc_now()
        path = Path(rundir) / STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"
        handle, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):  # a failed replace leaves no stray temp file
                os.unlink(tmp)
        return path

    @classmethod
    def load(cls, rundir: Path) -> "RunState":
        """Read the state back; a missing or unreadable file fails loudly."""
        path = Path(rundir) / STATE_FILE
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RunState":
        run = raw.get("run") or {}
        state = cls(
            run_id=str(run.get("id") or ""),
            created=str(run.get("created") or utc_now()),
            updated=str(run.get("updated") or ""),
            config_digest=str(run.get("config_digest") or ""),
            status=str(run.get("status") or RUN_ACTIVE),
            notes=list(run.get("notes") or []),
        )
        for name, record in (raw.get("targets") or {}).items():
            lifecycle_raw = record.get("lifecycle") or {}
            lifecycle = LifecycleState(
                up=dict(lifecycle_raw.get("up") or {}),
                teardown=dict(lifecycle_raw.get("teardown") or {}),
                reused=bool(lifecycle_raw.get("reused")),
                verified_teardown=lifecycle_raw.get("verified_teardown"),
                leftovers=list(lifecycle_raw.get("leftovers") or []),
            )
            target = TargetState(
                target=str(record.get("target") or name),
                session_creator=str(record.get("session_creator") or ""),
                base_url=record.get("base_url"),
                status=str(record.get("status") or PENDING),
                repair_attempts=int(record.get("repair_attempts") or 0),
                model=record.get("model"),
                gates={str(k): str(v) for k, v in (record.get("gates") or {}).items()},
                lifecycle=lifecycle,
                notes=list(record.get("notes") or []),
            )
            for phase_name, phase_raw in (record.get("phases") or {}).items():
                target.phases[phase_name] = PhaseState(
                    read=str(phase_raw.get("read") or PENDING),
                    gate=str(phase_raw.get("gate") or PENDING),
                    gate_output=str(phase_raw.get("gate_output") or ""),
                    session=str(phase_raw.get("session") or ""),
                    turns=int(phase_raw.get("turns") or 0),
                    repairs=int(phase_raw.get("repairs") or 0),
                    timeouts=int(phase_raw.get("timeouts") or 0),
                    started=str(phase_raw.get("started") or ""),
                    finished=str(phase_raw.get("finished") or ""),
                    logs=list(phase_raw.get("logs") or []),
                    notes=list(phase_raw.get("notes") or []),
                )
            state.targets[name] = target
        return state

    def status_table(self) -> list[dict[str, str]]:
        """The `status` view: one row per target, in registration order."""
        return [record.status_row(self.run_id) for record in self.targets.values()]


def new_state(run_id: str, *, config_digest: str = "", targets: Sequence[str] = ()) -> RunState:
    """A fresh run state with its targets registered."""
    state = RunState(run_id=run_id, config_digest=config_digest)
    state.set_targets(targets)
    return state


def config_digest(resolved: Mapping[str, Any]) -> str:
    """A stable digest of the RESOLVED config, so a resume can detect a drift."""
    import hashlib

    payload = json.dumps(resolved, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]
