from agent.ingestion.audit import AuditIssue, AuditReport, has_critical_issues


def test_audit_report_model_dump_contains_required_fields():
    report = AuditReport(
        job_id="job-123",
        source_key="docs/foo.md",
        checked_at="2025-01-01T00:00:00Z",
    )
    dumped = report.model_dump(mode="json")
    assert "critical_issues" in dumped
    assert "warnings" in dumped
    assert "merge_candidates" in dumped
    assert "checked_at" in dumped
    assert dumped["critical_issues"] == []
    assert dumped["warnings"] == []
    assert dumped["merge_candidates"] == []


def test_has_critical_issues_false_for_warnings_only():
    report = AuditReport(
        job_id="job-123",
        source_key="docs/foo.md",
        checked_at="2025-01-01T00:00:00Z",
        warnings=[
            AuditIssue(
                code="WARN-1",
                message="minor issue",
                severity="warning",
                evidence={"detail": "something"},
            )
        ],
    )
    assert has_critical_issues(report) is False


def test_has_critical_issues_true_when_critical_present():
    report = AuditReport(
        job_id="job-123",
        source_key="docs/foo.md",
        checked_at="2025-01-01T00:00:00Z",
        critical_issues=[
            AuditIssue(
                code="CRIT-1",
                message="blocking issue",
                severity="critical",
                evidence={"detail": "bad"},
            )
        ],
    )
    assert has_critical_issues(report) is True


def test_audit_report_mutable_defaults_are_not_shared():
    report_a = AuditReport(job_id="a", source_key="a.md", checked_at="now")
    report_b = AuditReport(job_id="b", source_key="b.md", checked_at="now")
    report_a.critical_issues.append(
        AuditIssue(code="X", message="x", severity="critical")
    )
    assert report_b.critical_issues == []
