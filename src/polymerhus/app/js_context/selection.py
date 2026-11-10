"""Immutable application-owned JS context selection carried by Analysis."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from polymerhus.app.data_root import validate_path_component
from polymerhus.app.js_context.records import normalize_origin

_CONTEXT_ID = re.compile(r"^jsctx_[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_SAFE_GAP = re.compile(r"^[a-z][a-z0-9_]{0,79}$")

STATUSES = frozenset(
    {
        "published",
        "pending",
        "failed",
        "skipped",
        "unavailable",
        "not_applicable",
    }
)


def _bounded_id(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 200
        or not _SAFE_ID.fullmatch(value)
    ):
        raise ValueError(f"{field} must be a bounded identifier")
    return value


@dataclass(frozen=True)
class JsContextOrigin:
    """The explicit, credential-free origin binding for a JS publication."""

    status: str
    value: str | None

    def __post_init__(self) -> None:
        if self.status == "unknown":
            if self.value is not None:
                raise ValueError("unknown JS context origin cannot carry a value")
            return
        if self.status != "known":
            raise ValueError("unsupported JS context origin status")
        normalized = normalize_origin(self.value)
        if normalized != {"status": "known", "value": self.value}:
            object.__setattr__(self, "value", normalized["value"])

    def as_dict(self) -> dict:
        return {"status": self.status, "value": self.value}


@dataclass(frozen=True)
class JsContextInput:
    """One frozen producer result; never a live pointer to ``current``."""

    project_id: str
    producing_run_id: str
    context_id: str | None
    document_id: str | None
    document_sha256: str | None
    auth_ref: str
    origin: JsContextOrigin
    status: str
    gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_path_component(self.project_id, "project_id")
        _bounded_id(self.producing_run_id, "producing_run_id")
        if not isinstance(self.origin, JsContextOrigin):
            if not isinstance(self.origin, dict):
                raise ValueError("origin must be an object")
            status = self.origin.get("status")
            value = normalize_origin(self.origin.get("value"))["value"] if status == "known" else None
            object.__setattr__(self, "origin", JsContextOrigin(status, value))
        if self.status not in STATUSES:
            raise ValueError("unsupported JS context status")
        if not isinstance(self.auth_ref, str) or len(self.auth_ref) > 200:
            raise ValueError("auth_ref must be bounded text")
        if not isinstance(self.gaps, tuple):
            object.__setattr__(self, "gaps", tuple(self.gaps))
        if any(
            not isinstance(gap, str) or not _SAFE_GAP.fullmatch(gap)
            for gap in self.gaps
        ):
            raise ValueError("JS context gaps must be bounded codes")
        if len(set(self.gaps)) != len(self.gaps):
            raise ValueError("JS context gaps must be unique")

        publication_values = (
            self.context_id,
            self.document_id,
            self.document_sha256,
        )
        if self.status == "published":
            if (
                self.context_id is None
                or not _CONTEXT_ID.fullmatch(self.context_id)
                or self.document_id is None
                or not _SAFE_ID.fullmatch(self.document_id)
                or self.document_sha256 is None
                or not _SHA256.fullmatch(self.document_sha256)
            ):
                raise ValueError(
                    "published selection requires context/document identity"
                )
        elif any(value is not None for value in publication_values):
            raise ValueError(
                "non-published selection cannot carry publication references"
            )

    def _identity(self) -> dict:
        return {
            "project_id": self.project_id,
            "producing_run_id": self.producing_run_id,
            "context_id": self.context_id,
            "document_id": self.document_id,
            "document_sha256": self.document_sha256,
            "auth_ref": self.auth_ref,
            "origin": self.origin.as_dict(),
            "status": self.status,
            "gaps": list(self.gaps),
        }

    @property
    def input_id(self) -> str:
        raw = json.dumps(
            self._identity(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "jsinput_" + hashlib.sha256(raw).hexdigest()[:40]

    def as_dict(self) -> dict:
        return {**self._identity(), "input_id": self.input_id}

    @classmethod
    def from_dict(cls, value: Any) -> "JsContextInput":
        if not isinstance(value, dict):
            raise ValueError("JS context input must be an object")
        gaps = value.get("gaps") or []
        if not isinstance(gaps, (list, tuple)):
            raise ValueError("JS context gaps must be a list")
        origin = value.get("origin") or {"status": "unknown", "value": None}
        if not isinstance(origin, dict):
            raise ValueError("origin must be an object")
        result = cls(
            project_id=value.get("project_id"),
            producing_run_id=value.get("producing_run_id"),
            context_id=value.get("context_id"),
            document_id=value.get("document_id"),
            document_sha256=value.get("document_sha256"),
            auth_ref=value.get("auth_ref") or "",
            origin=origin,
            status=value.get("status"),
            gaps=tuple(gaps),
        )
        if value.get("input_id") not in (None, result.input_id):
            raise ValueError("JS context input identity mismatch")
        return result


def _safe_gaps(values: Any, *extra: str) -> tuple[str, ...]:
    gaps = []
    for value in [*(values or []), *extra]:
        if isinstance(value, str) and _SAFE_GAP.fullmatch(value):
            gaps.append(value)
    return tuple(dict.fromkeys(gaps))


def publication_input(
    *,
    project_id: str,
    producing_run_id: str,
    publication: dict,
    auth_ref: str = "",
    origin: dict | None = None,
) -> JsContextInput:
    """Freeze the publication outcome without consulting a newer ``current``."""
    raw_status = publication.get("status")
    status = {
        "prepared": "pending",
        "identical": "published",
        "recovered": "published",
    }.get(raw_status, raw_status)
    if status not in STATUSES - {"not_applicable"}:
        status = "unavailable"

    gaps = _safe_gaps(
        publication.get("gaps"),
        *(
            [publication["error"]]
            if isinstance(publication.get("error"), str)
            else []
        ),
    )
    context_id = publication.get("context_id")
    document_id = publication.get("document_id")
    document_sha256 = publication.get("document_sha256")
    if status == "published" and not (
        isinstance(context_id, str)
        and _CONTEXT_ID.fullmatch(context_id)
        and isinstance(document_id, str)
        and _SAFE_ID.fullmatch(document_id)
        and isinstance(document_sha256, str)
        and _SHA256.fullmatch(document_sha256)
    ):
        status = "unavailable"
        gaps = _safe_gaps(gaps, "context_publication_identity_missing")
    if status != "published":
        context_id = document_id = document_sha256 = None

    binding = publication.get("origin") or origin
    if binding is None:
        binding = {"status": "unknown", "value": None}
    return JsContextInput(
        project_id=project_id,
        producing_run_id=producing_run_id,
        context_id=context_id,
        document_id=document_id,
        document_sha256=document_sha256,
        auth_ref=publication.get("auth_ref") or auth_ref,
        origin=binding,
        status=status,
        gaps=gaps,
    )


def gap_input(
    *,
    project_id: str,
    producing_run_id: str,
    status: str,
    gaps: tuple[str, ...] | list[str],
    auth_ref: str = "",
    origin: dict | None = None,
) -> JsContextInput:
    if status == "published":
        raise ValueError("a gap cannot claim a published context")
    return JsContextInput(
        project_id=project_id,
        producing_run_id=producing_run_id,
        context_id=None,
        document_id=None,
        document_sha256=None,
        auth_ref=auth_ref,
        origin=origin or {"status": "unknown", "value": None},
        status=status,
        gaps=tuple(gaps),
    )


def not_applicable(
    *,
    project_id: str,
    producing_run_id: str,
) -> JsContextInput:
    return gap_input(
        project_id=project_id,
        producing_run_id=producing_run_id,
        status="not_applicable",
        gaps=["js_not_selected"],
    )


def analysis_steering(value: JsContextInput, *, role: str) -> str:
    """Render the bounded JS-integration work order for an Analysis proposer."""
    identity = (
        f"context_id={value.context_id}; producing_run_id={value.producing_run_id}; "
        f"document_id={value.document_id}; document_sha256={value.document_sha256}"
        if value.status == "published"
        else "no published context reference is available"
    )
    gaps = ", ".join(value.gaps) or "(none)"
    return (
        "JS CONTEXT INTEGRATION. Treat this as one bounded refinement pass, not a "
        "new analysis. The application has frozen the publication below; do not "
        "substitute a newer `current` publication.\n"
        f"status={value.status}; {identity}; gaps={gaps}\n"
        "When status is published, inspect the published behaviours relevant to "
        "the current L1 through the shared `js_context` read tool using the bound "
        "publication. Compare them with existing evidence and propose only "
        "source-supported refinements through your normal output contract. A "
        "reasoned no-change result is valid. Preserve provenance and unresolved "
        "gaps; a client-side guard is not proof of server-side enforcement. Do "
        "not bulk-replace or delete existing graph descriptions.\n"
        "When status is not published, do not infer that client behaviour is "
        "absent: carry the published gap honestly and make no unsupported claim.\n"
        f"Integration role: {role}; input_id={value.input_id}."
    )


__all__ = [
    "JsContextInput",
    "JsContextOrigin",
    "STATUSES",
    "analysis_steering",
    "gap_input",
    "not_applicable",
    "publication_input",
]
