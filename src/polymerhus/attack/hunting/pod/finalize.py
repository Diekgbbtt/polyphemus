"""The ONE PodExport finalizer.

The pod graph, the pod entry point, and the surfer all terminate a pod through
this module. It is the only production writer of a `PodExport`.

Responsibilities:

- assemble the evidence from an in-memory `ExperimentLog` or the durable store;
- return an existing terminal unchanged (first terminal wins);
- write the envelope atomically;
- clear the resume cursor only after a durable terminal exists.

It does not know about the surfer, the hunter store, the gate, or pipeline
synchronisation.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.types import (
    DOMAIN_TERMINAL_REASONS,
    HARNESS_TERMINAL_REASONS,
    TERMINAL_REASONS,
    PodExport,
)

logger = logging.getLogger(__name__)

_LOCK_GUARD = threading.Lock()
_LOCKS: dict[tuple[str, str], threading.Lock] = {}


@dataclass(frozen=True)
class PodTerminal:
    """One pod terminal: a domain verdict or a harness-owned infrastructure end."""

    verdict: Literal["successful", "unsuccessful"]
    reason: str
    clean: bool
    error: str | None = None
    iterations: int | None = None
    init_validation: tuple[str, ...] = ()

    @classmethod
    def domain(
        cls,
        *,
        verdict: Literal["successful", "unsuccessful"],
        reason: str,
        clean: bool,
        error: str | None = None,
        iterations: int | None = None,
        init_validation: Iterable[str] = (),
    ) -> "PodTerminal":
        """A triager-selectable domain terminal."""
        if verdict not in ("successful", "unsuccessful"):
            raise ValueError(f"verdict {verdict!r} is not a binary pod verdict")
        if not isinstance(clean, bool):
            raise ValueError("clean must be a boolean")
        if reason not in DOMAIN_TERMINAL_REASONS:
            raise ValueError(
                f"terminal reason {reason!r} is not a domain terminal")
        return cls(
            verdict=verdict, reason=reason, clean=clean, error=error,
            iterations=iterations,
            init_validation=tuple(init_validation),
        )

    @classmethod
    def infrastructure(
        cls,
        *,
        reason: str,
        error: str | None = None,
        iterations: int | None = None,
        init_validation: Iterable[str] = (),
    ) -> "PodTerminal":
        """A harness-owned terminal. It is always unsuccessful and not clean."""
        if reason not in HARNESS_TERMINAL_REASONS:
            raise ValueError(
                f"terminal reason {reason!r} is not a harness terminal")
        return cls(
            verdict="unsuccessful", reason=reason, clean=False, error=error,
            iterations=iterations,
            init_validation=tuple(init_validation),
        )


def _lock_for(spec_id: str, run_id: str) -> threading.Lock:
    key = (spec_id, run_id)
    with _LOCK_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _clear_resume(store: Any, spec_id: str, run_id: str) -> None:
    clear = getattr(store, "clear_resume", None)
    if clear is None:
        return
    try:
        clear(spec_id, run_id)
    except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
        logger.warning("pod resume cursor cleanup failed (%s)", exc)


def _assemble(
    terminal: PodTerminal,
    log: ExperimentLog | None,
    iterations: int,
) -> dict:
    export = PodExport(
        verdict=terminal.verdict,
        terminal_reason=terminal.reason,
        iterations=iterations,
        clean=terminal.clean,
        init_validation=list(terminal.init_validation),
        variant_specs=[v.model_dump() for v in log.variant_specs] if log else [],
        raw_observations=[o.model_dump() for o in log.raw_observations] if log else [],
        interpretations=[i.model_dump() for i in log.interpretations] if log else [],
        error=terminal.error,
    )
    return export.to_envelope()


def _normalise_terminal(terminal: PodTerminal) -> PodTerminal:
    """Enforce the harness rule even on a directly constructed PodTerminal."""
    if terminal.reason not in TERMINAL_REASONS:
        raise ValueError(
            f"terminal reason {terminal.reason!r} is not in the pod vocabulary")
    if terminal.reason in HARNESS_TERMINAL_REASONS:
        return PodTerminal(
            verdict="unsuccessful", reason=terminal.reason, clean=False,
            error=terminal.error, iterations=terminal.iterations,
            init_validation=terminal.init_validation,
        )
    if terminal.verdict not in ("successful", "unsuccessful"):
        raise ValueError(f"verdict {terminal.verdict!r} is not a binary pod verdict")
    if not isinstance(terminal.clean, bool):
        raise ValueError("clean must be a boolean")
    return terminal


def finalize_pod(
    *,
    store: Any,
    spec_id: str,
    run_id: str,
    terminal: PodTerminal | None = None,
    log: ExperimentLog | None = None,
    envelope: dict | None = None,
    replace_existing: bool = False,
) -> dict:
    """Write the pod's terminal once and return the durable envelope.

    `terminal` is the pod graph or surfer path. `log` optionally supplies the
    in-memory trail; otherwise the finalizer hydrates it from the store.
    `envelope` is the already-built envelope a normal `arun_pod` return hands
    back; it is written only when no terminal exists yet.

    Mechanical ownership rule:

    - a scheduler backstop (`replace_existing=False`) never overwrites an
      existing terminal; it is a fallback;
    - a pod execution terminal (`replace_existing=True`) is authoritative and
      replaces a prior export for the same spec and run, so a legitimate
      re-dispatch of the same spec still rewrites its own result.

    The graph and the surfer are therefore idempotent clients of one writer,
    and the surfer can never downgrade a domain terminal to a backstop terminal.
    """
    if terminal is None and envelope is None:
        raise ValueError("finalize_pod needs a terminal or an envelope")
    if envelope is not None and not isinstance(envelope, dict):
        raise ValueError("envelope must be a mapping")
    if terminal is not None:
        terminal = _normalise_terminal(terminal)

    spec_key = str(spec_id or "")
    run_key = str(run_id or "")
    lock = _lock_for(spec_key, run_key)
    with lock:
        # A fallback terminal never overwrites an existing terminal. An
        # execution terminal is authoritative and may replace its own prior
        # export (the legitimate re-run case).
        if store is not None and spec_key and run_key:
            reader = getattr(store, "read_pod_export", None)
            if reader is not None:
                try:
                    existing = reader(spec_key, run_key)
                except Exception as exc:  # noqa: BLE001
                    # An unreadable export is not proof of absence.
                    logger.warning("pod export read failed (%s)", exc)
                    existing = {}
                if existing and not replace_existing:
                    _clear_resume(store, spec_key, run_key)
                    return existing

        if envelope is not None:
            built = envelope
        else:
            cursor: dict = {}
            if store is not None and spec_key and run_key:
                resume_reader = getattr(store, "read_resume", None)
                if resume_reader is not None:
                    try:
                        cursor = resume_reader(spec_key, run_key) or {}
                    except Exception as exc:  # noqa: BLE001 - resume is best-effort
                        logger.warning("pod resume cursor read failed (%s)", exc)
                        cursor = {}
            evidence = log
            if evidence is None and store is not None and spec_key:
                evidence = ExperimentLog(store=store, spec_id=spec_key)
                try:
                    evidence.hydrate()
                except Exception as exc:  # noqa: BLE001 - partial evidence is still evidence
                    logger.warning(
                        "pod finalizer could not hydrate the trail (%s)", exc)
            iterations = terminal.iterations
            if iterations is None:
                raw_iteration = cursor.get("iteration")
                if raw_iteration is not None:
                    try:
                        iterations = int(raw_iteration)
                    except (TypeError, ValueError):
                        iterations = None
            if iterations is None:
                iterations = len(evidence.variant_specs) if evidence else 0
            built = _assemble(terminal, evidence, iterations)

        if store is not None and spec_key and run_key:
            writer = getattr(store, "write_pod_export", None)
            if writer is not None:
                try:
                    writer(spec_key, run_key, built)
                except Exception as exc:  # noqa: BLE001 - fail-open (O3/IA-4)
                    logger.warning(
                        "pod export persistence failed; returning the in-memory "
                        "envelope (%s)", exc)
                    return built
            _clear_resume(store, spec_key, run_key)
        return built


__all__ = ["PodTerminal", "finalize_pod"]
