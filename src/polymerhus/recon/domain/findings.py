"""Triager finding contract: parser-emitted finding dicts -> `Observation`s.

Parser modules that expose `parse_findings(stdout) -> list[dict]` (currently
`graphql_parser` and `takeover_parser`) return finding dicts of the shape
`{title, severity, evidence, anchor?}`. This module normalizes those into the
same `Observation` shape the LLM triager produces, so the pod's triager node
can merge deterministic, parser-derived findings with LLM-derived ones
uniformly.

graphql-cop emits UPPERCASE severities (`"HIGH"`, `"MEDIUM"`, `"LOW"`,
`"INFO"`); the takeover parser emits lowercase already. `normalize_severity`
maps both (and any unrecognized/missing value) onto a canonical lowercase set.
"""
import logging

from polymerhus.recon.domain.types import Observation

logger = logging.getLogger(__name__)

_CANONICAL_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def normalize_severity(raw: str | None) -> str:
    """Map a raw severity string to the canonical lowercase set
    `{"critical","high","medium","low","info"}`. Unknown or missing values
    default to `"info"`."""
    if not isinstance(raw, str) or not raw:
        return "info"

    normalized = raw.strip().lower()
    if normalized in _CANONICAL_SEVERITIES:
        return normalized

    return "info"


def finding_to_observation(
    finding: dict, *, source_job: str, source_tool: str
) -> Observation | None:
    """Build an `Observation` from a parser-emitted finding dict.

    Returns `None` (and logs at debug level) when the finding carries no
    `anchor` - the curator's Observation path requires a valid broad anchor
    (Domain/Subdomain/BaseURL/IP/Service - matching `curator.ANCHOR_ALLOWLIST`;
    `Endpoint` is NOT allowed, since it is not a broad graph element), so an
    anchorless finding is dropped rather than mis-attached. (graphql-cop
    findings get a BaseURL anchor when the pod threads the job's target_url
    into `graphql_parser.parse_findings` - SP3-T5; a graphql-cop finding is
    only anchorless, and therefore dropped, when neither target_url nor the
    curl_verify regex fallback can derive a base URL.)
    """
    anchor = finding.get("anchor")
    if not anchor:
        logger.debug(
            "dropping finding %r from %s/%s: no anchor",
            finding.get("title"), source_job, source_tool,
        )
        return None

    title = finding.get("title", "")
    evidence = finding.get("evidence", "")

    return Observation(
        macro_kind=title,
        severity=normalize_severity(finding.get("severity")),
        evidence=evidence,
        rationale=evidence or title,
        anchor=anchor,
        source_job=source_job,
        source_tool=source_tool,
    )
