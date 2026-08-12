from typing import Any, Literal

from pydantic import BaseModel, Field


class AuditIssue(BaseModel):
    code: str
    message: str
    severity: Literal["critical", "warning"]
    evidence: dict[str, Any] = Field(default_factory=dict)


class AuditReport(BaseModel):
    job_id: str
    source_key: str
    critical_issues: list[AuditIssue] = Field(default_factory=list)
    warnings: list[AuditIssue] = Field(default_factory=list)
    merge_candidates: list[dict[str, Any]] = Field(default_factory=list)
    checked_at: str


def has_critical_issues(report: AuditReport) -> bool:
    return len(report.critical_issues) > 0
