"""The evidence chain: resolve and validate the artifacts backing a verdict.

For an `identified`/`partial` verdict the chain is the parent hunt config, the
child `TestImplementationSpec` directory, the child experiment logs, and the
yielded `PodExport` - plus optional phase-mapped observability reasoning refs.
Every path is data-root-relative and must resolve on disk through the injected
`FileStore`: a missing required element is a named validation error, never a
silently short chain (N13/D17).

The reasoning seam is read-only and injected: given a trace id recorded by the
trial it returns reasoning observations, which are mapped to the agent workflow
phases. With no source (no Langfuse configuration) the refs are simply empty.

Stdlib only. Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Sequence

from orchestrator.files import (
    FileStore,
    hunt_configs_dir,
    hunter_test_specs_dir,
    pod_experiment_logs_dir,
    pod_spec_dir,
)

# The agent workflow phases a reasoning ref maps to, in output order.
PHASES = ("recon", "analysis", "hunting")

_REASONING_FIELDS = ("phase", "decision_node", "rationale", "observation_ref")


class EvidenceError(ValueError):
    """A required chain element is absent, malformed, or unresolvable."""


@dataclass(frozen=True)
class ReasoningRef:
    """One phase-mapped observability reference backing a verdict (D17)."""

    phase: str
    decision_node: str
    rationale: str
    observation_ref: str

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "decision_node": self.decision_node,
            "rationale": self.rationale,
            "observation_ref": self.observation_ref,
        }


# The read-only observability seam: trace id -> raw reasoning observations.
# Each observation is a mapping keyed by the four `_REASONING_FIELDS`; the real
# implementation reads Langfuse, tests inject a fake. Absent a source, the
# resolver leaves the refs empty.
ReasoningSource = Callable[[str], Sequence[Mapping]]


@dataclass(frozen=True)
class EvidenceTarget:
    """The identities a verdict's chain is resolved from within a project."""

    project_id: str
    hunt_config: str
    fault_key: str
    spec_id: str
    pod_export: str | None = None
    trace_id: str | None = None


@dataclass(frozen=True)
class EvidenceChain:
    """The resolved, data-root-relative evidence chain of one verdict."""

    hunt_config: str
    spec_dir: str
    experiment_logs: tuple[str, ...]
    pod_export: str
    reasoning: tuple[ReasoningRef, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "hunt_config": self.hunt_config,
            "spec_dir": self.spec_dir,
            "experiment_logs": list(self.experiment_logs),
            "pod_export": self.pod_export,
            "reasoning": [ref.to_dict() for ref in self.reasoning],
        }


def map_reasoning(observations: Sequence[Mapping]) -> tuple[ReasoningRef, ...]:
    """Map raw observability observations to phase-ordered reasoning refs."""
    refs: list[ReasoningRef] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise EvidenceError(f"reasoning observation is not a mapping: {observation!r}")
        missing = [name for name in _REASONING_FIELDS if not observation.get(name)]
        if missing:
            raise EvidenceError(
                f"reasoning observation missing field(s): {', '.join(missing)}"
            )
        phase = str(observation["phase"])
        if phase not in PHASES:
            raise EvidenceError(
                f"reasoning phase must be one of {', '.join(PHASES)}, got {phase!r}"
            )
        refs.append(
            ReasoningRef(
                phase=phase,
                decision_node=str(observation["decision_node"]),
                rationale=str(observation["rationale"]),
                observation_ref=str(observation["observation_ref"]),
            )
        )
    return tuple(sorted(refs, key=lambda ref: PHASES.index(ref.phase)))


def resolve_evidence(
    data_root: str | Path,
    target: EvidenceTarget,
    *,
    files: FileStore,
    reasoning_source: ReasoningSource | None = None,
) -> EvidenceChain:
    """Resolve every chain element from the data root by identity.

    The hunt config is searched on both sides; the spec directory is the
    `<fault_key>/` family; the experiment logs are every `*.yaml` slice; the
    pod export is the named `<run_id>.yaml` or the spec's single terminal
    record. A missing or ambiguous element raises `EvidenceError`.

    This is the harness-facing chain resolver (CODING_STANDARD section 12): the
    orchestrator dispatches the assessment as an external subagent, so no
    orchestrator code path calls this yet; the live materializer re-validates
    the copied chain through `verdicts.load_verdicts`. The trace id it accepts
    is the same one the trial record now carries into the dispatches.
    """
    root = Path(data_root)
    project = target.project_id

    hunt_config = _resolve_hunt_config(root, project, target.hunt_config, files)
    spec_dir = hunter_test_specs_dir(root, project) / target.fault_key
    _require_dir(spec_dir, "spec_dir", files)

    logs_dir = pod_experiment_logs_dir(root, project, target.spec_id)
    experiment_logs = tuple(_relative(root, path) for path in files.list_files(logs_dir))
    if not experiment_logs:
        raise EvidenceError(
            f"experiment_logs: no experiment-log slice under "
            f"{_relative(root, logs_dir)}"
        )

    pod_export = _resolve_pod_export(root, project, target.spec_id, target.pod_export, files)

    reasoning: tuple[ReasoningRef, ...] = ()
    if reasoning_source is not None and target.trace_id:
        reasoning = map_reasoning(reasoning_source(target.trace_id))

    chain = EvidenceChain(
        hunt_config=hunt_config,
        spec_dir=_relative(root, spec_dir),
        experiment_logs=experiment_logs,
        pod_export=pod_export,
        reasoning=reasoning,
    )
    validate_evidence(chain, root, files=files)
    return chain


def validate_evidence(chain: EvidenceChain, data_root: str | Path, *, files: FileStore) -> None:
    """Check every chain path is data-root-relative and present on disk."""
    root = Path(data_root)
    for label, path in (
        ("hunt_config", chain.hunt_config),
        ("spec_dir", chain.spec_dir),
        ("pod_export", chain.pod_export),
    ):
        resolved = _resolve_relative(root, path, label)
        if not files.exists(resolved):
            raise EvidenceError(f"{label}: {path!r} does not resolve under the data root")
    if not chain.experiment_logs:
        raise EvidenceError("experiment_logs: a positive verdict needs at least one log")
    for path in chain.experiment_logs:
        resolved = _resolve_relative(root, path, "experiment_logs")
        if not files.exists(resolved):
            raise EvidenceError(
                f"experiment_logs: {path!r} does not resolve under the data root"
            )


# --- internals ----------------------------------------------------------------


def _resolve_hunt_config(
    root: Path, project: str, name: str, files: FileStore
) -> str:
    stem = name[:-5] if name.endswith(".yaml") else name
    for side in ("produced", "consumed"):
        directory = hunt_configs_dir(root, project, side)
        for path in files.glob(directory, "*.yaml"):
            if path.name == name or path.stem == stem:
                return _relative(root, path)
    raise EvidenceError(
        f"hunt_config: {name!r} not found in the produced/consumed inboxes"
    )


def _resolve_pod_export(
    root: Path, project: str, spec_id: str, name: str | None, files: FileStore
) -> str:
    spec_dir = pod_spec_dir(root, project, spec_id)
    if name is not None:
        candidate = spec_dir / (name if name.endswith(".yaml") else f"{name}.yaml")
        if not files.exists(candidate):
            raise EvidenceError(f"pod_export: {name!r} does not resolve under the data root")
        return _relative(root, candidate)

    candidates = [path for path in files.list_files(spec_dir) if path.suffix == ".yaml"]
    if not candidates:
        raise EvidenceError(f"pod_export: no terminal record under {_relative(root, spec_dir)}")
    if len(candidates) > 1:
        raise EvidenceError(
            f"pod_export: ambiguous terminal record under {_relative(root, spec_dir)}: "
            f"{', '.join(sorted(path.name for path in candidates))}"
        )
    return _relative(root, candidates[0])


def _require_dir(path: Path, label: str, files: FileStore) -> None:
    if not files.is_dir(path):
        raise EvidenceError(f"{label}: {path.name!r} is not a directory on the data root")


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError as exc:
        raise EvidenceError(f"path {path} is not under the data root {root}") from exc


def _resolve_relative(root: Path, path: str, label: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        raise EvidenceError(f"{label}: {path!r} must be data-root-relative, not absolute")
    resolved = (root / candidate).resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise EvidenceError(f"{label}: {path!r} escapes the data root")
    return root / candidate
