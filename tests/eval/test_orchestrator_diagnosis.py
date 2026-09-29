"""The diagnosis schema, the dispatcher seam, and the issue-bank seam (#272).

`diagnoses.yaml` is paired with `verdicts.yaml`: one entry per `missed`/`partial`
verdict, keyed by the verdict's `vuln`. Every entry carries the trial record's
`eval_sha` and `stack_fingerprint`, exactly like a verdict row. Validation is
strict on write (atomic rename) and pairing is checked in both directions - an
entry needs a `missed`/`partial` verdict, and close verification needs an entry
for every one.
The issue bank is read-only by construction: `GitHubIssueBank` exposes only a
`search` method and only ever issues GET requests.
"""
from __future__ import annotations

import pytest
import yaml

from orchestrator import diagnosis, trial, verdicts
from orchestrator.files import FileStore

SHA = "eval-sha-1"
FINGERPRINT = "fp-1"

# The schema requires exactly one issue reference per row; a factory default
# carries a proposal so every "valid row" is valid by construction.
_UNSET = object()


def _proposal() -> dict:
    return {"title": "new gap", "body": "b", "labels": []}


# --- fixtures -----------------------------------------------------------------


def verdict(vuln_id: str, identified: str) -> verdicts.Verdict:
    return verdicts.Verdict(
        vuln_id=vuln_id,
        identified=identified,
        confidence=0.5,
        matched=verdicts.Matched(unit="u", fault_class="CWE-89", symptom="s"),
        evidence_chain=None,
        eval_sha=SHA,
        stack_fingerprint=FINGERPRINT,
    )


def row(
    vuln: str = "v1",
    *,
    failure_mode: str = "surface_gap",
    type_: str = "implementation_defect",
    combination_of: list | None = None,
    extended_description: str = "the scanner missed the route",
    diagnosis_overview: str = "the pipeline never reached the sink",
    evidences: list | None = None,
    closest_issue: object = _UNSET,
    proposed_issue: object = _UNSET,
    sha: str = SHA,
    fingerprint: str = FINGERPRINT,
) -> dict:
    payload: dict = {
        "vuln": vuln,
        "failure_mode": failure_mode,
        "root_cause": {
            "type": type_,
            "extended_description": extended_description,
        },
        "diagnosis_overview": diagnosis_overview,
        "evidences": evidences if evidences is not None else [
            {"source": "pod_export", "ref": "run1", "note": "no terminal success"}
        ],
        "eval_sha": sha,
        "stack_fingerprint": fingerprint,
    }
    if combination_of is not None:
        payload["root_cause"]["combination_of"] = combination_of
    if closest_issue is _UNSET and proposed_issue is _UNSET:
        # Default valid row: exactly one of the two, a proposal.
        payload["proposed_issue"] = _proposal()
    else:
        if closest_issue is not _UNSET and closest_issue is not None:
            payload["closest_issue"] = closest_issue
        if proposed_issue is not _UNSET and proposed_issue is not None:
            payload["proposed_issue"] = proposed_issue
    return payload


# The trial record's identity the fixture verdicts (and so every valid row)
# carry. The schema-level tests below inject it here so the fixtures stay valid
# by construction; the dedicated identity tests call the real API explicitly.
_IDENTITY = {"eval_sha": SHA, "stack_fingerprint": FINGERPRINT}


def _validate(rows, *, verdicts):
    return diagnosis.validate_diagnoses(rows, verdicts=verdicts, **_IDENTITY)


def _write(path, rows, *, files, verdicts):
    diagnosis.write_diagnoses(path, rows, files=files, verdicts=verdicts, **_IDENTITY)


def _load(path, *, files, verdicts):
    return diagnosis.load_diagnoses(path, files=files, verdicts=verdicts, **_IDENTITY)


def _check(request, *, files, verdicts):
    return diagnosis.check_diagnoses(request, files=files, verdicts=verdicts, **_IDENTITY)


def _verify(request, *, dispatcher, files, verdicts, **kwargs):
    return diagnosis.verify_diagnoses(
        request,
        dispatcher=dispatcher,
        files=files,
        verdicts=verdicts,
        **_IDENTITY,
        **kwargs,
    )


class FakeDispatcher:
    def __init__(self, action=None):
        self.requests = []
        self.action = action

    def __call__(self, request):
        self.requests.append(request)
        if self.action is not None:
            self.action(request)


class FakeBank:
    """An `IssueBank` double: returns a scripted hit list, records queries."""

    def __init__(self, hits=()):
        self.hits = tuple(hits)
        self.queries = []
        self.limits = []

    def search(self, query: str, *, limit: int = 5):
        self.queries.append(query)
        self.limits.append(limit)
        return self.hits


# --- schema accept/reject ------------------------------------------------------


def test_validate_accepts_a_missed_and_a_partial_entry() -> None:
    rows = [row("v1", failure_mode="cap_hit"), row("v2", failure_mode="pod_diverged_trajectory")]
    diags = _validate(
        rows, verdicts=[verdict("v1", "missed"), verdict("v2", "partial")]
    )
    assert [d.vuln for d in diags] == ["v1", "v2"]
    assert diags[0].failure_mode == "cap_hit"
    assert diags[0].root_cause.type == "implementation_defect"
    # Every entry carries the trial record's version identity (D32/#276 AC2).
    assert diags[0].eval_sha == SHA
    assert diags[0].stack_fingerprint == FINGERPRINT


def test_rejects_an_entry_with_no_identity_fields() -> None:
    bad = row()
    del bad["eval_sha"]
    with pytest.raises(diagnosis.DiagnosisError, match="eval_sha"):
        _validate([bad], verdicts=[verdict("v1", "missed")])

    bad = row()
    del bad["stack_fingerprint"]
    with pytest.raises(diagnosis.DiagnosisError, match="stack_fingerprint"):
        _validate([bad], verdicts=[verdict("v1", "missed")])


def test_rejects_an_empty_identity_on_an_entry() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="eval_sha"):
        _validate([row(sha="")], verdicts=[verdict("v1", "missed")])
    with pytest.raises(diagnosis.DiagnosisError, match="stack_fingerprint"):
        _validate([row(fingerprint="")], verdicts=[verdict("v1", "missed")])


def test_rejects_an_identity_that_does_not_match_the_trial_record() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="eval_sha"):
        _validate([row(sha="invented-sha")], verdicts=[verdict("v1", "missed")])
    with pytest.raises(diagnosis.DiagnosisError, match="stack_fingerprint"):
        _validate([row(fingerprint="invented-fp")], verdicts=[verdict("v1", "missed")])


def test_rejects_a_record_without_an_identity() -> None:
    # The record's own identity is the expected side; a record with none is
    # refused rather than defaulting (the diagnosis may never invent one).
    with pytest.raises(diagnosis.DiagnosisError, match="trial record"):
        diagnosis.validate_diagnoses(
            [row()],
            verdicts=[verdict("v1", "missed")],
            eval_sha=None,
            stack_fingerprint=FINGERPRINT,
        )
    with pytest.raises(diagnosis.DiagnosisError, match="trial record"):
        diagnosis.validate_diagnoses(
            [row()],
            verdicts=[verdict("v1", "missed")],
            eval_sha=SHA,
            stack_fingerprint=None,
        )


def test_write_validates_the_identity_before_writing() -> None:
    import tempfile
    from pathlib import Path

    files = FileStore()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "diagnoses.yaml"
        with pytest.raises(diagnosis.DiagnosisError, match="eval_sha"):
            diagnosis.write_diagnoses(
                path,
                [row(sha="invented-sha")],
                files=files,
                verdicts=[verdict("v1", "missed")],
                eval_sha=SHA,
                stack_fingerprint=FINGERPRINT,
            )
        assert not path.exists()


def test_rejects_an_unknown_failure_mode() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="failure_mode"):
        _validate(
            [row(failure_mode="made_up")], verdicts=[verdict("v1", "missed")]
        )


def test_rejects_an_unknown_root_cause_type() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="root_cause.type"):
        _validate(
            [row(type_="made_up")], verdicts=[verdict("v1", "missed")]
        )


def test_root_cause_accepts_the_data_layer_types_and_a_combination() -> None:
    diags = _validate(
        [row(type_="kb_coverage_gap", combination_of=["skill_defect"])],
        verdicts=[verdict("v1", "missed")],
    )
    assert diags[0].root_cause.type == "kb_coverage_gap"
    assert diags[0].root_cause.combination_of == ("skill_defect",)


def test_rejects_a_self_referential_or_duplicated_combination() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="combination_of"):
        _validate(
            [row(type_="implementation_defect", combination_of=["implementation_defect"])],
            verdicts=[verdict("v1", "missed")],
        )
    with pytest.raises(diagnosis.DiagnosisError, match="combination_of"):
        _validate(
            [row(type_="implementation_defect", combination_of=["implementation_defect"])],
            verdicts=[verdict("v1", "missed")],
        )
    with pytest.raises(diagnosis.DiagnosisError, match="combination_of"):
        _validate(
            [row(type_="implementation_defect", combination_of=["skill_defect", "skill_defect"])],
            verdicts=[verdict("v1", "missed")],
        )


def test_rejects_empty_narratives() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="diagnosis_overview"):
        _validate(
            [row(diagnosis_overview="")], verdicts=[verdict("v1", "missed")]
        )
    with pytest.raises(diagnosis.DiagnosisError, match="extended_description"):
        _validate(
            [row(extended_description="")], verdicts=[verdict("v1", "missed")]
        )


def test_rejects_a_duplicate_vuln_entry() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="duplicate"):
        _validate(
            [row("v1"), row("v1")], verdicts=[verdict("v1", "missed")]
        )


def test_rejects_an_entry_with_no_verdict() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="no verdict"):
        _validate(
            [row("ghost")], verdicts=[verdict("v1", "missed")]
        )


def test_rejects_an_entry_for_an_identified_vuln() -> None:
    # `identified` is a success; it may not carry a diagnosis entry (D20).
    with pytest.raises(diagnosis.DiagnosisError, match="identified"):
        _validate(
            [row("v1")], verdicts=[verdict("v1", "identified")]
        )


def test_rejects_both_a_closest_and_a_proposed_issue() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="closest_issue"):
        _validate(
            [
                row(
                    closest_issue={"repo": "o/r", "number": 1, "title": "t", "rationale": "r"},
                    proposed_issue={"title": "new", "body": "b", "labels": []},
                )
            ],
            verdicts=[verdict("v1", "missed")],
        )


def test_rejects_neither_a_closest_nor_a_proposed_issue() -> None:
    with pytest.raises(diagnosis.DiagnosisError, match="exactly one"):
        _validate(
            [row(closest_issue=None, proposed_issue=None)],
            verdicts=[verdict("v1", "missed")],
        )


def test_accepts_a_closest_issue_only() -> None:
    diags = _validate(
        [
            row(
                closest_issue={
                    "repo": "o/r",
                    "number": 7,
                    "title": "known gap",
                    "rationale": "same surface gap",
                }
            )
        ],
        verdicts=[verdict("v1", "missed")],
    )

    assert diags[0].closest_issue is not None
    assert diags[0].closest_issue.number == 7
    assert diags[0].proposed_issue is None


def test_accepts_a_proposed_issue_only() -> None:
    diags = _validate(
        [row(proposed_issue={"title": "new", "body": "b", "labels": ["bug"]})],
        verdicts=[verdict("v1", "missed")],
    )

    assert diags[0].proposed_issue is not None
    assert diags[0].proposed_issue.labels == ("bug",)
    assert diags[0].closest_issue is None


def test_write_is_atomic_and_round_trips() -> None:
    import tempfile
    from pathlib import Path

    files = FileStore()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "diagnoses.yaml"
        _write(
            path,
            [row("v1", proposed_issue={"title": "new", "body": "b", "labels": ["bug"]})],
            files=files,
            verdicts=[verdict("v1", "missed")],
        )
        loaded = _load(
            path, files=files, verdicts=[verdict("v1", "missed")]
        )
        leftovers = [p.name for p in path.parent.iterdir() if p.name.startswith(".diagnoses")]
    assert [d.vuln for d in loaded] == ["v1"]
    assert loaded[0].proposed_issue is not None
    assert loaded[0].proposed_issue.labels == ("bug",)
    assert loaded[0].closest_issue is None
    # The atomic writer never leaves a temp sibling behind.
    assert leftovers == []


def test_write_validates_before_writing() -> None:
    import tempfile
    from pathlib import Path

    files = FileStore()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "diagnoses.yaml"
        with pytest.raises(diagnosis.DiagnosisError):
            _write(
                path, [row(failure_mode="nope")], files=files,
                verdicts=[verdict("v1", "missed")],
            )
        assert not path.exists()


# --- pairing (both directions) -------------------------------------------------


def test_missing_entries_lists_every_unpaired_missed_and_partial() -> None:
    vs = [verdict("v1", "missed"), verdict("v2", "partial"), verdict("v3", "identified")]
    diags = _validate([row("v1")], verdicts=vs)
    assert diagnosis.required_vulns(vs) == ("v1", "v2")
    assert diagnosis.missing_entries(vs, diags) == ("v2",)
    with pytest.raises(diagnosis.DiagnosisError, match="v2"):
        diagnosis.check_pairing(vs, diags)


def test_identified_verdict_contributes_no_entry_and_no_missing() -> None:
    vs = [verdict("v3", "identified")]
    assert diagnosis.required_vulns(vs) == ()
    assert diagnosis.missing_entries(vs, ()) == ()


# --- the dispatcher seam -------------------------------------------------------


def test_plan_dispatch_formats_each_request_path_into_the_argv() -> None:
    request = diagnosis.DiagnosisRequest(
        prompt=diagnosis.DIAGNOSER_PROMPT,
        trial_record="/runs/trial.yaml",
        verdicts="/runs/verdicts.yaml",
        ground_truth="/gt/comfyui",
        data_root="/data",
        destination="/runs/diagnoses.yaml",
        vulns=("v1", "v2"),
    )
    command = diagnosis.plan_dispatch(
        request,
        (
            "agent", "diagnose",
            "--prompt", "{prompt}",
            "--trial", "{trial_record}",
            "--verdicts", "{verdicts}",
            "--gt", "{ground_truth}",
            "--data", "{data_root}",
            "--out", "{destination}",
            "--vulns", "{vulns}",
        ),
    )
    rendered = " ".join(command.argv)
    assert "diagnoser.md" in rendered
    assert "/runs/verdicts.yaml" in rendered
    assert "/gt/comfyui" in rendered
    assert "/runs/diagnoses.yaml" in rendered
    assert "v1,v2" in rendered


def test_command_dispatcher_raises_on_a_nonzero_exit(recording_runner, fake_result) -> None:
    runner = recording_runner(default=fake_result(2, stderr="agent exploded"))
    dispatcher = diagnosis.CommandDispatcher(runner, ("agent", "{prompt}"))
    with pytest.raises(diagnosis.DiagnosisError, match="agent"):
        dispatcher(
            diagnosis.DiagnosisRequest(
                prompt=diagnosis.DIAGNOSER_PROMPT,
                trial_record="/r/trial.yaml",
                verdicts="/r/verdicts.yaml",
                ground_truth="/gt",
                data_root="/data",
                destination="/r/diagnoses.yaml",
            )
        )


def test_dispatch_is_fire_and_forget_and_records_an_attempt() -> None:
    request = diagnosis.DiagnosisRequest(
        prompt=diagnosis.DIAGNOSER_PROMPT,
        trial_record="/r/trial.yaml",
        verdicts="/r/verdicts.yaml",
        ground_truth="/gt",
        data_root="/data",
        destination="/r/diagnoses.yaml",
    )
    dispatcher = FakeDispatcher()
    record = diagnosis.dispatch(request, dispatcher=dispatcher, now=lambda: "t")
    assert dispatcher.requests == [request]
    assert record.status == "dispatched"
    assert [a.outcome for a in record.attempts] == ["dispatched"]
    assert record.entries_written == 0


def test_classify_maps_each_diagnosis_cause() -> None:
    assert (
        diagnosis.classify_failure(diagnosis_state="missing", error=None).cause
        == "empty_file"
    )
    assert (
        diagnosis.classify_failure(diagnosis_state="invalid", error=None).cause
        == "schema_invalid"
    )
    assert (
        diagnosis.classify_failure(diagnosis_state="unpaired", error=None).cause
        == "unpaired"
    )
    assert (
        diagnosis.classify_failure(diagnosis_state="missing", error=RuntimeError("x")).cause
        == "dispatcher_process"
    )
    unknown = diagnosis.classify_failure(diagnosis_state="present", error=None)
    assert unknown.cause == "unknown"
    assert unknown.repair is None


# --- close verification --------------------------------------------------------


def _paired_request(tmp_path):
    root = tmp_path / "data"
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    gt = tmp_path / "gt" / "comfyui"
    gt.mkdir(parents=True, exist_ok=True)
    return diagnosis.DiagnosisRequest(
        prompt=diagnosis.DIAGNOSER_PROMPT,
        trial_record=trial_dir / "trial.yaml",
        verdicts=trial_dir / "verdicts.yaml",
        ground_truth=gt,
        data_root=root,
        destination=trial_dir / "diagnoses.yaml",
        vulns=("v1",),
    )


def test_verify_diagnoses_not_required_when_every_verdict_is_identified(tmp_path) -> None:
    request = _paired_request(tmp_path)
    dispatcher = FakeDispatcher()
    record = _verify(
        request, dispatcher=dispatcher, files=FileStore(),
        verdicts=[verdict("v1", "identified")],
    )
    assert record.status == "not_required"
    assert dispatcher.requests == []


def test_verify_diagnoses_short_circuits_on_a_present_paired_file(tmp_path) -> None:
    request = _paired_request(tmp_path)
    files = FileStore()
    _write(
        request.destination,
        [row("v1", closest_issue={"repo": "o/r", "number": 3, "title": "t", "rationale": "r"})],
        files=files,
        verdicts=[verdict("v1", "missed")],
    )
    dispatcher = FakeDispatcher()
    record = _verify(
        request, dispatcher=dispatcher, files=files, verdicts=[verdict("v1", "missed")]
    )
    assert record.status == "present"
    assert dispatcher.requests == []
    assert record.entries_written == 1
    assert record.issues_matched == 1
    assert record.issues_proposed == 0


def test_verify_diagnoses_redispatches_twice_then_escalates(tmp_path) -> None:
    request = _paired_request(tmp_path)
    dispatcher = FakeDispatcher()  # never writes the file
    record = _verify(
        request, dispatcher=dispatcher, files=FileStore(),
        verdicts=[verdict("v1", "missed")],
    )
    assert record.status == "escalated"
    assert record.failure == "diagnosis_empty_file"
    assert len(dispatcher.requests) == 2


def test_verify_diagnoses_repairs_a_missing_entry_then_passes(tmp_path) -> None:
    request = _paired_request(tmp_path)
    files = FileStore()
    calls = {"n": 0}

    def action(req):
        calls["n"] += 1
        if calls["n"] > 2:
            _write(
                req.destination, [row("v1")], files=files,
                verdicts=[verdict("v1", "missed")],
            )

    dispatcher = FakeDispatcher(action)
    repair = diagnosis.DiagnoserReDispatchRepair(dispatcher, request)
    record = _verify(
        request, dispatcher=dispatcher, repair=repair, files=files,
        verdicts=[verdict("v1", "missed")],
    )
    assert record.status == "present"
    assert "repaired" in [a.outcome for a in record.attempts]
    assert len(dispatcher.requests) == 3


def test_verify_diagnoses_flags_an_unpaired_file(tmp_path) -> None:
    request = _paired_request(tmp_path)
    files = FileStore()
    # A valid entry for v1, but the verdict set requires v1 and v2.
    _write(
        request.destination, [row("v1")], files=files,
        verdicts=[verdict("v1", "missed"), verdict("v2", "missed")],
    )
    vs = [verdict("v1", "missed"), verdict("v2", "missed")]
    assert _check(request, files=files, verdicts=vs) == "unpaired"


def test_record_diagnosis_preserves_the_rest_of_the_trial_record(tmp_path) -> None:
    files = FileStore()
    trial_dir = tmp_path / "runs" / "comfyui" / "trial-1"
    files.write_text(
        trial_dir / "trial.yaml",
        yaml.safe_dump({"trial_id": "t", "project_id": "pid", "target_id": "comfyui"}),
    )
    record = trial.DiagnosisRecord(
        status="escalated",
        attempts=[trial.DiagnosisAttempt(1, "dispatched", None, "t")],
        diagnoses_path=str(trial_dir / "diagnoses.yaml"),
        failure="diagnosis_unpaired",
    )
    diagnosis.record_diagnosis(trial_dir / "trial.yaml", record, files=files)
    payload = yaml.safe_load((trial_dir / "trial.yaml").read_text())
    assert payload["project_id"] == "pid"
    assert payload["diagnosis"]["status"] == "escalated"
    assert payload["diagnosis"]["attempts"][0]["outcome"] == "dispatched"
    assert payload["diagnosis"]["failure"] == "diagnosis_unpaired"


def test_diagnoser_prompt_is_a_file_and_states_the_contract() -> None:
    assert diagnosis.DIAGNOSER_PROMPT.exists()
    text = diagnosis.DIAGNOSER_PROMPT.read_text(encoding="utf-8")
    assert "diagnoses.yaml" in text
    assert "only" in text.lower()
    assert "failure_mode" in text
    assert "kb_coverage_gap" in text
    assert "skill_defect" in text
    assert "closest_issue" in text
    assert "proposed_issue" in text
    # Every row carries exactly one issue reference; an unavailable bank still
    # forces a proposal.
    assert "exactly one" in text.lower()
    assert "unavailable" in text.lower()
    # The adapted procedure grounds on the two named skills by full path.
    assert "debug-hypothesis" in text
    assert "diagnosing-bugs" in text


# --- the issue-bank seam -------------------------------------------------------


def test_match_issue_records_the_closest_candidate_when_one_exists() -> None:
    bank = FakeBank([diagnosis.Issue(repo="o/r", number=7, title="known gap")])
    outcome = diagnosis.match_issue(
        bank, query="route discovery", rationale="same surface gap"
    )
    assert outcome.closest_issue is not None
    assert outcome.closest_issue.number == 7
    assert outcome.closest_issue.rationale == "same surface gap"
    assert outcome.proposed_issue is None
    assert bank.queries == ["route discovery"]


def test_match_issue_records_the_proposal_when_none_exists() -> None:
    bank = FakeBank([])
    proposal = diagnosis.ProposedIssue(title="new gap", body="b", labels=("bug",))
    outcome = diagnosis.match_issue(
        bank, query="route discovery", rationale="none", proposed=proposal
    )
    assert outcome.closest_issue is None
    assert outcome.proposed_issue is proposal


def test_match_issue_takes_the_first_relevance_ordered_hit() -> None:
    bank = FakeBank(
        [
            diagnosis.Issue(repo="o/r", number=11, title="closest"),
            diagnosis.Issue(repo="o/r", number=22, title="less close"),
        ]
    )

    outcome = diagnosis.match_issue(bank, query="q", rationale="r")

    assert outcome.closest_issue is not None
    assert outcome.closest_issue.number == 11
    # The default limit is passed through to the bank.
    assert bank.limits == [5]


def test_github_issue_bank_defaults_to_relevance_ordering() -> None:
    seen: list[str] = []

    def transport(request):
        seen.append(request.full_url)
        return b'{"items": []}'

    bank = diagnosis.GitHubIssueBank("token", transport=transport)
    bank.search("surface gap")

    url = seen[0]
    # No forced sort: GitHub's default is best-match (relevance), so the first
    # hit is the closest match (N14).
    assert "sort=" not in url
    assert "order=" not in url
    assert "per_page=5" in url


def test_github_issue_bank_honours_an_explicit_sort() -> None:
    seen: list[str] = []

    def transport(request):
        seen.append(request.full_url)
        return b'{"items": []}'

    bank = diagnosis.GitHubIssueBank("token", transport=transport)
    bank.search("x", sort="updated")

    assert "sort=updated" in seen[0]


def test_github_issue_bank_is_get_only_against_a_fake_transport() -> None:
    seen: list = []

    def transport(request):
        seen.append(request)
        return (
            b'{"items": [{"repository_url": "https://api.github.com/repos/o/r",'
            b' "number": 5, "title": "hit"}]}'
        )

    bank = diagnosis.GitHubIssueBank("token", transport=transport)
    hits = bank.search("surface gap")

    assert [i.number for i in hits] == [5]
    assert len(seen) == 1
    assert seen[0].get_method() == "GET"
    # Never a write verb, ever.
    assert all(req.get_method() == "GET" for req in seen)
    assert "POST" not in seen[0].get_method()
    assert "Authorization" in {k.title() for k in seen[0].headers}


def test_github_issue_bank_exposes_only_search() -> None:
    bank = diagnosis.GitHubIssueBank("token")
    public = sorted(n for n in dir(bank) if not n.startswith("_"))
    assert public == ["from_env", "search"]


def test_github_issue_bank_from_env_reads_the_token(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_GITHUB_TOKEN", "secret")
    bank = diagnosis.GitHubIssueBank.from_env()
    assert bank is not None
    monkeypatch.delenv("EVAL_GITHUB_TOKEN")
    with pytest.raises(diagnosis.DiagnosisError, match="EVAL_GITHUB_TOKEN"):
        diagnosis.GitHubIssueBank.from_env()


def test_repository_url_is_parsed_into_the_repo_slug() -> None:
    def transport(request):
        return (
            b'{"items": [{"repository_url": "https://api.github.com/repos/Diekgbbtt/polyphemus",'
            b' "number": 272, "title": "diagnosis"}]}'
        )

    bank = diagnosis.GitHubIssueBank("token", transport=transport)
    (hit,) = bank.search("x")
    assert hit.repo == "Diekgbbtt/polyphemus"
    assert hit.number == 272
