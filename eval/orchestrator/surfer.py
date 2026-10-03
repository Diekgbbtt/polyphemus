"""The surfer loop: background state assertion and lifecycle recovery (#275, D5/D31/N17).

The symbolic layer owns lifecycle (D5). The trial engine enforces the hunting cap
and stops a run at a failed terminal; the surfer is the background supervisor
that asserts the environment state, detects a cap-reached or failed state (a
failed/interrupted run, or a credit-exhaustion-like failure signal), and prompts
the orchestrator. The orchestrator decides exactly one of:

- `terminate`: stop the in-flight run(s) cleanly through the REST seam;
- `destroy`: tear the instance down through `instances.down`;
- `fix`: a repair bounded to the configuration layer (the `.env` preflight and
  recreate) or the data layer (re-place pre-mined hunting artifacts), then
  restart the affected services and resume the trial at its recorded phase;
- `escalate`: write a surfer hold (the same mechanism an alignment escalation
  uses) and stop until an operator resolves it.

No code change is ever applied. A decision the loop does not recognise as one of
the three bounded actions, or a `fix` whose repair is not in the enumerated
bounded set, becomes an escalation - structurally, in `_resolve`, not by trusting
the prompt. A structural escalation records the handled trigger exactly like an
explicit `escalate`, so an unchanged trigger is not re-dispatched each cycle.

A trigger is acted on once: its deterministic identity (`trigger_key`) is
recorded in the alignment state through `record_applied`, so a long-running loop
skips a trigger it already handled and a new record (a new run or phase) is a new
identity that prompts afresh. The record survives a loop restart; `alignment
resolve` never clears it, so an escalated trigger stays disarmed after the hold
is resolved. The operator remedy is to start the trial manually (a new run/phase
is a new identity that the loop acts on); there is deliberately no re-arm verb,
because re-arming an unchanged record would only re-escalate.

Every effect is injected - the state source, the decider agent turn, the command
runner, the REST client, the repair kit, the trial resumer, the clock, the log,
and the hold state. Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

import yaml

from advance.app_state import AppState
from orchestrator import alignment, api, instances, subagents, trial
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.files import FileStore
from orchestrator.instances import InstancePaths
from orchestrator.setup import PreloadedArtifacts

# `eval/orchestrator/surfer.py` -> `eval/prompts/surfer.md`.
SURFER_PROMPT = Path(__file__).parents[1] / "prompts" / "surfer.md"

# The decision vocabulary. The loop applies exactly these; anything else is an
# escalation, so a decider cannot smuggle in a code change.
TERMINATE = "terminate"
DESTROY = "destroy"
FIX = "fix"
ESCALATE = "escalate"
DECISION_KINDS = (TERMINATE, DESTROY, FIX, ESCALATE)

# The asserted-state trigger kinds, in the source's priority order.
FAILURE_SIGNAL = "failure_signal"
FAILED_RUN = "failed_run"
CAP_REACHED = "cap_reached"
TOKEN_BUDGET_REACHED = "token_budget_reached"
TRIGGER_KINDS = (FAILURE_SIGNAL, FAILED_RUN, CAP_REACHED, TOKEN_BUDGET_REACHED)

# The bounded repair vocabulary. `env` is configuration-layer; the data-layer
# repair re-places the target's pre-mined hunting artifacts into the pipeline's
# own `produced/` inboxes. Anything else escalates. There is deliberately no
# lock/lease repair: the app's locks are in-process `threading.Lock`s, so no
# data-root lock marker exists for a repair to clear (CODING_STANDARD section 12).
REPAIR_ENV = "env"
REPAIR_REPLACE_ARTIFACTS = "replace_artifacts"
REPAIR_KINDS = (REPAIR_ENV, REPAIR_REPLACE_ARTIFACTS)

CREDIT_EXHAUSTION = "credit_exhaustion"
# Substrings that classify an error payload as credit exhaustion. Data, not
# policy: documented here so the operator can extend the vocabulary.
CREDIT_MARKERS = (
    "insufficient_quota",
    "insufficient quota",
    "exceeded your current quota",
    "quota exceeded",
    "credit balance",
    "credits exceeded",
    "credits exhausted",
    "credit exhausted",
    "out of credits",
    "no credits",
    "billing hard limit",
    "credit exhaustion",
)

# A phase terminal that names a failure stops the trial (mirrors trial.py).
FAILED_TERMINALS = frozenset({"failed", "interrupted"})
# A phase is cleanly finished only on its healthy terminal; anything else (a cap
# `stopped`, a failure) is where a resume re-enters.
HEALTHY_PHASE_TERMINALS = {
    "recon": frozenset({"complete"}),
    "analysis": frozenset({"drained"}),
    "hunting": frozenset({"complete"}),
}

# The alignment-state namespace for handled surfer triggers. Reusing the
# alignment `applied` map keeps one atomic state file; this constant pair
# isolates the surfer's handled keys from the alignment's per-version action
# keys, so neither can ever clear the other. Defined in `alignment` so
# `resolve_hold` can re-arm a surfer hold's triggers (I7).
HANDLED_SHA = alignment.SURFER_HANDLED_SHA
HANDLED_FINGERPRINT = alignment.SURFER_HANDLED_FINGERPRINT


class SurferError(RuntimeError):
    """The surfer was asked to decide or execute without one of its seams."""


# --- the failure-signal seam --------------------------------------------------


@dataclass(frozen=True)
class FailureSignal:
    """A classified failed-state signal (e.g. LLM credit exhaustion)."""

    kind: str
    instance_id: str
    detail: str
    target_id: str | None = None
    project_id: str | None = None


@dataclass(frozen=True)
class FailureEvidence:
    """One error payload offered to the classifier.

    `source` names where it came from (`trial_record`, `run_error`); the text is
    whatever the evidence carries - a phase failure, a run error, a trial note.
    """

    instance_id: str
    text: str
    source: str
    target_id: str | None = None
    project_id: str | None = None


class FailureSignalReader(Protocol):
    """The injected classifier: evidence in, failed-state signals out."""

    def read(self, evidence: Sequence[FailureEvidence]) -> tuple[FailureSignal, ...]: ...


class CreditExhaustionReader:
    """The documented default: classify credit-exhaustion-like error payloads."""

    def read(self, evidence: Sequence[FailureEvidence]) -> tuple[FailureSignal, ...]:
        signals: list[FailureSignal] = []
        for item in evidence:
            text = (item.text or "").lower()
            if any(marker in text for marker in CREDIT_MARKERS):
                signals.append(
                    FailureSignal(
                        kind=CREDIT_EXHAUSTION,
                        instance_id=item.instance_id,
                        detail=item.text.strip(),
                        target_id=item.target_id,
                        project_id=item.project_id,
                    )
                )
        return tuple(signals)


@dataclass
class RunErrorEvidence:
    """The production evidence reader (I9): a failed run's error payloads.

    The trial record carries phase-level failures and notes but not the run's own
    error text (the recon per-job `error`). This reads each run the trial log
    names through the injected REST seam, so a credit-exhaustion error is
    classified even when the record is terse. A read failure is logged and
    skipped: evidence is advisory, never a reason to crash the loop.
    """

    api_runner: api.ApiRunner
    trial_log: TrialLog
    log: Callable[[dict], None] = lambda record: None

    def __call__(self) -> tuple[FailureEvidence, ...]:
        evidence: list[FailureEvidence] = []
        for record in self.trial_log.records():
            if not isinstance(record, Mapping):
                continue
            instance_id = str(record.get("instance_id") or "")
            target_id = record.get("target_id")
            project_id = record.get("project_id")
            if not project_id:
                continue
            for phase in phase_mappings(record):
                run_kind = str(phase.get("phase") or "")
                run_id = phase.get("run_id")
                if not run_id or run_kind not in ("recon", "analysis", "hunting"):
                    continue
                for text in self._read_run(str(project_id), run_kind, str(run_id)):
                    evidence.append(
                        FailureEvidence(
                            instance_id, text, "run_error", target_id, project_id
                        )
                    )
        return tuple(evidence)

    def _read_run(self, project_id: str, run_kind: str, run_id: str) -> tuple[str, ...]:
        if run_kind == "recon":
            call = api.recon_status(project_id, run_id)
        elif run_kind == "analysis":
            call = api.analysis_status(project_id, run_id)
        else:
            call = api.hunting_status(project_id, run_id)
        try:
            payload = self.api_runner(call)
        except Exception as exc:  # noqa: BLE001 - evidence is advisory, never fatal
            self.log(
                {
                    "event": "run_error_evidence_failed",
                    "run_kind": run_kind,
                    "run_id": run_id,
                    "project_id": project_id,
                    "error": str(exc),
                }
            )
            return ()
        return _run_error_texts(payload)


def _run_error_texts(payload: object) -> tuple[str, ...]:
    """Every error string a run's status payload carries (top-level + per-job)."""
    if not isinstance(payload, Mapping):
        return ()
    texts: list[str] = []
    error = payload.get("error")
    if error:
        texts.append(str(error))
    for job in api.per_job_rows(payload):
        if isinstance(job, Mapping) and job.get("error"):
            texts.append(str(job["error"]))
    return tuple(texts)


# --- the asserted state -------------------------------------------------------


@dataclass(frozen=True)
class Trigger:
    """One reason the surfer prompted the orchestrator."""

    kind: str
    instance_id: str
    detail: str
    target_id: str | None = None
    project_id: str | None = None
    run_kind: str | None = None
    run_id: str | None = None
    recon_run_id: str | None = None
    start_phase: str | None = None
    signal: str | None = None
    eval_sha: str | None = None
    stack_fingerprint: str | None = None
    # The trial-scoped cap baseline the record counted against, carried into a
    # resumed trial so its count continues rather than resetting (D8/D16).
    cap_baseline: tuple[str, ...] | None = None
    # The trial-scoped spend baseline the record counted against, carried into a
    # resumed trial so its spend continues rather than resetting.
    spend_baseline: int | None = None

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(frozen=True)
class SurfacedState:
    """The asserted environment state for one cycle: the idle verdict and triggers."""

    idle: bool
    triggers: tuple[Trigger, ...] = ()
    projects: tuple[Mapping, ...] = ()

    @property
    def primary(self) -> Trigger | None:
        """The first asserted trigger, the one a fix acts on."""
        return self.triggers[0] if self.triggers else None

    def to_dict(self) -> dict:
        return {
            "idle": self.idle,
            # I3: only mapping project entries survive; a non-mapping one is a
            # malformed app-state payload, not a reason to crash the loop.
            "projects": [
                dict(project) for project in self.projects if isinstance(project, Mapping)
            ],
            "triggers": [trigger.to_dict() for trigger in self.triggers],
        }


class StateAsserter(Protocol):
    """The injected per-cycle assertion."""

    def assert_state(self) -> SurfacedState: ...


class TrialLog(Protocol):
    """The injected source of persisted trial records."""

    def records(self) -> tuple[Mapping, ...]: ...


class FileTrialLog:
    """Read every `trial.yaml` under the runs root through the file seam.

    `log` receives a structured record when a `trial.yaml` cannot be parsed or
    is not a mapping, so a corrupt record is named to the operator instead of
    silently vanishing; the walk always continues.
    """

    def __init__(
        self,
        runs_root: str | Path,
        *,
        files: FileStore | None = None,
        log: Callable[[dict], None] | None = None,
    ) -> None:
        self._runs_root = Path(runs_root)
        self._files = files or FileStore()
        self._log = log or (lambda record: None)

    def records(self) -> tuple[Mapping, ...]:
        records: list[Mapping] = []
        for path in self._files.walk_files(self._runs_root):
            if path.name != "trial.yaml":
                continue
            try:
                payload = yaml.safe_load(self._files.read_text(path))
            except yaml.YAMLError as exc:
                self._log(
                    {"event": "trial_record_invalid", "path": str(path), "error": str(exc)}
                )
                continue
            if not isinstance(payload, Mapping):
                self._log(
                    {
                        "event": "trial_record_invalid",
                        "path": str(path),
                        "error": f"expected a mapping, got {type(payload).__name__}",
                    }
                )
                continue
            records.append(payload)
        return tuple(records)


@dataclass
class SurferStateSource:
    """The default asserter: app-state plus trial records plus failure signals.

    `app_state` is the injected idle proxy (`IdleProxy.fetch`); `trial_log` is the
    persisted cap/phase evidence; `evidence` supplies run-error payloads the
    app-state surface does not carry. The `signals` reader classifies all the
    evidence into failed-state signals.
    """

    app_state: Callable[[], AppState]
    trial_log: TrialLog
    signals: FailureSignalReader
    evidence: Callable[[], Sequence[FailureEvidence]] = lambda: ()
    log: Callable[[dict], None] = lambda record: None

    def assert_state(self) -> SurfacedState:
        app = self.app_state()
        records = self.trial_log.records()
        signals: list[Trigger] = []
        failed: list[Trigger] = []
        caps: list[Trigger] = []
        spends: list[Trigger] = []
        valid: list[Mapping] = []
        for record in records:
            error = _record_shape_error(record)
            if error is not None:
                # I3: a record the surfer cannot safely walk is skipped and
                # named, never a crash and never a silent drop.
                self._log_invalid(record, error)
                continue
            valid.append(record)
            caps.extend(cap_triggers(record))
            spends.extend(spend_triggers(record))
            trigger = failed_run_trigger(record)
            if trigger is not None:
                failed.append(trigger)
        evidence = tuple(self.evidence()) + trial_evidence(valid)
        for signal in self.signals.read(evidence):
            signals.append(
                Trigger(
                    kind=FAILURE_SIGNAL,
                    instance_id=signal.instance_id,
                    detail=signal.detail,
                    target_id=signal.target_id,
                    project_id=signal.project_id,
                    signal=signal.kind,
                )
            )
        return SurfacedState(
            idle=app.idle,
            triggers=tuple(signals + failed + caps + spends),
            projects=tuple(app.projects),
        )

    def _log_invalid(self, record: object, error: str) -> None:
        mapping = record if isinstance(record, Mapping) else {}
        self.log(
            {
                "event": "surfer_record_invalid",
                "instance_id": str(mapping.get("instance_id") or ""),
                "target_id": mapping.get("target_id"),
                "project_id": mapping.get("project_id"),
                "error": error,
            }
        )


def _record_shape_error(record: object) -> str | None:
    """A named reason a record's shape is unsafe to read, or None (I3).

    Guards every nesting depth the surfer reads: the record must be a mapping,
    `phases` a list of mappings, and `notes` a list. Anything else is skipped.
    """
    if not isinstance(record, Mapping):
        return f"record is not a mapping: {type(record).__name__}"
    phases = record.get("phases")
    if phases is not None:
        if not isinstance(phases, list):
            return f"phases is not a list: {type(phases).__name__}"
        for index, phase in enumerate(phases):
            if not isinstance(phase, Mapping):
                return f"phases[{index}] is not a mapping: {type(phase).__name__}"
    notes = record.get("notes")
    if notes is not None and not isinstance(notes, list):
        return f"notes is not a list: {type(notes).__name__}"
    return None


def phase_mappings(record: Mapping) -> tuple[Mapping, ...]:
    """The record's phase entries that are mappings; malformed entries ignored.

    Every surfer reader walks phases through this shape guard (I3), so a record
    reached directly (or a reader outside `assert_state`) cannot crash on a
    non-mapping entry.
    """
    phases = record.get("phases") if isinstance(record, Mapping) else None
    if not isinstance(phases, list):
        return ()
    return tuple(phase for phase in phases if isinstance(phase, Mapping))


def cap_triggers(record: Mapping) -> list[Trigger]:
    """Cap-reached triggers from the trial engine's own cap accounting.

    The trigger names the hunting run (`run_kind`/`run_id`) so `terminate` can
    actually stop it and so two distinct cap events in the same instance/target/
    project are two identities rather than one.
    """
    cap = record.get("cap")
    stop = record.get("stop_count")
    if not isinstance(cap, int) or not isinstance(stop, int) or stop < cap:
        return []
    return [
        _trigger(
            CAP_REACHED,
            record,
            detail=(
                f"hunting cap {cap} reached (stopped at {stop}, "
                f"final {record.get('final_count')})"
            ),
            run_kind="hunting",
            run_id=_hunting_run_id(record),
            start_phase="hunting",
            cap_baseline=_cap_baseline(record),
        )
    ]


def _cap_baseline(record: Mapping) -> tuple[str, ...] | None:
    """The record's persisted trial-scoped baseline, when it is well-formed.

    A missing or malformed baseline is treated as absent (the resumed trial
    snapshots a fresh one), never as a crash (I3).
    """
    value = record.get("cap_baseline")
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        return None
    return tuple(value)


def spend_triggers(record: Mapping) -> list[Trigger]:
    """Token-budget-reached triggers from the trial engine's own spend accounting.

    The trigger names the run the trial stopped in (the phase whose status is
    `stopped`, defaulting to hunting) so `terminate` can actually stop it.
    """
    budget = record.get("token_budget")
    spent = record.get("spent_tokens")
    if not isinstance(budget, int) or not isinstance(spent, int) or spent < budget:
        return []
    phase = _stopped_phase(record)
    if phase is not None:
        run_kind = str(phase.get("phase") or "hunting")
        run_id = phase.get("run_id")
    else:
        run_kind = "hunting"
        run_id = _hunting_run_id(record)
    return [
        _trigger(
            TOKEN_BUDGET_REACHED,
            record,
            detail=(
                f"token budget {budget} reached (spent {spent}, "
                f"overshoot {record.get('spend_overshoot')})"
            ),
            run_kind=run_kind,
            run_id=run_id,
            start_phase=run_kind,
            spend_baseline=_spend_baseline(record),
        )
    ]


def _stopped_phase(record: Mapping) -> Mapping | None:
    """The phase whose run the trial stopped, when one is recorded."""
    for phase in phase_mappings(record):
        if phase.get("status") == "stopped":
            return phase
    return None


def _spend_baseline(record: Mapping) -> int | None:
    """The record's persisted spend baseline, when it is a plain int.

    A missing, non-int, or bool baseline is treated as absent (the resumed trial
    snapshots a fresh one), never as a crash (I3).
    """
    value = record.get("spend_baseline")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def failed_run_trigger(record: Mapping) -> Trigger | None:
    """A failed/interrupted run trigger from the record's phase terminals."""
    for phase in phase_mappings(record):
        name = str(phase.get("phase") or "")
        status = phase.get("status")
        failure = phase.get("failure")
        if failure or status in FAILED_TERMINALS:
            detail = str(failure) if failure else f"{name} run {status}"
            return _trigger(
                FAILED_RUN,
                record,
                detail=detail,
                run_kind=name,
                run_id=phase.get("run_id"),
                start_phase=resume_phase(record),
                cap_baseline=_cap_baseline(record),
                spend_baseline=_spend_baseline(record),
            )
    if record.get("terminal") == "failed":
        return _trigger(
            FAILED_RUN,
            record,
            detail="trial terminal failed",
            start_phase=resume_phase(record),
            cap_baseline=_cap_baseline(record),
            spend_baseline=_spend_baseline(record),
        )
    return None


def resume_phase(record: Mapping) -> str:
    """The phase a resumed trial re-enters: the first not cleanly completed one.

    A `stopped` hunting run (the cap) is not a clean `complete`, so a cap stop
    resumes hunting; a failed recon resumes recon; an all-clean record resumes at
    its last phase.
    """
    phases = phase_mappings(record)
    for phase in phases:
        name = str(phase.get("phase") or "")
        if phase.get("failure"):
            return name
        healthy = HEALTHY_PHASE_TERMINALS.get(name)
        if healthy is not None and phase.get("status") not in healthy:
            return name
    if phases:
        return str(phases[-1].get("phase") or record.get("start_phase") or "hunting")
    return str(record.get("start_phase") or "hunting")


def trial_evidence(records: Sequence[Mapping]) -> tuple[FailureEvidence, ...]:
    """The error text a trial record carries: phase failures and notes."""
    evidence: list[FailureEvidence] = []
    for record in records:
        instance_id = str(record.get("instance_id") or "")
        target_id = record.get("target_id")
        project_id = record.get("project_id")
        for phase in phase_mappings(record):
            failure = phase.get("failure")
            if failure:
                evidence.append(
                    FailureEvidence(
                        instance_id, str(failure), "trial_record", target_id, project_id
                    )
                )
        notes = record.get("notes")
        if not isinstance(notes, list):
            continue
        for note in notes:
            evidence.append(
                FailureEvidence(
                    instance_id, str(note), "trial_record", target_id, project_id
                )
            )
    return tuple(evidence)


def _trigger(kind: str, record: Mapping, **fields) -> Trigger:
    return Trigger(
        kind=kind,
        instance_id=str(record.get("instance_id") or ""),
        target_id=record.get("target_id"),
        project_id=record.get("project_id"),
        recon_run_id=_recon_run_id(record),
        eval_sha=record.get("eval_sha"),
        stack_fingerprint=record.get("stack_fingerprint"),
        **fields,
    )


def _recon_run_id(record: Mapping) -> str | None:
    for phase in phase_mappings(record):
        if phase.get("phase") == "recon":
            return phase.get("run_id")
    return record.get("recon_run_id")


def _hunting_run_id(record: Mapping) -> str | None:
    for phase in phase_mappings(record):
        if phase.get("phase") == "hunting":
            return phase.get("run_id")
    return record.get("hunting_run_id")


# --- the decider seam ---------------------------------------------------------


@dataclass(frozen=True)
class SurferDecision:
    """One orchestrator decision; the loop resolves it mechanically."""

    kind: str
    repair: str | None = None
    reason: str = ""


class SurferDecider(Protocol):
    """The injected seam: the real one interposes an agent turn."""

    def decide(self, request: "SurferRequest") -> SurferDecision: ...


# The static decider is the shared shape (`subagents.StaticDecider`); the module
# keeps the public name for callers that reach it off this module.
StaticDecider = subagents.StaticDecider


@dataclass(frozen=True)
class SurferRequest:
    """What the decider receives: the asserted state and the bounded vocabulary."""

    prompt: Path
    input_file: Path
    destination: Path
    state: Mapping
    repairs: tuple[str, ...]
    environment: Mapping


def render_request_input(request: SurferRequest) -> str:
    """The agent-turn input: the asserted state, the repairs, the environment."""
    payload = {
        "state": dict(request.state),
        "repairs": list(request.repairs),
        "environment": dict(request.environment),
    }
    return yaml.safe_dump(payload, sort_keys=False)


def plan_dispatch(
    request: SurferRequest,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Command:
    """Render the configured agent command with `{prompt}`/`{input}`/`{destination}`."""
    return subagents.plan_dispatch(
        request, argv, cwd=cwd, env=env, description="surfer decision"
    )


def load_decision(path: str | Path, *, files: FileStore) -> SurferDecision:
    """Read and validate the agent-written decision document.

    The shape is enforced (a `fix` needs a `repair`), but the vocabulary is not:
    an unknown kind or repair parses and is then escalated by the loop, so an
    attempted code change can never be applied.
    """
    if not files.exists(path):
        raise SurferError(f"surfer decision not found: {path}")
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError as exc:
        raise SurferError(f"surfer decision {path}: invalid YAML: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise SurferError(f"surfer decision {path}: expected a mapping")
    kind = payload.get("decision") or payload.get("kind")
    if not isinstance(kind, str) or not kind:
        raise SurferError(f"surfer decision {path}: expected a non-empty 'decision'")
    repair = payload.get("repair")
    if repair is not None and (not isinstance(repair, str) or not repair):
        raise SurferError(f"surfer decision {path}: 'repair' must be a non-empty string")
    if kind == FIX and not repair:
        raise SurferError(f"surfer decision {path}: a fix decision requires 'repair'")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise SurferError(f"surfer decision {path}: 'reason' must be a string")
    return SurferDecision(kind=kind, repair=repair, reason=reason or "")


@dataclass
class SubagentSurferDecider:
    """The production seam: write the input, run the agent command, read the decision."""

    runner: CommandRunner
    argv: tuple[str, ...]
    prompt: Path = SURFER_PROMPT
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    files: FileStore = field(default_factory=FileStore)

    def decide(self, request: SurferRequest) -> SurferDecision:
        return subagents.decide_via_agent(
            request,
            runner=self.runner,
            argv=self.argv,
            files=self.files,
            render_input=render_request_input,
            load=load_decision,
            error=SurferError,
            description="surfer decision",
            cwd=self.cwd,
            env=self.env,
        )


# --- the bounded repairs ------------------------------------------------------


class SurferRepairs(Protocol):
    """The bounded configuration/data-layer repairs a fix may apply."""

    def supports(self, repair: str) -> bool: ...

    def apply(self, repair: str, *, project_id: str) -> None: ...

    def restart(self, repair: str) -> None: ...


@dataclass
class SurferRepairKit:
    """The concrete bounded repairs for one instance.

    `preloaded` is the target's pre-mined artifact configuration, when the fix
    is scoped to one target; without it `replace_artifacts` is unsupported and a
    fix naming it escalates.
    """

    paths: InstancePaths
    runner: CommandRunner | None = None
    data_root: Path = Path("data")
    files: FileStore = field(default_factory=FileStore)
    preloaded: PreloadedArtifacts | None = None

    def supports(self, repair: str) -> bool:
        if repair == REPAIR_ENV:
            return True
        if repair == REPAIR_REPLACE_ARTIFACTS:
            return self.preloaded is not None
        return False

    def apply(self, repair: str, *, project_id: str) -> None:
        """Apply the bounded change; never touches anything but the named layer."""
        if repair == REPAIR_ENV:
            self._require_runner()
            command = instances.plan_preflight(self.paths)
            require_ok(self.runner(command), command, error=SurferError)
            return
        if repair == REPAIR_REPLACE_ARTIFACTS:
            if self.preloaded is None:
                raise SurferError("replace_artifacts needs pre-mined artifacts configured")
            trial.place_premined(
                self.files,
                data_root=self.data_root,
                project_id=project_id,
                preloaded=self.preloaded,
            )
            return
        raise SurferError(f"unsupported repair: {repair!r}")

    def restart(self, repair: str) -> None:
        """Restart the affected services after the bounded change."""
        if repair == REPAIR_ENV:
            self._require_runner()
            command = Command(
                argv=tuple(instances.compose_argv(self.paths, "up", "-d", "--force-recreate")),
                cwd=str(self.paths.worktree),
                description=f"recreate {self.paths.compose_project} after env fix",
            )
            require_ok(self.runner(command), command, error=SurferError)
            return
        if repair == REPAIR_REPLACE_ARTIFACTS:
            self._require_runner()
            instances.up(self.paths, self.runner)
            return
        raise SurferError(f"unsupported repair: {repair!r}")

    def _require_runner(self) -> None:
        if self.runner is None:
            raise SurferError("this repair requires a command runner")


# --- the trial resumer --------------------------------------------------------


@dataclass(frozen=True)
class ResumePlan:
    """How to relaunch a failed trial: its recorded phase and its identity."""

    instance_id: str
    target_id: str
    project_id: str
    start_phase: str
    intervention: str
    recon_run_id: str | None = None
    # The resumed trial's carried-over cap baseline (D8/D16): both the trial
    # engine and the CLI thread it into the new `TrialConfig`.
    cap_baseline: tuple[str, ...] | None = None
    # The resumed trial's carried-over spend baseline: the CLI threads it into
    # the new `TrialConfig` so a resume does not reset the token budget.
    spend_baseline: int | None = None


class TrialResumer(Protocol):
    def resume(self, plan: ResumePlan) -> str: ...


@dataclass
class CallbackResumer:
    """A resumer over an injected callable (the CLI wires the trial engine)."""

    run: Callable[[ResumePlan], str]

    def resume(self, plan: ResumePlan) -> str:
        return self.run(plan)


# --- the loop -----------------------------------------------------------------


@dataclass(frozen=True)
class SurferConfig:
    """The loop's knobs: the poll interval and an optional cycle bound."""

    interval_s: float = 60.0
    max_cycles: int | None = None


@dataclass(frozen=True)
class SurferOutcome:
    """One cycle's result."""

    cycle: int
    state: SurfacedState
    decision: SurferDecision | None = None
    action: str | None = None
    detail: str = ""
    hold: alignment.Hold | None = None
    escalated: bool = False
    no_op: bool = False
    planned: bool = False
    dry_run: bool = False
    # The identities of already-handled triggers this cycle skipped.
    skipped: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.escalated


class Surfer:
    """The surfer loop: assert, prompt, and resolve one bounded decision per cycle."""

    def __init__(
        self,
        config: SurferConfig,
        *,
        asserter: StateAsserter,
        decider: SurferDecider,
        instances: tuple[InstancePaths, ...] = (),
        runner: CommandRunner | None = None,
        api: api.ApiRunner | None = None,
        repairs: Callable[[Trigger], SurferRepairs] | None = None,
        resumer: TrialResumer | None = None,
        state: alignment.AlignmentState | None = None,
        now: Callable[[], str] | None = None,
        sleep: Callable[[float], None] | None = None,
        log: Callable[[dict], None] | None = None,
        dry_run: bool = False,
    ) -> None:
        self._config = config
        self._asserter = asserter
        self._decider = decider
        self._instances = {paths.instance.instance_id: paths for paths in instances}
        self._runner = runner
        self._api = api
        self._repairs = repairs
        self._resumer = resumer
        self._state = state
        self._now = now or subagents.utcnow
        self._sleep = sleep or time.sleep
        self._log = log or (lambda record: None)
        self._dry_run = dry_run
        self._cycle = 0

    def cycle(self) -> SurferOutcome:
        """One poll-assert-decide (and, unless dry-run, execute) cycle.

        A trigger already recorded as handled in the alignment state is skipped,
        so a long-running loop acts once per distinct trigger identity; a new
        record (a new run/phase) is a new identity and is handled normally. A
        dry-run never records, so it always shows the pending triggers.
        """
        self._cycle += 1
        state = self._asserter.assert_state()
        handled = self._handled_keys()
        pending = tuple(t for t in state.triggers if trigger_key(t) not in handled)
        skipped = tuple(trigger_key(t) for t in state.triggers if trigger_key(t) in handled)
        for key in skipped:
            self._log({"event": "surfer_skip", "trigger": key, "reason": "already handled"})
        if not pending:
            return SurferOutcome(
                cycle=self._cycle,
                state=state,
                no_op=True,
                dry_run=self._dry_run,
                skipped=skipped,
                detail=(
                    f"{len(skipped)} already-handled trigger(s); nothing to do"
                    if skipped
                    else ""
                ),
            )
        pending_state = SurfacedState(
            idle=state.idle, triggers=pending, projects=state.projects
        )
        if self._dry_run:
            return SurferOutcome(
                cycle=self._cycle,
                state=pending_state,
                planned=True,
                dry_run=True,
                skipped=skipped,
                detail=(
                    f"{len(pending)} trigger(s) asserted; "
                    "the decider is not dispatched"
                ),
            )
        request = self._request(pending_state)
        decision = self._decider.decide(request)
        outcome = self._resolve(pending_state, decision)
        return replace(outcome, skipped=skipped)

    def run(self, *, once: bool = False) -> list[SurferOutcome]:
        """Run cycles until `once`, the cycle bound, or forever (the supervisor)."""
        outcomes: list[SurferOutcome] = []
        while True:
            outcomes.append(self.cycle())
            if once:
                break
            if self._config.max_cycles is not None and len(outcomes) >= self._config.max_cycles:
                break
            self._sleep(self._config.interval_s)
        return outcomes

    # --- resolution -----------------------------------------------------------

    def _resolve(self, state: SurfacedState, decision: SurferDecision) -> SurferOutcome:
        if decision.kind not in DECISION_KINDS:
            return self._escalate(
                state,
                f"unsupported decision {decision.kind!r}: a code change is never applied",
                decision,
            )
        if decision.kind == ESCALATE:
            return self._escalate(
                state, decision.reason or "the orchestrator escalated", decision
            )
        if decision.kind == TERMINATE:
            calls, unactionable = self._terminate(state)
            if unactionable:
                # A terminate that cannot name a run must not report success:
                # an operator has to see the unactionable trigger instead.
                return self._escalate(
                    state, _unactionable_terminate(unactionable), decision
                )
            self._record_handled(state.triggers)
            return SurferOutcome(
                cycle=self._cycle,
                state=state,
                decision=decision,
                action=TERMINATE,
                detail=f"stopped {len(calls)} run(s)",
            )
        if decision.kind == DESTROY:
            done = self._destroy(state)
            self._record_handled(state.triggers)
            return SurferOutcome(
                cycle=self._cycle,
                state=state,
                decision=decision,
                action=DESTROY,
                detail=f"destroyed {', '.join(done)}",
            )
        return self._fix(state, decision)

    def _terminate(self, state: SurfacedState) -> tuple[list[api.ApiCall], list[Trigger]]:
        """Plan the stop calls; return them and any trigger that names no run.

        All calls are planned before any is issued, and an unactionable trigger
        returns no calls at all: a partial stop followed by an escalation would
        leave the state half-resolved, so the caller escalates instead.
        """
        if self._api is None:
            raise SurferError("terminate requires an API runner")
        calls: list[api.ApiCall] = []
        unactionable: list[Trigger] = []
        for trigger in state.triggers:
            call = _stop_call(trigger)
            if call is None:
                unactionable.append(trigger)
            else:
                calls.append(call)
        if unactionable:
            return [], unactionable
        for call in calls:
            self._api(call)
        return calls, []

    def _destroy(self, state: SurfacedState) -> list[str]:
        if self._runner is None:
            raise SurferError("destroy requires a command runner")
        done: list[str] = []
        for instance_id in dict.fromkeys(
            trigger.instance_id for trigger in state.triggers if trigger.instance_id
        ):
            instances.down(self._paths_for(instance_id), self._runner)
            done.append(instance_id)
        return done

    def _fix(self, state: SurfacedState, decision: SurferDecision) -> SurferOutcome:
        repair = decision.repair
        if repair not in REPAIR_KINDS:
            return self._escalate(
                state,
                f"repair {repair!r} is not a bounded configuration/data-layer repair",
                decision,
            )
        primary = state.primary
        if primary is None:
            return self._escalate(state, "no trigger to fix", decision)
        if self._repairs is None:
            return self._escalate(
                state, "no bounded repair kit is available for this environment", decision
            )
        kit = self._repairs(primary)
        if kit is None or not kit.supports(repair):
            return self._escalate(
                state,
                f"repair {repair!r} is not supported; check the configuration "
                "and the target's pre-mined artifacts",
                decision,
            )
        kit.apply(repair, project_id=primary.project_id or "")
        kit.restart(repair)
        if self._resumer is None:
            raise SurferError("fix requires a trial resumer")
        start_phase = primary.start_phase or "hunting"
        plan = ResumePlan(
            instance_id=primary.instance_id,
            target_id=primary.target_id or "",
            project_id=primary.project_id or "",
            start_phase=start_phase,
            recon_run_id=primary.recon_run_id,
            cap_baseline=primary.cap_baseline,
            spend_baseline=primary.spend_baseline,
            intervention=(
                f"surfer: fix {repair} on trigger {primary.kind}; resumed at {start_phase}"
            ),
        )
        new_id = self._resumer.resume(plan)
        self._record_handled((primary,))
        return SurferOutcome(
            cycle=self._cycle,
            state=state,
            decision=decision,
            action=FIX,
            detail=f"applied {repair}, restarted, resumed {new_id}",
        )

    def _escalate(
        self, state: SurfacedState, reason: str, decision: SurferDecision | None = None
    ) -> SurferOutcome:
        hold = None
        if self._state is not None:
            hold = write_hold(
                self._state, triggers=state.triggers, reason=reason, now=self._now()
            )
        # Every escalation - a decider `escalate`, an unknown decision kind, or an
        # unbounded repair - records the acted-on trigger, so an unchanged trigger
        # is not re-dispatched every cycle. The hold itself is idempotent.
        self._record_handled(state.triggers)
        return SurferOutcome(
            cycle=self._cycle,
            state=state,
            decision=decision or SurferDecision(ESCALATE, reason=reason),
            action=ESCALATE,
            detail=reason,
            hold=hold,
            escalated=True,
        )

    # --- seams ----------------------------------------------------------------

    def _handled_keys(self) -> frozenset[str]:
        """The trigger identities already acted on (persisted in the state file)."""
        if self._state is None:
            return frozenset()
        return self._state.applied_for(HANDLED_SHA, HANDLED_FINGERPRINT)

    def _record_handled(self, triggers: Sequence[Trigger]) -> None:
        """Record the acted-on trigger identities so the loop does not repeat them."""
        if self._state is None or not triggers:
            return
        self._state.record_applied(
            HANDLED_SHA, HANDLED_FINGERPRINT, [trigger_key(t) for t in triggers]
        )

    def _request(self, state: SurfacedState) -> SurferRequest:
        directory = self._state.path.parent if self._state is not None else Path("eval/state")
        return SurferRequest(
            prompt=SURFER_PROMPT,
            input_file=directory / "surfer-input.yaml",
            destination=directory / "surfer-decision.yaml",
            state=state.to_dict(),
            repairs=REPAIR_KINDS,
            environment=self._environment(),
        )

    def _environment(self) -> dict:
        return {
            "instances": [
                {
                    "instance_id": paths.instance.instance_id,
                    "compose_project": paths.compose_project,
                    "worktree": str(paths.worktree),
                    "env_file": str(paths.env_file),
                }
                for paths in self._instances.values()
            ],
            "repairs": list(REPAIR_KINDS),
        }

    def _paths_for(self, instance_id: str) -> InstancePaths:
        paths = self._instances.get(instance_id)
        if paths is None:
            raise SurferError(f"no instance {instance_id!r} in the surfer environment")
        return paths


def _stop_call(trigger: Trigger) -> api.ApiCall | None:
    """The clean-stop call for one named run, or None when the trigger names none."""
    if not trigger.project_id or not trigger.run_id:
        return None
    if trigger.run_kind == "recon":
        return api.stop_recon(trigger.project_id, trigger.run_id)
    if trigger.run_kind == "analysis":
        return api.stop_analysis(trigger.project_id, trigger.run_id)
    if trigger.run_kind == "hunting":
        return api.stop_hunting(trigger.project_id, trigger.run_id)
    return None


def _unactionable_terminate(triggers: Sequence[Trigger]) -> str:
    """A named reason for a terminate whose triggers name no run to stop."""
    named = ", ".join(f"{trigger.kind} ({trigger.instance_id})" for trigger in triggers)
    return f"terminate names no run to stop for {named}"


def trigger_key(trigger: Trigger) -> str:
    """A stable identity for one asserted trigger, for the handled record.

    Deterministic and record-derived: instance + target + project + run
    kind/id + resume phase + trigger kind (+ signal kind). A new failure (a new
    run id, a new phase) is a new identity and is handled; an unchanged terminal
    record keeps its identity and is skipped after it was handled once.
    """
    return "|".join(
        str(part)
        for part in (
            trigger.kind,
            trigger.instance_id,
            trigger.target_id or "",
            trigger.project_id or "",
            trigger.run_kind or "",
            trigger.run_id or "",
            trigger.start_phase or "",
            trigger.signal or "",
        )
    )


def write_hold(
    state: alignment.AlignmentState,
    *,
    triggers: Sequence[Trigger],
    reason: str,
    now: str,
) -> alignment.Hold:
    """Write a surfer hold through the alignment state (D42's mechanism).

    The hold records its triggers' identities (I7), so `alignment resolve` can
    clear exactly those handled markers and re-arm them.
    """
    primary = triggers[0] if triggers else None
    return state.add_hold(
        target_sha=(primary.eval_sha if primary else None) or "surfer",
        target_fingerprint=(primary.stack_fingerprint if primary else None) or "",
        rationale=f"surfer: {reason}",
        now=now,
        trigger_keys=tuple(trigger_key(trigger) for trigger in triggers),
    )
