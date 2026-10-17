"""The bootstrap loop: lifecycle, phases, gates, repair, teardown, resume.

This is THE high seam of the module (the architecture doc, section 3.1). One
target at a time, in plan order:

    observe(target)  ->  reuse if ready, else up + a bounded readiness wait
    dispatch the authn wrapper        (the target's creator session)
    gate auth-only                    -> red? re-dispatch the verbatim errors,
                                         bounded, then fail the target
    dispatch the l1 wrapper           (the SAME session)
    gate full                         -> red? the same bounded repair
    down(target)  ->  observe  ->  require ZERO containers

Decisions are made from the environment's RAW signals (`Observation`),
interpreted by the pure helpers in `runner.env`: readiness reuses the platform's
own rules (`ServiceHealth.ready` semantics plus a non-5xx HTTP answer) and
teardown is an observation, never an assumption. Leftovers are recorded as
evidence and reported.

Failure policy: a target whose phases cannot be made green is marked failed and
the run CONTINUES to the next target (default). `continue_on_failure: false`
stops after the failed target. Every target is torn down and verified, including
a failed one (`teardown_on_failure: false` keeps it up for debugging).

No phase of this loop reads the ground truth, and no phase of it prunes
anything: the two validator gates are the only quality checkpoints.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from runner import state as state_mod
from runner.config import RunConfig
from runner.env import Observation, not_ready_reason, project_name
from runner.gates import AUTH_ONLY, FULL
from runner.harness import (
    HarnessError,
    SessionSpec,
    TurnResult,
    TurnTimeout,
    assistant_text,
    transcript_tail,
)
from runner.state import DONE, FAILED, PENDING
from runner.wrappers import WrapperFacts, WrapperSources, authn_wrapper, l1_wrapper

# The two phases, in order. The phase names are load-bearing: they are the state
# keys, the log directory names, and the `status` column names.
PHASES = ("authn", "l1")

# The hosts that never name a real target: targetctl prints `0.0.0.0`, a local
# run reaches itself through `127.0.0.1`/`localhost`, and `::` is the v6 wildcard.
PLACEHOLDER_HOSTS = frozenset({"0.0.0.0", "127.0.0.1", "localhost", "::", "[::]"})

# How much of the transcript a per-turn log carries.
TRANSCRIPT_TAIL_LIMIT = 40

# Where a target's pre-existing data dependencies are moved aside, under the
# run directory. The slot doubles as the idempotence marker (see
# `archive_pre_existing`): once it exists, that root was already handled.
PRE_EXISTING = "pre-existing"


def archive_pre_existing(
    rundir: Path, target: str, sources: Mapping[str, Path]
) -> list[tuple[str, str]]:
    """Move a target's pre-existing data dependencies aside, once per run.

    The run regenerates every artifact FROM SCRATCH (issue #358): anything a
    previous run left in an output root must not be readable by this run's
    workers, and must not survive a phase that fails to overwrite it. The
    destination is the idempotence marker: once a slot exists, an earlier entry
    or a resume already handled that root, so fresh artifacts written since are
    never touched. A source that never existed still gets its (empty) slot, so a
    resume after a phase wrote fresh artifacts never re-examines the root.
    """
    archived: list[tuple[str, str]] = []
    root = rundir / target / PRE_EXISTING
    for label, source in sources.items():
        slot = root / label
        if slot.exists():
            continue
        if source.exists():
            slot.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(slot))
            archived.append((label, str(slot)))
        else:
            slot.mkdir(parents=True, exist_ok=True)
    return archived


@dataclass(frozen=True)
class Dispatch:
    """The wrapper (or repair message) one phase dispatch sends."""

    text: str
    label: str = "dispatch"


@dataclass(frozen=True)
class GateDirective:
    """One phase's gate requirement: the validator mode it is gated with.

    Both phases of the loop are always gated (the architecture doc, section 3.5);
    there is no ungated phase, so the directive carries only the mode.
    """

    mode: str = FULL


@dataclass
class PhaseResult:
    """The outcome of one phase: whether it is green, and why not."""

    ok: bool
    reason: str = ""


@dataclass
class RunSummary:
    """What the run did, for the CLI's closing report."""

    run_id: str
    completed: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    # Targets whose teardown could not be verified (leftover containers). This is
    # REPORTING only: a leftover never fails a target, but it is never silent.
    teardown_unverified: tuple[str, ...] = ()
    stopped_early: bool = False
    notes: list[str] = field(default_factory=list)
    state_path: Path | None = None

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


def rewrite_base_url(url: str, *, public_host: str) -> str:
    """Point the workers' base URL at a reachable host.

    The rewrite is for the WORKERS only: targetctl prints the wildcard bind
    (`http://0.0.0.0:<port>/`), and a local run prints loopback. Any other host
    is a real one and is left exactly as reported. The path is preserved (a
    target may be rooted at one).
    """
    if not url or not public_host:
        return url
    parts = urlsplit(url)
    if parts.hostname in PLACEHOLDER_HOSTS:
        host = public_host
        netloc = f"{host}:{parts.port}" if parts.port else host
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


def ready_to_work(observation: Observation) -> str | None:
    """The readiness reason, or None when the target can be worked on."""
    return not_ready_reason(observation)


def build_instructions(
    config: RunConfig,
    *,
    facts_for: Callable[[str], WrapperFacts],
    sources_for: Callable[[str], WrapperSources],
    validator_invocation: Callable[[str, str], str],
    target: str | None = None,
) -> dict[str, Dispatch]:
    """Build the authn and L1 wrappers for one target from the versioned carriers.

    The wrappers are pure builders; the caller's `sources_for` performs the only
    side effect - reading the carrier file the phase needs (keyed by gate mode) -
    and hands the text in. The validator invocation is overwritten here so the
    mode's exact command is the one the wrapper names.
    """
    name = target or config.run.targets[0]
    facts = facts_for(name)

    def sources_for_mode(mode: str) -> WrapperSources:
        source = sources_for(mode)
        return replace(
            source, validator_invocation=validator_invocation(name, mode)
        )

    return {
        "authn": Dispatch(
            text=authn_wrapper(facts, sources_for_mode(AUTH_ONLY)),
            label="dispatch",
        ),
        "l1": Dispatch(
            text=l1_wrapper(facts, sources_for_mode(FULL)),
            label="dispatch",
        ),
    }


def build_instructions_for_all(
    config: RunConfig,
    *,
    facts_for: Callable[[str], WrapperFacts],
    sources_for: Callable[[str], WrapperSources],
    validator_invocation: Callable[[str, str], str],
) -> dict[str, dict[str, Dispatch]]:
    """One wrapper pair per target, so a multi-target run gets real per-target text."""
    return {
        target: build_instructions(
            config,
            facts_for=facts_for,
            sources_for=sources_for,
            validator_invocation=validator_invocation,
            target=target,
        )
        for target in config.run.targets
    }


class Orchestrator:
    """The run loop, wired to injected seams: harness, environment, gate, state."""

    def __init__(
        self,
        *,
        config: RunConfig,
        harness,
        env,
        gate,
        state: state_mod.RunState,
        rundir: Path,
        instructions: Mapping[str, object] | Callable[[str], Mapping[str, Dispatch]],
        write_log: Callable[[Path, str], Path] | None = None,
        sleep: Callable[[float], None] | None = None,
        skip_lifecycle: bool = False,
    ) -> None:
        self.config = config
        self.harness = harness
        self.env = env
        self.gate = gate
        self.state = state
        self.rundir = Path(rundir)
        self.instructions = instructions
        self.skip_lifecycle = skip_lifecycle
        self._write_log = write_log or _write_text
        self.sleep = sleep or _noop
        self.notes: list[str] = []
        # One creator session per target per run: `create_session` is the
        # adopt-or-create call, and a resume must not issue a second session.
        self._sessions: dict[str, str] = {}

    # --- entry ---

    def run_plan(self, *, targets: Sequence[str] | None = None) -> RunSummary:
        """Run, or resume, the plan: one target at a time, serial, in plan order.

        The loop always resumes from the state: a target whose phases are all
        complete is skipped with its record intact, and a target with an
        incomplete phase starts at that phase. Nothing complete is replayed.
        """
        selected = list(targets) if targets else list(self.config.run.targets)
        unknown = [target for target in selected if target not in set(self.config.run.targets)]
        if unknown:
            raise ValueError(f"targets not in the config: {', '.join(unknown)}")
        self.state.status = state_mod.RUN_ACTIVE
        self._save()

        summary = RunSummary(run_id=self.state.run_id)
        halted = False
        for target in selected:
            if halted:
                break
            if self.state.first_incomplete_phase(target) is None:
                record = self.state.target(target)
                record.notes.append(f"{target}: all phases already complete; skipped")
                summary.skipped += (target,)
                self._save()
                continue
            if self._run_target(target) == "done":
                summary.completed += (target,)
            else:
                summary.failed += (target,)
                if not self.config.run.continue_on_failure:
                    summary.stopped_early = True
                    halted = True

        summary.notes = list(self.notes)
        summary.state_path = self._save()
        # Teardown leftovers are evidence on EVERY run, including a resumed one
        # whose targets were completed by an earlier process.
        summary.teardown_unverified = tuple(
            target
            for target in selected
            if self.state.target(target).lifecycle.leftovers
        )
        self.state.status = state_mod.RUN_FAILED if summary.failed else state_mod.RUN_DONE
        self._save()
        return summary

    # --- one target ---

    def _run_target(self, target: str) -> str:
        record = self.state.target(target)
        record.status = state_mod.ACTIVE
        self._save()
        failed = False
        try:
            self._archive_target_dependencies(target)
            self._ensure_ready(target)
        except TargetNotReadyError as failure:
            record.notes.append(str(failure))
            self.notes.append(f"{target}: {failure}")
            failed = True
        except OSError as failure:
            record.notes.append(f"{target}: pre-existing artifacts could not be archived: {failure}")
            self.notes.append(f"{target}: pre-existing artifacts could not be archived: {failure}")
            failed = True
        else:
            for phase, directive in zip(PHASES, self._directives()):
                phase_state = record.phases.get(phase)
                if phase_state is not None and phase_state.complete:
                    continue
                result = self._run_phase(target, phase, directive)
                if not result.ok:
                    self.notes.append(f"{target}: {phase} failed: {result.reason}")
                    failed = True
                    break
        self._teardown(target, failed)
        record.status = FAILED if failed else DONE
        self._save()
        return "failed" if failed else "done"

    def _directives(self) -> tuple[GateDirective, ...]:
        return (GateDirective(mode=AUTH_ONLY), GateDirective(mode=FULL))

    def _archive_target_dependencies(self, target: str) -> None:
        """Move a target's pre-existing KB and auth bundle aside, once per run.

        The run is from scratch: a prior run's artifacts (in particular a
        research-notes.md that must not survive, or a stale authn skill that
        would hide a `mechanism: none` result) are archived under the run
        directory before the target's first dispatch. The slots are the
        idempotence markers, so a resume never re-archives fresh artifacts.
        """
        sources = {
            "kb": self.config.paths.target_dir(target),
            "auth-bundle": self.config.paths.staging / target,
        }
        archived = archive_pre_existing(self.rundir, target, sources)
        if not archived:
            return
        record = self.state.target(target)
        for label, slot in archived:
            record.notes.append(f"{target}: archived pre-existing {label} -> {slot}")
            self.notes.append(f"{target}: archived pre-existing {label} -> {slot}")
        self._save()

    def _ensure_ready(self, target: str) -> Observation:
        """Observe, reuse when ready, else up plus a bounded readiness wait."""
        record = self.state.target(target)
        observation = self.env.observe(target)
        if ready_to_work(observation) is None:
            record.lifecycle.reused = True
            record.notes.append(f"{target}: reused the already-ready deployment")
            record.base_url = self._worker_url(observation)
            self._save()
            return observation
        if self.skip_lifecycle:
            raise TargetNotReadyError(
                f"{target}: not ready ({ready_to_work(observation)}) and the "
                "lifecycle is disabled"
            )
        result = self.env.up(target)
        record.lifecycle.up = {
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-2000:],
            "stderr": (result.stderr or "")[-2000:],
        }
        record.notes.append(f"{target}: deployed (targetctl exit {result.returncode})")
        self._save()
        return self._wait_ready(target)

    def _wait_ready(self, target: str) -> Observation:
        """Poll the raw observation until every signal agrees, or fail loudly."""
        record = self.state.target(target)
        policy = self.config.run.readiness
        last: Observation | None = None
        reason = "no observation yet"
        for attempt in range(max(1, policy.retries)):
            last = self.env.observe(target)
            reason = ready_to_work(last)
            if reason is None:
                record.base_url = self._worker_url(last)
                record.notes.append(f"{target}: ready after {attempt + 1} observation(s)")
                self._save()
                return last
            self.sleep(policy.interval_s)
        record.notes.append(f"{target}: never ready ({reason})")
        self._save()
        raise TargetNotReadyError(f"{target} did not become ready: {reason}")

    def _worker_url(self, observation: Observation) -> str | None:
        """The base URL a worker is handed: targetctl's URL, host rewritten."""
        if not observation.url:
            return None
        return rewrite_base_url(
            observation.url, public_host=self.config.environment.public_host
        )

    # --- phases ---

    def _run_phase(self, target: str, phase: str, directive: GateDirective) -> PhaseResult:
        record = self.state.target(target)
        phase_state = record.phase(phase)
        instructions = self._instructions_for(target)
        if phase not in instructions:
            raise RuntimeError(
                f"{target}: no {phase} wrapper is configured; refusing to skip a phase"
            )

        self._prepare_phase(phase_state, target)
        dispatch = instructions[phase]
        try:
            self._drive_turn(target, phase, dispatch, phase_state)
        except TargetPhaseFailed as failure:
            # A red READ is never gated: the gate would only re-report what the
            # phase never produced, and the phase is incomplete either way.
            phase_state.read = FAILED
            phase_state.finished = state_mod.utc_now()
            phase_state.notes.append(failure.reason)
            record.notes.append(f"{target}: {phase} {failure.reason}")
            self._save()
            return PhaseResult(ok=False, reason=failure.reason)
        phase_state.read = DONE
        return self._repair_loop(target, phase, directive, phase_state, record)

    def _prepare_phase(self, phase_state, target: str) -> None:
        """Mark the phase active and its gate pending again.

        A resumed phase keeps its counters and its logs: the evidence is
        append-only, and the turn numbers continue where the crash left off.
        """
        phase_state.read = state_mod.ACTIVE
        if phase_state.gate != DONE:
            phase_state.gate = PENDING
        phase_state.started = state_mod.utc_now()
        phase_state.session = self.state.target(target).creator_session(self.state.run_id)
        self._save()

    def _drive_turn(
        self, target: str, phase: str, dispatch: Dispatch, phase_state
    ) -> TurnResult:
        """Send one dispatch and await its terminal turn, with the bounded policies.

        Three bounded policies live here, and no unbounded loop does:

        * a retryable harness failure - a failed turn, a prompt that never went
          out, a broken transcript read, a session that could not be created -
          backs off along the configured ladder (default 60/300/900s, three
          attempts) and then fails the phase;
        * a stalled turn (the harness's `TurnTimeout`) is interrupted and
          re-prompted ONCE with a short resume instruction (`timeout_reprompts`),
          then fails the phase;
        * a non-retryable harness failure fails the phase immediately.

        Every exit is either an OK `TurnResult` or `TargetPhaseFailed`: session
        creation is inside the guarded region too, so neither a repair turn nor
        a target's first dispatch can abort `run_plan`.
        """
        attempts = max(1, self.config.run.retry.attempts)
        backoff = self.config.run.retry.backoff_s
        tries = 0
        timeouts = phase_state.timeouts
        reprompts = max(0, self.config.run.timeout_reprompts)
        text = dispatch.text
        label = dispatch.label
        record = self.state.target(target)
        session = record.creator_session(self.state.run_id)
        model = self.config.run.model_for(target)
        header = f"session={session}\nmodel={model.provider_id}/{model.id}#{model.variant}"

        def retry_delay() -> float:
            return backoff[min(tries, len(backoff) - 1)] if backoff else 0.0

        while True:
            phase_state.turns += 1
            index = phase_state.turns
            try:
                self._ensure_session(target)
                self.harness.prompt(session, text)
                turn = self.harness.wait_terminal(
                    session, timeout_s=self.config.run.turn_timeout_s
                )
            except TurnTimeout as failure:
                self._log_turn(
                    target,
                    phase,
                    index,
                    f"{label}-timeout",
                    text,
                    str(failure) + "\n",
                    header=header,
                )
                timeouts += 1
                phase_state.timeouts = timeouts
                if timeouts > reprompts:
                    raise TargetPhaseFailed(
                        f"no terminal turn after {timeouts} attempt(s): {failure}"
                    ) from failure
                self.harness.interrupt(session)
                text = _resume_instruction()
                label = "resume"
                self._save()
                continue
            except HarnessError as failure:
                # A provider or transport failure: the SAME ladder a failed
                # turn gets. Never the timeout branch, which would interrupt a
                # session that may not be running and swallow the backoff.
                self._log_turn(
                    target,
                    phase,
                    index,
                    f"{label}-error",
                    text,
                    str(failure) + "\n",
                    header=header,
                )
                if not failure.retryable or tries >= attempts - 1:
                    raise TargetPhaseFailed(f"harness failure: {failure}") from failure
                delay = retry_delay()
                tries += 1
                phase_state.notes.append(f"{label}: retry in {delay:.0f}s after {failure}")
                self._save()
                self.sleep(delay)
                text = _resume_instruction()
                label = "retry"
                continue
            self._log_turn(target, phase, index, label, text, _turn_log(turn), header=header)
            if turn.ok:
                return turn
            detail = turn.error or f"turn outcome {turn.outcome}"
            if not turn.retryable:
                raise TargetPhaseFailed(f"turn failed: {detail}")
            if tries >= attempts - 1:
                raise TargetPhaseFailed(
                    f"provider failure after {attempts} attempt(s): {detail}"
                )
            delay = retry_delay()
            tries += 1
            phase_state.notes.append(f"{label}: retry in {delay:.0f}s after {detail}")
            self._save()
            self.sleep(delay)
            text = _resume_instruction()
            label = "retry"

    def _repair_loop(
        self,
        target: str,
        phase: str,
        directive: GateDirective,
        phase_state,
        record,
    ) -> PhaseResult:
        """Gate, and on red re-dispatch the verbatim errors; bounded, then fail."""
        attempts = max(1, self.config.run.repair_attempts)
        for attempt in range(attempts + 1):
            result = self._run_gate(target, phase, directive, phase_state, record)
            if result.ok:
                return PhaseResult(ok=True)
            if attempt >= attempts:
                return PhaseResult(
                    ok=False, reason=f"gate {directive.mode} red after {attempts} repair(s)"
                )
            phase_state.repairs += 1
            record.repair_attempts += 1
            text = _repair_instruction(result.failure_text, target, phase)
            try:
                # `_drive_turn` returns an OK turn or raises TargetPhaseFailed:
                # a repair dispatch that cannot be driven fails THIS phase, and
                # the target goes failed without aborting the rest of the run.
                self._drive_turn(
                    target, phase, Dispatch(text=text, label="repair"), phase_state
                )
            except TargetPhaseFailed as failure:
                return PhaseResult(ok=False, reason=failure.reason)
            self._save()
        return PhaseResult(ok=False, reason="repair budget exhausted")

    def _run_gate(
        self, target: str, phase: str, directive: GateDirective, phase_state, record
    ):
        result = self.gate.run(target, directive.mode)
        phase_state.gate_output = result.failure_text
        phase_state.gate = DONE if result.ok else FAILED
        record.gates[directive.mode] = phase_state.gate
        if result.ok:
            phase_state.finished = state_mod.utc_now()
            record.notes.append(f"{target}: {phase} gate {directive.mode} OK")
        else:
            record.notes.append(
                f"{target}: {phase} gate {directive.mode} red; output recorded verbatim"
            )
        self._log_gate(target, phase, phase_state.turns, directive.mode, result)
        self._save()
        return result

    # --- sessions ---

    def _ensure_session(self, target: str) -> str:
        """Create (or adopt) the target's deterministic creator session, once per run.

        Both phases of a target run in the SAME session, and a resume adopts the
        live session with the deterministic id (`create_session` handles the
        duplicate id), so the create call is issued once per target per run.
        """
        cached = self._sessions.get(target)
        if cached:
            return cached
        record = self.state.target(target)
        session = record.creator_session(self.state.run_id)
        model = self.config.run.model_for(target)
        record.model = {
            "providerID": model.provider_id,
            "id": model.id,
            "variant": model.variant,
        }
        spec = SessionSpec(
            session_id=session,
            title=f"external bootstrap {self.state.run_id} {target}",
            agent=self.config.run.agent,
            model=model,
            directory=str(self.config.run.worktree),
            metadata={
                "bootstrap_run": self.state.run_id,
                "target": target,
                "phase": "creator",
            },
        )
        created = self.harness.create_session(spec)
        if created != session:
            # A harness is allowed to answer with the id it adopted, but the
            # state's deterministic id must hold or resume would lose the session.
            raise HarnessError(
                f"harness created {created!r} instead of the deterministic {session!r}"
            )
        self._sessions[target] = session
        return session

    # --- teardown ---

    def _teardown(self, target: str, failed: bool) -> None:
        """Down, then REQUIRE the observation to show zero containers."""
        record = self.state.target(target)
        if failed and not self.config.run.teardown_on_failure:
            record.notes.append(f"{target}: teardown skipped after a failure (policy)")
            self._save()
            return
        if self.skip_lifecycle:
            record.notes.append(f"{target}: lifecycle disabled; teardown not attempted")
            self._save()
            return
        result = self.env.down(target)
        record.lifecycle.teardown = {
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[-2000:],
            "stderr": (result.stderr or "")[-2000:],
        }
        if not supported_containers(self.env):
            record.lifecycle.verified_teardown = None
            record.notes.append(
                f"{target}: teardown unverifiable (this driver exposes no container facts)"
            )
            self._save()
            return
        observation = self.env.observe(target)
        remaining = observation.containers
        record.lifecycle.leftovers = [fact.name for fact in remaining]
        record.lifecycle.verified_teardown = not remaining
        if remaining:
            names = ", ".join(record.lifecycle.leftovers)
            record.notes.append(
                f"{target}: {len(remaining)} leftover container(s) after down: {names}"
            )
            self.notes.append(
                f"{target}: {project_name(target)} has {len(remaining)} leftover "
                f"container(s): {names}"
            )
        else:
            record.notes.append(f"{target}: teardown verified (zero containers)")
        self._save()

    # --- instruction access, logs, persistence ---

    def _instructions_for(self, target: str) -> Mapping[str, Dispatch]:
        """The wrappers for one target, from every accepted shape.

        A CALLABLE is the production shape: the CLI builds a target's wrappers
        lazily, because their base URL comes from the readiness observation. A
        mapping keyed by target is what `build_instructions_for_all` returns; the
        single-target `build_instructions` keys by phase, and that flat mapping is
        taken as the answer for every target asked for.
        """
        source = self.instructions(target) if callable(self.instructions) else self.instructions
        entry = source.get(target)
        if entry is None:
            flat = {
                phase: source[phase]
                for phase in PHASES
                if phase in source
            }
            return flat
        if isinstance(entry, Mapping):
            return entry
        return {"authn": entry}  # a single wrapper: the authn phase only

    def _log_turn(
        self,
        target: str,
        phase: str,
        index: int,
        label: str,
        prompt: str,
        extra: str,
        *,
        header: str = "",
    ) -> Path:
        """One dispatch's evidence: who ran it, the prompt sent, the turn's tail."""
        body = f"{header}\n\n" if header else ""
        if prompt:
            body += f"### prompt\n\n{prompt}\n\n"
        if extra:
            body += f"### turn\n\n{extra}"
        path = self._log_path(target, phase, index, label)
        self._record_log(target, phase, path)
        return self._write_log(path, body)

    def _log_gate(self, target: str, phase: str, index: int, mode: str, result) -> Path:
        body = f"### command\n\n{' '.join(result.command)}\n\n### output\n\n{result.output}\n"
        path = self._log_path(target, phase, index, f"gate-{mode}")
        self._record_log(target, phase, path)
        return self._write_log(path, body)

    def _record_log(self, target: str, phase: str, path: Path) -> None:
        """Register the log on the phase state (so `status` shows its evidence).

        The path is stored rundir-relative: the state and its logs move together.
        """
        record = self.state.target(target)
        record.phase(phase).logs.append(str(path.relative_to(self.rundir)))

    def _log_path(self, target: str, phase: str, index: int, label: str) -> Path:
        return self.rundir / target / phase / f"{index:02d}-{label}.log"

    def _save(self) -> Path:
        return self.state.save(self.rundir)


def supported_containers(env) -> bool:
    """Whether this driver can report container facts (a duck-typed probe)."""
    probe = getattr(env, "supported_containers", None)
    if callable(probe):
        return bool(probe())
    return True


class TargetNotReadyError(RuntimeError):
    """A deployment never reached readiness inside its bounded window."""


class TargetPhaseFailed(RuntimeError):
    """A phase could not be made green inside its budgets."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _turn_log(turn: TurnResult) -> str:
    return (
        f"outcome={turn.outcome} ok={turn.ok} retryable={turn.retryable} "
        f"error_status={turn.error_status}\n"
        f"model={json.dumps(turn.model)}\n\n"
        f"{transcript_tail(turn, limit=TRANSCRIPT_TAIL_LIMIT)}\n\n"
        f"### assistant report\n\n{assistant_text(turn)}\n"
    )


def _resume_instruction() -> str:
    return (
        "Resume where you stopped. Do not restart from the beginning and do not repeat "
        "completed work: check what already exists on disk and in the target, finish the "
        "remaining steps of your wrapper, then run the validator command it names until "
        "it prints OK."
    )


def _repair_instruction(failure_text: str, target: str, phase: str) -> str:
    return (
        f"The shape validator rejected the {phase} phase output for target `{target}`.\n"
        "Its output follows verbatim.\n"
        "Fix ONLY what it reports, re-run the validator command from your wrapper until "
        "it prints OK, and stop when it does.\n"
        "Do not redo the phase from scratch, and do not edit the validator.\n\n"
        "```\n"
        f"{failure_text.strip()}\n"
        "```"
    )


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _noop(_seconds: float) -> None:
    """A sleep seam the tests replace; production passes `time.sleep`."""
