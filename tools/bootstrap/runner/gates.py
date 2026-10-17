"""The phase gate: the shape validator run as a subprocess, and its OK/FAIL parse.

The validator (`tools/bootstrap/validate_data_dependencies.py`) IS the gate
(architecture doc, section 3.5): it is deterministic, it is the same script the
worker is told to run, and a phase never advances while it reports errors.

This module owns two things only: the exact argv/mode selection, and the
reading of the validator's own report - one `OK <dir>` / `FAIL <dir>` line per
target, error lines beneath a FAIL. The failure TEXT is passed through
verbatim, because the orchestrator re-dispatches it into the worker session.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol

from runner.env import decode_output

# The two gate modes this loop uses. `auth_only` is the authn phase's gate (the
# L1 surface does not exist yet); `full` is the L1 phase's gate.
AUTH_ONLY = "auth_only"
FULL = "full"

_OK_RE = re.compile(r"^OK\s+(\S+)", re.MULTILINE)
_FAIL_RE = re.compile(r"^FAIL\s+(\S+)", re.MULTILINE)


@dataclass(frozen=True)
class GateResult:
    """One gate run: the validator's exit code and its verbatim output."""

    ok: bool
    output: str
    command: tuple[str, ...] = ()
    mode: str = ""

    @property
    def failure_text(self) -> str:
        """The verbatim portion a repair dispatch must carry."""
        return self.output.strip()


class Gate(Protocol):
    """The gate seam: run one validator mode for one target."""

    def run(self, target: str, mode: str) -> GateResult: ...


def validator_argv(
    *,
    python: str,
    validator: Path,
    target: str,
    mode: str,
    staging: Path | None = None,
    target_dir: Path | None = None,
) -> tuple[str, ...]:
    """The exact validator invocation for one target and mode.

    `auth_only` validates the staging project dir by NAME (before the KB dir
    exists); `full` validates the KB dir with `--staging` so the auth artifacts
    are read from the staging root.
    """
    argv: list[str] = [python, str(validator)]
    if mode == AUTH_ONLY:
        argv.append("--auth-only")
    elif mode != FULL:
        raise ValueError(f"unknown gate mode {mode!r} (expected {AUTH_ONLY!r} or {FULL!r})")
    if staging is not None:
        argv += ["--staging", str(staging)]
    argv.append(target if mode == AUTH_ONLY else str(target_dir or target))
    return tuple(argv)


def validator_env(worktree: Path, base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The validator's environment: the platform import root on PYTHONPATH.

    The validator imports `polymerhus.analysis.*`, which resolves only with
    `src/` on the path, so the gate exports it exactly as the prompt's documented
    invocation (`PYTHONPATH=src`) does.
    """
    env = dict(os.environ if base is None else base)
    src = str(worktree / "src")
    parts = [part for part in (env.get("PYTHONPATH") or "").split(os.pathsep) if part]
    if src not in parts:
        parts.insert(0, src)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    return env


def parse_report(output: str, target: str) -> bool | None:
    """Read the validator's report for `target`: True OK, False FAIL, None absent.

    None means the report never mentioned the target (a crash before the
    per-target line), which the caller treats as a failure, never as a pass.
    """
    ok_dirs = _OK_RE.findall(output or "")
    fail_dirs = _FAIL_RE.findall(output or "")
    in_ok = any(_names_target(name, target) for name in ok_dirs)
    in_fail = any(_names_target(name, target) for name in fail_dirs)
    if in_fail:
        return False
    if in_ok:
        return True
    return None


def _names_target(reported: str, target: str) -> bool:
    """Match the validator's reported path against the target name or dir."""
    cleaned = reported.strip().rstrip("/")
    return cleaned == target or Path(cleaned).name == target


@dataclass(frozen=True)
class ValidatorGate:
    """The production gate: one `python3 validate_data_dependencies.py` subprocess.

    `cwd` is the worktree (the contract's documented invocation), and the
    environment carries `PYTHONPATH=src`. The subprocess timeout is a safety net
    only: the validator is pure I/O over local files.
    """

    validator: Path
    staging: Path
    kbs: Path
    worktree: Path
    python: str = field(default_factory=lambda: sys.executable)
    timeout_s: float = 300.0
    extra_env: Mapping[str, str] = field(default_factory=dict)

    def argv(self, target: str, mode: str) -> tuple[str, ...]:
        return validator_argv(
            python=self.python,
            validator=self.validator,
            target=target,
            mode=mode,
            staging=self.staging,
            target_dir=self.kbs / target,
        )

    def run(self, target: str, mode: str) -> GateResult:
        argv = self.argv(target, mode)
        try:
            proc = subprocess.run(
                list(argv),
                cwd=str(self.worktree),
                env=validator_env(self.worktree, {**os.environ, **self.extra_env}),
                capture_output=True,
                timeout=self.timeout_s,
            )
            # A validator that trips over an undecodable byte in a worker's
            # artifact must come back as a red, readable gate, never as a
            # traceback that kills the run.
            output = decode_output(proc.stdout) + decode_output(proc.stderr)
            parsed = parse_report(output, target)
            ok = proc.returncode == 0 and parsed is not False
        except (OSError, subprocess.SubprocessError) as exc:
            output = f"gate could not run: {exc}"
            ok = False
        return GateResult(ok=ok, output=output, command=argv, mode=mode)
