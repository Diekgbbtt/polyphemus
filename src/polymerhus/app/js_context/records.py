"""Pure records for the final client-side JS context publication.

The schema has exactly four top-level sections: ``schema_version``,
``context``, ``behaviors`` and ``evidence``. This module performs no I/O and
does not import recon collaborators; the store owns persistence and the recon
writer owns deterministic assembly from saved run records.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from urllib.parse import urlsplit

from polymerhus.app.data_root import validate_path_component

SCHEMA_VERSION = 1
MAX_BEHAVIORS = 256
MAX_EVIDENCE = 2048
MAX_STEPS = 12
MAX_ASSUMPTIONS = 8
MAX_GAPS = 16
MAX_COVERAGE_GAPS = 8192
MAX_READ_IDS = 8
MAX_TEXT = 512
MAX_ID = 200
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STEP_KINDS = frozenset(
    {
        "trigger",
        "input",
        "transform",
        "call",
        "request",
        "sink",
        "response",
        "error",
        "effect",
    }
)
_ASSUMPTION_STATUSES = frozenset({"supported", "unverified"})
_COVERAGE_STATUSES = frozenset({"complete", "partial", "empty"})
_DELIVERY_STATUSES = frozenset({"delivered", "missing_or_foreign"})
_AVAILABILITY_STATUSES = frozenset(
    {
        "retained_unverified",
        "pending",
        "unavailable",
        "receipt_only",
        "receipt_missing_or_foreign",
    }
)
_RETENTION_STATUSES = frozenset(
    {"retained", "pending", "gap", "missing", "unknown"}
)


class JsContextInvalidError(ValueError):
    """A denoted schema refusal naming the offending field and reason."""

    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"js_context_invalid: {field} {reason}")
        self.field = field
        self.reason = reason


def _fail(field: str, reason: str) -> None:
    raise JsContextInvalidError(field, reason)


def _mapping(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        _fail(field, "must be an object")
    return value


def _list(value: object, field: str) -> list:
    if not isinstance(value, list):
        _fail(field, "must be a list")
    return value


def _string(
    value: object,
    field: str,
    *,
    nonempty: bool = True,
    max_length: int = MAX_TEXT,
    nullable: bool = False,
    allow_linebreaks: bool = False,
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        _fail(field, "must be a string")
    if nonempty and not value.strip():
        _fail(field, "must be a non-empty string")
    if len(value) > max_length:
        _fail(field, "is too long")
    if "\x00" in value or any(
        ord(char) < 32
        and not (allow_linebreaks and char in "\r\n\t")
        for char in value
    ):
        _fail(field, "contains a control character")
    return value


def _integer(
    value: object,
    field: str,
    *,
    minimum: int = 0,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        _fail(field, f"must be an integer >= {minimum}")
    return value


def _exact_keys(value: dict, *, allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed, key=repr)
    if unknown:
        _fail(f"{field}.{unknown[0]}", "is not a known field")
    missing = sorted(allowed - set(value))
    if missing:
        _fail(f"{field}.{missing[0]}", "is required")


def _path_component(value: object, field: str) -> str:
    text = _string(value, field, max_length=MAX_ID)
    try:
        return validate_path_component(text, field)
    except ValueError as exc:
        raise JsContextInvalidError(field, str(exc)) from None


def normalize_origin(origin: str | dict[str, object] | None) -> dict:
    """Return the explicit origin binding or the explicit unknown state.

    Callers may supply either the writer-layer string or the trusted pipeline's
    explicit ``{status, value}`` envelope. Both must identify a clean HTTP(S)
    origin. This function never derives an origin from a module, page or request
    URL; those remain separate analysis facts.
    """
    if isinstance(origin, dict):
        return _origin_binding(origin, "context.origin")
    if origin is None:
        return {"status": "unknown", "value": None}
    text = _string(origin, "context.origin", max_length=MAX_ID)
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        _fail("context.origin", "is not a valid HTTP origin")
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        _fail("context.origin", "must be a clean HTTP(S) origin without credentials or path")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = 80 if scheme == "http" else 443
    authority = host if port in {None, default_port} else f"{host}:{port}"
    return {"status": "known", "value": f"{scheme}://{authority}"}


def _origin_binding(value: object, field: str) -> dict:
    origin = _mapping(value, field)
    _exact_keys(origin, allowed={"status", "value"}, field=field)
    status = origin["status"]
    if status == "unknown":
        if origin["value"] is not None:
            _fail(f"{field}.value", "must be null when origin status is unknown")
        return {"status": "unknown", "value": None}
    if status != "known":
        _fail(f"{field}.status", 'must be "known" or "unknown"')
    value = origin["value"]
    if not isinstance(value, str):
        _fail(f"{field}.value", "must be a string when origin status is known")
    normalized = normalize_origin(value)
    if normalized["status"] != "known":
        _fail(f"{field}.value", "must be a known HTTP(S) origin")
    return normalized


def _auth_ref(value: object) -> str:
    text = _string(
        value,
        "context.auth_ref",
        nonempty=False,
        max_length=MAX_ID,
    )
    return text


def _identity_values(
    *,
    project_id: object,
    origin: object,
    auth_ref: object,
) -> tuple[str, dict, str]:
    project = _path_component(project_id, "context.project_id")
    binding = _origin_binding(origin, "context.origin")
    auth = _auth_ref(auth_ref)
    return project, binding, auth


def context_id_for(
    *,
    project_id: str,
    origin: dict,
    auth_ref: str,
) -> str:
    """Derive the credential-free, deterministic context-directory identity."""
    project, binding, auth = _identity_values(
        project_id=project_id,
        origin=origin,
        auth_ref=auth_ref,
    )
    body = json.dumps(
        {
            "project_id": project,
            "origin": binding,
            "auth_ref": auth,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "jsctx_" + hashlib.sha256(body).hexdigest()[:40]


def _read_ids(value: object, field: str, *, required: bool) -> list[str]:
    items = _list(value, field)
    if required and not items:
        _fail(field, "must contain at least one read id")
    if len(items) > MAX_READ_IDS:
        _fail(field, "contains too many read ids")
    result = [
        _string(item, f"{field}[{index}]", max_length=MAX_ID)
        for index, item in enumerate(items)
    ]
    if len(set(result)) != len(result):
        _fail(field, "must not contain duplicates")
    return result


def _validate_behavior(value: object, index: int) -> dict:
    field = f"behaviors[{index}]"
    behavior = _mapping(value, field)
    keys = {
        "behavior_id",
        "revision",
        "reconstruction_level",
        "question_ref",
        "question",
        "priority",
        "lead_id",
        "record_sha256",
        "redaction_policy",
        "redaction_count",
        "steps",
        "assumptions",
        "gaps",
    }
    _exact_keys(behavior, allowed=keys, field=field)
    behavior_id = _string(
        behavior["behavior_id"], f"{field}.behavior_id", max_length=MAX_ID
    )
    revision = _integer(behavior["revision"], f"{field}.revision", minimum=1)
    reconstruction = _string(
        behavior["reconstruction_level"],
        f"{field}.reconstruction_level",
        max_length=64,
    )
    question_ref = _string(
        behavior["question_ref"], f"{field}.question_ref", max_length=MAX_ID
    )
    question = _string(
        behavior["question"],
        f"{field}.question",
        allow_linebreaks=True,
    )
    priority = _string(behavior["priority"], f"{field}.priority", max_length=64)
    lead_id = _string(behavior["lead_id"], f"{field}.lead_id", max_length=MAX_ID)
    record_sha = _string(
        behavior["record_sha256"], f"{field}.record_sha256", max_length=64
    )
    if not _SHA256.fullmatch(record_sha):
        _fail(f"{field}.record_sha256", "must be a lowercase SHA-256")
    policy = _string(
        behavior["redaction_policy"], f"{field}.redaction_policy", max_length=100
    )
    redactions = _integer(
        behavior["redaction_count"], f"{field}.redaction_count"
    )

    steps = _list(behavior["steps"], f"{field}.steps")
    if not steps or len(steps) > MAX_STEPS:
        _fail(f"{field}.steps", "must contain between 1 and 12 steps")
    clean_steps = []
    for step_index, raw_step in enumerate(steps):
        step_field = f"{field}.steps[{step_index}]"
        step = _mapping(raw_step, step_field)
        _exact_keys(step, allowed={"kind", "text", "read_ids"}, field=step_field)
        kind = _string(step["kind"], f"{step_field}.kind", max_length=32)
        if kind not in _STEP_KINDS:
            _fail(f"{step_field}.kind", "is not a supported step kind")
        clean_steps.append(
            {
                "kind": kind,
                "text": _string(
                    step["text"],
                    f"{step_field}.text",
                    allow_linebreaks=True,
                ),
                "read_ids": _read_ids(
                    step["read_ids"], f"{step_field}.read_ids", required=True
                ),
            }
        )

    assumptions = _list(behavior["assumptions"], f"{field}.assumptions")
    if len(assumptions) > MAX_ASSUMPTIONS:
        _fail(f"{field}.assumptions", "contains too many assumptions")
    clean_assumptions = []
    for assumption_index, raw_assumption in enumerate(assumptions):
        assumption_field = f"{field}.assumptions[{assumption_index}]"
        assumption = _mapping(raw_assumption, assumption_field)
        _exact_keys(
            assumption,
            allowed={"text", "status", "read_ids"},
            field=assumption_field,
        )
        status = _string(
            assumption["status"], f"{assumption_field}.status", max_length=32
        )
        if status not in _ASSUMPTION_STATUSES:
            _fail(
                f"{assumption_field}.status",
                'must be "supported" or "unverified"',
            )
        read_ids = _read_ids(
            assumption["read_ids"],
            f"{assumption_field}.read_ids",
            required=status == "supported",
        )
        clean_assumptions.append(
            {
                "text": _string(
                    assumption["text"],
                    f"{assumption_field}.text",
                    allow_linebreaks=True,
                ),
                "status": status,
                "read_ids": read_ids,
            }
        )

    raw_gaps = _list(behavior["gaps"], f"{field}.gaps")
    if len(raw_gaps) > MAX_GAPS:
        _fail(f"{field}.gaps", "contains too many gaps")
    gaps = [
        _string(
            gap,
            f"{field}.gaps[{gap_index}]",
            allow_linebreaks=True,
        )
        for gap_index, gap in enumerate(raw_gaps)
    ]
    return {
        "behavior_id": behavior_id,
        "revision": revision,
        "reconstruction_level": reconstruction,
        "question_ref": question_ref,
        "question": question,
        "priority": priority,
        "lead_id": lead_id,
        "record_sha256": record_sha,
        "redaction_policy": policy,
        "redaction_count": redactions,
        "steps": clean_steps,
        "assumptions": clean_assumptions,
        "gaps": gaps,
    }


def validate_behavior(value: object) -> dict:
    """Validate one behavior entry before whole-document assembly."""
    return _validate_behavior(value, 0)


def _nullable_sha(value: object, field: str) -> str | None:
    if value is None:
        return None
    text = _string(value, field, max_length=64)
    if not _SHA256.fullmatch(text):
        _fail(field, "must be a lowercase SHA-256 or null")
    return text


def _validate_evidence(value: object, index: int) -> dict:
    field = f"evidence[{index}]"
    evidence = _mapping(value, field)
    keys = {
        "read_id",
        "lead_id",
        "selector",
        "content_sha256",
        "range",
        "redaction_policy",
        "delivery_status",
        "availability",
        "retention_status",
        "artifact_ref",
        "limitations",
    }
    _exact_keys(evidence, allowed=keys, field=field)
    read_id = _string(evidence["read_id"], f"{field}.read_id", max_length=MAX_ID)
    lead_id = _string(evidence["lead_id"], f"{field}.lead_id", max_length=MAX_ID)
    selector = _mapping(evidence["selector"], f"{field}.selector")
    _exact_keys(
        selector,
        allowed={"type", "id"},
        field=f"{field}.selector",
    )
    selector_type = _string(
        selector["type"], f"{field}.selector.type", max_length=32
    )
    if selector_type not in {"item", "source", "match", "unknown"}:
        _fail(f"{field}.selector.type", "is not a supported selector")
    selector_id = _string(
        selector["id"], f"{field}.selector.id", max_length=MAX_ID
    )
    byte_range = _mapping(evidence["range"], f"{field}.range")
    _exact_keys(
        byte_range,
        allowed={"start", "end"},
        field=f"{field}.range",
    )
    start = _integer(byte_range["start"], f"{field}.range.start")
    end = _integer(byte_range["end"], f"{field}.range.end")
    if end < start:
        _fail(f"{field}.range.end", "must be >= range.start")
    content_sha = _nullable_sha(
        evidence["content_sha256"], f"{field}.content_sha256"
    )
    policy = _string(
        evidence["redaction_policy"],
        f"{field}.redaction_policy",
        max_length=100,
        nullable=True,
    )
    delivery = _string(
        evidence["delivery_status"], f"{field}.delivery_status", max_length=32
    )
    if delivery not in _DELIVERY_STATUSES:
        _fail(f"{field}.delivery_status", "is not a supported delivery status")
    availability = _string(
        evidence["availability"], f"{field}.availability", max_length=64
    )
    if availability not in _AVAILABILITY_STATUSES:
        _fail(f"{field}.availability", "is not a supported availability status")
    retention = _string(
        evidence["retention_status"],
        f"{field}.retention_status",
        max_length=32,
    )
    if retention not in _RETENTION_STATUSES:
        _fail(f"{field}.retention_status", "is not a supported retention status")
    artifact_ref = _string(
        evidence["artifact_ref"],
        f"{field}.artifact_ref",
        max_length=MAX_TEXT,
        nullable=True,
    )
    limitations = _list(evidence["limitations"], f"{field}.limitations")
    if len(limitations) > MAX_GAPS:
        _fail(f"{field}.limitations", "contains too many limitations")
    clean_limitations = [
        _string(item, f"{field}.limitations[{item_index}]", max_length=MAX_ID)
        for item_index, item in enumerate(limitations)
    ]
    if delivery == "delivered":
        if content_sha is None or policy is None:
            _fail(field, "a delivered read must retain its content hash and policy")
        if availability == "receipt_missing_or_foreign":
            _fail(f"{field}.availability", "conflicts with a delivered read")
        expected_availability = {
            "retained": "retained_unverified",
            "pending": "pending",
            "gap": "unavailable",
            "missing": "receipt_only",
        }.get(retention)
        if expected_availability is None or availability != expected_availability:
            _fail(
                f"{field}.availability",
                "must agree with the recorded retention status",
            )
        if selector_type == "unknown":
            _fail(f"{field}.selector.type", "cannot be unknown for a delivered read")
        if retention == "retained" and artifact_ref is None:
            _fail(
                f"{field}.artifact_ref",
                "is required when retention is retained",
            )
        if retention in {"missing", "unknown"} and artifact_ref is not None:
            _fail(
                f"{field}.artifact_ref",
                "must be null without retained metadata",
            )
    else:
        if content_sha is not None:
            _fail(
                f"{field}.content_sha256",
                "must be null when the scoped receipt is missing or foreign",
            )
        if availability != "receipt_missing_or_foreign":
            _fail(
                f"{field}.availability",
                "must be receipt_missing_or_foreign",
            )
        if retention != "unknown":
            _fail(f"{field}.retention_status", "must be unknown")
        if artifact_ref is not None:
            _fail(f"{field}.artifact_ref", "must be null for a missing receipt")
        if start != 0 or end != 0:
            _fail(f"{field}.range", "must be zero without a delivered receipt")
        if selector_type != "unknown":
            _fail(
                f"{field}.selector.type",
                "must be unknown for a missing receipt",
            )
    return {
        "read_id": read_id,
        "lead_id": lead_id,
        "selector": {"type": selector_type, "id": selector_id},
        "content_sha256": content_sha,
        "range": {"start": start, "end": end},
        "redaction_policy": policy,
        "delivery_status": delivery,
        "availability": availability,
        "retention_status": retention,
        "artifact_ref": artifact_ref,
        "limitations": clean_limitations,
    }


def _validate_context(value: object) -> dict:
    context = _mapping(value, "context")
    _exact_keys(
        context,
        allowed={"project_id", "run_id", "origin", "auth_ref", "coverage"},
        field="context",
    )
    project_id = _path_component(context["project_id"], "context.project_id")
    run_id = _path_component(context["run_id"], "context.run_id")
    origin = _origin_binding(context["origin"], "context.origin")
    auth_ref = _auth_ref(context["auth_ref"])
    coverage = _mapping(context["coverage"], "context.coverage")
    _exact_keys(
        coverage,
        allowed={"status", "gaps"},
        field="context.coverage",
    )
    status = _string(
        coverage["status"], "context.coverage.status", max_length=32
    )
    if status not in _COVERAGE_STATUSES:
        _fail("context.coverage.status", "is not a supported coverage status")
    raw_gaps = _list(coverage["gaps"], "context.coverage.gaps")
    if len(raw_gaps) > MAX_COVERAGE_GAPS:
        _fail("context.coverage.gaps", "contains too many gaps")
    gaps = [
        _string(gap, f"context.coverage.gaps[{index}]", max_length=MAX_ID)
        for index, gap in enumerate(raw_gaps)
    ]
    if status == "empty" and "no_saved_behaviors" not in gaps:
        _fail("context.coverage.gaps", "empty coverage requires no_saved_behaviors")
    if status == "partial" and not gaps:
        _fail("context.coverage.gaps", "partial coverage requires at least one gap")
    if status == "complete" and gaps:
        _fail("context.coverage.gaps", "complete coverage cannot carry gaps")
    return {
        "project_id": project_id,
        "run_id": run_id,
        "origin": origin,
        "auth_ref": auth_ref,
        "coverage": {"status": status, "gaps": gaps},
    }


def validate_document(document: object) -> dict:
    """Validate and deep-copy one final context document."""
    value = _mapping(document, "document")
    _exact_keys(
        value,
        allowed={"schema_version", "context", "behaviors", "evidence"},
        field="document",
    )
    if (
        not isinstance(value["schema_version"], int)
        or isinstance(value["schema_version"], bool)
        or value["schema_version"] != SCHEMA_VERSION
    ):
        _fail("schema_version", f"must be {SCHEMA_VERSION}")
    context = _validate_context(value["context"])
    raw_behaviors = _list(value["behaviors"], "behaviors")
    if len(raw_behaviors) > MAX_BEHAVIORS:
        _fail("behaviors", "contains too many behaviors")
    behaviors = [
        _validate_behavior(behavior, index)
        for index, behavior in enumerate(raw_behaviors)
    ]
    behavior_ids = [behavior["behavior_id"] for behavior in behaviors]
    if len(behavior_ids) != len(set(behavior_ids)):
        _fail("behaviors", "behavior ids must be unique")

    raw_evidence = _list(value["evidence"], "evidence")
    if len(raw_evidence) > MAX_EVIDENCE:
        _fail("evidence", "contains too many entries")
    evidence = [
        _validate_evidence(item, index)
        for index, item in enumerate(raw_evidence)
    ]
    evidence_ids = [item["read_id"] for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        duplicate_index = next(
            index
            for index, read_id in enumerate(evidence_ids)
            if read_id in evidence_ids[:index]
        )
        _fail(f"evidence[{duplicate_index}].read_id", "must be unique")

    cited = set()
    for behavior_index, behavior in enumerate(behaviors):
        for step_index, step in enumerate(behavior["steps"]):
            for read_index, read_id in enumerate(step["read_ids"]):
                cited.add(read_id)
                if read_id not in evidence_ids:
                    _fail(
                        f"behaviors[{behavior_index}].steps"
                        f"[{step_index}].read_ids[{read_index}]",
                        "has no evidence entry",
                    )
        for assumption_index, assumption in enumerate(
            behavior["assumptions"]
        ):
            for read_index, read_id in enumerate(assumption["read_ids"]):
                cited.add(read_id)
                if read_id not in evidence_ids:
                    _fail(
                        f"behaviors[{behavior_index}].assumptions"
                        f"[{assumption_index}].read_ids[{read_index}]",
                        "has no evidence entry",
                    )
    uncited = [read_id for read_id in evidence_ids if read_id not in cited]
    if uncited:
        _fail(
            f"evidence[{evidence_ids.index(uncited[0])}].read_id",
            "is not cited by a behavior",
        )
    if context["coverage"]["status"] == "empty" and behaviors:
        _fail("context.coverage.status", "empty coverage requires no behaviors")
    if context["coverage"]["status"] == "complete" and not behaviors:
        _fail("behaviors", "complete coverage requires a behavior")
    if (
        context["coverage"]["status"] == "complete"
        and any(
            item["availability"] != "retained_unverified"
            for item in evidence
        )
    ):
        _fail(
            "context.coverage.status",
            "complete coverage requires retained evidence metadata",
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "context": context,
        "behaviors": behaviors,
        "evidence": evidence,
    }


def document_identity(document: object) -> str:
    """The canonical semantic identity used for same-run conflict checks."""
    value = validate_document(document)
    body = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


__all__ = [
    "JsContextInvalidError",
    "context_id_for",
    "document_identity",
    "normalize_origin",
    "validate_behavior",
    "validate_document",
]
