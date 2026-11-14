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
from polymerhus.attack.hunting.pod.pod_memory import (
    order_of,
    read_variant_summary,
)
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


def _terminal_order(
    store: Any,
    spec_id: str,
    run_id: str,
    log: ExperimentLog | None,
) -> int:
    """The variant order the pod terminated on.

    The in-memory log is authoritative when present (its `variant_specs` list
    is the symbolic variant sequence). Otherwise the resume cursor names the
    last variant, and a bare store falls back to the highest persisted order.
    """
    if log is not None and log.variant_specs:
        return len(log.variant_specs) - 1
    reader = getattr(store, "read_resume", None)
    if reader is not None:
        try:
            cursor = reader(spec_id, run_id) or {}
        except Exception:  # noqa: BLE001 - the cursor is best-effort
            cursor = {}
        raw_order = cursor.get("last_order")
        if raw_order is not None:
            try:
                return int(raw_order)
            except (TypeError, ValueError):
                pass
        ref = cursor.get("current_variant_ref")
        if ref:
            return order_of(str(ref))
    lister = getattr(store, "list_variant_orders", None)
    if lister is not None:
        try:
            orders = lister(spec_id)
        except Exception:  # noqa: BLE001 - the check is best-effort
            orders = []
        if orders:
            return max(orders)
    return 0


def _check_terminal_summary(
    store: Any,
    spec_id: str,
    run_id: str,
    log: ExperimentLog | None,
) -> None:
    """The finalizer's last-layer check for the current variant's summary.

    The graph's terminal gate asks the Runner for a missing summary. The
    finalizer verifies the result and records a remaining gap; it never writes
    a synthetic summary, because a hard teardown may have destroyed the live
    context and a fabricated consolidation would be false evidence.
    """
    if store is None or not spec_id:
        return
    order = _terminal_order(store, spec_id, run_id, log)
    try:
        summary = read_variant_summary(store, spec_id, order)
    except Exception as exc:  # noqa: BLE001 - the check never gates the export
        logger.warning(
            "pod terminal summary check failed for %s order %s (%s)",
            spec_id, order, exc)
        return
    if not summary.strip():
        logger.warning(
            "pod terminal %s/%s order %s has no experiment_summary",
            spec_id, run_id, order)


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


def _export_reason(envelope: Any) -> str:
    """The terminal reason of a persisted envelope, or '' when absent."""
    if not isinstance(envelope, dict):
        return ""
    evidence = envelope.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    return str(evidence.get("terminal_reason") or "")


def _latched(envelope: Any) -> bool:
    """Whether a persisted envelope is an EVALUABLE terminal (monotonicity
    rule d): a binary verdict AND a terminal reason from the pod vocabulary.
    Anything else - no verdict, an empty verdict, no reason, or a foreign
    reason - does not latch, so the next write may fill it."""
    if not isinstance(envelope, dict):
        return False
    if envelope.get("verdict") not in ("successful", "unsuccessful"):
        return False
    return _export_reason(envelope) in TERMINAL_REASONS


def _is_domain(envelope: Any) -> bool:
    """Whether a terminal (a PodTerminal or an envelope) is a DOMAIN verdict."""
    if isinstance(envelope, PodTerminal):
        return envelope.reason in DOMAIN_TERMINAL_REASONS
    return _export_reason(envelope) in DOMAIN_TERMINAL_REASONS


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

    Monotonicity ladder (the ratified lifecycle v2 rules, enforced here because
    this is the ONE writer):

    1. a latched DOMAIN verdict is final: no later write replaces it, whatever
       `replace_existing` says;
    2. a DOMAIN verdict may replace a latched HARNESS terminal (the pod did
       evaluate after the infrastructure stop); the superseded control-plane
       end reason survives additively as `evidence.control_plane_end_reason`;
    3. a HARNESS terminal may replace a latched HARNESS terminal only through
       the `replace_existing` policy;
    4. an unlatched export (no verdict, an empty verdict, or no terminal
       reason) never latches: the next write fills it, even from the backstop.

    The graph and the surfer are therefore idempotent clients of one writer,
    and no caller can downgrade a domain terminal to a backstop terminal.
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
        # The monotonicity gate. An unlatched export does not latch, so the
        # write falls through and fills it. A latched domain verdict is final.
        # A latched harness terminal yields to a domain verdict (rule 2) and
        # yields to another harness terminal only under `replace_existing`
        # (rule 3).
        superseded_reason = ""
        if store is not None and spec_key and run_key:
            reader = getattr(store, "read_pod_export", None)
            if reader is not None:
                try:
                    existing = reader(spec_key, run_key)
                except Exception as exc:  # noqa: BLE001
                    # An unreadable export is not proof of absence.
                    logger.warning("pod export read failed (%s)", exc)
                    existing = {}
                if existing:
                    latched = _latched(existing)
                    if latched and not replace_existing \
                            and not _is_domain(terminal or {}):
                        _clear_resume(store, spec_key, run_key)
                        _check_terminal_summary(store, spec_key, run_key, log)
                        return existing
                    if latched and _is_domain(existing):
                        _clear_resume(store, spec_key, run_key)
                        _check_terminal_summary(store, spec_key, run_key, log)
                        return existing
                    if latched and not _is_domain(existing) \
                            and _is_domain(terminal or {}):
                        superseded_reason = _export_reason(existing)

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
                if superseded_reason:
                    # Monotonicity rule 2: the control-plane end reason the
                    # harness wrote survives the domain replacement as an
                    # additive fact. A domain verdict says what the evidence
                    # shows; this says why the runner stopped. Both are true.
                    evidence = built.get("evidence")
                    if isinstance(evidence, dict):
                        evidence["control_plane_end_reason"] = superseded_reason
                try:
                    writer(spec_key, run_key, built)
                except Exception as exc:  # noqa: BLE001 - fail-open (O3/IA-4)
                    logger.warning(
                        "pod export persistence failed; returning the in-memory "
                        "envelope (%s)", exc)
                    return built
            _clear_resume(store, spec_key, run_key)
        _check_terminal_summary(store, spec_key, run_key, log)
        return built


__all__ = ["PodTerminal", "finalize_pod"]
