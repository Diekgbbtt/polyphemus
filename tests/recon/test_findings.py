from agent.recon.findings import normalize_severity, finding_to_observation
from agent.recon.types import Observation


def test_normalize_severity_uppercase():
    assert normalize_severity("HIGH") == "high"
    assert normalize_severity("MEDIUM") == "medium"
    assert normalize_severity("LOW") == "low"
    assert normalize_severity("INFO") == "info"


def test_normalize_severity_lowercase_passthrough():
    assert normalize_severity("critical") == "critical"
    assert normalize_severity("high") == "high"


def test_normalize_severity_none_defaults_info():
    assert normalize_severity(None) == "info"


def test_normalize_severity_unknown_defaults_info():
    assert normalize_severity("N/A") == "info"
    assert normalize_severity("") == "info"


def test_finding_to_observation_with_anchor():
    finding = {
        "title": "potential_subdomain_takeover",
        "severity": "high",
        "evidence": "e",
        "anchor": {"type": "Subdomain", "identity": {"name": "x"}},
    }
    obs = finding_to_observation(finding, source_job="takeover_check", source_tool="subdomain_takeover")
    assert isinstance(obs, Observation)
    assert obs.macro_kind == "potential_subdomain_takeover"
    assert obs.severity == "high"
    assert obs.evidence == "e"
    assert obs.rationale == "e"
    assert obs.anchor == {"type": "Subdomain", "identity": {"name": "x"}}
    assert obs.source_job == "takeover_check"
    assert obs.source_tool == "subdomain_takeover"


def test_finding_to_observation_uppercase_severity_normalized():
    finding = {"title": "Introspection", "severity": "MEDIUM", "evidence": "e",
               "anchor": {"type": "BaseURL", "identity": {"url": "https://x"}}}
    obs = finding_to_observation(finding, source_job="graphql_audit", source_tool="graphql-cop")
    assert obs.severity == "medium"


def test_finding_to_observation_without_anchor_returns_none():
    finding = {"title": "Introspection", "severity": "MEDIUM", "evidence": "e"}
    obs = finding_to_observation(finding, source_job="graphql_audit", source_tool="graphql-cop")
    assert obs is None


def test_finding_to_observation_rationale_falls_back_to_title():
    finding = {"title": "some_finding", "severity": "low",
               "anchor": {"type": "Subdomain", "identity": {"name": "x"}}}
    obs = finding_to_observation(finding, source_job="j", source_tool="t")
    assert obs.rationale == "some_finding"
    assert obs.evidence == ""
