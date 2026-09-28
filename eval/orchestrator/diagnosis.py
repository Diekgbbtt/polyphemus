"""The `diagnoses.yaml` schema, the diagnoser dispatch, and the issue-bank seam (#272).

One `diagnoses.yaml` entry per `missed` and `partial` verdict of a trial,
keyed by the verdict's `vuln`. The entry carries a failure mode (D21/D33), a
typed root cause that may reach into the persisted data layer (D24), a
diagnosis overview, evidence references, and either the closest matching
issue-bank issue or a proposed issue - never both, and never a filed issue
(D22).

The diagnoser is dispatched through the same fire-and-forget seam as the
assessment (#271/D6): the orchestrator hands the configured command the prompt
file, the trial record, the verdicts, the ground truth, the data root, and the
destination, then returns without polling. The eval-close phase checks the file
is present, valid, and paired (an entry for every `missed`/`partial`), with the
same bounded re-dispatch plus escalation as #271.

The root-cause space is deliberately wider than code: `kb_coverage_gap` and
`skill_defect` name defects in the persisted data layer, beside the
`implementation_defect`/`design_defect`/`missing_component` code types.

The issue bank is read-only by construction: `GitHubIssueBank` exposes only a
`search` method and only ever builds GET requests, so it is structurally
incapable of filing. `EVAL_GITHUB_TOKEN` is read from the environment.

PyYAML is the one third-party dependency (the repo's existing dependency);
import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import yaml

from orchestrator import subagents, trial, verdicts
from orchestrator.commands import Command
from orchestrator.files import FileStore

# `eval/orchestrator/diagnosis.py` -> `eval/prompts/diagnoser.md`.
DIAGNOSER_PROMPT = Path(__file__).parents[1] / "prompts" / "diagnoser.md"

DIAGNOSES_FILENAME = "diagnoses.yaml"
# Two dispatches before the bounded re-dispatch (mirrors #271/D15).
MAX_DISPATCHES = 2
# The technical defects a bounded configuration-layer re-dispatch may address.
REPAIRABLE = ("dispatcher_process", "empty_file", "schema_invalid", "unpaired")

# D21/D33. The analysis layer will almost certainly contribute more modes, but
# they are a recorded future extension: inventing an enum value with no eval
# corpus to cite would be a fabricated taxonomy.
FAILURE_MODES = (
    "pod_notsufficient_space_coverage",
    "hunter_notsufficient_tests_exploration",
    "pod_diverged_trajectory",
    "surface_gap",
    "spec_underspecified",
    "cap_hit",
    "orchestrator_failed_unit-fault_binding",
)
# D24: the code types plus the persisted-data-layer types.
ROOT_CAUSE_TYPES = (
    "implementation_defect",
    "design_defect",
    "missing_component",
    "kb_coverage_gap",
    "skill_defect",
)
# D20: only a success (`identified`) is exempt from a diagnosis entry. Shared
# with the verdict vocabulary and the artifact store.
DIAGNOSABLE = verdicts.DIAGNOSABLE

_ROW_FIELDS = (
    "vuln",
    "failure_mode",
    "root_cause",
    "diagnosis_overview",
    "evidences",
    "closest_issue",
    "proposed_issue",
)
_REQUIRED_FIELDS = ("vuln", "failure_mode", "root_cause", "diagnosis_overview", "evidences")
_ROOT_CAUSE_FIELDS = ("type", "combination_of", "extended_description")
_EVIDENCE_FIELDS = ("source", "ref", "note")
_CLOSEST_FIELDS = ("repo", "number", "title", "rationale")
_PROPOSED_FIELDS = ("title", "body", "labels")


class DiagnosisError(ValueError):
    """A diagnosis row is malformed, unpaired, or the dispatch failed."""


# --- the typed surface ---------------------------------------------------------


@dataclass(frozen=True)
class RootCause:
    """The typed locus of a defect, with any additional combined types (D19/D24)."""

    type: str
    combination_of: tuple[str, ...] = ()
    extended_description: str = ""


@dataclass(frozen=True)
class Evidence:
    """One evidence reference: where it came from, what it points at, why."""

    source: str
    ref: str
    note: str


@dataclass(frozen=True)
class ClosestIssue:
    """The closest matching issue-bank issue (D22)."""

    repo: str
    number: int
    title: str
    rationale: str


@dataclass(frozen=True)
class ProposedIssue:
    """A proposed issue for the operator to file; the agent never files (D22)."""

    title: str
    body: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnosis:
    """One validated `diagnoses.yaml` entry."""

    vuln: str
    failure_mode: str
    root_cause: RootCause
    diagnosis_overview: str
    evidences: tuple[Evidence, ...]
    closest_issue: ClosestIssue | None
    proposed_issue: ProposedIssue | None


# --- validation ----------------------------------------------------------------


def parse_diagnosis(row: Mapping, *, verdicts_by_id: Mapping[str, str]) -> Diagnosis:
    """Validate one decoded row against the trial's verdicts and build it."""
    if not isinstance(row, Mapping):
        raise DiagnosisError(f"diagnosis row must be a mapping, got {type(row).__name__}")
    unknown = sorted(set(row) - set(_ROW_FIELDS))
    if unknown:
        raise DiagnosisError(f"diagnosis row: unknown field(s): {', '.join(unknown)}")
    missing = [name for name in _REQUIRED_FIELDS if name not in row or row[name] is None]
    if missing:
        raise DiagnosisError(f"diagnosis row: missing required field(s): {', '.join(missing)}")

    vuln = _non_empty(row["vuln"], "vuln")
    if vuln not in verdicts_by_id:
        raise DiagnosisError(
            f"diagnosis row {vuln}: no verdict for this vuln; an entry may only "
            "pair a missed or partial verdict"
        )
    identified = verdicts_by_id[vuln]
    if identified not in DIAGNOSABLE:
        raise DiagnosisError(
            f"diagnosis row {vuln}: the verdict is {identified!r}; an identified "
            "vuln receives no diagnosis entry"
        )

    failure_mode = row["failure_mode"]
    if failure_mode not in FAILURE_MODES:
        raise DiagnosisError(
            f"diagnosis row {vuln}: failure_mode must be one of "
            f"{', '.join(FAILURE_MODES)}, got {failure_mode!r}"
        )
    root_cause = _parse_root_cause(row["root_cause"], vuln)
    overview = _non_empty(row["diagnosis_overview"], "diagnosis_overview")
    evidences = _parse_evidences(row["evidences"], vuln)
    closest = _parse_closest(row.get("closest_issue"), vuln)
    proposed = _parse_proposed(row.get("proposed_issue"), vuln)
    if closest is not None and proposed is not None:
        raise DiagnosisError(
            f"diagnosis row {vuln}: closest_issue and proposed_issue are mutually "
            "exclusive; record one (the issue bank is searched before proposing)"
        )
    if closest is None and proposed is None:
        raise DiagnosisError(
            f"diagnosis row {vuln}: exactly one of closest_issue or proposed_issue "
            "is required; when no issue matches (or the issue bank is unavailable) "
            "write a proposed_issue"
        )

    return Diagnosis(
        vuln=vuln,
        failure_mode=failure_mode,
        root_cause=root_cause,
        diagnosis_overview=overview,
        evidences=evidences,
        closest_issue=closest,
        proposed_issue=proposed,
    )


def validate_diagnoses(
    rows: Sequence, *, verdicts: Sequence[verdicts.Verdict]
) -> tuple[Diagnosis, ...]:
    """Validate a whole `diagnoses.yaml` payload (a list of rows).

    The `verdicts` argument closes the entry -> verdict direction: an entry whose
    vuln has no verdict, or whose verdict is `identified`, is rejected. The
    verdict -> entry direction (every `missed`/`partial` has exactly one entry)
    is the pairing check `check_pairing` runs at close verification (D19).
    """
    if not isinstance(rows, list):
        raise DiagnosisError("diagnoses.yaml must be a list of rows")
    by_id = {v.vuln_id: v.identified for v in verdicts}
    seen: set[str] = set()
    parsed: list[Diagnosis] = []
    for row in rows:
        entry = parse_diagnosis(row, verdicts_by_id=by_id)
        if entry.vuln in seen:
            raise DiagnosisError(f"diagnosis row {entry.vuln}: duplicate entry")
        seen.add(entry.vuln)
        parsed.append(entry)
    return tuple(parsed)


def write_diagnoses(
    path: str | Path,
    rows: Sequence,
    *,
    files: FileStore,
    verdicts: Sequence[verdicts.Verdict],
) -> None:
    """Validate, then write the rows atomically (temp + rename)."""
    validate_diagnoses(rows, verdicts=verdicts)
    files.write_text_atomic(path, yaml.safe_dump(list(rows), sort_keys=False))


def load_diagnoses(
    path: str | Path,
    *,
    files: FileStore,
    verdicts: Sequence[verdicts.Verdict],
) -> tuple[Diagnosis, ...]:
    """Read and validate `diagnoses.yaml`; raise `DiagnosisError` on any defect."""
    if not files.exists(path):
        raise DiagnosisError(f"diagnoses.yaml not found at {path}")
    text = files.read_text(path)
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DiagnosisError(f"diagnoses.yaml: invalid YAML: {exc}") from exc
    return validate_diagnoses(payload, verdicts=verdicts)


# --- pairing (both directions) -------------------------------------------------


def required_vulns(verdicts: Sequence[verdicts.Verdict]) -> tuple[str, ...]:
    """The `missed` and `partial` vuln ids that each need a diagnosis entry."""
    return tuple(v.vuln_id for v in verdicts if v.identified in DIAGNOSABLE)


def missing_entries(
    verdicts: Sequence[verdicts.Verdict], diagnoses: Sequence[Diagnosis]
) -> tuple[str, ...]:
    """The required vulns with no diagnosis entry, in verdict order."""
    present = {d.vuln for d in diagnoses}
    return tuple(v for v in required_vulns(verdicts) if v not in present)


def check_pairing(
    verdicts: Sequence[verdicts.Verdict], diagnoses: Sequence[Diagnosis]
) -> None:
    """Refuse loud when a `missed`/`partial` verdict has no diagnosis entry."""
    missing = missing_entries(verdicts, diagnoses)
    if missing:
        raise DiagnosisError(
            "diagnoses.yaml: missing entr(y/ies) for missed/partial vuln(s): "
            + ", ".join(missing)
        )


def check_diagnoses(
    request: "DiagnosisRequest",
    *,
    files: FileStore,
    verdicts: Sequence[verdicts.Verdict],
) -> str:
    """`present`, `missing`, `invalid`, or `unpaired` for the request's destination."""
    if not files.exists(request.destination):
        return "missing"
    try:
        entries = load_diagnoses(request.destination, files=files, verdicts=verdicts)
    except (DiagnosisError, OSError):
        return "invalid"
    try:
        check_pairing(verdicts, entries)
    except DiagnosisError:
        return "unpaired"
    return "present"


# --- the dispatcher seam -------------------------------------------------------


@dataclass(frozen=True)
class DiagnosisRequest:
    """The inputs the diagnoser subagent receives (and writes into)."""

    prompt: Path
    trial_record: Path
    verdicts: Path
    ground_truth: Path
    data_root: Path
    destination: Path
    # The missed/partial vuln ids this dispatch must diagnose; the prompt writes
    # exactly one entry per id.
    vulns: tuple[str, ...] = ()
    trace_id: str | None = None


# The dispatch seam, reusing #271's fire-and-forget shape (D6) parameterized on
# this request: run the configured agent command with the request. The real
# implementation runs the configured command line (OPERATOR.md); tests inject a
# fake.
SubagentDispatcher = Callable[[DiagnosisRequest], None]


def _format_fields(request: DiagnosisRequest) -> dict[str, str]:
    fields = subagents.common_fields(request)
    fields["verdicts"] = str(request.verdicts)
    fields["vulns"] = ",".join(request.vulns)
    return fields


def plan_dispatch(
    request: DiagnosisRequest,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Command:
    """Render the configured agent command with the request's paths.

    The template names `{prompt}`, `{trial_record}`, `{verdicts}`,
    `{ground_truth}`, `{data_root}`, `{destination}`, `{vulns}`, and `{trace_id}`.
    """
    return subagents.render_command(
        argv,
        _format_fields(request),
        cwd=cwd,
        env=env,
        description=f"diagnose {request.trial_record}",
    )


class CommandDispatcher(subagents.CommandDispatcher):
    """The production seam: run the configured agent command line once."""

    error = DiagnosisError

    def plan(self, request: DiagnosisRequest) -> Command:
        return plan_dispatch(request, self.argv, cwd=self.cwd, env=self.env)


def dispatch(
    request: DiagnosisRequest,
    *,
    dispatcher: SubagentDispatcher,
    prior: Sequence[trial.DiagnosisAttempt] = (),
    now: Callable[[], str] | None = None,
) -> trial.DiagnosisRecord:
    """Fire-and-forget dispatch; return the recorded attempt (D6)."""
    return subagents.dispatch(
        request,
        dispatcher=dispatcher,
        prior=prior,
        now=now,
        make_attempt=trial.DiagnosisAttempt,
        make_record=lambda status, attempts, path: trial.DiagnosisRecord(
            status, attempts, path
        ),
    )


# --- close verification --------------------------------------------------------


# The persistent-failure classification (the shared cause/repair/detail shape).
DiagnosisFailure = subagents.Failure


def classify_failure(
    *, diagnosis_state: str, error: BaseException | None
) -> DiagnosisFailure:
    """Classify a persistent failure into a bounded re-dispatch or an escalation."""
    return subagents.classify_failure(
        state=diagnosis_state,
        error=error,
        label="diagnosis",
        missing_detail="no diagnoses.yaml was produced",
        invalid_detail="diagnoses.yaml failed schema validation",
        unpaired_detail=(
            "diagnoses.yaml is missing an entry for a missed/partial vuln"
        ),
    )


# The bounded, configuration-layer-only repair (D28).
DiagnosisRepair = subagents.Repair


class DiagnoserReDispatchRepair(subagents.ReDispatchRepair):
    """Re-run the configured command once with the corrected paths/flags (D28).

    The only bounded repair: it re-invokes the injected dispatcher and never
    touches the codebase.
    """

    def __init__(
        self, dispatcher: SubagentDispatcher, request: DiagnosisRequest
    ) -> None:
        super().__init__(dispatcher, request, repairable=REPAIRABLE, error=DiagnosisError)


def verify_diagnoses(
    request: DiagnosisRequest,
    *,
    dispatcher: SubagentDispatcher,
    files: FileStore,
    verdicts: Sequence[verdicts.Verdict],
    repair: DiagnosisRepair | None = None,
    prior: Sequence[trial.DiagnosisAttempt] = (),
    now: Callable[[], str] | None = None,
) -> trial.DiagnosisRecord:
    """The eval-close pairing check for one trial (presence, re-dispatch, micro-diagnosis)."""
    now = now or subagents.utcnow
    attempts = list(prior)

    def attempt(outcome: str, detail: str | None) -> None:
        attempts.append(
            trial.DiagnosisAttempt(len(attempts) + 1, outcome, detail, now())
        )

    if not required_vulns(verdicts):
        return trial.DiagnosisRecord(
            "not_required", attempts, str(request.destination)
        )

    def inspect() -> tuple[str, tuple[Diagnosis, ...]]:
        state = check_diagnoses(request, files=files, verdicts=verdicts)
        entries: tuple[Diagnosis, ...] = ()
        if state in ("present", "unpaired"):
            try:
                entries = load_diagnoses(request.destination, files=files, verdicts=verdicts)
            except (DiagnosisError, OSError):  # pragma: no cover - state is unpaired
                entries = ()
        return state, entries

    state, entries = inspect()
    if state == "present":
        return _present(attempts, request, entries)

    last_error: BaseException | None = None
    for _ in range(MAX_DISPATCHES):
        try:
            dispatcher(request)
            attempt("dispatched", None)
        except Exception as exc:  # noqa: BLE001 - the dispatcher outcome is arbitrary
            last_error = exc
            attempt("error", str(exc))
        state, entries = inspect()
        if state == "present":
            return _present(attempts, request, entries)

    failure = classify_failure(diagnosis_state=state, error=last_error)
    kit = repair or subagents.NullRepair(DiagnosisError)
    if kit.supports(failure.cause):
        try:
            kit.apply(failure.cause)
            attempt("repaired", failure.detail)
            state, entries = inspect()
            if state == "present":
                return _present(attempts, request, entries)
        except Exception as exc:  # noqa: BLE001 - a repair failure is itself a signal
            attempt("repair_error", str(exc))
    return trial.DiagnosisRecord(
        "escalated",
        attempts,
        str(request.destination),
        failure=f"diagnosis_{failure.cause}",
    )


# --- the trial record ----------------------------------------------------------


def load_trial_record(path: str | Path, *, files: FileStore) -> dict:
    """Read a trial record; a missing or non-mapping file is a loud error."""
    return subagents.load_trial_record(path, files=files, error=DiagnosisError)


def record_diagnosis(
    trial_record_path: str | Path,
    record: trial.DiagnosisRecord,
    *,
    files: FileStore,
) -> None:
    """Persist the diagnosis outcome, preserving the rest of the record."""
    payload = load_trial_record(trial_record_path, files=files)
    payload["diagnosis"] = record.to_dict()
    files.write_text_atomic(trial_record_path, yaml.safe_dump(payload, sort_keys=False))


# --- the issue bank (read-only) ------------------------------------------------


@dataclass(frozen=True)
class Issue:
    """One issue-bank hit."""

    repo: str
    number: int
    title: str


@dataclass(frozen=True)
class IssueMatch:
    """The resolved issue fields: the closest match, or a proposal (never both)."""

    closest_issue: ClosestIssue | None
    proposed_issue: ProposedIssue | None


class IssueBank(Protocol):
    """The issue-bank seam: search and nothing else."""

    def search(self, query: str, *, limit: int = 5) -> tuple[Issue, ...]: ...


def match_issue(
    bank: IssueBank,
    *,
    query: str,
    rationale: str,
    proposed: ProposedIssue | None = None,
    limit: int = 5,
) -> IssueMatch:
    """Record the closest issue-bank match, else fall back to the proposal (D22).

    The bank is relevance-ordered: the provider returns its best match first, so
    `hits[0]` IS the closest match. Reading is the only interaction the bank
    permits; whether the caller then records a `closest_issue` reference or a
    `proposed_issue` block, it never files anything.
    """
    hits = tuple(bank.search(query, limit=limit))
    if hits:
        best = hits[0]
        return IssueMatch(
            closest_issue=ClosestIssue(best.repo, best.number, best.title, rationale),
            proposed_issue=None,
        )
    return IssueMatch(closest_issue=None, proposed_issue=proposed)


# The HTTP transport seam: an injected fake lets the structural GET-only test
# run without a network. The real one reads bytes from urllib.
Transport = Callable[[Request], "bytes | str"]


def _urlopen_transport(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:  # noqa: S310 - the GitHub API only
        return response.read()


class GitHubIssueBank:
    """A read-only GitHub issue-bank implementation over the REST search API.

    Structurally incapable of filing: the only public capability is `search`,
    which only ever constructs a `GET` `Request`. There is no code path that
    issues POST, PATCH, or PUT. The token comes from `EVAL_GITHUB_TOKEN`.
    """

    def __init__(
        self,
        token: str,
        *,
        api: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        self._token = token
        self._api = api.rstrip("/")
        self._transport = transport or _urlopen_transport

    @classmethod
    def from_env(cls, *, transport: Transport | None = None) -> "GitHubIssueBank":
        """Build the bank from `EVAL_GITHUB_TOKEN`; a missing token is loud."""
        token = os.environ.get("EVAL_GITHUB_TOKEN")
        if not token:
            raise DiagnosisError(
                "EVAL_GITHUB_TOKEN is not set; the issue-bank search cannot authenticate"
            )
        return cls(token, transport=transport)

    def search(
        self,
        query: str,
        *,
        repo: str | None = None,
        limit: int = 5,
        sort: str | None = None,
    ) -> tuple[Issue, ...]:
        """Search issues read-only; returns the first `limit` hits, best first.

        GitHub's default ordering for `/search/issues` is best-match
        (relevance), so no `sort`/`order` is forced: the first hit is the
        closest matching issue (N14). An explicit `sort` (GitHub's
        `created|updated|comments`) is honoured when the caller asks for it.
        """
        scoped = f"{query} repo:{repo}" if repo else query
        url = (
            f"{self._api}/search/issues"
            f"?q={quote(scoped)}&per_page={int(limit)}"
        )
        if sort is not None:
            url += f"&sort={quote(sort)}"
        request = Request(url, method="GET")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        payload = json.loads(self._transport(request))
        items = payload.get("items") or []
        return tuple(_issue_from_item(item) for item in items)


def _issue_from_item(item: Mapping) -> Issue:
    repo = ""
    url = str(item.get("repository_url") or "")
    if url:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if len(parts) >= 2:
            repo = f"{parts[-2]}/{parts[-1]}"
    return Issue(repo=repo, number=int(item.get("number") or 0), title=str(item.get("title") or ""))


# --- internals ----------------------------------------------------------------


def _parse_root_cause(raw: object, vuln: str) -> RootCause:
    if not isinstance(raw, Mapping):
        raise DiagnosisError(f"diagnosis row {vuln}: root_cause must be a mapping")
    unknown = sorted(set(raw) - set(_ROOT_CAUSE_FIELDS))
    if unknown:
        raise DiagnosisError(
            f"diagnosis row {vuln}: root_cause unknown field(s): {', '.join(unknown)}"
        )
    cause_type = raw.get("type")
    if cause_type not in ROOT_CAUSE_TYPES:
        raise DiagnosisError(
            f"diagnosis row {vuln}: root_cause.type must be one of "
            f"{', '.join(ROOT_CAUSE_TYPES)}, got {cause_type!r}"
        )
    combination = _parse_combination(raw.get("combination_of"), cause_type, vuln)
    description = _non_empty(raw.get("extended_description"), "root_cause.extended_description")
    return RootCause(
        type=cause_type, combination_of=combination, extended_description=description
    )


def _parse_combination(raw: object, cause_type: str, vuln: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise DiagnosisError(
            f"diagnosis row {vuln}: root_cause.combination_of must be a list of types"
        )
    combination: list[str] = []
    for item in raw:
        if item not in ROOT_CAUSE_TYPES:
            raise DiagnosisError(
                f"diagnosis row {vuln}: root_cause.combination_of carries an unknown "
                f"type {item!r}"
            )
        if item == cause_type:
            raise DiagnosisError(
                f"diagnosis row {vuln}: root_cause.combination_of must carry the "
                "ADDITIONAL types only; it repeats the primary type"
            )
        if item in combination:
            raise DiagnosisError(
                f"diagnosis row {vuln}: root_cause.combination_of repeats {item!r}"
            )
        combination.append(item)
    return tuple(combination)


def _parse_evidences(raw: object, vuln: str) -> tuple[Evidence, ...]:
    if not isinstance(raw, list):
        raise DiagnosisError(f"diagnosis row {vuln}: evidences must be a list")
    evidences: list[Evidence] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise DiagnosisError(
                f"diagnosis row {vuln}: each evidence must be a mapping"
            )
        unknown = sorted(set(item) - set(_EVIDENCE_FIELDS))
        if unknown:
            raise DiagnosisError(
                f"diagnosis row {vuln}: evidence unknown field(s): {', '.join(unknown)}"
            )
        missing = [name for name in _EVIDENCE_FIELDS if name not in item or item[name] is None]
        if missing:
            raise DiagnosisError(
                f"diagnosis row {vuln}: evidence missing field(s): {', '.join(missing)}"
            )
        evidences.append(
            Evidence(
                source=_non_empty(item["source"], "evidence.source"),
                ref=_non_empty(item["ref"], "evidence.ref"),
                note=_non_empty(item["note"], "evidence.note"),
            )
        )
    return tuple(evidences)


def _parse_closest(raw: object, vuln: str) -> ClosestIssue | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise DiagnosisError(f"diagnosis row {vuln}: closest_issue must be a mapping or null")
    unknown = sorted(set(raw) - set(_CLOSEST_FIELDS))
    if unknown:
        raise DiagnosisError(
            f"diagnosis row {vuln}: closest_issue unknown field(s): {', '.join(unknown)}"
        )
    number = raw.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        raise DiagnosisError(f"diagnosis row {vuln}: closest_issue.number must be an integer")
    return ClosestIssue(
        repo=_non_empty(raw.get("repo"), "closest_issue.repo"),
        number=number,
        title=_non_empty(raw.get("title"), "closest_issue.title"),
        rationale=_non_empty(raw.get("rationale"), "closest_issue.rationale"),
    )


def _parse_proposed(raw: object, vuln: str) -> ProposedIssue | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise DiagnosisError(f"diagnosis row {vuln}: proposed_issue must be a mapping or null")
    unknown = sorted(set(raw) - set(_PROPOSED_FIELDS))
    if unknown:
        raise DiagnosisError(
            f"diagnosis row {vuln}: proposed_issue unknown field(s): {', '.join(unknown)}"
        )
    labels = raw.get("labels") or []
    if not isinstance(labels, list) or not all(isinstance(item, str) and item for item in labels):
        raise DiagnosisError(
            f"diagnosis row {vuln}: proposed_issue.labels must be a list of non-empty strings"
        )
    return ProposedIssue(
        title=_non_empty(raw.get("title"), "proposed_issue.title"),
        body=_non_empty(raw.get("body"), "proposed_issue.body"),
        labels=tuple(labels),
    )


def _present(
    attempts: list[trial.DiagnosisAttempt],
    request: DiagnosisRequest,
    entries: Sequence[Diagnosis],
) -> trial.DiagnosisRecord:
    return trial.DiagnosisRecord(
        status="present",
        attempts=attempts,
        diagnoses_path=str(request.destination),
        entries_written=len(entries),
        issues_matched=sum(1 for e in entries if e.closest_issue is not None),
        issues_proposed=sum(1 for e in entries if e.proposed_issue is not None),
    )


def _non_empty(raw: object, label: str) -> str:
    return subagents.non_empty(raw, label, error=DiagnosisError)
